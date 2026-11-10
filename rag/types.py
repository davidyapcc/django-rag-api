from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextChunk:
    """A retrieved chunk handed to the chat model."""

    id: int
    document_title: str
    text: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class AnswerResult:
    answer: str
    cited_chunk_ids: list[int]
    model: str
    usage: Usage = field(default_factory=Usage)
