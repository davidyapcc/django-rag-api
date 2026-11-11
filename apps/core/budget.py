"""The Demo budget: a global cap on LLM spend per UTC day."""

from decimal import Decimal

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from rag.providers import get_provider

from .models import DailySpend


class BudgetExceededError(Exception):
    pass


def _limit() -> Decimal:
    return Decimal(str(settings.DEMO_DAILY_BUDGET_USD))


def _enforced() -> bool:
    # The offline provider costs nothing, so there is nothing to cap.
    return _limit() > 0 and get_provider().name != "fake"


def spent_today() -> Decimal:
    row = DailySpend.objects.filter(day=timezone.now().date()).first()
    return row.cost_usd if row else Decimal(0)


def ensure_available() -> None:
    if _enforced() and spent_today() >= _limit():
        raise BudgetExceededError(
            "The demo's daily budget has been reached. Please try again tomorrow (UTC)."
        )


def record(cost_usd: Decimal) -> None:
    if cost_usd <= 0:
        return
    day = timezone.now().date()
    DailySpend.objects.get_or_create(day=day)
    DailySpend.objects.filter(day=day).update(cost_usd=F("cost_usd") + cost_usd)
