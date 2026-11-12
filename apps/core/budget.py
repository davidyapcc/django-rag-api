"""LLM spend caps: the Demo budget (global, per UTC day) and each Owner's Allowance."""

from decimal import Decimal

from django.conf import settings
from django.db.models import F
from django.utils import timezone

from apps.accounts.services import is_guest
from rag.providers import get_provider

from .models import DailySpend, OwnerDailySpend


class BudgetExceededError(Exception):
    pass


class AllowanceExceededError(BudgetExceededError):
    """One Owner has used their Allowance; the Demo budget may still have room for others."""


def _limit() -> Decimal:
    return Decimal(str(settings.DEMO_DAILY_BUDGET_USD))


def allowance_for(owner) -> Decimal:
    value = settings.GUEST_ALLOWANCE_DAILY_USD if is_guest(owner) else settings.ALLOWANCE_DAILY_USD
    return Decimal(str(value))


def _paid() -> bool:
    # The offline provider costs nothing, so there is nothing to cap.
    return get_provider().name != "fake"


def spent_today() -> Decimal:
    row = DailySpend.objects.filter(day=timezone.now().date()).first()
    return row.cost_usd if row else Decimal(0)


def spent_today_by(owner) -> Decimal:
    row = OwnerDailySpend.objects.filter(owner_id=owner.pk, day=timezone.now().date()).first()
    return row.cost_usd if row else Decimal(0)


def ensure_available(owner) -> None:
    """Call before any provider call: checks the Demo budget, then the Owner's Allowance."""
    if not _paid():
        return
    if _limit() > 0 and spent_today() >= _limit():
        raise BudgetExceededError(
            "The demo's daily budget has been reached. Please try again tomorrow (UTC)."
        )
    allowance = allowance_for(owner)
    if allowance > 0 and spent_today_by(owner) >= allowance:
        raise AllowanceExceededError(
            f"You've used your daily allowance (USD {allowance:.2f}). Please try again tomorrow (UTC)."
        )


def record(owner, cost_usd: Decimal) -> None:
    """Call after any provider call: adds the cost to the Demo budget and the Owner's ledger."""
    if cost_usd <= 0:
        return
    day = timezone.now().date()
    DailySpend.objects.get_or_create(day=day)
    DailySpend.objects.filter(day=day).update(cost_usd=F("cost_usd") + cost_usd)
    OwnerDailySpend.objects.get_or_create(owner_id=owner.pk, day=day)
    OwnerDailySpend.objects.filter(owner_id=owner.pk, day=day).update(cost_usd=F("cost_usd") + cost_usd)
