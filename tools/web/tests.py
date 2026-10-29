"""Tests for tools/web/api.py."""
import asyncio
import os
from unittest.mock import MagicMock, patch

from django.test import TestCase


MOCK_RESPONSE = {
    "results": [
        {
            "title": "Async Python Guide",
            "url": "https://docs.python.org/asyncio",
            "content": "An introduction to asyncio in Python.",
            "score": 0.95,
        },
        {
            "title": "Real Python — asyncio",
            "url": "https://realpython.com/async-io-python/",
            "content": "Deep dive into Python async patterns.",
            "score": 0.88,
        },
    ]
}

MOCK_RESPONSE_WITH_ANSWER = {
    **MOCK_RESPONSE,
    "answer": "asyncio is Python's built-in library for writing concurrent code using async/await syntax.",
}


def _run(coro):
    return asyncio.run(coro)


def _make_mock_response(payload):
    mock_resp = MagicMock()
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status.return_value = None
    return mock_resp


class WebSearchTests(TestCase):

    @patch("tools.web.api.requests.post")
    def test_returns_results(self, mock_post):
        mock_post.return_value = _make_mock_response(MOCK_RESPONSE)

        from tools.web.api import web_search

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            out = _run(web_search("Python async programming"))

        results = out["results"]
        self.assertIsNone(out["answer"])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Async Python Guide")
        self.assertEqual(results[0]["url"], "https://docs.python.org/asyncio")
        self.assertAlmostEqual(results[0]["score"], 0.95)

        call_json = mock_post.call_args.kwargs["json"]
        self.assertEqual(call_json["query"], "Python async programming")
        self.assertEqual(call_json["api_key"], "test-key")
        self.assertEqual(call_json["max_results"], 5)
        self.assertFalse(call_json["include_answer"])

    @patch("tools.web.api.requests.post")
    def test_include_answer(self, mock_post):
        mock_post.return_value = _make_mock_response(MOCK_RESPONSE_WITH_ANSWER)

        from tools.web.api import web_search

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            out = _run(web_search("What is asyncio?", include_answer=True))

        self.assertIsNotNone(out["answer"])
        self.assertIn("asyncio", out["answer"])
        self.assertEqual(len(out["results"]), 2)
        self.assertTrue(mock_post.call_args.kwargs["json"]["include_answer"])

    @patch("tools.web.api.requests.post")
    def test_clamps_max_results_upper(self, mock_post):
        mock_post.return_value = _make_mock_response({"results": [], "answer": None})

        from tools.web.api import web_search

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            _run(web_search("test", max_results=999))

        self.assertEqual(mock_post.call_args.kwargs["json"]["max_results"], 10)

    @patch("tools.web.api.requests.post")
    def test_clamps_max_results_lower(self, mock_post):
        mock_post.return_value = _make_mock_response({"results": [], "answer": None})

        from tools.web.api import web_search

        with patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}):
            _run(web_search("test", max_results=0))

        self.assertEqual(mock_post.call_args.kwargs["json"]["max_results"], 1)

    def test_missing_api_key_raises(self):
        from tools.web.api import web_search

        env_without_key = {k: v for k, v in os.environ.items() if k != "TAVILY_API_KEY"}
        with patch.dict(os.environ, env_without_key, clear=True):
            with self.assertRaisesRegex(RuntimeError, "TAVILY_API_KEY"):
                _run(web_search("test"))

    def test_registered(self):
        import tools.web.api  # noqa — ensure module is loaded
        from tools.registry import get

        tool = get("web.search")
        self.assertEqual(tool.name, "web.search")
        self.assertFalse(tool.requires_confirmation)
        self.assertIsNone(tool.plugin_id)
        self.assertFalse(tool.requires_creds)
        self.assertFalse(tool.requires_user_id)
        self.assertIn("query", tool.params_schema)
        self.assertIn("max_results", tool.params_schema)
