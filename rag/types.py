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

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens, self.output_tokens + other.output_tokens)


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


@dataclass(frozen=True)
class EarlierQuery:
    """One earlier Query in a Follow-up chain, handed to the rewrite step as data."""

    question: str
    answer: str


@dataclass(frozen=True)
class RewriteResult:
    """A Follow-up rewritten into a standalone question."""

    question: str
    model: str
    usage: Usage = field(default_factory=Usage)
