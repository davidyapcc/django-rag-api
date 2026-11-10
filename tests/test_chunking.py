import pytest

from rag.chunking import chunk_text


def test_empty_text_gives_no_chunks():
    assert chunk_text("   \n\n ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("Hello world.") == ["Hello world."]


def test_paragraphs_are_packed_up_to_limit():
    text = "\n\n".join(["a" * 300] * 5)
    chunks = chunk_text(text, max_chars=700, overlap_chars=50)
    assert len(chunks) > 1
    assert all(len(c) <= 700 for c in chunks)


def test_long_sentence_is_hard_wrapped():
    chunks = chunk_text("x" * 2500, max_chars=1000, overlap_chars=100)
    assert all(len(c) <= 1000 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks).count("x") >= 2500


def test_overlap_carries_context_between_chunks():
    words = " ".join(f"word{i}." for i in range(400))
    chunks = chunk_text(words, max_chars=500, overlap_chars=100)
    assert len(chunks) > 2
    last_word_of_first = chunks[0].split()[-1]
    assert last_word_of_first in chunks[1]


def test_invalid_overlap_rejected():
    with pytest.raises(ValueError):
        chunk_text("abc", max_chars=100, overlap_chars=100)
