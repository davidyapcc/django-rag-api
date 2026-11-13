from decimal import Decimal

from django.db.models import Count, Sum
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.budget import BudgetExceededError
from rag.providers import ProviderError

from .models import Query
from .serializers import AskSerializer, QuerySerializer, UsageSummarySerializer
from .services import PredecessorNotFoundError, ask


class AskView(generics.GenericAPIView):
    serializer_class = AskSerializer
    throttle_scope = "ask"

    @extend_schema(request=AskSerializer, responses={201: QuerySerializer, 404: None})
    def post(self, request: Request) -> Response:
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            query = ask(request.user, **ser.validated_data)
        except PredecessorNotFoundError:
            return Response({"detail": "Predecessor query not found."}, status=status.HTTP_404_NOT_FOUND)
        except BudgetExceededError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except ProviderError:
            return Response({"detail": "LLM provider unavailable"}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(QuerySerializer(query).data, status=status.HTTP_201_CREATED)


class QueryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = QuerySerializer

    def get_queryset(self):
        return Query.objects.filter(owner=self.request.user).prefetch_related("cited_chunks__document")

    @extend_schema(responses={200: UsageSummarySerializer})
    @action(detail=False, methods=["get"])
    def usage(self, request: Request) -> Response:
        totals = Query.objects.filter(owner_id=request.user.pk).aggregate(
            queries=Count("id"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
            embedding_tokens=Sum("embedding_tokens"),
            cost_usd=Sum("cost_usd"),
        )
        data = {k: v or 0 for k, v in totals.items()}
        data["cost_usd"] = totals["cost_usd"] or Decimal(0)
        return Response(UsageSummarySerializer(data).data)
