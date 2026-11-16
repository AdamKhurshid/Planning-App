"""Dump every owned object to a JSON backup file.

Usage:
    python manage.py backup_data backup.json
    python manage.py backup_data -            # print to stdout

The file is the same shape as GET /api/export/?format=json, so
`restore_data` can read back anything the API exported.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from planner.export import export_payload


class Command(BaseCommand):
    help = "Write a full JSON backup of all calendar/project data."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Output file path, or '-' for stdout.")

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.order_by("id").first()
        if user is None:
            raise CommandError("No user exists yet — run `manage.py setup` first.")

        payload = export_payload(user)
        line = json.dumps(payload)
        path = options["path"]
        counts = {k: len(v) for k, v in payload.items() if isinstance(v, list)}
        if path == "-":
            self.stdout.write(line)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(line)
            self.stdout.write(self.style.SUCCESS(f"Backup written to {path} ({counts})."))
