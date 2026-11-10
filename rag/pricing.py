from decimal import Decimal

from django.conf import settings

from .types import Usage

_MTOK = Decimal(1_000_000)


def chat_cost(usage: Usage) -> Decimal:
    return (
        Decimal(usage.input_tokens) * Decimal(str(settings.CHAT_INPUT_PRICE_PER_MTOK))
        + Decimal(usage.output_tokens) * Decimal(str(settings.CHAT_OUTPUT_PRICE_PER_MTOK))
    ) / _MTOK


def embedding_cost(usage: Usage) -> Decimal:
    return Decimal(usage.input_tokens) * Decimal(str(settings.EMBEDDING_PRICE_PER_MTOK)) / _MTOK
