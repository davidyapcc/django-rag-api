from pathlib import Path

from rest_framework import serializers

from rag.extraction import SUPPORTED_EXTENSIONS

from .models import Chunk, Document
from .services import max_upload_bytes


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = [
            "id",
            "title",
            "content_type",
            "size_bytes",
            "status",
            "error",
            "chunk_count",
            "embedding_tokens",
            "created_at",
        ]
        read_only_fields = fields


class DocumentUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    title = serializers.CharField(max_length=255, required=False, allow_blank=False)

    def validate_file(self, f):
        ext = Path(f.name).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
            raise serializers.ValidationError(f"unsupported file type; allowed: {allowed}")
        if f.size > max_upload_bytes():
            raise serializers.ValidationError(f"file too large; max {max_upload_bytes()} bytes")
        return f


class ChunkSerializer(serializers.ModelSerializer):
    class Meta:
        model = Chunk
        fields = ["id", "index", "text"]
        read_only_fields = fields
