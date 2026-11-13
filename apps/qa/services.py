"""Retrieval-augmented answering."""

import logging
import time
from dataclasses import dataclass
from typing import cast

from django.conf import settings
from django.db import connection
from pgvector.django import CosineDistance

from apps.core import budget
from apps.documents.models import Chunk
from rag.pricing import chat_cost, embedding_cost
from rag.providers import LLMProvider, get_provider
from rag.tracing import set_attributes, stage
from rag.types import AnswerResult, ContextChunk, EarlierQuery, RewriteResult, Usage

from .models import Query

logger = logging.getLogger(__name__)

NO_ANSWER = "I don't know based on the uploaded documents."

# How many Queries of a Follow-up chain the rewrite sees: the predecessor and up to 2 of its own.
FOLLOW_UP_HISTORY_LENGTH = 3


class PredecessorNotFoundError(Exception):
    """The named predecessor does not exist or belongs to another Owner (indistinguishable on purpose)."""


RRF_K = 60  # the usual reciprocal rank fusion constant; only orders candidates, never gates them

# Full-text gate: the share of the question's lexemes (english stems, stopwords dropped) that a
# Chunk contains. Postgres ranks have no IDF, so a share separates "names the rare term the
# question is about" from "shares one common word" where ts_rank_cd cannot (ADR 0004).
_TEXT_GATE_SQL = """
WITH q AS (
    SELECT lex, (SELECT string_agg(quote_literal(l), ' | ')::tsquery FROM unnest(lex) l) AS any_term
    FROM (SELECT tsvector_to_array(to_tsvector('english', %(question)s)) AS lex) t
    WHERE cardinality(lex) > 0
), matches AS (
    SELECT c.id,
           (SELECT count(*) FROM unnest(q.lex) l WHERE c.search @@ quote_literal(l)::tsquery)::float
               / cardinality(q.lex) AS coverage,
           ts_rank_cd(c.search, q.any_term) AS rank
    FROM documents_chunk c, q
    WHERE c.owner_id = %(owner_id)s
      AND (%(document_ids)s::bigint[] IS NULL OR c.document_id = ANY(%(document_ids)s::bigint[]))
      AND c.search @@ q.any_term
)
SELECT id, coverage FROM matches
WHERE coverage >= %(min_coverage)s
ORDER BY coverage DESC, rank DESC, id
LIMIT %(top_k)s
"""


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float  # reciprocal rank fusion; higher is better
    distance: float | None  # set when the Chunk passed the vector gate
    text_coverage: float | None  # set when the Chunk passed the full-text gate


def _vector_gate(owner, question_vector, top_k, max_distance, document_ids) -> list[tuple[int, float]]:
    qs = Chunk.objects.filter(owner=owner)
    if document_ids:
        qs = qs.filter(document_id__in=document_ids)
    rows = (
        qs.annotate(distance=CosineDistance("embedding", question_vector))
        .order_by("distance")
        .values_list("id", "distance")[:top_k]
    )
    return [(pk, float(d)) for pk, d in rows if d <= max_distance]


def _text_gate(owner, question, top_k, min_coverage, document_ids) -> list[tuple[int, float]]:
    params = {
        "question": question,
        "owner_id": owner.pk,
        "document_ids": list(document_ids) if document_ids else None,
        "min_coverage": min_coverage,
        "top_k": top_k,
    }
    with connection.cursor() as cursor:
        cursor.execute(_TEXT_GATE_SQL, params)
        return [(pk, float(coverage)) for pk, coverage in cursor.fetchall()]


def retrieve(
    owner,
    question: str,
    question_vector: list[float],
    top_k: int,
    max_distance: float,
    document_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    """Hybrid retrieval. A Chunk is a candidate if it passes either gate: vector distance within
    the provider's max_distance, or full-text coverage of the question at or above
    RAG_MIN_TEXT_COVERAGE. Both gates scope by Owner in their own SQL. Candidates are ordered by
    reciprocal rank fusion; no candidates means the caller Abstains."""
    vector = _vector_gate(owner, question_vector, top_k, max_distance, document_ids)
    text = _text_gate(owner, question, top_k, settings.RAG_MIN_TEXT_COVERAGE, document_ids)

    scores: dict[int, float] = {}
    for ranked in (vector, text):
        for rank, (pk, _) in enumerate(ranked, start=1):
            scores[pk] = scores.get(pk, 0.0) + 1.0 / (RRF_K + rank)
    best = sorted(scores, key=lambda pk: (-scores[pk], pk))[:top_k]
    chunks = Chunk.objects.filter(owner=owner).select_related("document").in_bulk(best)
    distances, coverages = dict(vector), dict(text)
    return [
        RetrievedChunk(chunks[pk], scores[pk], distances.get(pk), coverages.get(pk))
        for pk in best
        if pk in chunks
    ]


def ask(
    owner,
    question: str,
    document_ids: list[int] | None = None,
    top_k: int | None = None,
    predecessor_id: int | None = None,
) -> Query:
    """Answer a question from the Owner's Chunks. With `predecessor_id` the Query is a Follow-up:
    it is first rewritten into a standalone question, which retrieval and answering then use."""
    with stage("ask", owner__id=owner.pk) as span:
        query = _ask(owner, question, document_ids, top_k, predecessor_id)
        set_attributes(
            span,
            query__id=query.pk,
            query__is_follow_up=query.predecessor_id is not None,
            query__abstained=not query.retrieved_chunk_ids,
            query__cited_count=query.cited_chunks.count(),
            cost_usd=float(query.cost_usd),
            latency_ms=query.latency_ms,
        )
        return query


def _predecessor(owner, predecessor_id: int | None) -> Query | None:
    if predecessor_id is None:
        return None
    found = (
        Query.objects.filter(owner=owner, pk=predecessor_id)
        .select_related("predecessor__predecessor")
        .first()
    )
    if found is None:
        raise PredecessorNotFoundError
    return found


def _history(predecessor: Query) -> list[EarlierQuery]:
    """The last FOLLOW_UP_HISTORY_LENGTH Queries of the chain, oldest first. An earlier Follow-up
    contributes its standalone question, which already carries its own context."""
    chain = [predecessor]
    while len(chain) < FOLLOW_UP_HISTORY_LENGTH and chain[-1].predecessor_id is not None:
        chain.append(cast(Query, chain[-1].predecessor))
    return [EarlierQuery(q.standalone_question or q.question, q.answer) for q in reversed(chain)]


def _rewrite(provider: LLMProvider, question: str, predecessor: Query) -> RewriteResult:
    history = _history(predecessor)
    with stage("ask.rewrite", llm__provider=provider.name, history_count=len(history)) as span:
        result = provider.rewrite(question, history)
        set_attributes(
            span,
            llm__model=result.model,
            llm__input_tokens=result.usage.input_tokens,
            llm__output_tokens=result.usage.output_tokens,
        )
    return result


def _ask(
    owner, question: str, document_ids: list[int] | None, top_k: int | None, predecessor_id: int | None
) -> Query:
    predecessor = _predecessor(owner, predecessor_id)
    budget.ensure_available(owner)
    started = time.monotonic()
    provider = get_provider()
    top_k = top_k or settings.RAG_TOP_K

    rewrite = _rewrite(provider, question, predecessor) if predecessor else None
    # Earlier answers stop here: from this point on only the standalone question is used.
    search_question = rewrite.question if rewrite else question

    with stage("ask.embed", llm__provider=provider.name) as span:
        embedded = provider.embed([search_question])
        set_attributes(span, llm__embedding_tokens=embedded.usage.input_tokens)
    with stage("ask.retrieve", top_k=top_k, max_distance=provider.max_distance) as span:
        hits = retrieve(
            owner, search_question, embedded.vectors[0], top_k, provider.max_distance, document_ids
        )
        set_attributes(
            span,
            retrieved_count=len(hits),
            vector_count=sum(h.distance is not None for h in hits),
            text_count=sum(h.text_coverage is not None for h in hits),
            min_distance=min((h.distance for h in hits if h.distance is not None), default=None),
        )

    if hits:
        context = [ContextChunk(h.chunk.pk, h.chunk.document.title, h.chunk.text) for h in hits]
        with stage("ask.answer", llm__provider=provider.name, chunk_count=len(context)) as span:
            result = provider.answer(search_question, context)
            set_attributes(
                span,
                llm__model=result.model,
                llm__input_tokens=result.usage.input_tokens,
                llm__output_tokens=result.usage.output_tokens,
            )
    else:
        # Nothing relevant: skip the chat call entirely (saves cost, avoids guessing).
        result = AnswerResult(NO_ANSWER, [], model="none", usage=Usage())

    # Never trust the model's citations blindly: keep only ids we actually sent.
    retrieved_ids = [h.chunk.pk for h in hits]
    cited = [cid for cid in dict.fromkeys(result.cited_chunk_ids) if cid in retrieved_ids]

    chat_usage = result.usage + rewrite.usage if rewrite else result.usage
    query = Query.objects.create(
        owner=owner,
        predecessor=predecessor,
        question=question,
        standalone_question=rewrite.question if rewrite else None,
        answer=result.answer,
        retrieved_chunk_ids=retrieved_ids,
        provider=provider.name,
        model=result.model,
        input_tokens=chat_usage.input_tokens,
        output_tokens=chat_usage.output_tokens,
        embedding_tokens=embedded.usage.input_tokens,
        cost_usd=chat_cost(chat_usage) + embedding_cost(embedded.usage),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    query.cited_chunks.set(cited)
    budget.record(owner, query.cost_usd)
    logger.info(
        "ask query=%s retrieved=%d cited=%d cost_usd=%s latency_ms=%d",
        query.pk,
        len(hits),
        len(cited),
        query.cost_usd,
        query.latency_ms,
    )
    return query
