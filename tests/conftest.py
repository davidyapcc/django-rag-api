import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from rag import providers


@pytest.fixture(autouse=True)
def _fake_provider(settings):
    settings.LLM_PROVIDER = "fake"
    settings.SECURE_SSL_REDIRECT = False
    providers._build.cache_clear()
    cache.clear()  # throttling state
    yield
    providers._build.cache_clear()


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="alice", password="s3cure-Passw0rd!")


@pytest.fixture
def other_user(db):
    return get_user_model().objects.create_user(username="bob", password="s3cure-Passw0rd!")


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def auth_api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


COFFEE = (
    b"# Coffee\n\nUse water between 90 and 96 degrees Celsius for brewing.\n\n"
    b"French press needs a coarse grind so the metal filter can hold it back."
)


@pytest.fixture
def coffee_file():
    return SimpleUploadedFile("coffee.md", COFFEE, content_type="text/markdown")


@pytest.fixture
def uploaded(auth_api, coffee_file):
    resp = auth_api.post("/api/v1/documents/", {"file": coffee_file}, format="multipart")
    assert resp.status_code == 201, resp.content
    return resp.json()
