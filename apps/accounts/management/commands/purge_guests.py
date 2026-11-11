from django.core.management.base import BaseCommand

from apps.accounts.services import purge_expired_guests


class Command(BaseCommand):
    help = "Delete expired Guests and everything they own."

    def handle(self, *args, **options):
        self.stdout.write(f"purged {purge_expired_guests()} expired guest(s)")
