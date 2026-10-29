import asyncio
import uuid
import unittest
from unittest.mock import AsyncMock, MagicMock

import requests

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase

from orchestrator.exceptions import ToolExecutionError
from orchestrator.orchestrator import _is_retryable, _resolve, execute
from tools.registry import ToolDef, _REGISTRY, register
from planner.schemas import Plan, PlanStep

User = get_user_model()


def _make_plan(*steps, final_output_var=None):
    plan_steps = []
    for i, (tool, output_var) in enumerate(steps, 1):
        plan_steps.append(PlanStep(id=f"step_{i}", tool=tool, params={}, output_var=output_var))
    return Plan(
        steps=plan_steps,
        final_output_var=final_output_var or steps[-1][1],
        summary="I will execute.",
    )


def _register_mock(name, return_value="ok", requires_creds=False, requires_confirmation=False):
    fn = AsyncMock(return_value=return_value)
    register(
        ToolDef(
            name=name,
            description="mock",
            params_schema={},
            fn=fn,
            requires_creds=requires_creds,
            requires_confirmation=requires_confirmation,
        )
    )
    return fn


class ResolveTests(unittest.TestCase):
    def test_literal_string_unchanged(self):
        self.assertEqual(_resolve("hello", {}), "hello")

    def test_dollar_ref_resolved(self):
        self.assertEqual(_resolve("$foo", {"foo": "bar"}), "bar")

    def test_nested_dict_resolved(self):
        result = _resolve({"key": "$val"}, {"val": 42})
        self.assertEqual(result, {"key": 42})

    def test_nested_list_resolved(self):
        result = _resolve(["$x", "$y"], {"x": 1, "y": 2})
        self.assertEqual(result, [1, 2])

    def test_deeply_nested_resolved(self):
        result = _resolve({"outer": {"inner": "$v"}}, {"v": "found"})
        self.assertEqual(result["outer"]["inner"], "found")

    def test_undefined_var_raises_key_error(self):
        with self.assertRaises(KeyError):
            _resolve("$undefined", {})

    def test_non_dollar_string_unchanged(self):
        self.assertEqual(_resolve("regular text", {}), "regular text")

    def test_integer_unchanged(self):
        self.assertEqual(_resolve(42, {}), 42)


class IsRetryableTests(unittest.TestCase):
    def test_http_500_is_retryable(self):
        exc = requests.exceptions.HTTPError()
        exc.response = MagicMock(status_code=500)
        self.assertTrue(_is_retryable(exc))

    def test_http_503_is_retryable(self):
        exc = requests.exceptions.HTTPError()
        exc.response = MagicMock(status_code=503)
        self.assertTrue(_is_retryable(exc))

    def test_http_400_not_retryable(self):
        exc = requests.exceptions.HTTPError()
        exc.response = MagicMock(status_code=400)
        self.assertFalse(_is_retryable(exc))

    def test_http_401_not_retryable(self):
        exc = requests.exceptions.HTTPError()
        exc.response = MagicMock(status_code=401)
        self.assertFalse(_is_retryable(exc))

    def test_generic_exception_not_retryable(self):
        self.assertFalse(_is_retryable(ValueError("boom")))

    def test_connection_error_not_retryable(self):
        self.assertFalse(_is_retryable(requests.exceptions.ConnectionError()))


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self._saved = dict(_REGISTRY)

    def tearDown(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    def test_single_step_returns_output(self):
        _register_mock("processing_llm", "Hello!")
        plan = _make_plan(("processing_llm", "result"))
        self.assertEqual(asyncio.run(execute(plan, user_id="u1")), "Hello!")

    def test_multi_step_resolves_variable_references(self):
        fetch_fn = _register_mock("data.fetch", {"items": ["a", "b"]})
        process_fn = _register_mock("processing_llm", "Processed!")
        plan = Plan(
            steps=[
                PlanStep(id="step_1", tool="data.fetch", params={}, output_var="data"),
                PlanStep(
                    id="step_2",
                    tool="processing_llm",
                    params={"input": "$data"},
                    output_var="final",
                ),
            ],
            final_output_var="final",
            summary="I will fetch and process.",
        )
        result = asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(result, "Processed!")
        call_kwargs = process_fn.call_args.kwargs
        self.assertEqual(call_kwargs["input"], {"items": ["a", "b"]})

    def test_unknown_tool_raises_tool_execution_error(self):
        plan = _make_plan(("nonexistent.tool", "result"))
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(ctx.exception.step_id, "step_1")
        self.assertEqual(ctx.exception.tool, "nonexistent.tool")

    def test_undefined_variable_raises_tool_execution_error(self):
        _register_mock("processing_llm", "done")
        plan = Plan(
            steps=[
                PlanStep(
                    id="step_1",
                    tool="processing_llm",
                    params={"input": "$undefined_var"},
                    output_var="result",
                )
            ],
            final_output_var="result",
            summary="I will fail.",
        )
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(ctx.exception.step_id, "step_1")

    def test_non_string_result_serialized_to_json(self):
        _register_mock("processing_llm", {"key": "value"})
        plan = _make_plan(("processing_llm", "result"))
        result = asyncio.run(execute(plan, user_id="u1"))
        self.assertIn("key", result)
        self.assertIn("value", result)

    def test_steps_execute_in_order(self):
        call_order = []

        async def step1_fn(**kwargs):
            call_order.append("step1")
            return "step1_result"

        async def step2_fn(**kwargs):
            call_order.append("step2")
            return "step2_result"

        register(ToolDef(name="step1.tool", description="", params_schema={}, fn=step1_fn))
        register(ToolDef(name="step2.tool", description="", params_schema={}, fn=step2_fn))

        plan = _make_plan(("step1.tool", "r1"), ("step2.tool", "r2"))
        asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(call_order, ["step1", "step2"])

    # ------------------------------------------------------------------
    # Dry-run tests
    # ------------------------------------------------------------------

    def test_dry_run_skips_confirmation_step(self):
        confirm_fn = _register_mock("action.do", "side_effect!", requires_confirmation=True)
        _register_mock("processing_llm", "Summary.")
        plan = Plan(
            steps=[
                PlanStep(id="step_1", tool="action.do", params={}, output_var="action_result"),
                PlanStep(id="step_2", tool="processing_llm", params={"data": "$action_result"}, output_var="final"),
            ],
            final_output_var="final",
            summary="I will do an action.",
        )
        asyncio.run(execute(plan, user_id="u1", dry_run=True))
        confirm_fn.assert_not_awaited()

    def test_dry_run_appends_notice(self):
        _register_mock("action.do", "side_effect!", requires_confirmation=True)
        _register_mock("processing_llm", "Summary.")
        plan = Plan(
            steps=[
                PlanStep(id="step_1", tool="action.do", params={}, output_var="action_result"),
                PlanStep(id="step_2", tool="processing_llm", params={"data": "$action_result"}, output_var="final"),
            ],
            final_output_var="final",
            summary="I will do an action.",
        )
        result = asyncio.run(execute(plan, user_id="u1", dry_run=True))
        self.assertIn("Dry run", result)
        self.assertIn("action.do", result)

    def test_dry_run_executes_non_confirmation_steps(self):
        fetch_fn = _register_mock("data.fetch", {"rows": [1, 2]}, requires_confirmation=False)
        _register_mock("processing_llm", "Got data.")
        plan = Plan(
            steps=[
                PlanStep(id="step_1", tool="data.fetch", params={}, output_var="data"),
                PlanStep(id="step_2", tool="processing_llm", params={"d": "$data"}, output_var="final"),
            ],
            final_output_var="final",
            summary="I will fetch and summarize.",
        )
        result = asyncio.run(execute(plan, user_id="u1", dry_run=True))
        fetch_fn.assert_awaited_once()
        self.assertEqual(result, "Got data.")

    def test_normal_run_executes_confirmation_step(self):
        confirm_fn = _register_mock("action.do", "done!", requires_confirmation=True)
        _register_mock("processing_llm", "All done.")
        plan = Plan(
            steps=[
                PlanStep(id="step_1", tool="action.do", params={}, output_var="action_result"),
                PlanStep(id="step_2", tool="processing_llm", params={"d": "$action_result"}, output_var="final"),
            ],
            final_output_var="final",
            summary="I will do an action.",
        )
        asyncio.run(execute(plan, user_id="u1", dry_run=False))
        confirm_fn.assert_awaited_once()

    # ------------------------------------------------------------------
    # on_step callback tests
    # ------------------------------------------------------------------

    def test_on_step_called_for_each_completed_step(self):
        _register_mock("processing_llm", "done")
        plan = _make_plan(("processing_llm", "result"))
        calls = []

        async def on_step(step_id, tool, index, total):
            calls.append((step_id, tool, index, total))

        asyncio.run(execute(plan, user_id="u1", on_step=on_step))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("step_1", "processing_llm", 0, 1))

    def test_on_step_called_with_correct_index_for_multi_step(self):
        _register_mock("step1.tool", "r1")
        _register_mock("processing_llm", "done")
        plan = _make_plan(("step1.tool", "r1"), ("processing_llm", "result"))
        calls = []

        async def on_step(step_id, tool, index, total):
            calls.append((index, total, tool))

        asyncio.run(execute(plan, user_id="u1", on_step=on_step))
        self.assertEqual(calls, [(0, 2, "step1.tool"), (1, 2, "processing_llm")])

    def test_on_step_not_called_for_dry_run_skipped_steps(self):
        _register_mock("action.do", "x", requires_confirmation=True)
        _register_mock("processing_llm", "Summary.")
        plan = Plan(
            steps=[
                PlanStep(id="step_1", tool="action.do", params={}, output_var="r"),
                PlanStep(id="step_2", tool="processing_llm", params={"d": "$r"}, output_var="final"),
            ],
            final_output_var="final",
            summary="I will do.",
        )
        calls = []

        async def on_step(step_id, tool, index, total):
            calls.append(tool)

        asyncio.run(execute(plan, user_id="u1", dry_run=True, on_step=on_step))
        self.assertNotIn("action.do", calls)
        self.assertIn("processing_llm", calls)

    def test_on_step_none_does_not_raise(self):
        _register_mock("processing_llm", "ok")
        plan = _make_plan(("processing_llm", "result"))
        result = asyncio.run(execute(plan, user_id="u1", on_step=None))
        self.assertEqual(result, "ok")


class ExecuteCompletedStepsTests(unittest.TestCase):
    """Verify completed_steps dict format in ToolExecutionError on partial failure."""

    def setUp(self):
        self._saved = dict(_REGISTRY)

    def tearDown(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    def test_completed_steps_empty_when_first_step_fails(self):
        fn = _register_mock("step1.tool", "r1")
        fn.side_effect = RuntimeError("boom")
        plan = _make_plan(("step1.tool", "r1"))
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(ctx.exception.completed_steps, [])

    def test_completed_steps_has_prior_step_on_mid_failure(self):
        _register_mock("step1.tool", "ok")
        fail_fn = _register_mock("step2.tool", "r2")
        fail_fn.side_effect = RuntimeError("boom")
        plan = _make_plan(("step1.tool", "r1"), ("step2.tool", "r2"))
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(len(ctx.exception.completed_steps), 1)
        step = ctx.exception.completed_steps[0]
        self.assertEqual(step["step_id"], "step_1")
        self.assertEqual(step["tool"], "step1.tool")
        self.assertFalse(step["requires_confirmation"])

    def test_completed_steps_flags_irreversible_prior_step(self):
        _register_mock("action.do", "done", requires_confirmation=True)
        fail_fn = _register_mock("step2.tool", "r2")
        fail_fn.side_effect = RuntimeError("boom")
        plan = _make_plan(("action.do", "r1"), ("step2.tool", "r2"))
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        step = ctx.exception.completed_steps[0]
        self.assertTrue(step["requires_confirmation"])
        self.assertEqual(step["tool"], "action.do")

    def test_completed_steps_dicts_have_required_keys(self):
        _register_mock("step1.tool", "ok")
        fail_fn = _register_mock("step2.tool", "r2")
        fail_fn.side_effect = RuntimeError("boom")
        plan = _make_plan(("step1.tool", "r1"), ("step2.tool", "r2"))
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        for entry in ctx.exception.completed_steps:
            self.assertIn("step_id", entry)
            self.assertIn("tool", entry)
            self.assertIn("requires_confirmation", entry)

    def test_multiple_completed_steps_accumulated(self):
        _register_mock("step1.tool", "r1")
        _register_mock("step2.tool", "r2")
        fail_fn = _register_mock("step3.tool", "r3")
        fail_fn.side_effect = RuntimeError("boom")
        plan = _make_plan(("step1.tool", "r1"), ("step2.tool", "r2"), ("step3.tool", "r3"))
        with self.assertRaises(ToolExecutionError) as ctx:
            asyncio.run(execute(plan, user_id="u1"))
        self.assertEqual(len(ctx.exception.completed_steps), 2)
        self.assertEqual(ctx.exception.completed_steps[0]["step_id"], "step_1")
        self.assertEqual(ctx.exception.completed_steps[1]["step_id"], "step_2")


class AgentActionAuditTests(TransactionTestCase):
    """Verify that _record_action creates AgentAction rows for confirmed-step executions."""

    def setUp(self):
        self._saved = dict(_REGISTRY)
        self.user = User.objects.create_user(
            email="audit@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        self.user.supabase_uid = str(uuid.uuid4())
        self.user.save()

    def tearDown(self):
        _REGISTRY.clear()
        _REGISTRY.update(self._saved)

    def test_confirmed_success_creates_audit_record(self):
        from agent.models import AgentAction
        _register_mock("action.do", "done", requires_confirmation=True)
        _register_mock("processing_llm", "All done.")
        plan = Plan(
            steps=[
                PlanStep(id="s1", tool="action.do", params={}, output_var="r"),
                PlanStep(id="s2", tool="processing_llm", params={"d": "$r"}, output_var="final"),
            ],
            final_output_var="final",
            summary="I will act.",
        )
        asyncio.run(execute(plan, user_id=self.user.supabase_uid))
        self.assertEqual(
            AgentAction.objects.filter(user=self.user, tool="action.do", status="success").count(), 1
        )

    def test_confirmed_failure_creates_failed_audit_record(self):
        from agent.models import AgentAction
        fail_fn = _register_mock("action.do", requires_confirmation=True)
        fail_fn.side_effect = RuntimeError("boom")
        plan = _make_plan(("action.do", "r1"))
        with self.assertRaises(ToolExecutionError):
            asyncio.run(execute(plan, user_id=self.user.supabase_uid))
        self.assertEqual(
            AgentAction.objects.filter(user=self.user, tool="action.do", status="failed").count(), 1
        )

    def test_non_confirmation_step_does_not_create_audit_record(self):
        from agent.models import AgentAction
        _register_mock("processing_llm", "done", requires_confirmation=False)
        plan = _make_plan(("processing_llm", "result"))
        asyncio.run(execute(plan, user_id=self.user.supabase_uid))
        self.assertEqual(AgentAction.objects.filter(user=self.user).count(), 0)
