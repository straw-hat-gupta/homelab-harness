import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from orchestrator.exceptions import PluginNotConnectedError
from workflows.models import SavedWorkflow
from workflows.runner import run_saved_workflow

User = get_user_model()

VALID_PLAN = {
    "steps": [
        {
            "id": "step1",
            "tool": "processing_llm",
            "params": {"prompt": "Summarize this."},
            "output_var": "out1",
        }
    ],
    "final_output_var": "out1",
    "summary": "I will summarize the provided input.",
}

CONFIRMATION_PLAN = {
    "steps": [
        {
            "id": "step1",
            "tool": "gmail.send_email",
            "params": {"to": ["test@example.com"], "subject": "Hi", "body": "Hello"},
            "output_var": "out1",
        }
    ],
    "final_output_var": "out1",
    "summary": "I will send an email.",
}


def _create_user(email="runner@example.com"):
    return User.objects.create_user(email=email, password="pw", supabase_uid=str(uuid.uuid4()))


class WorkflowRunnerTests(TestCase):
    def setUp(self):
        self.user = _create_user()

    def test_run_executes_valid_workflow(self):
        workflow = SavedWorkflow.objects.create(user=self.user, name="WF", plan=VALID_PLAN)

        with patch("workflows.runner.async_to_sync", return_value=lambda *args, **kwargs: "done") as wrapper:
            result = run_saved_workflow(workflow, self.user)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result, "done")
        self.assertIsNone(result.error_code)
        wrapper.assert_called_once()

    def test_run_executes_confirmation_required_workflow_without_runner_policy(self):
        workflow = SavedWorkflow.objects.create(user=self.user, name="Danger", plan=CONFIRMATION_PLAN)

        with patch("workflows.runner.async_to_sync", return_value=lambda *args, **kwargs: "sent") as wrapper:
            result = run_saved_workflow(workflow, self.user)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.result, "sent")
        wrapper.assert_called_once()

    def test_plugin_not_connected_is_structured_failure(self):
        workflow = SavedWorkflow.objects.create(user=self.user, name="WF", plan=VALID_PLAN)

        def raise_missing(*args, **kwargs):
            raise PluginNotConnectedError("gmail")

        with patch("workflows.runner.async_to_sync", return_value=raise_missing):
            result = run_saved_workflow(workflow, self.user)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "plugin_not_connected")
        self.assertEqual(result.plugin_id, "gmail")
