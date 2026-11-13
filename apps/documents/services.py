"""Document ingestion: accept upload (extract text) -> enqueue task (chunk -> embed -> store)."""

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.tasks import task

from apps.accounts.services import is_guest
from apps.core import budget
from apps.core.budget import BudgetExceededError
from rag.chunking import chunk_text
from rag.extraction import ExtractionError, extract_text
from rag.pricing import embedding_cost
from rag.providers import ProviderError, get_provider
from rag.tracing import set_attributes, stage
from rag.types import Usage

from .models import Chunk, Document

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64


class IngestionError(Exception):
    pass


class DuplicateDocumentError(IngestionError):
    def __init__(self, existing: Document) -> None:
        super().__init__("document already uploaded")
        self.existing = existing


class UploadLimitError(IngestionError):
    pass


@dataclass(frozen=True)
class Upload:
    title: str
    content_type: str
    data: bytes


def check_upload_allowed(owner, size_bytes: int) -> None:
    """Guests are anonymous, so they get a smaller allowance than registered users."""
    limit = settings.GUEST_MAX_UPLOAD_BYTES if is_guest(owner) else settings.MAX_UPLOAD_BYTES
    if size_bytes > limit:
        raise UploadLimitError(f"file too large; max {limit // 1024} KB")
    if is_guest(owner) and Document.objects.filter(owner=owner).count() >= settings.GUEST_MAX_DOCUMENTS:
        raise UploadLimitError(
            f"guests can keep up to {settings.GUEST_MAX_DOCUMENTS} documents; delete one or sign up"
        )


def ingest(owner, upload: Upload) -> Document:
    with stage("ingest", owner__id=owner.pk, document__size_bytes=len(upload.data)) as span:
        doc = _accept_upload(owner, upload)
        ingest_document.enqueue(doc.pk)
        doc.refresh_from_db()
        set_attributes(span, document__id=doc.pk, document__chunk_count=doc.chunk_count)
        return doc


def _accept_upload(owner, upload: Upload) -> Document:
    check_upload_allowed(owner, len(upload.data))
    sha = hashlib.sha256(upload.data).hexdigest()
    existing = Document.objects.filter(owner=owner, sha256=sha).first()
    if existing:
        raise DuplicateDocumentError(existing)

    budget.ensure_available(owner)
    with stage("ingest.extract", document__content_type=upload.content_type):
        try:
            text = extract_text(upload.data, upload.content_type)
        except ExtractionError as exc:
            raise IngestionError(str(exc)) from exc
    if not text.strip():
        raise IngestionError("document contains no extractable text")

    return Document.objects.create(
        owner=owner,
        title=upload.title,
        content_type=upload.content_type,
        size_bytes=len(upload.data),
        sha256=sha,
        text=text,
        status=Document.Status.PENDING,
    )


def _mark_failed(doc: Document, error: str) -> None:
    doc.status = Document.Status.FAILED
    doc.error = error
    doc.save(update_fields=["status", "error"])


@task
def ingest_document(document_id: int) -> None:
    doc = Document.objects.select_related("owner").filter(pk=document_id).first()
    if doc is None or doc.status != Document.Status.PENDING:
        return

    try:
        budget.ensure_available(doc.owner)
    except BudgetExceededError as exc:
        _mark_failed(doc, str(exc))
        return

    with stage("ingest.chunk") as span:
        pieces = chunk_text(doc.text)
        set_attributes(span, chunk_count=len(pieces))
    if not pieces:
        _mark_failed(doc, "document contains no extractable text")
        return

    provider = get_provider()
    vectors: list[list[float]] = []
    tokens = 0
    try:
        with stage("ingest.embed", llm__provider=provider.name, chunk_count=len(pieces)) as span:
            try:
                for start in range(0, len(pieces), EMBED_BATCH_SIZE):
                    result = provider.embed(pieces[start : start + EMBED_BATCH_SIZE])
                    vectors.extend(result.vectors)
                    tokens += result.usage.input_tokens
            except ProviderError:
                logger.exception("embedding failed for %s", doc.title)
                raise
            finally:
                cost = embedding_cost(Usage(input_tokens=tokens))
                set_attributes(span, llm__embedding_tokens=tokens, cost_usd=float(cost))
                budget.record(doc.owner, cost)
    except ProviderError as exc:
        if not exc.transient:
            _mark_failed(doc, str(exc) or "embedding failed")
            return
        raise

    with stage("ingest.store", chunk_count=len(pieces)), transaction.atomic():
        locked = Document.objects.select_for_update().get(pk=doc.pk)
        if locked.status != Document.Status.PENDING:
            return
        Chunk.objects.bulk_create(
            Chunk(document=locked, owner=locked.owner, index=i, text=t, embedding=v)
            for i, (t, v) in enumerate(zip(pieces, vectors, strict=True))
        )
        locked.status = Document.Status.READY
        locked.error = ""
        locked.chunk_count = len(pieces)
        locked.embedding_tokens = tokens
        locked.save(update_fields=["status", "error", "chunk_count", "embedding_tokens"])
    logger.info("ingested document=%s chunks=%d tokens=%d", doc.pk, len(pieces), tokens)


def fail_document(document_id: int, error: str = "embedding provider unavailable") -> None:
    Document.objects.filter(pk=document_id, status=Document.Status.PENDING).update(
        status=Document.Status.FAILED,
        error=error,
    )


def max_upload_bytes() -> int:
    return int(settings.MAX_UPLOAD_BYTES)
