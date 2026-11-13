from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        READY = "ready"
        FAILED = "failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents")
    title = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    text = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices)
    error = models.TextField(blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    embedding_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "sha256"], name="unique_document_per_owner"),
            # Target of Chunk's composite foreign key (document_id, owner_id); see ADR 0001.
            models.UniqueConstraint(fields=["id", "owner"], name="document_id_owner_key"),
        ]

    def __str__(self) -> str:
        return self.title


class Chunk(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    # Denormalised so retrieval can filter by owner without a join. A composite foreign key
    # (migration 0003) keeps it equal to document.owner and follows ownership changes.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    index = models.PositiveIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=settings.EMBEDDING_DIM)
    # Full-text side of hybrid retrieval (ADR 0004). Generated, so existing Chunks get it from
    # the migration with no re-embedding.
    search = models.GeneratedField(
        expression=SearchVector("text", config="english"),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        ordering = ["document_id", "index"]
        constraints = [
            models.UniqueConstraint(fields=["document", "index"], name="unique_chunk_index"),
        ]
        indexes = [
            HnswIndex(
                name="chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
            GinIndex(name="chunk_search_gin", fields=["search"]),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}#{self.index}"
