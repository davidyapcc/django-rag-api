"""Retrieval-augmented answering."""

import logging
import time
from dataclasses import dataclass

from django.conf import settings
from pgvector.django import CosineDistance

from apps.core import budget
from apps.documents.models import Chunk
from rag.pricing import chat_cost, embedding_cost
from rag.providers import get_provider
from rag.tracing import set_attributes, stage
from rag.types import AnswerResult, ContextChunk, Usage

from .models import Query

logger = logging.getLogger(__name__)

NO_ANSWER = "I don't know based on the uploaded documents."


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    distance: float


def retrieve(
    owner,
    question_vector: list[float],
    top_k: int,
    max_distance: float,
    document_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    qs = Chunk.objects.filter(owner=owner).select_related("document")
    if document_ids:
        qs = qs.filter(document_id__in=document_ids)
    qs = qs.annotate(distance=CosineDistance("embedding", question_vector)).order_by("distance")[:top_k]
    return [RetrievedChunk(c, float(c.distance)) for c in qs if c.distance <= max_distance]


def ask(owner, question: str, document_ids: list[int] | None = None, top_k: int | None = None) -> Query:
    with stage("ask", owner__id=owner.pk) as span:
        query = _ask(owner, question, document_ids, top_k)
        set_attributes(
            span,
            query__id=query.pk,
            query__abstained=not query.retrieved_chunk_ids,
            query__cited_count=query.cited_chunks.count(),
            cost_usd=float(query.cost_usd),
            latency_ms=query.latency_ms,
        )
        return query


def _ask(owner, question: str, document_ids: list[int] | None, top_k: int | None) -> Query:
    budget.ensure_available(owner)
    started = time.monotonic()
    provider = get_provider()
    top_k = top_k or settings.RAG_TOP_K

    with stage("ask.embed", llm__provider=provider.name) as span:
        embedded = provider.embed([question])
        set_attributes(span, llm__embedding_tokens=embedded.usage.input_tokens)
    with stage("ask.retrieve", top_k=top_k, max_distance=provider.max_distance) as span:
        hits = retrieve(owner, embedded.vectors[0], top_k, provider.max_distance, document_ids)
        set_attributes(
            span,
            retrieved_count=len(hits),
            min_distance=min((h.distance for h in hits), default=None),
        )

    if hits:
        context = [ContextChunk(h.chunk.pk, h.chunk.document.title, h.chunk.text) for h in hits]
        with stage("ask.answer", llm__provider=provider.name, chunk_count=len(context)) as span:
            result = provider.answer(question, context)
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

    query = Query.objects.create(
        owner=owner,
        question=question,
        answer=result.answer,
        retrieved_chunk_ids=retrieved_ids,
        provider=provider.name,
        model=result.model,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        embedding_tokens=embedded.usage.input_tokens,
        cost_usd=chat_cost(result.usage) + embedding_cost(embedded.usage),
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
