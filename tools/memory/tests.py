"""Tests for tools/memory/api.py."""
import asyncio
from unittest.mock import AsyncMock, patch

from django.test import TestCase


def _run(coro):
    return asyncio.run(coro)


class MemorySaveTests(TestCase):

    def test_creates_new_memory(self):
        from tools.memory import api as mem_api

        expected = {"key": "city", "value": "Seattle", "action": "created"}
        mock_save = AsyncMock(return_value=expected)
        with patch.object(mem_api, "_save", new=mock_save):
            result = _run(mem_api.memory_save(key="city", value="Seattle", user_id="uid"))
            mock_save.assert_awaited_once_with("uid", "city", "Seattle")

        self.assertEqual(result["action"], "created")
        self.assertEqual(result["key"], "city")

    def test_updates_existing_memory(self):
        from tools.memory import api as mem_api

        expected = {"key": "city", "value": "Boston", "action": "updated"}
        with patch.object(mem_api, "_save", new=AsyncMock(return_value=expected)):
            result = _run(mem_api.memory_save(key="city", value="Boston", user_id="uid"))

        self.assertEqual(result["action"], "updated")

    def test_registered(self):
        import tools.memory.api  # noqa
        from tools.registry import get

        tool = get("memory.save")
        self.assertEqual(tool.name, "memory.save")
        self.assertFalse(tool.requires_confirmation)
        self.assertFalse(tool.requires_creds)
        self.assertTrue(tool.requires_user_id)
        self.assertIn("key", tool.params_schema)
        self.assertIn("value", tool.params_schema)


class MemoryDeleteTests(TestCase):

    def test_deletes_existing_key(self):
        from tools.memory import api as mem_api

        expected = {"key": "city", "deleted": True}
        mock_delete = AsyncMock(return_value=expected)
        with patch.object(mem_api, "_delete", new=mock_delete):
            result = _run(mem_api.memory_delete(key="city", user_id="uid"))
            mock_delete.assert_awaited_once_with("uid", "city")

        self.assertTrue(result["deleted"])

    def test_delete_missing_key_returns_false(self):
        from tools.memory import api as mem_api

        expected = {"key": "nonexistent", "deleted": False}
        with patch.object(mem_api, "_delete", new=AsyncMock(return_value=expected)):
            result = _run(mem_api.memory_delete(key="nonexistent", user_id="uid"))

        self.assertFalse(result["deleted"])

    def test_registered(self):
        import tools.memory.api  # noqa
        from tools.registry import get

        tool = get("memory.delete")
        self.assertEqual(tool.name, "memory.delete")
        self.assertTrue(tool.requires_user_id)
        self.assertIn("key", tool.params_schema)
