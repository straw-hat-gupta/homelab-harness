import uuid
import unittest

from django.test import TestCase

from agent.chat_context import ChatContext, DbContextStore, _char_size, get_ctx


class CharSizeTests(unittest.TestCase):
    def test_empty_messages(self):
        self.assertEqual(_char_size([]), 0)

    def test_single_message_nonzero(self):
        msg = {"role": "user", "content": "hello"}
        self.assertGreater(_char_size([msg]), 0)

    def test_longer_content_is_larger(self):
        short = [{"role": "user", "content": "hi"}]
        long = [{"role": "user", "content": "hi" * 100}]
        self.assertGreater(_char_size(long), _char_size(short))


class ChatContextTests(unittest.TestCase):
    def _ctx(self, max_size=12000):
        # Use _char_size so unit tests remain deterministic regardless of tiktoken.
        return ChatContext(user_id="u1", project_id="p1", max_size=max_size, size_fn=_char_size)

    def test_add_user_appends_message(self):
        ctx = self._ctx()
        ctx.add_user("hello")
        self.assertEqual(ctx.messages[0], {"role": "user", "content": "hello"})

    def test_add_user_tracks_unsaved_sequence(self):
        ctx = self._ctx()
        ctx.add_user("hello")
        self.assertEqual(len(ctx._sequences), 1)
        self.assertIsNone(ctx._sequences[0])

    def test_add_assistant_appends_message(self):
        ctx = self._ctx()
        ctx.add_assistant("hi there")
        self.assertEqual(ctx.messages[0]["role"], "assistant")

    def test_as_messages_returns_copy(self):
        ctx = self._ctx()
        ctx.add_user("hello")
        msgs = ctx.as_messages()
        msgs.append({"role": "injected", "content": "x"})
        self.assertEqual(len(ctx.messages), 1)

    def test_as_transcript_formats_correctly(self):
        ctx = self._ctx()
        ctx.add_user("hello")
        ctx.add_assistant("hi")
        transcript = ctx.as_transcript()
        self.assertIn("User: hello", transcript)
        self.assertIn("Assistant: hi", transcript)

    def test_prune_drops_oldest_when_over_budget(self):
        ctx = self._ctx(max_size=50)
        for i in range(20):
            ctx.add_user(f"message number {i:03}")
        # _prune already ran inside add_message; verify count is reduced
        self.assertLess(len(ctx.messages), 20)

    def test_prune_keeps_at_least_one_message(self):
        ctx = self._ctx(max_size=1)
        ctx.messages = [{"role": "user", "content": "a very long message that far exceeds budget"}]
        ctx._sequences = [None]
        ctx._prune()
        self.assertEqual(len(ctx.messages), 1)

    def test_prune_prefers_dropping_system_messages(self):
        ctx = self._ctx(max_size=50)
        ctx.messages = [
            {"role": "system", "content": "sys instruction"},
            {"role": "user", "content": "user message here"},
            {"role": "assistant", "content": "assistant reply"},
        ]
        ctx._sequences = [None, None, None]
        ctx._prune()
        roles = [m["role"] for m in ctx.messages]
        self.assertNotIn("system", roles)

    def test_prune_advances_active_from_for_saved_messages(self):
        ctx = self._ctx(max_size=50)
        # Simulate messages already in DB with known sequences
        ctx.messages = [
            {"role": "user", "content": "old message"},
            {"role": "assistant", "content": "old reply"},
            {"role": "user", "content": "newer message here"},
        ]
        ctx._sequences = [3, 4, 5]
        ctx._active_from = 3
        ctx._prune()
        # At least one message was dropped; _active_from should have advanced
        self.assertGreater(ctx._active_from, 3)

    def test_prune_does_not_advance_active_from_for_unsaved_messages(self):
        ctx = self._ctx(max_size=50)
        # All messages are unsaved (None sequences)
        ctx.messages = [
            {"role": "user", "content": "msg a"},
            {"role": "user", "content": "msg b"},
            {"role": "user", "content": "msg c"},
        ]
        ctx._sequences = [None, None, None]
        ctx._active_from = 0
        ctx._prune()
        self.assertEqual(ctx._active_from, 0)

    def test_sequences_stays_in_sync_with_messages(self):
        ctx = self._ctx(max_size=50)
        for i in range(10):
            ctx.add_user(f"message {i}")
        self.assertEqual(len(ctx.messages), len(ctx._sequences))

    def test_to_dict_from_dict_roundtrip(self):
        ctx = self._ctx()
        ctx.add_user("test message")
        data = ctx.to_dict()
        restored = ChatContext.from_dict(data)
        self.assertEqual(restored.user_id, "u1")
        self.assertEqual(restored.project_id, "p1")
        self.assertEqual(restored.messages, ctx.messages)

    def test_from_dict_populates_sequences_and_active_from(self):
        data = {
            "user_id": "u1",
            "project_id": "p1",
            "messages": [{"role": "user", "content": "hi"}],
            "sequences": [7],
            "active_from": 7,
        }
        ctx = ChatContext.from_dict(data)
        self.assertEqual(ctx._sequences, [7])
        self.assertEqual(ctx._active_from, 7)

    def test_callable_returns_string(self):
        ctx = self._ctx()
        result = ctx()
        self.assertIsInstance(result, str)
        self.assertIn("u1", result)


class DbContextStoreTests(TestCase):
    def _make_user_and_project(self):
        from django.contrib.auth import get_user_model
        from projects.models import Projects
        User = get_user_model()
        uid = str(uuid.uuid4())
        user = User.objects.create_user(email=f"{uid}@test.com", supabase_uid=uid)
        project = Projects.objects.create(user=user, name="Test Project")
        return user, project, uid

    def test_load_nonexistent_project_returns_none(self):
        store = DbContextStore()
        result = store.load("no-such-uid", "99999")
        self.assertIsNone(result)

    def test_load_non_integer_project_id_returns_none(self):
        store = DbContextStore()
        result = store.load("uid", "default")
        self.assertIsNone(result)

    def test_load_includes_sequences_and_active_from(self):
        user, project, uid = self._make_user_and_project()
        store = DbContextStore()
        ctx = ChatContext(user_id=str(uid), project_id=str(project.pk))
        ctx.add_user("hello")
        ctx._store = None
        store.save(ctx)

        data = store.load(str(uid), str(project.pk))
        self.assertIn("sequences", data)
        self.assertIn("active_from", data)
        self.assertEqual(len(data["sequences"]), 1)
        self.assertIsInstance(data["sequences"][0], int)

    def test_save_and_load_roundtrip(self):
        user, project, uid = self._make_user_and_project()
        store = DbContextStore()
        ctx = ChatContext(user_id=str(uid), project_id=str(project.pk))
        ctx.add_user("hello from db")
        ctx._store = None
        store.save(ctx)

        data = store.load(str(uid), str(project.pk))
        self.assertIsNotNone(data)
        self.assertEqual(data["messages"][0]["content"], "hello from db")

    def test_save_assigns_sequence_to_new_messages(self):
        user, project, uid = self._make_user_and_project()
        store = DbContextStore()
        ctx = ChatContext(user_id=str(uid), project_id=str(project.pk))
        ctx.add_user("first")
        ctx._store = None
        store.save(ctx)
        # After save, the sequence should be set
        self.assertIsNotNone(ctx._sequences[0])

    def test_save_appends_incrementally(self):
        """Each call to save only inserts newly added messages; existing rows are untouched."""
        user, project, uid = self._make_user_and_project()
        store = DbContextStore()
        ctx = ChatContext(user_id=str(uid), project_id=str(project.pk))
        ctx.add_user("first")
        ctx._store = None
        store.save(ctx)

        seq_first = ctx._sequences[0]
        ctx.add_assistant("reply")
        store.save(ctx)

        # First message sequence unchanged
        self.assertEqual(ctx._sequences[0], seq_first)
        # Second message now has a sequence > first
        self.assertIsNotNone(ctx._sequences[1])
        self.assertGreater(ctx._sequences[1], seq_first)

        data = store.load(str(uid), str(project.pk))
        self.assertEqual(len(data["messages"]), 2)
        self.assertEqual(data["messages"][0]["content"], "first")
        self.assertEqual(data["messages"][1]["content"], "reply")

    def test_db_rows_survive_after_prune(self):
        """Pruning updates activeContextFrom but does NOT delete DB rows."""
        user, project, uid = self._make_user_and_project()
        store = DbContextStore()
        ctx = ChatContext(user_id=str(uid), project_id=str(project.pk), size_fn=_char_size, max_size=60)
        ctx._store = None
        # Insert several messages (each ~20 chars → 4 messages exceed budget of 60)
        for i in range(6):
            ctx.messages.append({"role": "user", "content": f"message {i:02d}"})
            ctx._sequences.append(None)
        store.save(ctx)  # save all 6 with sequences 1-6

        # Now prune with small budget
        ctx._prune()
        store.save(ctx)  # updates activeContextFrom

        from context.models import ProjectContext
        total = ProjectContext.objects.filter(project=project).count()
        self.assertEqual(total, 6, "All 6 rows should remain in DB after prune")

        project.refresh_from_db()
        self.assertGreater(project.active_context_from, 0, "active_context_from should advance past pruned rows")

    def test_frontend_rows_survive_agent_save(self):
        """Agent append-only save does not wipe rows written by context/views.py."""
        from context.models import ProjectContext
        user, project, uid = self._make_user_and_project()

        # Simulate frontend writing a row directly (as context/views.py does)
        ProjectContext.objects.create(project=project, role="user", content="frontend row", sequence=1)

        # Agent picks up context and adds a reply
        ctx = get_ctx(str(uid), str(project.pk))
        ctx.add_assistant("agent reply")

        # Frontend row still in DB
        self.assertTrue(
            ProjectContext.objects.filter(project=project, content="frontend row").exists()
        )
        self.assertEqual(ProjectContext.objects.filter(project=project).count(), 2)

    def test_save_is_noop_when_nothing_changed(self):
        """Calling save() again without new messages does not hit the DB."""
        user, project, uid = self._make_user_and_project()
        store = DbContextStore()
        ctx = ChatContext(user_id=str(uid), project_id=str(project.pk))
        ctx.add_user("msg")
        ctx._store = None
        store.save(ctx)

        from context.models import ProjectContext
        before = ProjectContext.objects.filter(project=project).count()
        store.save(ctx)  # no new messages, activeContextFrom unchanged
        after = ProjectContext.objects.filter(project=project).count()
        self.assertEqual(before, after)


class GetCtxDbTests(TestCase):
    def _make_user_and_project(self):
        from django.contrib.auth import get_user_model
        from projects.models import Projects
        User = get_user_model()
        uid = str(uuid.uuid4())
        user = User.objects.create_user(email=f"{uid}@test.com", supabase_uid=uid)
        project = Projects.objects.create(user=user, name="Test Project")
        return user, project, uid

    def test_creates_new_context_for_valid_project(self):
        _, project, uid = self._make_user_and_project()
        ctx = get_ctx(str(uid), str(project.pk))
        self.assertEqual(ctx.user_id, str(uid))
        self.assertEqual(ctx.messages, [])

    def test_persists_and_reloads_messages(self):
        _, project, uid = self._make_user_and_project()
        ctx1 = get_ctx(str(uid), str(project.pk))
        ctx1.add_user("persisted message")

        ctx2 = get_ctx(str(uid), str(project.pk))
        self.assertEqual(ctx2.messages[0]["content"], "persisted message")

    def test_reloaded_context_has_sequences_set(self):
        _, project, uid = self._make_user_and_project()
        ctx1 = get_ctx(str(uid), str(project.pk))
        ctx1.add_user("hello")

        ctx2 = get_ctx(str(uid), str(project.pk))
        self.assertEqual(len(ctx2._sequences), 1)
        self.assertIsNotNone(ctx2._sequences[0])

    def test_different_users_isolated(self):
        _, project_a, uid_a = self._make_user_and_project()
        _, project_b, uid_b = self._make_user_and_project()

        ctx_a = get_ctx(str(uid_a), str(project_a.pk))
        ctx_a.add_user("user a message")

        ctx_b = get_ctx(str(uid_b), str(project_b.pk))
        self.assertEqual(ctx_b.messages, [])

    def test_fallback_for_non_integer_project_id(self):
        ctx = get_ctx("some-user", "default")
        self.assertEqual(ctx.messages, [])
        self.assertIsNone(ctx._store._get_project("some-user", "default"))

    def test_reset_clears_active_from_and_all_rows(self):
        """After reset, new messages at low sequences are visible on next load."""
        from context.models import ProjectContext
        from projects.models import Projects
        from django.contrib.auth import get_user_model

        _, project, uid = self._make_user_and_project()

        # Write some messages then simulate pruning advancing activeContextFrom
        ctx = get_ctx(str(uid), str(project.pk))
        ctx.add_user("old msg 1")
        ctx.add_assistant("old reply 1")
        project.refresh_from_db()
        project.active_context_from = 2
        project.save(update_fields=["active_context_from", "updated_at"])

        # Reset: delete all rows and clear active_context_from
        ProjectContext.objects.filter(project=project).delete()
        project.active_context_from = 0
        project.save(update_fields=["active_context_from", "updated_at"])

        # After reset, new messages should be visible
        ctx_new = get_ctx(str(uid), str(project.pk))
        ctx_new.add_user("fresh start")

        ctx_reload = get_ctx(str(uid), str(project.pk))
        self.assertEqual(len(ctx_reload.messages), 1)
        self.assertEqual(ctx_reload.messages[0]["content"], "fresh start")
