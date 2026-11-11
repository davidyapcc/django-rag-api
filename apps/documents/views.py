from pathlib import Path

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.budget import BudgetExceededError
from rag.extraction import SUPPORTED_EXTENSIONS
from rag.providers import ProviderError

from .models import Document
from .serializers import ChunkSerializer, DocumentSerializer, DocumentUploadSerializer
from .services import DuplicateDocumentError, IngestionError, Upload, ingest


class DocumentViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = DocumentSerializer
    parser_classes = [MultiPartParser]  # only upload takes a request body

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user)

    def get_throttles(self):
        self.throttle_scope = "upload" if self.action == "create" else ""
        return super().get_throttles()

    @extend_schema(
        request={"multipart/form-data": DocumentUploadSerializer}, responses={201: DocumentSerializer}
    )
    def create(self, request: Request) -> Response:
        upload_ser = DocumentUploadSerializer(data=request.data)
        upload_ser.is_valid(raise_exception=True)
        f = upload_ser.validated_data["file"]
        upload = Upload(
            title=upload_ser.validated_data.get("title") or f.name,
            content_type=SUPPORTED_EXTENSIONS[Path(f.name).suffix.lower()],
            data=f.read(),
        )
        try:
            doc = ingest(request.user, upload)
        except DuplicateDocumentError as exc:
            return Response(
                {"detail": str(exc), "document": DocumentSerializer(exc.existing).data},
                status=status.HTTP_409_CONFLICT,
            )
        except BudgetExceededError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except IngestionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except ProviderError:
            return Response({"detail": "embedding provider unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(DocumentSerializer(doc).data, status=status.HTTP_201_CREATED)

    @extend_schema(responses={200: ChunkSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def chunks(self, request: Request, pk: str | None = None) -> Response:
        doc = self.get_object()
        page = self.paginate_queryset(doc.chunks.all())
        return self.get_paginated_response(ChunkSerializer(page, many=True).data)
