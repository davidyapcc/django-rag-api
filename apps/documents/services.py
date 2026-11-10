"""Document ingestion: extract -> chunk -> embed -> store, in one transaction."""

import hashlib
import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from rag.chunking import chunk_text
from rag.extraction import ExtractionError, extract_text
from rag.providers import ProviderError, get_provider

from .models import Chunk, Document

logger = logging.getLogger(__name__)

EMBED_BATCH_SIZE = 64


class IngestionError(Exception):
    pass


class DuplicateDocumentError(IngestionError):
    def __init__(self, existing: Document) -> None:
        super().__init__("document already uploaded")
        self.existing = existing


@dataclass(frozen=True)
class Upload:
    title: str
    content_type: str
    data: bytes


def ingest(owner, upload: Upload) -> Document:
    sha = hashlib.sha256(upload.data).hexdigest()
    existing = Document.objects.filter(owner=owner, sha256=sha).first()
    if existing:
        raise DuplicateDocumentError(existing)

    try:
        text = extract_text(upload.data, upload.content_type)
    except ExtractionError as exc:
        raise IngestionError(str(exc)) from exc
    pieces = chunk_text(text)
    if not pieces:
        raise IngestionError("document contains no extractable text")

    provider = get_provider()
    vectors: list[list[float]] = []
    tokens = 0
    try:
        for start in range(0, len(pieces), EMBED_BATCH_SIZE):
            result = provider.embed(pieces[start : start + EMBED_BATCH_SIZE])
            vectors.extend(result.vectors)
            tokens += result.usage.input_tokens
    except ProviderError:
        logger.exception("embedding failed for %s", upload.title)
        raise

    with transaction.atomic():
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
