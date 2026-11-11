from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.accounts.models import Guest
from apps.accounts.services import create_guest, is_guest, purge_expired_guests
from apps.core import budget
from apps.core.budget import BudgetExceededError
from apps.core.models import DailySpend
from apps.documents.models import Chunk, Document
from apps.documents.samples import load_samples
from apps.documents.services import Upload, UploadLimitError, ingest
from apps.qa.services import ask
from rag import providers

pytestmark = pytest.mark.django_db


def test_create_guest_expires_in_a_day():
    user = create_guest()
    assert is_guest(user)
    assert user.guest.expires_at - timezone.now() > timedelta(hours=23)
    assert not user.has_usable_password()


def test_registered_user_is_not_guest(user):
    assert not is_guest(user)


def test_purge_removes_expired_guest_and_their_data():
    old = create_guest()
    load_samples(old)
    Guest.objects.filter(user=old).update(expires_at=timezone.now() - timedelta(minutes=1))
    fresh = create_guest()  # creating a guest purges expired ones

    assert not get_user_model().objects.filter(pk=old.pk).exists()
    assert not Document.objects.filter(owner_id=old.pk).exists()
    assert not Chunk.objects.filter(owner_id=old.pk).exists()
    assert get_user_model().objects.filter(pk=fresh.pk).exists()


def test_purge_command(capsys):
    g = create_guest()
    Guest.objects.filter(user=g).update(expires_at=timezone.now() - timedelta(seconds=1))
    call_command("purge_guests")
    assert "purged 1" in capsys.readouterr().out
    assert purge_expired_guests() == 0


def test_guest_document_limit(settings):
    settings.GUEST_MAX_DOCUMENTS = 1
    g = create_guest()
    ingest(g, Upload("a.txt", "text/plain", b"first document"))
    with pytest.raises(UploadLimitError):
        ingest(g, Upload("b.txt", "text/plain", b"second document"))


def test_guest_size_limit_but_registered_users_get_more(settings, user):
    settings.GUEST_MAX_UPLOAD_BYTES = 10
    with pytest.raises(UploadLimitError):
        ingest(create_guest(), Upload("a.txt", "text/plain", b"x" * 11))
    assert ingest(user, Upload("a.txt", "text/plain", b"x" * 11)).pk


def test_registered_user_size_limit(settings, user):
    settings.MAX_UPLOAD_BYTES = 10
    with pytest.raises(UploadLimitError):
        ingest(user, Upload("a.txt", "text/plain", b"x" * 11))


def test_api_maps_guest_limit_to_422(settings):
    from rest_framework.test import APIClient

    settings.GUEST_MAX_UPLOAD_BYTES = 5
    client = APIClient()
    client.force_authenticate(create_guest())
    resp = client.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("a.txt", b"too long")}, format="multipart"
    )
    assert resp.status_code == 422


def test_load_samples_is_idempotent(user):
    first = load_samples(user)
    assert len(first) == 3
    assert load_samples(user) == []


@pytest.fixture
def paid_provider(monkeypatch, settings):
    """Make the fake provider look like a paid one so the budget is enforced."""
    settings.DEMO_DAILY_BUDGET_USD = 0.01
    monkeypatch.setattr(providers.FakeProvider, "name", "paid-fake")


def test_budget_not_enforced_for_free_provider(settings, user):
    settings.DEMO_DAILY_BUDGET_USD = 0.01
    DailySpend.objects.create(day=timezone.now().date(), cost_usd=Decimal("5"))
    budget.ensure_available()  # fake provider costs nothing: no cap


def test_budget_disabled_when_zero(settings, paid_provider):
    settings.DEMO_DAILY_BUDGET_USD = 0
    DailySpend.objects.create(day=timezone.now().date(), cost_usd=Decimal("5"))
    budget.ensure_available()


def test_budget_blocks_ask_and_upload_once_spent(paid_provider, user):
    DailySpend.objects.create(day=timezone.now().date(), cost_usd=Decimal("0.01"))
    with pytest.raises(BudgetExceededError):
        ask(user, "anything?")
    with pytest.raises(BudgetExceededError):
        ingest(user, Upload("a.txt", "text/plain", b"hello"))


def test_spend_is_recorded_from_queries_and_ingestion(user, settings):
    settings.CHAT_INPUT_PRICE_PER_MTOK = 1_000_000.0  # $1 per token, so the fake usage shows up
    settings.EMBEDDING_PRICE_PER_MTOK = 1_000_000.0
    ingest(user, Upload("c.txt", "text/plain", b"French press needs a coarse grind."))
    after_ingest = budget.spent_today()
    assert after_ingest > 0
    ask(user, "What grind does a French press need?")
    assert budget.spent_today() > after_ingest


def test_spend_survives_guest_deletion(settings):
    settings.EMBEDDING_PRICE_PER_MTOK = 1_000_000.0
    g = create_guest()
    ingest(g, Upload("c.txt", "text/plain", b"some words here"))
    spent = budget.spent_today()
    g.delete()
    assert budget.spent_today() == spent


def test_api_returns_429_when_budget_spent(paid_provider, auth_api):
    DailySpend.objects.create(day=timezone.now().date(), cost_usd=Decimal("1"))
    resp = auth_api.post("/api/v1/ask/", {"question": "x"}, format="json")
    assert resp.status_code == 429
    resp = auth_api.post(
        "/api/v1/documents/", {"file": SimpleUploadedFile("a.txt", b"hello")}, format="multipart"
    )
    assert resp.status_code == 429
