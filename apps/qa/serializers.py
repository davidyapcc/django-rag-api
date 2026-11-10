from rest_framework import serializers

from apps.documents.models import Chunk

from .models import Query


class AskSerializer(serializers.Serializer):
    question = serializers.CharField(max_length=2000)
    document_ids = serializers.ListField(child=serializers.IntegerField(), required=False, max_length=50)
    top_k = serializers.IntegerField(required=False, min_value=1, max_value=20)


class CitationSerializer(serializers.ModelSerializer):
    chunk_id = serializers.IntegerField(source="id")
    document_id = serializers.IntegerField()
    document_title = serializers.CharField(source="document.title")

    class Meta:
        model = Chunk
        fields = ["chunk_id", "document_id", "document_title", "index", "text"]


class QuerySerializer(serializers.ModelSerializer):
    citations = CitationSerializer(source="cited_chunks", many=True, read_only=True)

    class Meta:
        model = Query
        fields = [
            "id",
            "question",
            "answer",
            "citations",
            "provider",
            "model",
            "input_tokens",
            "output_tokens",
            "embedding_tokens",
            "cost_usd",
            "latency_ms",
            "created_at",
        ]
        read_only_fields = fields


class UsageSummarySerializer(serializers.Serializer):
    queries = serializers.IntegerField()
    input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()
    embedding_tokens = serializers.IntegerField()
    cost_usd = serializers.DecimalField(max_digits=14, decimal_places=8)
