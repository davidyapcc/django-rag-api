from django.db import models


class DailySpend(models.Model):
    """LLM spend per UTC day, across all Owners. Kept apart from Owners so deleting a Guest
    never hands budget back."""

    day = models.DateField(primary_key=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)

    def __str__(self) -> str:
        return f"{self.day}: ${self.cost_usd}"
