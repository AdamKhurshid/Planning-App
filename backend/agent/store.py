"""File-backed agent state: conversation history and database backups.

Why files instead of models: the agent ships with **no migrations** — nothing
is added to the user's db.sqlite3 schema. The conversation lives in one JSON
file (auto-archived when it grows), and backups are full SQLite copies taken
with the sqlite3 backup API (safe while the server is running).

Undo model: before EVERY tool call a backup file is created and attached to
the assistant message that triggered it. The user can undo any of the last
TEMPO_AGENT_UNDO_DEPTH (default 5) agent messages: undo restores the backup
that was taken just before that message's FIRST tool call (i.e. data goes
back to the state before that message acted) and the conversation is
truncated to just before that exchange, so the window truly rewinds.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time as _time
from pathlib import Path

from django.conf import settings

DATA_DIR = Path(__file__).resolve().parent / "data"
CONV_PATH = DATA_DIR / "conversation.json"
ARCHIVE_DIR = DATA_DIR / "archive"
BACKUP_DIR = DATA_DIR / "backups"

MAX_CONV_BYTES = 400_000
MAX_BACKUP_FILES = 25

# Never let settings import fail if the vars are missing (defaults here are
# also declared in config/settings.py).
def undo_depth() -> int:
    try:
        return max(1, min(10, int(getattr(settings, "TEMPO_AGENT_UNDO_DEPTH", 5))))
    except Exception:
        return 5


def _ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Conversation (file-backed, no DB rows involved)
# ---------------------------------------------------------------------------

def load_conversation() -> dict:
    try:
        data = json.loads(CONV_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("messages", []), list):
            raise ValueError("bad shape")
        return data
    except FileNotFoundError:
        return {"mode": "native", "messages": []}
    except Exception:
        # A corrupt history must never take the app down: archive it, start fresh.
        try:
            _ensure_dirs()
            CONV_PATH.rename(ARCHIVE_DIR / f"corrupt-{int(_time.time())}.json")
        except Exception:
            pass
        return {"mode": "native", "messages": []}


def save_conversation(conv: dict) -> None:
    _ensure_dirs()
    payload = json.dumps(conv, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_CONV_BYTES:
        # Rotate: archive the old file, start a new conversation with just the mode.
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        try:
            CONV_PATH.rename(ARCHIVE_DIR / f"conversation-{stamp}.json")
        except Exception:
            pass
        conv = {"mode": conv.get("mode", "native"), "messages": []}
        payload = json.dumps(conv, ensure_ascii=False)
    tmp = CONV_PATH.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, CONV_PATH)


def reset_conversation() -> dict:
    _ensure_dirs()
    if CONV_PATH.exists():
        stamp = _time.strftime("%Y%m%d-%H%M%S")
        try:
            CONV_PATH.rename(ARCHIVE_DIR / f"conversation-{stamp}.json")
        except Exception:
            pass
    conv = {"mode": "native", "messages": []}
    save_conversation(conv)
    return conv


# ---------------------------------------------------------------------------
# Database backups (sqlite3 backup API — safe against a live server)
# ---------------------------------------------------------------------------

def _live_connection():
    from django.db import connection
    connection.ensure_connection()
    return connection.connection


def backup_db(message_id: int, call_index: int) -> str:
    """Full, consistent copy of db.sqlite3 BEFORE a tool call runs.
    Returns the backup path (also recorded in the message by the caller)."""
    _ensure_dirs()
    stamp = _time.strftime("%Y%m%d-%H%M%S")
    path = BACKUP_DIR / f"pre-{message_id or 'x'}-c{call_index}-{stamp}.sqlite3"
    src = _live_connection()
    dst = sqlite3.connect(str(path))
    try:
        src.backup(dst)
    finally:
        dst.close()
    prune_backups()
    return str(path)


def restore_db(path: str) -> None:
    """Copy a backup INTO the live database (backup API in reverse: pages are
    copied into the open connection, so no file swap, no open-file hazards).
    Only files inside BACKUP_DIR are ever accepted."""
    p = Path(path).resolve()
    if BACKUP_DIR.resolve() not in p.parents or p.suffix != ".sqlite3":
        raise ValueError("Refusing to restore: not a registered backup file.")
    if not p.exists():
        raise FileNotFoundError(p)
    src = sqlite3.connect(str(p))
    try:
        src.backup(_live_connection())
    finally:
        src.close()


def prune_backups(keep_paths: list[str] | None = None) -> None:
    """Keep backups referenced by the newest messages plus a hard file cap."""
    keep = {str(Path(p).resolve()) for p in (keep_paths or [])}
    try:
        files = sorted(BACKUP_DIR.glob("*.sqlite3"), key=lambda f: f.stat().st_mtime)
    except Exception:
        return
    excess = [f for f in files if str(f.resolve()) not in keep]
    # Newest excess files may still be needed by recent messages; drop the
    # oldest beyond the cap first.
    for f in excess[: max(0, len(files) - MAX_BACKUP_FILES)]:
        try:
            f.unlink()
        except Exception:
            pass


def backups_for(messages: list[dict]) -> list[str]:
    return [m["backup"] for m in messages if m.get("backup")]


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------

def undo_message(message_id: int) -> dict:
    """Rewind to the backup taken before `message_id`'s first tool call and
    truncate the conversation to before that exchange. Only the most recent
    undo_depth() agent messages are undoable."""
    conv = load_conversation()
    msgs = conv["messages"]
    idx = next((i for i, m in enumerate(msgs)
                if m.get("id") == message_id and m.get("role") == "assistant"), None)
    if idx is None:
        return {"ok": False, "error": "That message no longer exists in the conversation."}
    window = [m for m in msgs if m.get("role") == "assistant"][-undo_depth():]
    target = next((m for m in window if m.get("id") == message_id), None)
    if target is None:
        return {"ok": False, "error": "Only the most recent "
                f"{undo_depth()} agent messages can be undone."}
    backup = target.get("backup")
    if not backup:
        return {"ok": False, "error": "That message made no data changes (no backup), "
                                      "so there is nothing to undo."}
    if target.get("undone"):
        return {"ok": False, "error": "That message was already undone."}
    try:
        restore_db(backup)
    except Exception as exc:
        return {"ok": False, "error": f"Restore failed: {exc}"}
    # Truncate: drop this assistant message and the user message before it.
    cut = idx
    if cut > 0 and msgs[cut - 1].get("role") == "user":
        cut -= 1
    conv["messages"] = msgs[:cut]
    target["undone"] = True
    save_conversation(conv)
    prune_backups(backups_for([m for m in conv["messages"] if m.get("role") == "assistant"]
                              + [target]))
    return {"ok": True, "restored_from": Path(backup).name,
            "reverted_message": message_id}
