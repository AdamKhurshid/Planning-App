"""Restore a JSON backup written by `backup_data` / exported via the API.

Usage:
    python manage.py restore_data backup.json --mode merge    # upsert by id (default)
    python manage.py restore_data backup.json --mode replace  # wipe, then restore

Restore assigns every object to the single app user (TEMPO_USERNAME).
`replace` DELETES existing data first — use `merge` to layer a backup onto
the current state (ids are preserved; rows that no longer exist in the file
are kept in merge mode).
"""
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from planner.models import Event, Task, TimeBlock
from projects.models import Project, Section

# FK targets must exist before dependents; task M2M last.
KEY_TO_MODEL = {"projects": Project, "sections": Section, "events": Event,
                "tasks": Task, "time_blocks": TimeBlock}


def _row_fields(row, model):
    """Keep the keys that map to concrete model fields; computed/serialiser
    extras and M2M ("depends_on") are handled separately."""
    concrete = {f.name for f in model._meta.concrete_fields} - {"id", "owner", "created_at", "updated_at"}
    return {k: v for k, v in row.items() if k in concrete}


class Command(BaseCommand):
    help = "Restore calendar/project data from a JSON backup file."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Backup file path.")
        parser.add_argument("--mode", choices=["merge", "replace"], default="merge",
                             help="merge = upsert by id; replace = delete existing rows first.")

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            with open(options["path"], encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            raise CommandError(f"Cannot read backup: {exc}")

        if payload.get("app") != "tempo":
            raise CommandError("Not a Tempo backup file.")

        user = get_user_model().objects.filter(username=settings.TEMPO_USERNAME).first()
        if user is None:
            raise CommandError(f"No user named '{settings.TEMPO_USERNAME}' — run `manage.py setup` first.")

        if options["mode"] == "replace":
            for model in reversed(list(KEY_TO_MODEL.values())):
                model.all_objects.filter(owner=user).delete()

        depends = []
        for key, model in KEY_TO_MODEL.items():
            for row in payload.get(key) or []:
                fields = _row_fields(row, model)
                fields["owner"] = user
                try:
                    obj = model.all_objects.update_or_create(id=row["id"], defaults=fields)[0]
                except Exception as exc:
                    raise CommandError(f"Row {key}#{row.get('id')}: {exc}")
                if key == "tasks" and row.get("depends_on"):
                    depends.append((obj, row["depends_on"]))
        for obj, dep_ids in depends:
            obj.depends_on.set(Task.all_objects.filter(id__in=dep_ids))

        counts = {k: len(payload.get(k) or []) for k in KEY_TO_MODEL}
        self.stdout.write(self.style.SUCCESS(f"Restored {counts} for user '{user.username}'."))
