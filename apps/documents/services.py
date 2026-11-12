"""Document ingestion: extract -> chunk -> embed -> store, in one transaction."""

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from apps.accounts.services import is_guest
from apps.core import budget
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
        doc = _ingest(owner, upload)
        set_attributes(span, document__id=doc.pk, document__chunk_count=doc.chunk_count)
        return doc


def _ingest(owner, upload: Upload) -> Document:
    check_upload_allowed(owner, len(upload.data))
    sha = hashlib.sha256(upload.data).hexdigest()
    existing = Document.objects.filter(owner=owner, sha256=sha).first()
    if existing:
        raise DuplicateDocumentError(existing)

    with stage("ingest.extract", document__content_type=upload.content_type):
        try:
            text = extract_text(upload.data, upload.content_type)
        except ExtractionError as exc:
            raise IngestionError(str(exc)) from exc
    with stage("ingest.chunk") as span:
        pieces = chunk_text(text)
        set_attributes(span, chunk_count=len(pieces))
    if not pieces:
        raise IngestionError("document contains no extractable text")

    budget.ensure_available(owner)
    provider = get_provider()
    vectors: list[list[float]] = []
    tokens = 0
    with stage("ingest.embed", llm__provider=provider.name, chunk_count=len(pieces)) as span:
        try:
            for start in range(0, len(pieces), EMBED_BATCH_SIZE):
                result = provider.embed(pieces[start : start + EMBED_BATCH_SIZE])
                vectors.extend(result.vectors)
                tokens += result.usage.input_tokens
        except ProviderError:
            logger.exception("embedding failed for %s", upload.title)
            raise
        finally:
            cost = embedding_cost(Usage(input_tokens=tokens))
            set_attributes(span, llm__embedding_tokens=tokens, cost_usd=float(cost))
            budget.record(owner, cost)

    with stage("ingest.store", chunk_count=len(pieces)), transaction.atomic():
        doc = Document.objects.create(
            owner=owner,
            title=upload.title,
            content_type=upload.content_type,
            size_bytes=len(upload.data),
            sha256=sha,
            status=Document.Status.READY,
            chunk_count=len(pieces),
            embedding_tokens=tokens,
        )
        Chunk.objects.bulk_create(
            Chunk(document=doc, owner=owner, index=i, text=t, embedding=v)
            for i, (t, v) in enumerate(zip(pieces, vectors, strict=True))
        )
    logger.info("ingested document=%s chunks=%d tokens=%d", doc.pk, len(pieces), tokens)
    return doc


def max_upload_bytes() -> int:
    return int(settings.MAX_UPLOAD_BYTES)
