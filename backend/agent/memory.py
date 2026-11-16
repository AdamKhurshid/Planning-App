"""The agent's documents: base memory, a small file-backed RAG store, and a
growing user-notes file the agent itself can append to.

All state lives in plain Markdown under backend/agent/memory_files/ so it is
inspectable, editable, and shipped with the app. Nothing here touches the
database, so undoing agent tool calls never wipes memory.
"""
from __future__ import annotations

import re
from pathlib import Path

from django.utils import timezone

BASE_DIR = Path(__file__).resolve().parent / "memory_files"
MEMORY_PATH = BASE_DIR / "MEMORY.md"
USER_NOTES_PATH = BASE_DIR / "USER_NOTES.md"
KNOWLEDGE_DIR = BASE_DIR / "knowledge"

MAX_USER_NOTES_BYTES = 200_000  # refuse to grow the notes file past this
CHUNK_MAX_CHARS = 700


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


def load_base_memory() -> str:
    """MEMORY.md — always injected into the agent's system prompt."""
    return _read(MEMORY_PATH).strip()


def load_user_notes(limit_chars: int = 4000) -> str:
    """The tail of USER_NOTES.md (what the agent has written down lately)."""
    text = _read(USER_NOTES_PATH).strip()
    return text[-limit_chars:]


def _chunks(text: str, source: str) -> list[dict]:
    """Split a knowledge file into chunks at ## headings."""
    parts = re.split(r"\n(?=## )", text)
    out = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        heading = part.splitlines()[0].lstrip("# ").strip() if part else source
        if len(part) > CHUNK_MAX_CHARS:
            # Hard-split oversized chunks so scores stay meaningful.
            for i in range(0, len(part), CHUNK_MAX_CHARS):
                out.append({"source": source, "heading": heading, "text": part[i:i + CHUNK_MAX_CHARS]})
        else:
            out.append({"source": source, "heading": heading, "text": part})
    return out


def _knowledge_chunks() -> list[dict]:
    chunks: list[dict] = []
    if KNOWLEDGE_DIR.exists():
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            chunks.extend(_chunks(_read(path), path.name))
    return chunks


_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def search_knowledge(query: str, k: int = 3) -> list[dict]:
    """Dependency-free retrieval: term-overlap scoring over the knowledge
    chunks. Good enough for a small curated corpus, and it cannot fail."""
    q_tokens = _tokens(query)
    if not q_tokens:
        return []
    scored = []
    for chunk in _knowledge_chunks():
        c_tokens = _tokens(chunk["heading"] + " " + chunk["text"])
        overlap = len(q_tokens & c_tokens)
        if overlap:
            # Heading hits weigh double — headings summarise the chunk.
            head_hits = len(q_tokens & _tokens(chunk["heading"]))
            scored.append((overlap + head_hits, chunk))
    scored.sort(key=lambda pair: -pair[0])
    return [chunk for _, chunk in scored[:max(1, k)]]


def retrieve_context(query: str, k: int = 3) -> str:
    """Rendered RAG context for the system prompt ('' when nothing matches)."""
    chunks = search_knowledge(query, k=k)
    if not chunks:
        return ""
    parts = []
    for c in chunks:
        parts.append(f"[{c['source']} · {c['heading']}]\n{c['text']}")
    return "\n\n".join(parts)


def append_user_note(text: str) -> dict:
    """remember(): the agent writes a durable note. Defensive: sanitised,
    single block, hard size cap, never destroys existing content."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return {"ok": False, "error": "Empty note — nothing to remember."}
    if len(text) > 500:
        text = text[:500] + "…"
    try:
        if USER_NOTES_PATH.exists() and USER_NOTES_PATH.stat().st_size > MAX_USER_NOTES_BYTES:
            return {"ok": False,
                    "error": "The notes file is full (200 KB). Prune USER_NOTES.md first."}
        USER_NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localdate().isoformat()
        with USER_NOTES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(f"\n- ({stamp}) {text}\n")
        return {"ok": True, "noted": text, "where": "USER_NOTES.md"}
    except Exception as exc:
        return {"ok": False, "error": f"Could not write the note: {exc}"}


# ---------------------------------------------------------------------------
# Wire the two memory tools into the shared tool registry
# ---------------------------------------------------------------------------

def register_tools(TOOLS: dict) -> None:
    def search_memory(user, query, limit=3):
        chunks = search_knowledge(str(query), k=int(limit or 3))
        return {"count": len(chunks),
                "chunks": [{"source": c["source"], "heading": c["heading"],
                            "text": c["text"][:400]} for c in chunks]}

    def remember(user, note):
        return append_user_note(note)

    TOOLS["search_memory"] = {
        "description": "Search the planner knowledge documents (how Tempo works, "
                       "prayer features, scheduling conventions). Use before asking "
                       "the user anything the docs already answer.",
        "inputSchema": {"type": "object", "required": ["query"],
                        "properties": {"query": {"type": "string", "description": "Search words",
                                                  "maxLength": 200},
                                       "limit": {"type": "integer", "minimum": 1, "maximum": 5}}},
        "func": search_memory,
    }
    TOOLS["remember"] = {
        "description": "Persist a short durable note about the user (preferences, "
                       "habits, facts worth remembering across conversations).",
        "inputSchema": {"type": "object", "required": ["note"],
                        "properties": {"note": {"type": "string", "description": "One-line note",
                                                "maxLength": 500}}},
        "func": remember,
    }
