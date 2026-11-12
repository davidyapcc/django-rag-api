from django.conf import settings
from django.db import models


class DailySpend(models.Model):
    """LLM spend per UTC day, across all Owners. Kept apart from Owners so deleting a Guest
    never hands budget back."""

    day = models.DateField(primary_key=True)
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)

    def __str__(self) -> str:
        return f"{self.day}: ${self.cost_usd}"


class OwnerDailySpend(models.Model):
    """One Owner's LLM spend per UTC day, checked against their Allowance. A ledger rather than
    a sum over Queries and Documents, so deleting a Document never hands Allowance back."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    day = models.DateField()
    cost_usd = models.DecimalField(max_digits=12, decimal_places=8, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "day"], name="one_spend_row_per_owner_day")]

    def __str__(self) -> str:
        return f"{self.owner_id} {self.day}: ${self.cost_usd}"
