"""Golden-question eval for retrieval and answers.

Metrics:
- retrieval_hit_rate: share of answerable questions whose source document is
  among the retrieved chunks.
- citation_precision: share of cited chunks that come from the expected document.
- answer_keyword_rate: share of answerable answers containing every expected phrase.
- abstain_rate: share of unanswerable questions answered with no citations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.documents.models import Chunk
from apps.documents.services import Upload, ingest
from apps.qa.services import ask

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
GOLDEN_PATH = EVAL_DIR / "golden.json"


@dataclass
class CaseResult:
    question: str
    retrieved_hit: bool | None
    cited_correct: int
    cited_total: int
    keywords_ok: bool | None
    abstained: bool | None
    answer: str


@dataclass
class EvalReport:
    cases: list[CaseResult] = field(default_factory=list)
    cost_usd: float = 0.0

    def _rate(self, values: list[bool]) -> float:
        return sum(values) / len(values) if values else 1.0

    @property
    def retrieval_hit_rate(self) -> float:
        return self._rate([c.retrieved_hit for c in self.cases if c.retrieved_hit is not None])

    @property
    def answer_keyword_rate(self) -> float:
        return self._rate([c.keywords_ok for c in self.cases if c.keywords_ok is not None])

    @property
    def abstain_rate(self) -> float:
        return self._rate([c.abstained for c in self.cases if c.abstained is not None])

    @property
    def citation_precision(self) -> float:
        total = sum(c.cited_total for c in self.cases)
        return sum(c.cited_correct for c in self.cases) / total if total else 1.0

    def as_dict(self) -> dict:
        return {
            "cases": len(self.cases),
            "retrieval_hit_rate": round(self.retrieval_hit_rate, 3),
            "citation_precision": round(self.citation_precision, 3),
            "answer_keyword_rate": round(self.answer_keyword_rate, 3),
            "abstain_rate": round(self.abstain_rate, 3),
            "cost_usd": round(self.cost_usd, 6),
        }


def run_eval(rollback: bool = True) -> EvalReport:
    """Ingest the corpus for a throwaway user, ask every golden question, score it.

    Runs in a transaction that is rolled back, so it leaves no data behind.
    """
    golden = json.loads(GOLDEN_PATH.read_text())
    report = EvalReport()

    with transaction.atomic():
        user = get_user_model().objects.create_user(username="__eval__", password=None)
        doc_ids: dict[str, int] = {}
        for path in sorted(CORPUS_DIR.glob("*.md")):
            doc = ingest(user, Upload(path.name, "text/markdown", path.read_bytes()))
            doc_ids[path.name] = doc.pk

        for case in golden:
            q = ask(user, case["question"])
            report.cost_usd += float(q.cost_usd)
            cited_docs = list(q.cited_chunks.values_list("document_id", flat=True))
            expected = case["document"]
            if expected is None:
                report.cases.append(CaseResult(case["question"], None, 0, 0, None, not cited_docs, q.answer))
                continue
            retrieved_docs = set(
                Chunk.objects.filter(pk__in=q.retrieved_chunk_ids).values_list("document_id", flat=True)
            )
            want = doc_ids[expected]
            answer = q.answer.lower()
            report.cases.append(
                CaseResult(
                    question=case["question"],
                    retrieved_hit=want in retrieved_docs,
                    cited_correct=sum(1 for d in cited_docs if d == want),
                    cited_total=len(cited_docs),
                    keywords_ok=all(k.lower() in answer for k in case["expect"]),
                    abstained=None,
                    answer=q.answer,
                )
            )
        if rollback:
            transaction.set_rollback(True)
    return report
