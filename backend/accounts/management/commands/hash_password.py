"""Print a Django-format password hash for TEMPO_PASSWORD_HASH.

Usage:
    python manage.py hash_password            # prompts twice (hidden input)
    python manage.py hash_password "mypw"     # inline (visible in shell history)

Store the printed value in backend/.env as TEMPO_PASSWORD_HASH=... .
The plaintext password is never saved anywhere by the app.
"""
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Generate a Django-format password hash for TEMPO_PASSWORD_HASH."

    def add_arguments(self, parser):
        parser.add_argument("password", nargs="?", help="Password (omit to be prompted privately).")

    def handle(self, *args, **options):
        password = options.get("password")
        if not password:
            import getpass

            password = getpass.getpass("Password: ")
            confirm = getpass.getpass("Confirm password: ")
            if password != confirm:
                self.stderr.write(self.style.ERROR("Passwords do not match."))
                raise SystemExit(1)
        if not password:
            self.stderr.write(self.style.ERROR("Empty password."))
            raise SystemExit(1)
        self.stdout.write(make_password(password))
