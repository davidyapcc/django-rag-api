"""Django tasks backend for Upstash QStash plus QStash request-signature verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import urllib.request
from typing import Any

import jwt
from django.conf import settings
from django.tasks.backends.base import BaseTaskBackend
from django.tasks.base import TaskResult, TaskResultStatus
from django.tasks.exceptions import InvalidTask
from django.tasks.signals import task_enqueued
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string


def _post(url: str, headers: dict[str, str], body: bytes) -> dict[str, Any]:
    if not url.startswith(("https://", "http://")):
        raise ValueError("QStash URL must use http or https")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
        raw = resp.read()
    return json.loads(raw) if raw else {}


class QStashBackend(BaseTaskBackend):
    """Push-queue backend that publishes Document ingestion tasks to Upstash QStash."""

    def enqueue(self, task, args, kwargs) -> TaskResult:
        self.validate_task(task)
        if "document_id" in kwargs:
            document_id = kwargs["document_id"]
        elif len(args) == 1 and not kwargs:
            document_id = args[0]
        else:
            raise InvalidTask("QStashBackend expects a single integer document_id.")
        if isinstance(document_id, bool) or not isinstance(document_id, int):
            raise InvalidTask("document_id must be an integer.")
        if not settings.QSTASH_TOKEN:
            raise ValueError("QSTASH_TOKEN is not set")

        base = settings.QSTASH_CALLBACK_BASE_URL.rstrip("/")
        callback_url = f"{base}{reverse('ingest-callback')}"
        failure_url = f"{base}{reverse('ingest-failure-callback')}"
        publish_url = f"{settings.QSTASH_URL.rstrip('/')}/v2/publish/{callback_url}"

        headers = {
            "Authorization": f"Bearer {settings.QSTASH_TOKEN}",
            "Content-Type": "application/json",
            "Upstash-Failure-Callback": failure_url,
        }
        body = json.dumps({"document_id": document_id}).encode("utf-8")
        resp = _post(publish_url, headers, body)

        task_result: TaskResult = TaskResult(
            task=task,
            id=str(resp.get("messageId") or get_random_string(32)),
            status=TaskResultStatus.READY,
            enqueued_at=timezone.now(),
            started_at=None,
            last_attempted_at=None,
            finished_at=None,
            args=list(args),
            kwargs=dict(kwargs),
            backend=self.alias,
            errors=[],
            worker_ids=[],
        )
        task_enqueued.send(type(self), task_result=task_result)
        return task_result


def _body_hash(body: bytes) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(body).digest()).rstrip(b"=").decode("ascii")


def verify_qstash_signature(body: bytes, signature: str) -> bool:
    """Verify the Upstash-Signature JWT against the current or next signing key."""
    if not signature:
        return False
    keys = [k for k in (settings.QSTASH_CURRENT_SIGNING_KEY, settings.QSTASH_NEXT_SIGNING_KEY) if k]
    if not keys:
        return False
    expected = _body_hash(body)
    for key in keys:
        try:
            claims = jwt.decode(
                signature,
                key,
                algorithms=["HS256"],
                issuer="Upstash",
                options={"require": ["iss", "exp", "body"]},
            )
        except jwt.PyJWTError:
            continue
        claim_body = str(claims.get("body", "")).rstrip("=").replace("+", "-").replace("/", "_")
        if hmac.compare_digest(claim_body, expected):
            return True
    return False
