"""Server-rendered demo UI. Calls the same services as the API, so the same rules apply."""

from pathlib import Path
from typing import cast

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import Guest
from apps.accounts.services import create_guest
from apps.core import budget
from apps.core.budget import BudgetExceededError
from apps.documents.models import Document
from apps.documents.samples import SUGGESTED_QUESTIONS, load_samples
from apps.documents.services import DuplicateDocumentError, IngestionError, Upload, ingest
from apps.qa.models import Query
from apps.qa.services import PredecessorNotFoundError, ask
from rag.extraction import SUPPORTED_EXTENSIONS
from rag.providers import ProviderError

from .forms import AskForm, SignUpForm, UploadForm
from .throttle import allowed

TOO_MANY = "You're going a bit fast. Please wait a moment and try again."


def landing(request: HttpRequest) -> HttpResponse:
    return render(request, "web/landing.html")


@require_POST
def start_guest(request: HttpRequest) -> HttpResponse:
    if not allowed(request, "guest"):
        messages.error(request, TOO_MANY)
        return redirect("web:landing")
    login(request, create_guest(), backend="django.contrib.auth.backends.ModelBackend")
    return redirect("web:app")


def signup(request: HttpRequest) -> HttpResponse:
    form = SignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save(), backend="django.contrib.auth.backends.ModelBackend")
        return redirect("web:app")
    return render(request, "registration/signup.html", {"form": form})


def _documents_context(request: HttpRequest) -> dict:
    guest = Guest.objects.filter(user_id=cast(int, request.user.pk)).first()
    return {
        "documents": Document.objects.filter(owner_id=request.user.pk),
        "guest": guest,
        "guest_max_documents": settings.GUEST_MAX_DOCUMENTS,
        "accept": ",".join(SUPPORTED_EXTENSIONS),
    }


def _history_context(request: HttpRequest) -> dict:
    queries = Query.objects.filter(owner_id=request.user.pk)
    totals = queries.aggregate(n=Count("id"), cost=Sum("cost_usd"))
    return {"queries": queries[:10], "totals": totals}


@login_required
def app(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "web/app.html",
        {
            **_documents_context(request),
            **_history_context(request),
            "ask_form": AskForm(),
            "suggested": SUGGESTED_QUESTIONS,
            "budget_spent": budget.spent_today(),
            "budget_limit": settings.DEMO_DAILY_BUDGET_USD,
        },
    )


def _documents_panel(request: HttpRequest, error: str = "", notice: str = "") -> HttpResponse:
    ctx = {**_documents_context(request), "error": error, "notice": notice}
    return render(request, "web/partials/documents.html", ctx)


@login_required
@require_POST
def upload(request: HttpRequest) -> HttpResponse:
    form = UploadForm(request.POST, request.FILES)
    if not form.is_valid():
        return _documents_panel(request, error="Choose a file to upload.")
    f = form.cleaned_data["file"]
    ext = Path(f.name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return _documents_panel(
            request, error=f"Unsupported file type. Use {', '.join(SUPPORTED_EXTENSIONS)}."
        )
    if not allowed(request, "upload"):
        return _documents_panel(request, error=TOO_MANY)
    try:
        doc = ingest(request.user, Upload(f.name, SUPPORTED_EXTENSIONS[ext], f.read()))
    except DuplicateDocumentError:
        return _documents_panel(request, error="You've already uploaded that document.")
    except (IngestionError, BudgetExceededError) as exc:
        return _documents_panel(request, error=str(exc).capitalize())
    if doc.status == Document.Status.PENDING:
        return _documents_panel(request, notice=f"Added {doc.title} (processing…).")
    if doc.status == Document.Status.FAILED:
        return _documents_panel(request, error=doc.error or f"Failed to process {doc.title}.")
    return _documents_panel(request, notice=f"Added {doc.title} ({doc.chunk_count} chunks).")


@login_required
@require_POST
def samples(request: HttpRequest) -> HttpResponse:
    try:
        added = load_samples(request.user)
    except (IngestionError, BudgetExceededError) as exc:
        return _documents_panel(request, error=str(exc).capitalize())
    notice = f"Loaded {len(added)} sample document(s)." if added else "Samples are already loaded."
    return _documents_panel(request, notice=notice)


@login_required
def document_row(request: HttpRequest, pk: int) -> HttpResponse:
    doc = get_object_or_404(Document, pk=pk, owner_id=request.user.pk)
    return render(request, "web/partials/document_row.html", {"d": doc})


@login_required
@require_POST
def delete_document(request: HttpRequest, pk: int) -> HttpResponse:
    get_object_or_404(Document, pk=pk, owner_id=request.user.pk).delete()
    return _documents_panel(request)


@login_required
@require_POST
def ask_view(request: HttpRequest) -> HttpResponse:
    form = AskForm(request.POST)
    ctx: dict = {}
    status = 200
    if not form.is_valid():
        ctx["error"] = "Type a question first."
    elif not allowed(request, "ask"):
        ctx["error"] = TOO_MANY
    else:
        try:
            ctx["query"] = ask(
                request.user,
                form.cleaned_data["question"],
                predecessor_id=form.cleaned_data["predecessor"],
            )
        except PredecessorNotFoundError:
            ctx["error"] = "That earlier question wasn't found."
            status = 404
        except BudgetExceededError as exc:
            ctx["error"] = str(exc)
        except ProviderError:
            ctx["error"] = "The language model is unavailable. Try again shortly."
    response = render(request, "web/partials/answer.html", ctx, status=status)
    if "query" in ctx:
        response["HX-Trigger"] = "query-created"  # refresh the history panel
    return response


@login_required
def history(request: HttpRequest) -> HttpResponse:
    return render(request, "web/partials/history.html", _history_context(request))
