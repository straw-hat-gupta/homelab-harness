import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase, override_settings

from planner.planner import (
    _build_direct_response_plan,
    _build_system,
    _is_executable_plan,
    _normalize_plan,
    _plan_cache_key,
    detect_intent,
    plan,
    revise_plan,
)
from planner.schemas import Plan, PlanStep


def _valid_plan():
    return Plan(
        steps=[PlanStep(id="step_1", tool="processing_llm", params={}, output_var="result")],
        final_output_var="result",
        summary="I will respond.",
    )


def _mock_client(response_text):
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = response_text
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)
    return mock_client


class BuildDirectResponsePlanTests(unittest.TestCase):
    def test_returns_processing_llm_step(self):
        p = _build_direct_response_plan("hello", [])
        self.assertEqual(p.steps[0].tool, "processing_llm")
        self.assertEqual(p.final_output_var, "final_response")

    def test_includes_user_request_in_inputs(self):
        p = _build_direct_response_plan("what is 2+2?", [])
        self.assertIn("user_request", p.steps[0].params["inputs"])

    def test_includes_history_when_present(self):
        history = [{"role": "user", "content": "earlier"}]
        p = _build_direct_response_plan("follow up", history)
        self.assertIn("conversation_history", p.steps[0].params["inputs"])

    def test_no_history_key_when_empty(self):
        p = _build_direct_response_plan("hello", [])
        self.assertNotIn("conversation_history", p.steps[0].params["inputs"])


class IsExecutablePlanTests(unittest.TestCase):
    def test_valid_plan_is_executable(self):
        self.assertTrue(_is_executable_plan(_valid_plan()))

    def test_empty_steps_not_executable(self):
        p = Plan(steps=[], final_output_var="result", summary="I will...")
        self.assertFalse(_is_executable_plan(p))

    def test_final_var_not_produced_not_executable(self):
        p = Plan(
            steps=[PlanStep(id="step_1", tool="tool", params={}, output_var="something_else")],
            final_output_var="result",
            summary="I will...",
        )
        self.assertFalse(_is_executable_plan(p))

    def test_blank_final_output_var_not_executable(self):
        p = Plan(
            steps=[PlanStep(id="step_1", tool="tool", params={}, output_var="result")],
            final_output_var="   ",
            summary="I will...",
        )
        self.assertFalse(_is_executable_plan(p))


class NormalizePlanTests(unittest.TestCase):
    def test_valid_plan_returned_unchanged(self):
        p = _valid_plan()
        result = _normalize_plan(p, "prompt", [])
        self.assertIs(result, p)

    def test_invalid_plan_falls_back_to_direct_response(self):
        invalid = Plan(steps=[], final_output_var="missing", summary="I will...")
        result = _normalize_plan(invalid, "prompt", [])
        self.assertEqual(result.steps[0].tool, "processing_llm")
        self.assertEqual(result.final_output_var, "final_response")


class BuildSystemTests(unittest.TestCase):
    def test_includes_tool_name_and_description(self):
        tools = [{"name": "gmail.read", "description": "read email", "params": {}}]
        system = _build_system(tools, [])
        self.assertIn("gmail.read", system)
        self.assertIn("read email", system)

    def test_includes_history_content(self):
        history = [
            {"role": "user", "content": "earlier message"},
            {"role": "assistant", "content": "my reply"},
        ]
        system = _build_system([], history)
        self.assertIn("earlier message", system)
        self.assertIn("my reply", system)

    def test_empty_history_shows_none(self):
        system = _build_system([], [])
        self.assertIn("(none)", system)


@override_settings(PLAN_CACHE_TTL=0)
class PlannerLLMTests(SimpleTestCase):
    def _plan_json(self, summary="I will reply."):
        return json.dumps(
            {
                "steps": [
                    {
                        "id": "step_1",
                        "tool": "processing_llm",
                        "params": {"task": "reply", "inputs": {}},
                        "output_var": "result",
                    }
                ],
                "final_output_var": "result",
                "summary": summary,
            }
        )

    def test_plan_returns_valid_plan_object(self):
        with patch("planner.planner._get_client", return_value=_mock_client(self._plan_json())):
            result = asyncio.run(plan("hello", [], [], model="gpt-4o-mini"))
        self.assertIsInstance(result, Plan)
        self.assertEqual(result.final_output_var, "result")

    def test_plan_falls_back_when_llm_returns_bad_plan(self):
        bad_json = json.dumps({"steps": [], "final_output_var": "missing", "summary": "I will..."})
        with patch("planner.planner._get_client", return_value=_mock_client(bad_json)):
            result = asyncio.run(plan("hello", [], [], model="gpt-4o-mini"))
        self.assertEqual(result.steps[0].tool, "processing_llm")

    def test_detect_intent_confirm(self):
        with patch("planner.planner._get_client", return_value=_mock_client("confirm")):
            intent = asyncio.run(detect_intent("yes proceed", "I will send email.", model="gpt-4o-mini"))
        self.assertEqual(intent, "confirm")

    def test_detect_intent_cancel(self):
        with patch("planner.planner._get_client", return_value=_mock_client("cancel")):
            intent = asyncio.run(detect_intent("no stop", "I will send email.", model="gpt-4o-mini"))
        self.assertEqual(intent, "cancel")

    def test_detect_intent_normalizes_with_extra_words(self):
        with patch("planner.planner._get_client", return_value=_mock_client("confirm please")):
            intent = asyncio.run(detect_intent("yes", "summary", model="gpt-4o-mini"))
        self.assertEqual(intent, "confirm")

    def test_detect_intent_cancel_with_prefix(self):
        with patch("planner.planner._get_client", return_value=_mock_client("cancel it")):
            intent = asyncio.run(detect_intent("no", "summary", model="gpt-4o-mini"))
        self.assertEqual(intent, "cancel")

    def test_detect_intent_modify_fallback(self):
        with patch("planner.planner._get_client", return_value=_mock_client("modify")):
            intent = asyncio.run(detect_intent("change the recipient", "summary", model="gpt-4o-mini"))
        self.assertEqual(intent, "modify")

    def test_detect_intent_unknown_response_defaults_to_modify(self):
        with patch("planner.planner._get_client", return_value=_mock_client("something unexpected")):
            intent = asyncio.run(detect_intent("huh?", "summary", model="gpt-4o-mini"))
        self.assertEqual(intent, "modify")

    def test_revise_plan_returns_plan(self):
        with patch("planner.planner._get_client", return_value=_mock_client(self._plan_json("I will do it revised."))):
            result = asyncio.run(
                revise_plan(_valid_plan(), "change something", [], [], model="gpt-4o-mini")
            )
        self.assertIsInstance(result, Plan)
        self.assertEqual(result.summary, "I will do it revised.")


_GMAIL_A = {"plugin": "gmail", "account_id": "a@gmail.com"}
_GMAIL_B = {"plugin": "gmail", "account_id": "b@gmail.com"}
_CALENDAR = {"plugin": "google_calendar", "account_id": None}


class PlanCacheKeyTests(unittest.TestCase):
    def test_same_inputs_produce_same_key(self):
        k1 = _plan_cache_key("hello", "gpt-4o-mini", [_GMAIL_A], [])
        k2 = _plan_cache_key("hello", "gpt-4o-mini", [_GMAIL_A], [])
        self.assertEqual(k1, k2)

    def test_different_prompt_produces_different_key(self):
        k1 = _plan_cache_key("hello", "gpt-4o-mini", [], [])
        k2 = _plan_cache_key("goodbye", "gpt-4o-mini", [], [])
        self.assertNotEqual(k1, k2)

    def test_different_accounts_produce_different_key(self):
        k1 = _plan_cache_key("hello", "gpt-4o-mini", [_GMAIL_A], [])
        k2 = _plan_cache_key("hello", "gpt-4o-mini", [_GMAIL_B], [])
        self.assertNotEqual(k1, k2)

    def test_different_plugins_produce_different_key(self):
        k1 = _plan_cache_key("hello", "gpt-4o-mini", [_GMAIL_A], [])
        k2 = _plan_cache_key("hello", "gpt-4o-mini", [_CALENDAR], [])
        self.assertNotEqual(k1, k2)

    def test_different_tool_schemas_produce_different_key(self):
        schemas_a = [{"name": "gmail.read"}]
        schemas_b = [{"name": "gmail.send"}]
        k1 = _plan_cache_key("hello", "gpt-4o-mini", [], schemas_a)
        k2 = _plan_cache_key("hello", "gpt-4o-mini", [], schemas_b)
        self.assertNotEqual(k1, k2)

    def test_account_order_does_not_affect_key(self):
        k1 = _plan_cache_key("hello", "gpt-4o-mini", [_GMAIL_A, _CALENDAR], [])
        k2 = _plan_cache_key("hello", "gpt-4o-mini", [_CALENDAR, _GMAIL_A], [])
        self.assertEqual(k1, k2)

    def test_key_has_cache_prefix(self):
        k = _plan_cache_key("hello", "gpt-4o-mini", [], [])
        self.assertTrue(k.startswith("aiva:plan:"))


class PlanCachingTests(unittest.TestCase):
    def _plan_json(self, summary="I will reply."):
        return json.dumps({
            "steps": [{"id": "step_1", "tool": "processing_llm", "params": {"task": "reply", "inputs": {}}, "output_var": "result"}],
            "final_output_var": "result",
            "summary": summary,
        })

    def test_cache_miss_calls_llm_and_stores(self):
        mock_cache_store = {}
        mock_cache_get = AsyncMock(return_value=None)
        mock_cache_set = AsyncMock(side_effect=lambda k, v, ttl: mock_cache_store.update({k: v}))
        with (
            patch("planner.planner._get_client", return_value=_mock_client(self._plan_json())),
            patch("planner.planner._cache_get", mock_cache_get),
            patch("planner.planner._cache_set", mock_cache_set),
            patch("planner.planner._persist_usage", AsyncMock()),
            patch("django.conf.settings", PLANNER_MODEL="gpt-4o-mini", PLAN_CACHE_TTL=3600),
        ):
            result = asyncio.run(plan("hello", [], [], model="gpt-4o-mini"))
        self.assertIsInstance(result, Plan)
        mock_cache_set.assert_called_once()

    def test_cache_hit_skips_llm(self):
        cached_plan = _valid_plan().model_dump_json()
        mock_cache_get = AsyncMock(return_value=cached_plan)
        mock_llm_client = _mock_client(self._plan_json())
        with (
            patch("planner.planner._get_client", return_value=mock_llm_client),
            patch("planner.planner._cache_get", mock_cache_get),
            patch("planner.planner._cache_set", AsyncMock()),
            patch("django.conf.settings", PLANNER_MODEL="gpt-4o-mini", PLAN_CACHE_TTL=3600),
        ):
            result = asyncio.run(plan("hello", [], [], model="gpt-4o-mini"))
        self.assertIsInstance(result, Plan)
        mock_llm_client.chat.completions.create.assert_not_called()

    def test_cache_skipped_when_history_present(self):
        mock_cache_get = AsyncMock()
        history = [{"role": "user", "content": "prior message"}]
        with (
            patch("planner.planner._get_client", return_value=_mock_client(self._plan_json())),
            patch("planner.planner._cache_get", mock_cache_get),
            patch("planner.planner._cache_set", AsyncMock()),
            patch("planner.planner._persist_usage", AsyncMock()),
            patch("django.conf.settings", PLANNER_MODEL="gpt-4o-mini", PLAN_CACHE_TTL=3600),
        ):
            asyncio.run(plan("hello", history, [], model="gpt-4o-mini"))
        mock_cache_get.assert_not_called()

    def test_cache_disabled_when_ttl_zero(self):
        mock_cache_get = AsyncMock()
        with (
            patch("planner.planner._get_client", return_value=_mock_client(self._plan_json())),
            patch("planner.planner._cache_get", mock_cache_get),
            patch("planner.planner._cache_set", AsyncMock()),
            patch("planner.planner._persist_usage", AsyncMock()),
            patch("django.conf.settings", PLANNER_MODEL="gpt-4o-mini", PLAN_CACHE_TTL=0),
        ):
            asyncio.run(plan("hello", [], [], model="gpt-4o-mini"))
        mock_cache_get.assert_not_called()
