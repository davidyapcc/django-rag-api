"""Sample documents: the eval corpus, loadable in one click for the demo."""

from django.conf import settings

from .models import Document
from .services import DuplicateDocumentError, Upload, ingest

SAMPLE_DIR = settings.BASE_DIR / "evals" / "corpus"

SUGGESTED_QUESTIONS = [
    "What grind size does a French press need?",
    "Which should I restart first, the modem or the router?",
    "How long does bulk fermentation take?",
    "What is the capital city of Australia?",
]


def load_samples(owner) -> list[Document]:
    """Ingest every sample the owner doesn't already have. Returns the newly added ones."""
    added = []
    for path in sorted(SAMPLE_DIR.glob("*.md")):
        try:
            added.append(ingest(owner, Upload(path.name, "text/markdown", path.read_bytes())))
        except DuplicateDocumentError:
            continue
    return added
