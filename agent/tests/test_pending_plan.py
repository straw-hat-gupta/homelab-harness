import uuid

from django.test import TestCase

from agent import pending_plan
from planner.schemas import Plan, PlanStep


def _make_plan(summary="I will do something."):
    return Plan(
        steps=[PlanStep(id="step_1", tool="processing_llm", params={}, output_var="result")],
        final_output_var="result",
        summary=summary,
    )


def _make_user_and_project():
    from django.contrib.auth import get_user_model
    from projects.models import Projects
    User = get_user_model()
    uid = str(uuid.uuid4())
    user = User.objects.create_user(email=f"{uid}@test.com", supabase_uid=uid)
    project = Projects.objects.create(user=user, name="Test Project")
    return uid, project


class PendingPlanTests(TestCase):
    def test_load_nonexistent_returns_none_for_invalid_id(self):
        result = pending_plan.load("user1", "default")
        self.assertIsNone(result)

    def test_load_nonexistent_project_pk_returns_none(self):
        result = pending_plan.load("user1", "99999")
        self.assertIsNone(result)

    def test_save_and_load_roundtrip(self):
        uid, project = _make_user_and_project()
        plan = _make_plan()
        pending_plan.save(uid, str(project.pk), plan)
        loaded = pending_plan.load(uid, str(project.pk))
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.summary, plan.summary)
        self.assertEqual(loaded.final_output_var, "result")
        self.assertEqual(len(loaded.steps), 1)

    def test_clear_removes_plan(self):
        uid, project = _make_user_and_project()
        plan = _make_plan()
        pending_plan.save(uid, str(project.pk), plan)
        pending_plan.clear(uid, str(project.pk))
        result = pending_plan.load(uid, str(project.pk))
        self.assertIsNone(result)

    def test_clear_nonexistent_does_not_raise(self):
        pending_plan.clear("nobody", "default")

    def test_different_projects_isolated(self):
        uid, project_a = _make_user_and_project()
        uid2, project_b = _make_user_and_project()
        pending_plan.save(uid, str(project_a.pk), _make_plan("plan A"))
        pending_plan.save(uid2, str(project_b.pk), _make_plan("plan B"))
        plan_a = pending_plan.load(uid, str(project_a.pk))
        plan_b = pending_plan.load(uid2, str(project_b.pk))
        self.assertEqual(plan_a.summary, "plan A")
        self.assertEqual(plan_b.summary, "plan B")

    def test_different_users_same_project_pk_isolated(self):
        uid_a, project_a = _make_user_and_project()
        uid_b, _ = _make_user_and_project()
        pending_plan.save(uid_a, str(project_a.pk), _make_plan("user_a plan"))
        # uid_b doesn't own project_a, so load returns None
        result = pending_plan.load(uid_b, str(project_a.pk))
        self.assertIsNone(result)
