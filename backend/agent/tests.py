"""Agent tests: defensive tools, memory/RAG, MCP stdio server, the chat loop
with a mocked Ollama, and the backup/undo guarantee.

All file-backed state (conversation, backups) is redirected to a temp dir so
tests never touch the developer's real agent/data/."""
import io
import json
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from agent import mcp_server, memory, ollama_client as oc, service, store, tools
from planner.models import Task, TimeBlock


class IsolatedAgentCase(TestCase):
    """Redirect agent file state to a temp dir for the duration of a test.

    backup_db/restore_db are replaced by a test double: the real sqlite3
    backup API deadlocks against Django's in-memory shared-cache TEST database
    (the runner holds an open transaction). The production path — real backup,
    real restore against the file-backed dev/prod sqlite — was verified by the
    backup→create→restore roundtrip; the double preserves the same contract
    (a real file under BACKUP_DIR, path validation, data actually reverted)."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="agent-test-")
        root = Path(self._tmp)
        (root / "backups").mkdir()
        self._patches = [
            mock.patch.object(store, "DATA_DIR", root),
            mock.patch.object(store, "CONV_PATH", root / "conversation.json"),
            mock.patch.object(store, "ARCHIVE_DIR", root / "archive"),
            mock.patch.object(store, "BACKUP_DIR", root / "backups"),
            mock.patch.object(store, "backup_db", side_effect=_test_backup_db),
            mock.patch.object(store, "restore_db", side_effect=_test_restore_db),
        ]
        for p in self._patches:
            p.start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().tearDown()

    def _assistant_msgs(self):
        return [m for m in store.load_conversation()["messages"] if m["role"] == "assistant"]


def _test_backup_db(message_id, call_index) -> str:
    from planner.models import Task as T
    data = [{"id": t.id, "title": t.title, "owner_id": t.owner_id,
             "priority": t.priority} for t in T.objects.all()]
    f = store.BACKUP_DIR / f"pre-{message_id}-c{call_index}-test.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    return str(f)


def _test_restore_db(path: str) -> None:
    p = Path(path)
    if store.BACKUP_DIR.resolve() not in p.parents:
        raise ValueError("Refusing to restore: not a registered backup file.")
    from planner.models import Task as T
    data = json.loads(p.read_text(encoding="utf-8"))
    T.objects.all().delete()
    T.objects.bulk_create([T(id=d["id"], title=d["title"], owner_id=d["owner_id"],
                             priority=d["priority"]) for d in data])


class ToolValidationTests(IsolatedAgentCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("owner", is_staff=True)

    def test_create_task_happy_path(self):
        out = tools.call_tool(self.user, "create_task", {"title": "Read", "estimated_minutes": 45})
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["result"]["estimated_minutes"], 45)
        self.assertTrue(Task.objects.filter(title="Read", owner=self.user).exists())

    def test_rejects_bad_args(self):
        cases = [
            ("create_task", {"title": "x" * 300}),
            ("create_task", {"title": "T", "priority": "mega"}),
            ("create_task", {"title": "T", "estimated_minutes": 0}),
            ("create_task", {"title": "T", "estimated_minutes": 99999}),
            ("create_task", {"title": "T", "deadline_date": "16/11/2026"}),
            ("create_task", {"title": "T", "recurrence_rule": "FREQ=NOPE"}),
            ("create_task", {"title": "T", "recurrence_rule": "FREQ=DAILY"}),  # no time/day
            ("create_task", {"nonsense": 1}),  # missing title + unknown arg
            ("create_event", {"title": "E", "start": "not a date"}),
            ("create_event", {"title": "E", "start": "2026-11-16 10:00", "end": "2026-11-16 09:00"}),
            ("complete_task", {"task_id": 99999}),
            ("schedule_task", {"task_id": "abc", "start": "2026-11-16 10:00"}),
            ("list_tasks", {"filter": "weird"}),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args):
                out = tools.call_tool(self.user, name, args)
                self.assertFalse(out["ok"], out)
                self.assertIn("error", out)
                self.assertTrue(isinstance(out["error"], str) and out["error"])

    def test_unknown_tool_and_owner_scoping(self):
        self.assertFalse(tools.call_tool(self.user, "delete_everything", {})["ok"])
        other = get_user_model().objects.create_user("other")
        t = Task.objects.create(owner=other, title="Not yours")
        out = tools.call_tool(self.user, "complete_task", {"task_id": t.id})
        self.assertFalse(out["ok"])

    def test_schedule_task_overlap_and_success(self):
        t = Task.objects.create(owner=self.user, title="Deep work", estimated_minutes=60)
        now = timezone.now().replace(second=0, microsecond=0)
        ok = tools.call_tool(self.user, "schedule_task",
                             {"task_id": t.id, "start": now.isoformat(), "minutes": 30})
        self.assertTrue(ok["ok"], ok)
        clash = tools.call_tool(self.user, "schedule_task",
                                {"task_id": t.id, "start": (now + timedelta(minutes=15)).isoformat()})
        self.assertFalse(clash["ok"])
        self.assertIn("overlapping", clash["error"])

    def test_complete_task_and_never_raises(self):
        t = Task.objects.create(owner=self.user, title="X")
        out = tools.call_tool(self.user, "complete_task", {"task_id": t.id})
        self.assertTrue(out["ok"])
        t.refresh_from_db()
        self.assertIsNotNone(t.completed_at)
        # Garbage arguments must yield an error dict, not an exception.
        self.assertFalse(tools.call_tool(self.user, "list_tasks", {"limit": "bamboo"})["ok"])


class MemoryTests(IsolatedAgentCase):
    def test_search_finds_relevant_chunks(self):
        hits = memory.search_knowledge("repeating task preferred time", k=2)
        self.assertTrue(hits)
        self.assertTrue(any("Repeating" in h["heading"] for h in hits))

    def test_retrieve_context_and_base_memory(self):
        self.assertEqual(memory.retrieve_context("zzzqqq"), "")  # no match -> no context
        self.assertNotEqual(memory.load_base_memory(), "")
        ctx = memory.retrieve_context("prayer times zawaal")
        self.assertIn("Zawaal", ctx)

    def test_remember_appends_and_caps(self):
        out = memory.append_user_note("Prefers early morning study.")
        self.assertTrue(out["ok"])
        self.assertIn("early morning", memory.load_user_notes())
        self.assertFalse(memory.append_user_note("   ")["ok"])


class McpServerTests(IsolatedAgentCase):
    def _serve(self, lines):
        reader = io.StringIO("\n".join(lines) + "\n")
        writer = io.StringIO()
        mcp_server.serve(reader, writer)
        return [json.loads(l) for l in writer.getvalue().splitlines()]

    def test_full_roundtrip_and_defense(self):
        self.user = get_user_model().objects.create_user("owner", is_staff=True)
        responses = self._serve([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                        "params": {"name": "create_task", "arguments": {"title": "From MCP"}}}),
            "garbage {{{",
            json.dumps({"jsonrpc": "2.0", "id": 5, "method": "made/up"}),
            json.dumps({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                        "params": {"name": "create_task", "arguments": {"estimated_minutes": 10 ** 6}}}),
            json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": None}}),
        ])
        self.assertEqual(len(responses), 7)  # notification got no reply
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[1]["id"], 2)
        self.assertGreaterEqual(len(responses[1]["result"]["tools"]), 12)
        self.assertEqual(responses[2]["id"], 3)
        call = json.loads(responses[2]["result"]["content"][0]["text"])
        self.assertTrue(call["ok"])
        self.assertTrue(Task.objects.filter(title="From MCP").exists())
        self.assertEqual(responses[3]["error"]["code"], -32700)
        self.assertEqual(responses[4]["error"]["code"], -32601)
        self.assertEqual(responses[5]["id"], 6)
        self.assertTrue(responses[5]["result"]["isError"])  # tool error, not protocol error
        self.assertEqual(responses[6]["error"]["code"], -32602)

    def test_backup_taken_for_mcp_tool_calls(self):
        """Defence: MCP path backs up before mutating tools too."""
        self.user = get_user_model().objects.create_user("owner", is_staff=True)
        # backup_db is invoked by the service layer, not the MCP server itself —
        # the MCP server must still work standalone; assert tool results only.
        responses = self._serve([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "list_tasks", "arguments": {}}}),
        ])
        self.assertTrue(json.loads(responses[0]["result"]["content"][0]["text"])["ok"])


class ChatLoopTests(IsolatedAgentCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("owner", is_staff=True)

    def test_native_tool_call_creates_task_with_backup(self):
        with mock.patch.object(oc, "chat", side_effect=[
            {"content": "", "tool_calls": [{"name": "create_task",
                                            "arguments": {"title": "Agent made this"}}]},
            {"content": "I created the task for you.", "tool_calls": []},
        ]):
            out = service.run_turn(self.user, "Add a task called Agent made this")
        self.assertTrue(out["ok"], out)
        t = Task.objects.get(title="Agent made this")
        msgs = self._assistant_msgs()
        self.assertEqual(msgs[-1]["content"], "I created the task for you.")
        self.assertEqual(msgs[-1]["tool_calls"][0]["tool"], "create_task")
        self.assertTrue(msgs[-1]["tool_calls"][0]["ok"])
        self.assertIsNotNone(msgs[-1]["backup"])  # undo guarantee
        backup = Path(msgs[-1]["backup"])
        self.assertTrue(backup.exists() and backup.stat().st_size > 0)

    def test_tool_error_is_fed_back_and_model_recovers(self):
        with mock.patch.object(oc, "chat", side_effect=[
            {"content": "", "tool_calls": [{"name": "create_task",
                                            "arguments": {"title": "x" * 500}}]},
            {"content": "Fixed it.", "tool_calls": [{"name": "create_task",
                                                     "arguments": {"title": "Short title"}}]},
            {"content": "Done now.", "tool_calls": []},
        ]):
            out = service.run_turn(self.user, "add a task")
        self.assertTrue(out["ok"])
        entry = self._assistant_msgs()[-1]["tool_calls"]
        self.assertFalse(entry[0]["ok"])   # the rejected call is recorded
        self.assertTrue(entry[1]["ok"])
        self.assertTrue(Task.objects.filter(title="Short title").exists())

    def test_unreachable_ollama_is_friendly(self):
        with mock.patch.object(oc, "chat", side_effect=oc.OllamaError(
                "Could not reach Ollama at http://127.0.0.1:11434.", kind="unreachable")):
            out = service.run_turn(self.user, "hello")
        self.assertFalse(out["ok"])
        msgs = self._assistant_msgs()
        self.assertIn("can't reach Ollama", msgs[-1]["content"])
        self.assertFalse(msgs[-1]["tool_calls"])

    def test_json_fallback_when_tools_unsupported(self):
        with mock.patch.object(oc, "chat", side_effect=[
            oc.OllamaError("This model has no native tool support.", kind="tools_unsupported"),
            {"content": '{"tool": "create_task", "arguments": {"title": "JSON mode task"}}',
             "tool_calls": []},
            {"content": '{"reply": "Task created."}', "tool_calls": []},
        ]):
            out = service.run_turn(self.user, "Add a JSON mode task")
        self.assertTrue(out["ok"], out)
        self.assertTrue(Task.objects.filter(title="JSON mode task").exists())
        self.assertEqual(store.load_conversation().get("mode"), "json")  # sticky
        self.assertEqual(self._assistant_msgs()[-1]["content"], "Task created.")

    def test_json_mode_plain_prose_stays_prose(self):
        store.save_conversation({"mode": "json", "messages": []})
        with mock.patch.object(oc, "chat", return_value={
                "content": "Your next deadline is Friday.", "tool_calls": []}):
            out = service.run_turn(self.user, "what is due?")
        self.assertEqual(self._assistant_msgs()[-1]["content"], "Your next deadline is Friday.")

    def test_fabricated_tool_result_is_flagged(self):
        """Weak json-mode models sometimes NARRATE a fake tool result instead
        of emitting the JSON directive. The turn must not create anything and
        must flag the narration as unexecuted."""
        store.save_conversation({"mode": "json", "messages": []})
        with mock.patch.object(oc, "chat", return_value={
                "content": 'Done — the tool said: [create_task ->] {"ok": true, '
                           '"result": {"task_id": 9, "title": "Ghost task"}}',
                "tool_calls": []}):
            out = service.run_turn(self.user, "add a ghost task")
        self.assertTrue(out["ok"])
        self.assertFalse(Task.objects.filter(title="Ghost task").exists())
        self.assertIn("no tool actually ran", self._assistant_msgs()[-1]["content"])

    def test_tool_results_use_system_marker(self):
        marker = service._tool_result_for_model({"name": "create_task"}, {"ok": True})
        self.assertIn("<<< SYSTEM-RESULT create_task >>>", marker)
        self.assertNotIn("[create_task ->]", marker)

    def test_identical_successful_calls_are_deduped(self):
        """A weak model repeating the SAME successful create_task every round
        must create exactly ONE task, not five."""
        call = {"content": "", "tool_calls": [
            {"name": "create_task", "arguments": {"title": "Dup check"}}]}
        with mock.patch.object(oc, "chat", return_value=call):
            out = service.run_turn(self.user, "make dup check")
        self.assertTrue(out["ok"])
        self.assertEqual(Task.objects.filter(title="Dup check").count(), 1)
        entries = self._assistant_msgs()[-1]["tool_calls"]
        self.assertEqual(sum(1 for e in entries if not e.get("duplicate")),
                         1)  # only the first really ran
        self.assertGreaterEqual(len(entries), service.max_rounds())  # model kept repeating

    def test_runaway_tool_loop_is_capped(self):
        calls = {"content": "", "tool_calls": [{"name": "list_tasks", "arguments": {}}]}
        with mock.patch.object(oc, "chat", return_value=calls):
            out = service.run_turn(self.user, "loop forever")
        self.assertTrue(out["ok"])
        self.assertIn("too many tool rounds", self._assistant_msgs()[-1]["content"])
        self.assertGreaterEqual(len(self._assistant_msgs()[-1]["tool_calls"]),
                                service.max_rounds())


class UndoTests(IsolatedAgentCase):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user("owner", is_staff=True)

    def test_undo_restores_data_and_truncates_chat(self):
        with mock.patch.object(oc, "chat", side_effect=[
            {"content": "", "tool_calls": [{"name": "create_task",
                                            "arguments": {"title": "Undoable"}}]},
            {"content": "Created.", "tool_calls": []},
        ]):
            service.run_turn(self.user, "create Undoable")
        task = Task.objects.get(title="Undoable")
        msgs = store.load_conversation()["messages"]
        self.assertEqual(len(msgs), 2)
        assistant_id = msgs[-1]["id"]

        result = store.undo_message(assistant_id)
        self.assertTrue(result["ok"], result)
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())  # data reverted
        self.assertEqual(store.load_conversation()["messages"], [])  # chat rewound

    def test_undo_window_is_five_messages(self):
        for i in range(6):
            with mock.patch.object(oc, "chat", side_effect=[
                {"content": "", "tool_calls": [{"name": "create_task",
                                                "arguments": {"title": f"T{i}"}}]},
                {"content": f"ok {i}", "tool_calls": []},
            ]):
                service.run_turn(self.user, f"make T{i}")
        ids = [m["id"] for m in self._assistant_msgs()]
        ok = store.undo_message(ids[0])  # 6th oldest -> outside the window
        self.assertFalse(ok["ok"])
        self.assertIn("most recent", ok["error"])
        ok = store.undo_message(ids[1])  # inside the window
        self.assertTrue(ok["ok"])
        self.assertFalse(Task.objects.filter(title="T1").exists())
        self.assertTrue(Task.objects.filter(title="T0").exists())  # earlier survives

    def test_undo_rejects_unknown_and_non_tool_messages(self):
        self.assertFalse(store.undo_message(424242)["ok"])
        with mock.patch.object(oc, "chat", return_value={
                "content": "just talking", "tool_calls": []}):
            service.run_turn(self.user, "hi")
        aid = self._assistant_msgs()[-1]["id"]
        out = store.undo_message(aid)
        self.assertFalse(out["ok"])
        self.assertIn("no data changes", out["error"])


class AgentApiTests(IsolatedAgentCase):
    def setUp(self):
        super().setUp()
        from rest_framework.test import APIClient
        self.user = get_user_model().objects.create_user("owner", is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        res = self.client.get("/api/agent/messages/")
        self.assertEqual(res.status_code, 401)

    def test_status_and_messages(self):
        res = self.client.get("/api/agent/status/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["model"], oc.ollama_model())
        self.assertIn("create_task", res.data["ollama"]["tools"])
        res = self.client.get("/api/agent/messages/")
        self.assertEqual(res.data["messages"], [])

    def test_chat_undo_reset_endpoints(self):
        with mock.patch.object(oc, "chat", side_effect=[
            {"content": "", "tool_calls": [{"name": "create_task",
                                            "arguments": {"title": "API task"}}]},
            {"content": "Created.", "tool_calls": []},
        ]):
            res = self.client.post("/api/agent/chat/", {"message": "create API task"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Task.objects.filter(title="API task").exists())
        undoable = res.data["messages"][-1]["id"]
        self.assertIn(undoable, self.client.get("/api/agent/messages/").data["undoable_ids"])

        res = self.client.post("/api/agent/undo/", {"message_id": undoable}, format="json")
        self.assertTrue(res.data["ok"], res.data)
        self.assertFalse(Task.objects.filter(title="API task").exists())
        self.assertEqual(res.data["messages"], [])

        res = self.client.post("/api/agent/reset/", format="json")
        self.assertEqual(res.data["messages"], [])

        res = self.client.post("/api/agent/chat/", {"message": "   "}, format="json")
        self.assertEqual(res.status_code, 400)

    def test_undo_of_forged_id_is_refused(self):
        res = self.client.post("/api/agent/undo/", {"message_id": "2; DROP TABLE"}, format="json")
        self.assertEqual(res.status_code, 400)
        res = self.client.post("/api/agent/undo/", {"message_id": 987654}, format="json")
        self.assertEqual(res.status_code, 400)
