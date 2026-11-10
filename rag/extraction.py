"""Turn an uploaded file into plain text."""

import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError

TEXT_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
PDF_TYPE = "application/pdf"
SUPPORTED_EXTENSIONS = {".txt": "text/plain", ".md": "text/markdown", ".pdf": PDF_TYPE}


class ExtractionError(ValueError):
    pass


def extract_text(data: bytes, content_type: str) -> str:
    if content_type in TEXT_TYPES:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ExtractionError("text files must be UTF-8") from exc
    if content_type == PDF_TYPE:
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as exc:
            raise ExtractionError("could not read PDF") from exc
    raise ExtractionError(f"unsupported content type: {content_type}")
