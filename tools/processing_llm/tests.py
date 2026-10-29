"""Tests for call_processing_llm — verifies timeout and max_tokens are forwarded."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase, override_settings


def _run(coro):
    return asyncio.run(coro)


class ProcessingLLMTimeoutTests(TestCase):
    @override_settings(PROCESSING_LLM_TIMEOUT=30, PROCESSING_LLM_MAX_TOKENS=512)
    @patch("tools.processing_llm.tool._get_client")
    def test_passes_timeout_and_max_tokens(self, mock_get_client):
        from tools.processing_llm.tool import call_processing_llm

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices[0].message.content = "summary text"
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = _run(call_processing_llm(task="Summarise", inputs={"data": "some data"}))

        self.assertEqual(result, "summary text")
        call_kwargs = mock_client.chat.completions.create.call_args.kwargs
        self.assertEqual(call_kwargs["timeout"], 30)
        self.assertEqual(call_kwargs["max_tokens"], 512)

    @override_settings()
    @patch("tools.processing_llm.tool._get_client")
    def test_defaults_when_settings_absent(self, mock_get_client):
        from django.conf import settings as django_settings
        # Remove optional settings to test fallback defaults
        for attr in ("PROCESSING_LLM_TIMEOUT", "PROCESSING_LLM_MAX_TOKENS"):
            if hasattr(django_settings, attr):
                delattr(django_settings, attr)

        from tools.processing_llm.tool import _timeout, _max_tokens
        self.assertEqual(_timeout(), 60)
        self.assertEqual(_max_tokens(), 1024)
