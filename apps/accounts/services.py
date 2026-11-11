"""Guests: one-click accounts that expire, taking everything they own with them."""

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import Guest

GUEST_TTL = timedelta(hours=24)


def is_guest(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and Guest.objects.filter(user_id=user.pk).exists()


def purge_expired_guests(now=None) -> int:
    """Delete expired Guests; cascades remove their Documents, Chunks and Queries."""
    now = now or timezone.now()
    user_ids = list(Guest.objects.filter(expires_at__lte=now).values_list("user_id", flat=True))
    get_user_model().objects.filter(pk__in=user_ids).delete()
    return len(user_ids)


@transaction.atomic
def create_guest():
    # Clean up on the way in: free hosting has no scheduler, and demo traffic is when it matters.
    purge_expired_guests()
    user = get_user_model().objects.create_user(username=f"guest-{secrets.token_hex(4)}", password=None)
    Guest.objects.create(user=user, expires_at=timezone.now() + GUEST_TTL)
    return user
