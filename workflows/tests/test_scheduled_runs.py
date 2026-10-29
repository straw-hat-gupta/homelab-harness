import datetime as dt
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from workflows.models import (
    SavedWorkflow,
    ScheduledRun,
    ScheduledRunExecution,
    compute_next_run_at,
    validate_cron_expression,
    validate_timezone_name,
)
from workflows.runner import WorkflowRunResult
from workflows.scheduling import validate_workflow_schedulable
from workflows.tasks import dispatch_due_scheduled_runs, execute_scheduled_run

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
            "params": {"to": "test@example.com", "subject": "Hi", "body": "Hello"},
            "output_var": "out1",
        }
    ],
    "final_output_var": "out1",
    "summary": "I will send an email.",
}


def _uid():
    return str(uuid.uuid4())


def _create_user(email="scheduled@example.com"):
    return User.objects.create_user(email=email, password="pw", supabase_uid=_uid())


class ScheduledRunModelTests(TestCase):
    def test_cron_validation_rejects_invalid_expression(self):
        with self.assertRaises(ValidationError):
            validate_cron_expression("not a cron")

    def test_timezone_validation_rejects_invalid_timezone(self):
        with self.assertRaises(ValidationError):
            validate_timezone_name("Mars/Olympus")

    def test_next_run_calculation_uses_schedule_timezone_and_returns_utc(self):
        base = dt.datetime(2026, 1, 1, 15, 0, tzinfo=dt.timezone.utc)

        next_run = compute_next_run_at("0 7 * * *", "America/Edmonton", from_time=base)

        self.assertEqual(next_run.tzinfo, dt.timezone.utc)
        self.assertEqual(next_run, dt.datetime(2026, 1, 2, 14, 0, tzinfo=dt.timezone.utc))

    def test_save_computes_next_run_at_when_missing(self):
        user = _create_user()
        workflow = SavedWorkflow.objects.create(user=user, name="WF", plan=VALID_PLAN)

        scheduled_run = ScheduledRun.objects.create(
            user=user,
            workflow=workflow,
            name="Daily",
            cron="0 7 * * *",
            timezone="UTC",
        )

        self.assertIsNotNone(scheduled_run.next_run_at)


class ScheduledWorkflowValidationTests(TestCase):
    def test_schedulable_workflow_accepts_non_confirmation_plan(self):
        user = _create_user()
        workflow = SavedWorkflow.objects.create(user=user, name="WF", plan=VALID_PLAN)

        plan = validate_workflow_schedulable(workflow)

        self.assertEqual(plan.final_output_var, "out1")

    def test_schedulable_workflow_accepts_confirmation_required_tool(self):
        user = _create_user()
        workflow = SavedWorkflow.objects.create(user=user, name="Danger", plan=CONFIRMATION_PLAN)

        plan = validate_workflow_schedulable(workflow)

        self.assertEqual(plan.steps[0].tool, "gmail.send_email")


class ScheduledRunApiTests(APITestCase):
    def setUp(self):
        self.user = _create_user("api@example.com")
        self.client.force_authenticate(user=self.user)
        self.workflow = SavedWorkflow.objects.create(user=self.user, name="WF", plan=VALID_PLAN)

    def test_create_scheduled_run(self):
        resp = self.client.post(
            "/scheduled-runs/",
            {
                "workflow_id": self.workflow.pk,
                "name": "Morning workflow",
                "cron": "0 7 * * *",
                "timezone": "UTC",
            },
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["name"], "Morning workflow")
        self.assertEqual(data["workflow_id"], self.workflow.pk)
        self.assertEqual(data["cron"], "0 7 * * *")
        self.assertTrue(data["enabled"])

    def test_create_rejects_invalid_cron(self):
        resp = self.client.post(
            "/scheduled-runs/",
            {"workflow_id": self.workflow.pk, "cron": "bad", "timezone": "UTC"},
            format="json",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"], "invalid_schedule")

    def test_create_rejects_other_users_workflow(self):
        other = _create_user("other@example.com")
        other_workflow = SavedWorkflow.objects.create(user=other, name="Other", plan=VALID_PLAN)

        resp = self.client.post(
            "/scheduled-runs/",
            {"workflow_id": other_workflow.pk, "cron": "0 7 * * *"},
            format="json",
        )

        self.assertEqual(resp.status_code, 404)

    def test_create_allows_confirmation_required_workflow(self):
        workflow = SavedWorkflow.objects.create(user=self.user, name="Danger", plan=CONFIRMATION_PLAN)

        resp = self.client.post(
            "/scheduled-runs/",
            {"workflow_id": workflow.pk, "cron": "0 7 * * *"},
            format="json",
        )

        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()["workflow_id"], workflow.pk)

    def test_list_returns_only_own_scheduled_runs(self):
        ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Mine",
            cron="0 7 * * *",
            timezone="UTC",
        )
        other = _create_user("other-list@example.com")
        other_workflow = SavedWorkflow.objects.create(user=other, name="Other", plan=VALID_PLAN)
        ScheduledRun.objects.create(
            user=other,
            workflow=other_workflow,
            name="Theirs",
            cron="0 7 * * *",
            timezone="UTC",
        )

        resp = self.client.get("/scheduled-runs/")

        self.assertEqual(resp.status_code, 200)
        names = {item["name"] for item in resp.json()["results"]}
        self.assertEqual(names, {"Mine"})

    def test_update_scheduled_run(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Old",
            cron="0 7 * * *",
            timezone="UTC",
        )

        resp = self.client.put(
            f"/scheduled-runs/{scheduled_run.pk}/",
            {"name": "New", "enabled": False},
            format="json",
        )

        self.assertEqual(resp.status_code, 200)
        scheduled_run.refresh_from_db()
        self.assertEqual(scheduled_run.name, "New")
        self.assertFalse(scheduled_run.enabled)

    def test_run_now_queues_execution(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Manual",
            cron="0 7 * * *",
            timezone="UTC",
        )
        async_result = MagicMock(id="task-123")

        with patch("workflows.scheduled_views.run_scheduled_run.delay", return_value=async_result) as delay:
            resp = self.client.post(f"/scheduled-runs/{scheduled_run.pk}/run-now/")

        self.assertEqual(resp.status_code, 202)
        execution = ScheduledRunExecution.objects.get(scheduled_run=scheduled_run)
        self.assertEqual(execution.status, "queued")
        self.assertEqual(execution.celery_task_id, "task-123")
        delay.assert_called_once_with(execution.pk)

    def test_run_now_marks_execution_failed_when_queue_unavailable(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Manual",
            cron="0 7 * * *",
            timezone="UTC",
        )

        with patch("workflows.scheduled_views.run_scheduled_run.delay", side_effect=RuntimeError("broker down")):
            resp = self.client.post(f"/scheduled-runs/{scheduled_run.pk}/run-now/")

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"], "queue_unavailable")
        execution = ScheduledRunExecution.objects.get(scheduled_run=scheduled_run)
        self.assertEqual(execution.status, "failed")
        self.assertIn("broker down", execution.error)

    def test_executions_list_returns_history(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="History",
            cron="0 7 * * *",
            timezone="UTC",
        )
        ScheduledRunExecution.objects.create(
            scheduled_run=scheduled_run,
            workflow=self.workflow,
            status="success",
            result="done",
        )

        resp = self.client.get(f"/scheduled-runs/{scheduled_run.pk}/executions/")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["status"], "success")
        self.assertEqual(resp.json()["results"][0]["result"], "done")


class ScheduledRunTaskTests(TestCase):
    def setUp(self):
        self.user = _create_user("tasks@example.com")
        self.workflow = SavedWorkflow.objects.create(user=self.user, name="WF", plan=VALID_PLAN)

    def test_dispatcher_enqueues_due_run_once_and_advances_next_run(self):
        due_at = timezone.now() - dt.timedelta(minutes=5)
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Due",
            cron="*/5 * * * *",
            timezone="UTC",
            next_run_at=due_at,
        )
        async_result = MagicMock(id="task-456")

        with patch("workflows.tasks.run_scheduled_run.delay", return_value=async_result) as delay:
            result = dispatch_due_scheduled_runs.run()

        scheduled_run.refresh_from_db()
        execution = ScheduledRunExecution.objects.get(scheduled_run=scheduled_run)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(execution.celery_task_id, "task-456")
        self.assertGreater(scheduled_run.next_run_at, due_at)
        delay.assert_called_once_with(execution.pk)

        with patch("workflows.tasks.run_scheduled_run.delay") as second_delay:
            second = dispatch_due_scheduled_runs.run()
        self.assertEqual(second["queued"], 0)
        second_delay.assert_not_called()

    def test_dispatcher_marks_execution_failed_when_queue_unavailable(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Due",
            cron="*/5 * * * *",
            timezone="UTC",
            next_run_at=timezone.now() - dt.timedelta(minutes=5),
        )

        with patch("workflows.tasks.run_scheduled_run.delay", side_effect=RuntimeError("broker down")):
            result = dispatch_due_scheduled_runs.run()

        execution = ScheduledRunExecution.objects.get(scheduled_run=scheduled_run)
        scheduled_run.refresh_from_db()
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["failed_to_queue"], 1)
        self.assertEqual(execution.status, "failed")
        self.assertEqual(scheduled_run.last_status, "failed")
        self.assertIn("broker down", execution.error)

    def test_worker_persists_success_result(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Success",
            cron="0 7 * * *",
            timezone="UTC",
        )
        execution = ScheduledRunExecution.objects.create(
            scheduled_run=scheduled_run,
            workflow=self.workflow,
            status="queued",
        )

        with patch(
            "workflows.tasks.run_saved_workflow",
            return_value=WorkflowRunResult(status="success", result="done"),
        ) as run_saved_workflow:
            result = execute_scheduled_run(execution.pk, celery_task_id="task-success")

        execution.refresh_from_db()
        scheduled_run.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(execution.status, "success")
        self.assertEqual(execution.result, "done")
        self.assertEqual(execution.celery_task_id, "task-success")
        self.assertEqual(scheduled_run.last_status, "success")
        run_saved_workflow.assert_called_once_with(self.workflow, self.user)

    def test_worker_executes_confirmation_required_workflow_through_runner(self):
        workflow = SavedWorkflow.objects.create(user=self.user, name="Danger", plan=CONFIRMATION_PLAN)
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=workflow,
            name="Danger",
            cron="0 7 * * *",
            timezone="UTC",
        )
        execution = ScheduledRunExecution.objects.create(
            scheduled_run=scheduled_run,
            workflow=workflow,
            status="queued",
        )

        with patch(
            "workflows.tasks.run_saved_workflow",
            return_value=WorkflowRunResult(status="success", result="sent"),
        ) as run_saved_workflow:
            result = execute_scheduled_run(execution.pk)

        execution.refresh_from_db()
        self.assertEqual(result["status"], "success")
        self.assertEqual(execution.status, "success")
        self.assertEqual(execution.result, "sent")
        run_saved_workflow.assert_called_once_with(workflow, self.user)

    def test_worker_skips_disabled_schedule(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Disabled",
            cron="0 7 * * *",
            timezone="UTC",
            enabled=False,
        )
        execution = ScheduledRunExecution.objects.create(
            scheduled_run=scheduled_run,
            workflow=self.workflow,
            status="queued",
        )

        result = execute_scheduled_run(execution.pk)

        execution.refresh_from_db()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(execution.status, "skipped")

    def test_worker_records_plugin_not_connected_failure(self):
        scheduled_run = ScheduledRun.objects.create(
            user=self.user,
            workflow=self.workflow,
            name="Plugin missing",
            cron="0 7 * * *",
            timezone="UTC",
        )
        execution = ScheduledRunExecution.objects.create(
            scheduled_run=scheduled_run,
            workflow=self.workflow,
            status="queued",
        )

        with patch(
            "workflows.tasks.run_saved_workflow",
            return_value=WorkflowRunResult(
                status="failed",
                error_code="plugin_not_connected",
                error_detail="Plugin not connected: gmail",
                plugin_id="gmail",
            ),
        ):
            result = execute_scheduled_run(execution.pk)

        execution.refresh_from_db()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(execution.status, "failed")
        self.assertIn("gmail", execution.error)
