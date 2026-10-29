import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from planner.schemas import Plan, PlanStep
from agent.views import _sse, _format_completed_steps
from orchestrator.exceptions import PluginNotConnectedError, ToolExecutionError
from tools.registry import UnknownToolError

User = get_user_model()


def _simple_plan(summary="I will respond."):
    return Plan(
        steps=[PlanStep(id="step_1", tool="processing_llm", params={}, output_var="result")],
        final_output_var="result",
        summary=summary,
    )


def _confirmation_plan():
    return Plan(
        steps=[PlanStep(id="step_1", tool="gmail.send_email", params={}, output_var="result")],
        final_output_var="result",
        summary="I will send an email to alice@example.com.",
    )


class AgentViewAuthTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="agent_user@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def test_unauthenticated_returns_4xx(self):
        response = self._post({"prompt": "hello"})
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_empty_prompt_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self._post({"prompt": ""})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_missing_prompt_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self._post({})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_json_returns_400(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(self.url, "not-json", content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class AgentViewFreshPromptTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="agent_fresh@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.pending_plan.save")
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="Here is your answer.")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_fresh_prompt_executes_immediately(
        self, mock_get_ctx, mock_plan, mock_execute, mock_save, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _simple_plan()

        response = self._post({"prompt": "what is the weather?"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["response"], "Here is your answer.")
        mock_execute.assert_awaited_once()
        mock_save.assert_not_called()

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.pending_plan.save")
    @patch("agent.views.execute", new_callable=AsyncMock)
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_plan_needing_confirmation_holds_and_asks(
        self, mock_get_ctx, mock_plan, mock_execute, mock_save, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _confirmation_plan()

        response = self._post({"prompt": "send email to alice"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Shall I proceed?", response.json()["response"])
        mock_save.assert_called_once()
        mock_execute.assert_not_awaited()

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.pending_plan.save")
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="done")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_response_includes_response_key(
        self, mock_get_ctx, mock_plan, mock_execute, mock_save, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _simple_plan()

        response = self._post({"prompt": "hello"})

        data = response.json()
        self.assertIn("response", data)
        self.assertNotIn("error", data)


class AgentViewPendingPlanTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="agent_pending@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @patch("agent.pending_plan.clear")
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="Email sent successfully!")
    @patch("agent.views.detect_intent", new_callable=AsyncMock, return_value="confirm")
    @patch("agent.pending_plan.load")
    @patch("agent.views.get_ctx")
    def test_confirm_executes_pending_plan(
        self, mock_get_ctx, mock_load, mock_intent, mock_execute, mock_clear
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_load.return_value = _confirmation_plan()

        response = self._post({"prompt": "yes go ahead"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["response"], "Email sent successfully!")
        mock_execute.assert_awaited_once()
        mock_clear.assert_called_once()

    @patch("agent.pending_plan.clear")
    @patch("agent.views.detect_intent", new_callable=AsyncMock, return_value="cancel")
    @patch("agent.pending_plan.load")
    @patch("agent.views.get_ctx")
    def test_cancel_clears_pending_plan(
        self, mock_get_ctx, mock_load, mock_intent, mock_clear
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_load.return_value = _confirmation_plan()

        response = self._post({"prompt": "no cancel it"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("cancelled", response.json()["response"])
        mock_clear.assert_called_once()

    @patch("agent.pending_plan.save")
    @patch("agent.views.revise_plan", new_callable=AsyncMock)
    @patch("agent.views.detect_intent", new_callable=AsyncMock, return_value="modify")
    @patch("agent.pending_plan.load")
    @patch("agent.views.get_ctx")
    def test_modify_revises_and_re_asks(
        self, mock_get_ctx, mock_load, mock_intent, mock_revise, mock_save
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_load.return_value = _confirmation_plan()
        revised = _simple_plan(summary="I will send a revised email.")
        mock_revise.return_value = revised

        response = self._post({"prompt": "change the subject to Hello"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()["response"]
        self.assertIn("Shall I proceed?", body)
        self.assertIn("revised", body)
        mock_save.assert_called_once()
        mock_revise.assert_awaited_once()

    @patch("agent.pending_plan.save")
    @patch("agent.views.revise_plan", new_callable=AsyncMock)
    @patch("agent.views.detect_intent", new_callable=AsyncMock, return_value="modify")
    @patch("agent.pending_plan.load")
    @patch("agent.views.get_ctx")
    def test_modify_with_unknown_tool_returns_400(
        self, mock_get_ctx, mock_load, mock_intent, mock_revise, mock_save
    ):
        """Revised plan referencing an unregistered tool must be rejected before summary is shown."""
        import tools  # noqa
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_load.return_value = _confirmation_plan()
        bad_plan = Plan(
            steps=[PlanStep(id="s1", tool="nonexistent.tool", params={}, output_var="r")],
            final_output_var="r",
            summary="I will do something unknown.",
        )
        mock_revise.return_value = bad_plan

        response = self._post({"prompt": "change it to use a different tool"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"]["code"], "unknown_tool")
        mock_save.assert_not_called()


class AgentViewDryRunTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="agent_dryrun@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.pending_plan.save")
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="Preview result.")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_dry_run_bypasses_confirmation_and_executes(
        self, mock_get_ctx, mock_plan, mock_execute, mock_save, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _confirmation_plan()

        response = self._post({"prompt": "send email to bob", "dry_run": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Should execute immediately (no confirmation prompt)
        mock_execute.assert_awaited_once()
        mock_save.assert_not_called()
        # execute must be called with dry_run=True
        _, kwargs = mock_execute.call_args
        self.assertTrue(kwargs.get("dry_run"))

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.pending_plan.save")
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="Preview result.")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_dry_run_flag_present_in_response(
        self, mock_get_ctx, mock_plan, mock_execute, mock_save, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _simple_plan()

        response = self._post({"prompt": "what time is it", "dry_run": True})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("dry_run", data)
        self.assertTrue(data["dry_run"])


class PluginFilterHelperTests(TestCase):
    """Unit tests for _get_enabled_plugins and _validate_plan_plugins helpers."""

    def _make_project(self, plugins=None):
        from projects.models import Projects
        uid = str(uuid.uuid4())
        user = User.objects.create_user(email=f"{uid}@test.com", supabase_uid=uid)
        return Projects.objects.create(user=user, name="Test", plugins=plugins or {})

    # --- _get_enabled_plugins ---

    def test_none_project_returns_none(self):
        from agent.views import _get_enabled_plugins
        self.assertIsNone(_get_enabled_plugins(None))

    def test_empty_plugins_returns_none(self):
        from agent.views import _get_enabled_plugins
        project = self._make_project(plugins={})
        self.assertIsNone(_get_enabled_plugins(project))

    def test_enabled_plugins_returns_frozenset(self):
        from agent.views import _get_enabled_plugins
        project = self._make_project(plugins={"gmail": True, "google_calendar": False})
        self.assertEqual(_get_enabled_plugins(project), frozenset({"gmail"}))

    def test_all_enabled_returns_full_set(self):
        from agent.views import _get_enabled_plugins
        project = self._make_project(plugins={"gmail": True, "google_calendar": True})
        self.assertEqual(_get_enabled_plugins(project), frozenset({"gmail", "google_calendar"}))

    # --- _validate_plan_plugins ---

    def test_validate_none_enabled_is_noop(self):
        """None enabled_plugins means no restriction — should never raise."""
        import tools  # noqa: ensure tools app is loaded
        from agent.views import _validate_plan_plugins
        plan = Plan(
            steps=[PlanStep(id="s1", tool="gmail.send_email", params={}, output_var="r")],
            final_output_var="r",
            summary="send",
        )
        _validate_plan_plugins(plan, None)  # must not raise

    def test_validate_raises_for_disabled_plugin(self):
        """A plan step using a disabled plugin should raise UnknownToolError."""
        import tools  # noqa: ensure tools app is loaded
        from agent.views import _validate_plan_plugins
        from tools.registry import UnknownToolError
        plan = Plan(
            steps=[PlanStep(id="s1", tool="gmail.send_email", params={}, output_var="r")],
            final_output_var="r",
            summary="send",
        )
        with self.assertRaises(UnknownToolError):
            _validate_plan_plugins(plan, frozenset({"google_calendar"}))

    def test_validate_passes_for_enabled_plugin(self):
        """A plan step using an enabled plugin should not raise."""
        import tools  # noqa
        from agent.views import _validate_plan_plugins
        plan = Plan(
            steps=[PlanStep(id="s1", tool="gmail.send_email", params={}, output_var="r")],
            final_output_var="r",
            summary="send",
        )
        _validate_plan_plugins(plan, frozenset({"gmail"}))  # must not raise

    def test_validate_passes_for_no_plugin_id_tool(self):
        """Tools with plugin_id=None (processing_llm) are always allowed."""
        import tools  # noqa
        from agent.views import _validate_plan_plugins
        plan = Plan(
            steps=[PlanStep(id="s1", tool="processing_llm", params={}, output_var="r")],
            final_output_var="r",
            summary="respond",
        )
        _validate_plan_plugins(plan, frozenset())  # empty set, but no plugin_id → ok

    # --- _validate_plan_tools ---

    def test_validate_plan_tools_passes_for_known_tool(self):
        import tools  # noqa
        from agent.views import _validate_plan_tools
        plan = Plan(
            steps=[PlanStep(id="s1", tool="processing_llm", params={}, output_var="r")],
            final_output_var="r",
            summary="respond",
        )
        _validate_plan_tools(plan)  # must not raise

    def test_validate_plan_tools_raises_for_unknown_tool(self):
        import tools  # noqa
        from agent.views import _validate_plan_tools
        from tools.registry import UnknownToolError
        plan = Plan(
            steps=[PlanStep(id="s1", tool="nonexistent.tool", params={}, output_var="r")],
            final_output_var="r",
            summary="do something",
        )
        with self.assertRaises(UnknownToolError):
            _validate_plan_tools(plan)


class GetSchemasForPlannerFilterTests(TestCase):
    """Unit tests for get_schemas_for_planner with enabled_plugins filtering."""

    def setUp(self):
        import tools  # noqa: register all tools

    def test_no_filter_returns_all_tools(self):
        from tools.registry import get_schemas_for_planner
        schemas = get_schemas_for_planner(enabled_plugins=None)
        names = {s["name"] for s in schemas}
        self.assertIn("gmail.send_email", names)
        self.assertIn("calendar.list_events", names)
        self.assertIn("processing_llm", names)

    def test_gmail_only_excludes_calendar(self):
        from tools.registry import get_schemas_for_planner
        schemas = get_schemas_for_planner(enabled_plugins=frozenset({"gmail"}))
        names = {s["name"] for s in schemas}
        self.assertIn("gmail.send_email", names)
        self.assertNotIn("calendar.list_events", names)
        self.assertIn("processing_llm", names)

    def test_empty_enabled_set_excludes_all_oauth_tools(self):
        from tools.registry import get_schemas_for_planner
        schemas = get_schemas_for_planner(enabled_plugins=frozenset())
        names = {s["name"] for s in schemas}
        self.assertNotIn("gmail.send_email", names)
        self.assertNotIn("calendar.list_events", names)
        self.assertIn("processing_llm", names)

    def test_google_drive_disabled_excludes_drive_tools(self):
        from tools.registry import get_schemas_for_planner
        schemas = get_schemas_for_planner(enabled_plugins=frozenset({"gmail", "google_calendar"}))
        names = {s["name"] for s in schemas}
        self.assertNotIn("drive.list_files", names)
        self.assertNotIn("drive.search_files", names)
        self.assertNotIn("drive.get_file_metadata", names)

    def test_google_drive_enabled_includes_drive_tools(self):
        from tools.registry import get_schemas_for_planner
        schemas = get_schemas_for_planner(enabled_plugins=frozenset({"google_drive"}))
        names = {s["name"] for s in schemas}
        self.assertIn("drive.list_files", names)
        self.assertIn("drive.search_files", names)
        self.assertIn("drive.get_file_metadata", names)


class AgentViewProjectScopingTests(APITestCase):
    """Verify that project_id is validated against an owned Projects row."""

    def setUp(self):
        from projects.models import Projects
        self.user = User.objects.create_user(
            email="scoping@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.project = Projects.objects.create(user=self.user, name="My Project")
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    def test_non_integer_project_id_returns_400(self):
        response = self._post({"prompt": "hello", "project_id": "default"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_project_id_returns_404(self):
        response = self._post({"prompt": "hello", "project_id": 999999})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_users_project_id_returns_404(self):
        from projects.models import Projects
        other = User.objects.create_user(
            email="other_scoping@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        other_project = Projects.objects.create(user=other, name="Other Project")
        response = self._post({"prompt": "hello", "project_id": other_project.pk})
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="done")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_valid_project_id_is_accepted(self, mock_get_ctx, mock_plan, mock_execute, mock_load):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _simple_plan()
        response = self._post({"prompt": "hello", "project_id": self.project.pk})
        self.assertEqual(response.status_code, status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# SSE helper + streaming view tests
# ---------------------------------------------------------------------------

class SseHelperTests(TestCase):
    def test_sse_encodes_event_and_data(self):
        result = _sse("done", {"response": "hello"})
        self.assertIsInstance(result, bytes)
        text = result.decode()
        self.assertTrue(text.startswith("event: done\n"))
        self.assertIn('"response": "hello"', text)
        self.assertTrue(text.endswith("\n\n"))

    def test_sse_terminates_with_double_newline(self):
        result = _sse("step", {"tool": "gmail.read", "index": 0, "total": 2})
        self.assertTrue(result.decode().endswith("\n\n"))


def _collect_stream(streaming_content) -> bytes:
    """Consume a sync or async streaming response generator and return all bytes."""
    if hasattr(streaming_content, "__anext__"):
        import asyncio

        async def _consume():
            return b"".join([chunk async for chunk in streaming_content])

        return asyncio.run(_consume())
    return b"".join(streaming_content)


def _parse_sse(content: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of {event, data} dicts."""
    events = []
    current: dict = {}
    for line in content.decode().splitlines():
        if line.startswith("event: "):
            current["event"] = line[len("event: "):]
        elif line.startswith("data: "):
            current["data"] = json.loads(line[len("data: "):])
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


class AgentStreamViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="stream@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.url = reverse("agent-stream")

    def _post_stream(self, payload, authenticate=True):
        if authenticate:
            self.client.force_login(self.user)
        return self.client.post(
            self.url,
            json.dumps(payload),
            content_type="application/json",
        )

    def test_get_returns_405(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_unauthenticated_returns_401(self):
        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(None, "Authentication required"))):
            response = self._post_stream({"prompt": "hello"}, authenticate=False)
        self.assertEqual(response.status_code, 401)

    def test_invalid_json_returns_400(self):
        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(self.user, None))):
            response = self.client.post(self.url, "not-json", content_type="application/json")
        self.assertEqual(response.status_code, 400)

    def test_missing_prompt_returns_400(self):
        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(self.user, None))):
            response = self._post_stream({})
        self.assertEqual(response.status_code, 400)

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="Streamed answer.")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_success_emits_status_and_done_events(
        self, mock_get_ctx, mock_plan, mock_execute, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _simple_plan()

        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(self.user, None))):
            with patch("agent.views.get_connected_plugins", new=AsyncMock(return_value=[])):
                response = self._post_stream({"prompt": "hello"})
                content = _collect_stream(response.streaming_content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get("Content-Type"), "text/event-stream")
        events = _parse_sse(content)
        kinds = [e["event"] for e in events]
        self.assertIn("status", kinds)
        self.assertIn("done", kinds)
        done = next(e for e in events if e["event"] == "done")
        self.assertEqual(done["data"]["response"], "Streamed answer.")

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.views.execute", new_callable=AsyncMock, return_value="Answer.")
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_step_events_emitted_during_execution(
        self, mock_get_ctx, mock_plan, mock_execute, mock_load
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_plan.return_value = _simple_plan()

        step_calls = []

        async def fake_execute(plan, user_id, dry_run=False, on_step=None):
            if on_step:
                await on_step("step_1", "processing_llm", 0, 1)
                step_calls.append("called")
            return "Answer."

        mock_exec = AsyncMock(side_effect=fake_execute)
        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(self.user, None))):
            with patch("agent.views.get_connected_plugins", new=AsyncMock(return_value=[])):
                with patch("agent.views.execute", mock_exec):
                    response = self._post_stream({"prompt": "hello"})
                    # Consume the stream while patches are still active — the generator
                    # runs lazily and needs the mocks to still be in scope.
                    content = _collect_stream(response.streaming_content)

        events = _parse_sse(content)
        step_events = [e for e in events if e["event"] == "step"]
        self.assertEqual(len(step_events), 1)
        self.assertEqual(step_events[0]["data"]["tool"], "processing_llm")
        self.assertEqual(step_events[0]["data"]["index"], 0)
        self.assertEqual(step_events[0]["data"]["total"], 1)

    @patch("agent.views.run_prompt", new_callable=AsyncMock, side_effect=PluginNotConnectedError("gmail"))
    def test_plugin_not_connected_emits_error_event(self, _):
        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(self.user, None))):
            response = self._post_stream({"prompt": "send email"})
            content = _collect_stream(response.streaming_content)
        events = _parse_sse(content)
        error_events = [e for e in events if e["event"] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["data"]["code"], "plugin_not_connected")
        self.assertEqual(error_events[0]["data"]["plugin"], "gmail")

    @patch("tools.processing_llm.tool.call_processing_llm", new_callable=AsyncMock, return_value="Something went wrong.")
    @patch("agent.views.run_prompt", new_callable=AsyncMock)
    def test_tool_execution_error_emits_error_event_with_completed_steps(self, mock_run, _):
        completed = [{"step_id": "s1", "tool": "gmail.read", "requires_confirmation": False}]
        mock_run.side_effect = ToolExecutionError("s2", "gmail.send_email", "API error", completed)
        with patch("agent.views._auth_stream", new=AsyncMock(return_value=(self.user, None))):
            response = self._post_stream({"prompt": "read then send"})
            content = _collect_stream(response.streaming_content)
        events = _parse_sse(content)
        error_events = [e for e in events if e["event"] == "error"]
        self.assertEqual(len(error_events), 1)
        err = error_events[0]["data"]
        self.assertEqual(err["code"], "tool_execution_failed")
        self.assertEqual(err["completed_steps"], completed)


# ---------------------------------------------------------------------------
# _format_completed_steps helper
# ---------------------------------------------------------------------------

class FormatCompletedStepsTests(TestCase):
    def test_empty_list_returns_none_string(self):
        self.assertEqual(_format_completed_steps([]), "none")

    def test_non_irreversible_step(self):
        result = _format_completed_steps([
            {"step_id": "s1", "tool": "gmail.read", "requires_confirmation": False}
        ])
        self.assertEqual(result, "gmail.read")

    def test_irreversible_step_labeled(self):
        result = _format_completed_steps([
            {"step_id": "s1", "tool": "gmail.send_email", "requires_confirmation": True}
        ])
        self.assertEqual(result, "gmail.send_email (irreversible)")

    def test_multiple_steps_joined(self):
        result = _format_completed_steps([
            {"step_id": "s1", "tool": "gmail.read", "requires_confirmation": False},
            {"step_id": "s2", "tool": "gmail.send_email", "requires_confirmation": True},
        ])
        self.assertEqual(result, "gmail.read, gmail.send_email (irreversible)")


# ---------------------------------------------------------------------------
# agent_view error handler paths
# ---------------------------------------------------------------------------

class AgentViewErrorTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="errors@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @patch("agent.views.run_prompt", new_callable=AsyncMock, side_effect=PluginNotConnectedError("gmail"))
    def test_plugin_not_connected_returns_422(self, _):
        response = self._post({"prompt": "send email"})
        self.assertEqual(response.status_code, 422)
        data = response.json()
        self.assertEqual(data["error"]["code"], "plugin_not_connected")
        self.assertEqual(data["error"]["plugin"], "gmail")

    @patch("tools.processing_llm.tool.call_processing_llm", new_callable=AsyncMock, return_value="Something went wrong.")
    @patch("agent.views.run_prompt", new_callable=AsyncMock, side_effect=ToolExecutionError("s1", "gmail.send_email", "API error"))
    def test_tool_execution_error_returns_500_with_friendly_message(self, _, __):
        response = self._post({"prompt": "send email"})
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data["error"]["code"], "tool_execution_failed")
        self.assertEqual(data["error"]["message"], "Something went wrong.")

    @patch("tools.processing_llm.tool.call_processing_llm", new_callable=AsyncMock, return_value="Partial failure.")
    @patch("agent.views.run_prompt", new_callable=AsyncMock)
    def test_tool_execution_error_includes_completed_steps(self, mock_run, _):
        completed = [{"step_id": "s1", "tool": "gmail.read", "requires_confirmation": False}]
        mock_run.side_effect = ToolExecutionError("s2", "gmail.send_email", "failed", completed)
        response = self._post({"prompt": "read then send"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["completed_steps"], completed)

    @patch("tools.processing_llm.tool.call_processing_llm", new_callable=AsyncMock, return_value="Partial failure.")
    @patch("agent.views.run_prompt", new_callable=AsyncMock)
    def test_tool_execution_error_omits_completed_steps_when_empty(self, mock_run, _):
        mock_run.side_effect = ToolExecutionError("s1", "gmail.send_email", "failed")
        response = self._post({"prompt": "send email"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("completed_steps", response.json()["error"])

    @patch("agent.views.run_prompt", new_callable=AsyncMock, side_effect=UnknownToolError("nonexistent.tool"))
    def test_unknown_tool_returns_400(self, _):
        response = self._post({"prompt": "do the impossible"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "unknown_tool")


# ---------------------------------------------------------------------------
# Capabilities query shortcut
# ---------------------------------------------------------------------------

class AgentViewCapabilitiesTests(APITestCase):
    def setUp(self):
        import tools  # noqa: register all tools
        self.user = User.objects.create_user(
            email="caps@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_capabilities_query_skips_planner(self, mock_get_ctx, mock_plan, _):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        response = self._post({"prompt": "what can you do"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_plan.assert_not_awaited()
        self.assertIn("Here's what I can help you with", response.json()["response"])

    @patch("agent.pending_plan.load", return_value=None)
    @patch("agent.views.make_plan", new_callable=AsyncMock)
    @patch("agent.views.get_ctx")
    def test_capabilities_response_lists_tool_groups(self, mock_get_ctx, mock_plan, _):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        response = self._post({"prompt": "list your tools"})
        body = response.json()["response"]
        self.assertIn("Gmail", body)
        mock_plan.assert_not_awaited()


# ---------------------------------------------------------------------------
# GET /agent/actions/ audit log endpoint
# ---------------------------------------------------------------------------

class AgentActionsViewTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="audit_view@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent-actions")

    def _create_action(self, tool="gmail.send_email", status="success", params_summary="{}"):
        from agent.models import AgentAction
        return AgentAction.objects.create(
            user=self.user, tool=tool, params_summary=params_summary, status=status
        )

    def test_unauthenticated_returns_4xx(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (401, 403))

    def test_empty_list_initially(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["actions"], [])

    def test_returns_own_actions_only(self):
        other = User.objects.create_user(
            email="other_audit@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        from agent.models import AgentAction
        AgentAction.objects.create(user=other, tool="gmail.send_email", params_summary="", status="success")
        self._create_action()
        response = self.client.get(self.url)
        self.assertEqual(len(response.json()["actions"]), 1)

    def test_action_response_fields(self):
        self._create_action(tool="gmail.send_email", status="success", params_summary='{"to": "alice"}')
        data = self.client.get(self.url).json()["actions"][0]
        for field in ("id", "tool", "params_summary", "status", "timestamp"):
            self.assertIn(field, data)
        self.assertEqual(data["tool"], "gmail.send_email")
        self.assertEqual(data["status"], "success")

    def test_limit_parameter_respected(self):
        for _ in range(5):
            self._create_action()
        response = self.client.get(self.url + "?limit=3")
        self.assertEqual(len(response.json()["actions"]), 3)

    def test_limit_capped_at_200(self):
        response = self.client.get(self.url + "?limit=9999")
        self.assertEqual(response.status_code, 200)

    def test_invalid_limit_falls_back_to_default(self):
        self._create_action()
        response = self.client.get(self.url + "?limit=notanumber")
        self.assertEqual(response.status_code, 200)
        self.assertIn("actions", response.json())

    def test_actions_ordered_newest_first(self):
        a1 = self._create_action(tool="gmail.read")
        a2 = self._create_action(tool="gmail.send_email")
        actions = self.client.get(self.url).json()["actions"]
        self.assertEqual(actions[0]["id"], a2.id)
        self.assertEqual(actions[1]["id"], a1.id)

    # ------------------------------------------------------------------
    # Filtering: ?tool=, ?status=, ?since=
    # ------------------------------------------------------------------

    def test_filter_by_tool(self):
        self._create_action(tool="gmail.send_email")
        self._create_action(tool="calendar.create_event")
        response = self.client.get(self.url + "?tool=gmail.send_email")
        actions = response.json()["actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["tool"], "gmail.send_email")

    def test_filter_by_status(self):
        self._create_action(tool="gmail.send_email", status="success")
        self._create_action(tool="gmail.send_email", status="failed")
        response = self.client.get(self.url + "?status=failed")
        actions = response.json()["actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["status"], "failed")

    def test_filter_by_since(self):
        from django.utils import timezone
        import datetime
        from urllib.parse import urlencode
        from agent.models import AgentAction

        old_action = AgentAction.objects.create(
            user=self.user, tool="gmail.read", params_summary="", status="success"
        )
        # Backdate it
        AgentAction.objects.filter(pk=old_action.pk).update(
            timestamp=timezone.now() - datetime.timedelta(days=10)
        )
        new_action = self._create_action(tool="gmail.send_email")

        since = (timezone.now() - datetime.timedelta(days=1)).isoformat()
        qs = urlencode({"since": since})
        response = self.client.get(f"{self.url}?{qs}")
        actions = response.json()["actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["id"], new_action.id)

    def test_filter_since_invalid_returns_400(self):
        response = self.client.get(self.url + "?since=not-a-date")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "bad_request")

    def test_filter_tool_and_status_combined(self):
        self._create_action(tool="gmail.send_email", status="success")
        self._create_action(tool="gmail.send_email", status="failed")
        self._create_action(tool="calendar.create_event", status="success")
        response = self.client.get(self.url + "?tool=gmail.send_email&status=success")
        actions = response.json()["actions"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["tool"], "gmail.send_email")
        self.assertEqual(actions[0]["status"], "success")


# ---------------------------------------------------------------------------
# Modify cap tests
# ---------------------------------------------------------------------------

class AgentViewModifyCapTests(APITestCase):
    """run_prompt clears the pending plan after AGENT_MAX_MODIFY_REVISIONS modify attempts."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="modifycap@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = uuid.uuid4()
        self.user.save()
        self.client.force_authenticate(user=self.user)
        self.url = reverse("agent")

    def _post(self, payload):
        return self.client.post(self.url, json.dumps(payload), content_type="application/json")

    @override_settings(AGENT_MAX_MODIFY_REVISIONS=2)
    @patch("agent.pending_plan.get_modify_count", return_value=2)
    @patch("agent.pending_plan.clear")
    @patch("agent.pending_plan.reset_modify_count")
    @patch("agent.views.detect_intent", new_callable=AsyncMock, return_value="modify")
    @patch("agent.pending_plan.load")
    @patch("agent.views.get_ctx")
    def test_modify_cap_clears_plan_and_returns_message(
        self, mock_get_ctx, mock_load, mock_intent, mock_reset, mock_clear, mock_get_count
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_load.return_value = _confirmation_plan()

        response = self._post({"prompt": "change it again"})

        self.assertEqual(response.status_code, 200)
        body = response.json()["response"]
        self.assertIn("fresh", body.lower())
        mock_clear.assert_called_once()
        mock_reset.assert_called_once()

    @override_settings(AGENT_MAX_MODIFY_REVISIONS=5)
    @patch("agent.pending_plan.get_modify_count", return_value=3)
    @patch("agent.pending_plan.increment_modify_count")
    @patch("agent.pending_plan.save")
    @patch("agent.views.revise_plan", new_callable=AsyncMock)
    @patch("agent.views.detect_intent", new_callable=AsyncMock, return_value="modify")
    @patch("agent.pending_plan.load")
    @patch("agent.views.get_ctx")
    def test_below_cap_still_revises(
        self, mock_get_ctx, mock_load, mock_intent, mock_revise, mock_save, mock_inc, mock_get_count
    ):
        mock_ctx = MagicMock()
        mock_ctx.as_messages.return_value = []
        mock_get_ctx.return_value = mock_ctx
        mock_load.return_value = _confirmation_plan()
        mock_revise.return_value = _simple_plan(summary="Revised plan.")

        response = self._post({"prompt": "tweak it"})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Shall I proceed?", response.json()["response"])
        mock_revise.assert_awaited_once()
        mock_inc.assert_called_once()
