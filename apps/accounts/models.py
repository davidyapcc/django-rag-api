from django.conf import settings
from django.db import models


class Guest(models.Model):
    """Marks a user as a Guest: created in one click, deleted with all they own on expiry."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="guest")
    expires_at = models.DateTimeField(db_index=True)

    def __str__(self) -> str:
        return f"guest {self.user_id} until {self.expires_at:%Y-%m-%d %H:%M}"
