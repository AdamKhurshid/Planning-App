"""Agent HTTP endpoints: status, history, chat, undo, reset.

All endpoints require the same token auth as the rest of the API. The chat
endpoint is exempt from the offline-queue on the client (it must never be
replayed silently). Undo restores a database backup and rewinds the chat.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import memory, ollama_client as oc, service, store, tools


class AgentStatusView(APIView):
    """GET /api/agent/status/ -> ollama reachability, model, tool count."""

    def get(self, request):
        st = oc.status()
        st["tools"] = sorted(set(tools.TOOLS) | _memory_tool_names())
        return Response({"ollama": st, "model": oc.ollama_model(),
                         "host": oc.ollama_host(),
                         "max_rounds": service.max_rounds(),
                         "undo_depth": store.undo_depth()})


def _memory_tool_names():
    # search_memory/remember are registered at import time (below); listed
    # here defensively in case registration is skipped.
    return {n for n in ("search_memory", "remember") if n in tools.TOOLS}


class AgentMessagesView(APIView):
    """GET /api/agent/messages/ -> conversation + which messages are undoable."""

    def get(self, request):
        conv = store.load_conversation()
        msgs = conv["messages"]
        undoable = [m["id"] for m in msgs if m.get("role") == "assistant"
                    and m.get("backup")][-store.undo_depth():]
        return Response({"messages": msgs, "mode": conv.get("mode", "native"),
                         "model": oc.ollama_model(), "undoable_ids": undoable})


class AgentChatView(APIView):
    """POST /api/agent/chat/ {message} -> full turn (may run tools)."""

    def post(self, request):
        message = str(request.data.get("message") or "")
        if not message.strip():
            return Response({"detail": "Message must not be empty."},
                            status=status.HTTP_400_BAD_REQUEST)
        if len(message) > 4000:
            return Response({"detail": "Message too long (max 4000 chars)."},
                            status=status.HTTP_400_BAD_REQUEST)
        result = service.run_turn(request.user, message)
        http_status = status.HTTP_200_OK if result.get("ok") else status.HTTP_502_BAD_GATEWAY
        return Response(result, status=http_status)


class AgentUndoView(APIView):
    """POST /api/agent/undo/ {message_id} -> restore backup, rewind chat."""

    def post(self, request):
        raw = request.data.get("message_id")
        try:
            message_id = int(raw)
        except (TypeError, ValueError):
            return Response({"detail": "message_id must be an integer."},
                            status=status.HTTP_400_BAD_REQUEST)
        result = store.undo_message(message_id)
        conv = store.load_conversation()
        undoable = [m["id"] for m in conv["messages"] if m.get("role") == "assistant"
                    and m.get("backup")][-store.undo_depth():]
        result["messages"] = conv["messages"]
        result["undoable_ids"] = undoable
        return Response(result, status=status.HTTP_200_OK if result.get("ok")
                        else status.HTTP_400_BAD_REQUEST)


class AgentResetView(APIView):
    """POST /api/agent/reset/ -> archive the conversation, start fresh."""

    def post(self, request):
        conv = store.reset_conversation()
        return Response({"messages": conv["messages"], "mode": conv["mode"],
                         "undoable_ids": []})
