import io

import pytest
from pypdf import PdfWriter

from rag.extraction import ExtractionError, extract_text


def test_plain_text():
    assert extract_text(b"hello", "text/plain") == "hello"


def test_non_utf8_text_rejected():
    with pytest.raises(ExtractionError):
        extract_text(b"\xff\xfe\xfa", "text/plain")


def test_unsupported_type_rejected():
    with pytest.raises(ExtractionError):
        extract_text(b"x", "image/png")


def test_blank_pdf_extracts_empty_text():
    buf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.write(buf)
    assert extract_text(buf.getvalue(), "application/pdf").strip() == ""


def test_corrupt_pdf_rejected():
    with pytest.raises(ExtractionError):
        extract_text(b"%PDF-1.4 not really a pdf", "application/pdf")
