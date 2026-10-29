"""Tests for saved workflow CRUD + run endpoints (/workflows/) and tool schema endpoint (/tools/)."""
import uuid
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from plugins.models import Credentials
from workflows.models import SavedWorkflow
from workflows.runner import WorkflowRunResult

_TEST_ENCRYPTION_KEY = Fernet.generate_key().decode()

User = get_user_model()

_VALID_PLAN = {
    "steps": [
        {
            "id": "step1",
            "tool": "processing_llm",
            "params": {"prompt": "Hello"},
            "output_var": "out1",
        }
    ],
    "final_output_var": "out1",
    "summary": "Say hello",
}


def _uid():
    return str(uuid.uuid4())


class WorkflowListViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="wf@example.com", password="pw", supabase_uid=_uid()
        )
        self.client.force_authenticate(user=self.user)

    def test_list_empty(self):
        resp = self.client.get("/workflows/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"], [])

    def test_list_returns_own_workflows(self):
        SavedWorkflow.objects.create(user=self.user, name="WF1", plan=_VALID_PLAN)
        SavedWorkflow.objects.create(user=self.user, name="WF2", plan=_VALID_PLAN)
        resp = self.client.get("/workflows/")
        self.assertEqual(resp.status_code, 200)
        names = {w["name"] for w in resp.json()["results"]}
        self.assertEqual(names, {"WF1", "WF2"})

    def test_list_isolates_other_users(self):
        other = User.objects.create_user(
            email="other@example.com", password="pw", supabase_uid=_uid()
        )
        SavedWorkflow.objects.create(user=other, name="Secret", plan=_VALID_PLAN)
        resp = self.client.get("/workflows/")
        self.assertEqual(resp.json()["results"], [])

    def test_post_creates_workflow(self):
        resp = self.client.post(
            "/workflows/",
            {"name": "My Workflow", "plan": _VALID_PLAN},
            format="json",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "My Workflow")
        self.assertEqual(data["plan"], _VALID_PLAN)
        self.assertTrue(SavedWorkflow.objects.filter(user=self.user, name="My Workflow").exists())

    def test_post_missing_name(self):
        resp = self.client.post(
            "/workflows/",
            {"plan": _VALID_PLAN},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_missing_plan(self):
        resp = self.client.post(
            "/workflows/",
            {"name": "No Plan"},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_post_invalid_plan(self):
        resp = self.client.post(
            "/workflows/",
            {"name": "Bad", "plan": {"steps": "not-a-list"}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_plan")

    def test_post_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post(
            "/workflows/",
            {"name": "WF", "plan": _VALID_PLAN},
            format="json",
        )
        self.assertIn(resp.status_code, [401, 403])


class WorkflowDetailViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="wfdetail@example.com", password="pw", supabase_uid=_uid()
        )
        self.client.force_authenticate(user=self.user)
        self.wf = SavedWorkflow.objects.create(
            user=self.user, name="Original", description="desc", plan=_VALID_PLAN
        )

    def test_get_returns_workflow(self):
        resp = self.client.get(f"/workflows/{self.wf.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "Original")

    def test_delete_removes_workflow(self):
        resp = self.client.delete(f"/workflows/{self.wf.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertFalse(SavedWorkflow.objects.filter(pk=self.wf.pk).exists())

    def test_put_updates_name(self):
        resp = self.client.put(
            f"/workflows/{self.wf.pk}/",
            {"name": "Renamed"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.wf.refresh_from_db()
        self.assertEqual(self.wf.name, "Renamed")

    def test_put_updates_plan(self):
        new_plan = dict(_VALID_PLAN, summary="Updated summary")
        resp = self.client.put(
            f"/workflows/{self.wf.pk}/",
            {"plan": new_plan},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.wf.refresh_from_db()
        self.assertEqual(self.wf.plan["summary"], "Updated summary")

    def test_put_rejects_invalid_plan(self):
        resp = self.client.put(
            f"/workflows/{self.wf.pk}/",
            {"plan": {"bad": True}},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_plan")

    def test_cannot_access_other_users_workflow(self):
        other = User.objects.create_user(
            email="other3@example.com", password="pw", supabase_uid=_uid()
        )
        other_wf = SavedWorkflow.objects.create(user=other, name="Theirs", plan=_VALID_PLAN)
        resp = self.client.get(f"/workflows/{other_wf.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_get_404_for_missing(self):
        resp = self.client.get("/workflows/99999/")
        self.assertEqual(resp.status_code, 404)


class WorkflowRunViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="wfrun@example.com",
            password="pw",
            supabase_uid=str(uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")),
        )
        self.client.force_authenticate(user=self.user)
        self.wf = SavedWorkflow.objects.create(
            user=self.user, name="Runner", plan=_VALID_PLAN
        )

    def test_run_calls_runner_and_returns_result(self):
        from workflows import views as workflow_views

        with patch.object(
            workflow_views,
            "run_saved_workflow",
            return_value=WorkflowRunResult(status="success", result="Hello!"),
        ) as run_saved_workflow:
            resp = self.client.post(f"/workflows/{self.wf.pk}/run/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["result"], "Hello!")
        run_saved_workflow.assert_called_once_with(self.wf, self.user, inputs={})

    def test_run_returns_404_for_missing(self):
        resp = self.client.post("/workflows/99999/run/")
        self.assertEqual(resp.status_code, 404)

    def test_run_returns_500_on_execution_error(self):
        from workflows import views as workflow_views

        with patch.object(
            workflow_views,
            "run_saved_workflow",
            return_value=WorkflowRunResult(status="failed", error_code="execution_error", error_detail="tool failed"),
        ):
            resp = self.client.post(f"/workflows/{self.wf.pk}/run/")
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.json()["error"], "execution_error")


@override_settings(CREDENTIAL_ENCRYPTION_KEY=_TEST_ENCRYPTION_KEY)
class WorkflowToolsViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="wftools@example.com", password="pw", supabase_uid=_uid()
        )
        self.client.force_authenticate(user=self.user)

    def test_returns_only_system_tools_when_no_credentials(self):
        resp = self.client.get("/tools/")
        self.assertEqual(resp.status_code, 200)
        tools = resp.json()["tools"]
        self.assertTrue(len(tools) > 0)
        # All returned tools should have no plugin_id (system tools only)
        for tool in tools:
            self.assertIsNone(tool["plugin_id"], f"Expected system tool, got plugin tool: {tool['name']}")

    def test_includes_plugin_tools_when_credential_connected(self):
        Credentials.objects.create(
            user=self.user,
            plugin="gmail",
            account_id="test@gmail.com",
            access_token="tok",
            status="active",
        )
        resp = self.client.get("/tools/")
        self.assertEqual(resp.status_code, 200)
        names = {t["name"] for t in resp.json()["tools"]}
        self.assertIn("gmail.send_email", names)

    def test_excludes_revoked_plugin_tools(self):
        Credentials.objects.create(
            user=self.user,
            plugin="gmail",
            account_id="test@gmail.com",
            access_token="tok",
            status="revoked",
        )
        resp = self.client.get("/tools/")
        names = {t["name"] for t in resp.json()["tools"]}
        self.assertNotIn("gmail.send_email", names)

    def test_plugin_filter(self):
        Credentials.objects.create(
            user=self.user,
            plugin="gmail",
            account_id="test@gmail.com",
            access_token="tok",
            status="active",
        )
        resp = self.client.get("/tools/?plugin=gmail")
        self.assertEqual(resp.status_code, 200)
        tools = resp.json()["tools"]
        self.assertTrue(len(tools) > 0)
        for tool in tools:
            self.assertEqual(tool["plugin_id"], "gmail")

    def test_system_filter(self):
        resp = self.client.get("/tools/?plugin=system")
        self.assertEqual(resp.status_code, 200)
        tools = resp.json()["tools"]
        self.assertTrue(len(tools) > 0)
        for tool in tools:
            self.assertIsNone(tool["plugin_id"])

    def test_tool_schema_shape(self):
        resp = self.client.get("/tools/")
        tool = resp.json()["tools"][0]
        self.assertIn("name", tool)
        self.assertIn("display_name", tool)
        self.assertIn("description", tool)
        self.assertIn("plugin_id", tool)
        self.assertIn("params", tool)

    def test_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.get("/tools/")
        self.assertIn(resp.status_code, [401, 403])
