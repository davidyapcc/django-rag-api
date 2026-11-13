from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from drf_spectacular.utils import extend_schema
from opentelemetry import trace
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.budget import BudgetExceededError
from rag.extraction import SUPPORTED_EXTENSIONS
from rag.providers import ProviderError
from rag.tracing import set_attributes

from .models import Document
from .qstash import parse_document_id, verify_qstash_signature
from .serializers import ChunkSerializer, DocumentSerializer, DocumentUploadSerializer
from .services import (
    DuplicateDocumentError,
    IngestionError,
    Upload,
    fail_document,
    ingest,
    ingest_document,
)


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
        except ProviderError:
            return Response({"detail": "embedding provider unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(DocumentSerializer(doc).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(responses={200: ChunkSerializer(many=True)})
    @action(detail=True, methods=["get"])
    def chunks(self, request: Request, pk: str | None = None) -> Response:
        doc = self.get_object()
        page = self.paginate_queryset(doc.chunks.all())
        return self.get_paginated_response(ChunkSerializer(page, many=True).data)


def _verified_document_id(request: HttpRequest, *, allow_source_body: bool = False) -> int | HttpResponse:
    expected_url = f"{settings.QSTASH_CALLBACK_BASE_URL.rstrip('/')}{request.path}"
    if not verify_qstash_signature(
        request.body, request.headers.get("Upstash-Signature", ""), url=expected_url
    ):
        return JsonResponse({"detail": "invalid signature"}, status=401)
    document_id = parse_document_id(request.body, allow_source_body=allow_source_body)
    if document_id is None:
        return JsonResponse({"detail": "invalid payload"}, status=400)
    raw_retried = request.headers.get("Upstash-Retried")
    retried = int(raw_retried) if raw_retried and raw_retried.isdigit() else None
    set_attributes(trace.get_current_span(), document__id=document_id, upstash__retried=retried)
    return document_id


@csrf_exempt
@require_POST
def ingest_callback(request: HttpRequest) -> HttpResponse:
    doc_or_err = _verified_document_id(request)
    if isinstance(doc_or_err, HttpResponse):
        return doc_or_err
    try:
        ingest_document.call(doc_or_err)
    except ProviderError:
        return JsonResponse({"detail": "embedding provider unavailable"}, status=502)
    return JsonResponse({"status": "ok"}, status=200)


@csrf_exempt
@require_POST
def ingest_failure_callback(request: HttpRequest) -> HttpResponse:
    doc_or_err = _verified_document_id(request, allow_source_body=True)
    if isinstance(doc_or_err, HttpResponse):
        return doc_or_err
    fail_document(doc_or_err)
    return JsonResponse({"status": "ok"}, status=200)
