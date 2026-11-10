import json
import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import openai
import pytest

from rag import providers
from rag.pricing import chat_cost, embedding_cost
from rag.providers import FakeProvider, OpenAIProvider, ProviderError, get_provider
from rag.types import ContextChunk, Usage


def test_fake_embeddings_are_normalised_and_deterministic():
    p = FakeProvider(dim=64)
    a, b = p.embed(["coffee grind", "coffee grind"]).vectors
    assert a == b
    assert math.isclose(sum(v * v for v in a), 1.0)


def test_fake_embedding_of_stopwords_is_not_zero():
    vec = FakeProvider(dim=8).embed(["the and of"]).vectors[0]
    assert any(vec)


def test_fake_answer_extracts_best_sentence():
    p = FakeProvider(dim=8)
    chunks = [
        ContextChunk(1, "a", "Cats sleep a lot."),
        ContextChunk(2, "b", "# Coffee\nCoffee needs hot water. Tea is different."),
    ]
    result = p.answer("How hot should coffee water be?", chunks)
    assert result.cited_chunk_ids == [2]
    assert result.answer == "Coffee needs hot water."


def test_fake_answer_without_chunks_abstains():
    assert FakeProvider(dim=8).answer("anything", []).cited_chunk_ids == []


def test_unknown_provider(settings):
    settings.LLM_PROVIDER = "nope"
    providers._build.cache_clear()
    with pytest.raises(ProviderError):
        get_provider()


def test_openai_requires_key(settings):
    settings.OPENAI_API_KEY = ""
    with pytest.raises(ProviderError):
        OpenAIProvider()


@pytest.fixture
def openai_provider(settings):
    settings.OPENAI_API_KEY = "sk-test"
    p = OpenAIProvider()
    p.client = MagicMock()
    return p


def test_openai_embed_orders_by_index(openai_provider):
    openai_provider.client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(index=1, embedding=[2.0]), SimpleNamespace(index=0, embedding=[1.0])],
        usage=SimpleNamespace(prompt_tokens=7),
    )
    result = openai_provider.embed(["a", "b"])
    assert result.vectors == [[1.0], [2.0]]
    assert result.usage.input_tokens == 7


def _chat_response(content, refusal=None):
    return SimpleNamespace(
        model="gpt-test",
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=refusal))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
    )


def test_openai_answer_parses_structured_output(openai_provider):
    openai_provider.client.chat.completions.create.return_value = _chat_response(
        json.dumps({"answer": "Use 90C.", "cited_chunk_ids": [3]})
    )
    result = openai_provider.answer("temp?", [ContextChunk(3, "doc", "Use 90C.")])
    assert result.answer == "Use 90C."
    assert result.cited_chunk_ids == [3]
    assert result.usage == Usage(100, 20)
    kwargs = openai_provider.client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert '<chunk id="3"' in kwargs["messages"][1]["content"]


def test_openai_refusal_raises(openai_provider):
    openai_provider.client.chat.completions.create.return_value = _chat_response(None, refusal="no")
    with pytest.raises(ProviderError):
        openai_provider.answer("q", [])


def test_openai_invalid_json_raises(openai_provider):
    openai_provider.client.chat.completions.create.return_value = _chat_response("not json")
    with pytest.raises(ProviderError):
        openai_provider.answer("q", [])


@pytest.mark.parametrize("method", ["embed", "answer"])
def test_openai_api_errors_are_wrapped(openai_provider, method):
    err = openai.APIConnectionError(request=MagicMock())
    openai_provider.client.embeddings.create.side_effect = err
    openai_provider.client.chat.completions.create.side_effect = err
    with pytest.raises(ProviderError):
        openai_provider.embed(["x"]) if method == "embed" else openai_provider.answer("q", [])


def test_pricing(settings):
    settings.CHAT_INPUT_PRICE_PER_MTOK = 1.0
    settings.CHAT_OUTPUT_PRICE_PER_MTOK = 2.0
    settings.EMBEDDING_PRICE_PER_MTOK = 0.5
    assert float(chat_cost(Usage(1_000_000, 500_000))) == 2.0
    assert float(embedding_cost(Usage(2_000_000))) == 1.0
