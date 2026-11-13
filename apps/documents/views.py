import base64
import json
from pathlib import Path

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
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
from .services import (
    DuplicateDocumentError,
    IngestionError,
    Upload,
    fail_document,
    ingest,
    ingest_document,
)
from .tasks import verify_qstash_signature


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
        request={"multipart/form-data": DocumentUploadSerializer}, responses={202: DocumentSerializer}
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
        return Response(DocumentSerializer(doc).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses={200: ChunkSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def chunks(self, request: Request, pk: str | None = None) -> Response:
        doc = self.get_object()
        page = self.paginate_queryset(doc.chunks.all())
        return self.get_paginated_response(ChunkSerializer(page, many=True).data)


def _parse_document_id(body: bytes, *, allow_source_body: bool = False) -> int | None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if allow_source_body and "sourceBody" in payload and "document_id" not in payload:
        try:
            raw_source = base64.b64decode(payload["sourceBody"])
            payload = json.loads(raw_source)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
    document_id = payload.get("document_id")
    if isinstance(document_id, bool) or not isinstance(document_id, int):
        return None
    return document_id


def _verified_document_id(
    request: HttpRequest, *, allow_source_body: bool = False
) -> tuple[int | None, HttpResponse | None]:
    if not verify_qstash_signature(request.body, request.headers.get("Upstash-Signature", "")):
        return None, JsonResponse({"detail": "invalid signature"}, status=401)
    document_id = _parse_document_id(request.body, allow_source_body=allow_source_body)
    if document_id is None:
        return None, JsonResponse({"detail": "invalid payload"}, status=400)
    return document_id, None


@csrf_exempt
@require_POST
def ingest_callback(request: HttpRequest) -> HttpResponse:
    document_id, error = _verified_document_id(request)
    if error is not None or document_id is None:
        return error or JsonResponse({"detail": "invalid payload"}, status=400)
    try:
        ingest_document.call(document_id)
    except ProviderError:
        return JsonResponse({"detail": "embedding provider unavailable"}, status=502)
    return JsonResponse({"status": "ok"}, status=200)


@csrf_exempt
@require_POST
def ingest_failure_callback(request: HttpRequest) -> HttpResponse:
    document_id, error = _verified_document_id(request, allow_source_body=True)
    if error is not None or document_id is None:
        return error or JsonResponse({"detail": "invalid payload"}, status=400)
    fail_document(document_id)
    return JsonResponse({"status": "ok"}, status=200)
