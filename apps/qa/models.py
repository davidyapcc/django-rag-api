from django.conf import settings
from django.db import models


class Query(models.Model):
    """One /ask call: what was asked, what came back, and what it cost. A Query with a
    predecessor is a Follow-up: retrieval and answering ran on its standalone question."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="queries")
    predecessor = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="follow_ups"
    )
    question = models.TextField()  # as asked
    # Set only on a Follow-up: what retrieval and answering actually ran on.
    standalone_question = models.TextField(null=True, blank=True)  # noqa: DJ001
    answer = models.TextField()
    cited_chunks = models.ManyToManyField("documents.Chunk", blank=True, related_name="+")
    retrieved_chunk_ids = models.JSONField(default=list)
    provider = models.CharField(max_length=32)
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    embedding_tokens = models.PositiveIntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "queries"

    def __str__(self) -> str:
        return self.question[:60]
