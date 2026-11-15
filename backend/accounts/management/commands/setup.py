"""One-time setup helper: verifies configuration and provisions the single user.

Usage: python manage.py setup
"""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from accounts.models import Profile

User = get_user_model()


class Command(BaseCommand):
    help = "Verify configuration and create the single private user + profile."

    def handle(self, *args, **options):
        problems = []
        #if settings.TEMPO_SECRET_KEY.startswith("insecure-dev-key"):
            #problems.append("TEMPO_SECRET_KEY is still the insecure default — set a real one in .env.")
        if not settings.TEMPO_PASSWORD_HASH:
            problems.append("TEMPO_PASSWORD_HASH is not set — login will fail. Generate one with `python manage.py hash_password`.")

        user, created = User.objects.get_or_create(
            username=settings.TEMPO_USERNAME,
            defaults={"is_staff": True, "is_superuser": True},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        profile, profile_created = Profile.objects.get_or_create(user=user)

        self.stdout.write(self.style.SUCCESS(f"User '{user.username}' {'created' if created else 'already exists'}"))
        self.stdout.write(self.style.SUCCESS(f"Profile {'created' if profile_created else 'already exists'}"))

        if problems:
            self.stdout.write("")
            for problem in problems:
                self.stdout.write(self.style.WARNING(f"! {problem}"))
        else:
            self.stdout.write(self.style.SUCCESS("Configuration looks good. Start the API with `python manage.py runserver`."))
