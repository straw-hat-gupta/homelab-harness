"""
Tests for tools/notion/api.py and the Notion-specific OAuth wiring.

All HTTP calls are mocked — no real Notion API is hit. The 7 tools receive
token_data directly (injected by the orchestrator), so the "not connected"
case is exercised by a 401 response mapping to PluginNotConnectedError.
"""
import asyncio
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

import requests

from orchestrator.exceptions import PluginNotConnectedError

TOKEN = {"access_token": "secret-token"}

NOTION_SETTINGS = {
    "NOTION_CLIENT_ID": "test-client-id",
    "NOTION_CLIENT_SECRET": "test-client-secret",
}


def _run(coro):
    return asyncio.run(coro)


def _resp(json_data=None, status=200, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    resp.json.return_value = {} if json_data is None else json_data
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Happy path — all 7 tools
# ---------------------------------------------------------------------------

class NotionSearchTests(TestCase):
    @patch("tools.notion.api._requests.post")
    def test_search_returns_results(self, mock_post):
        from tools.notion.api import notion_search

        mock_post.return_value = _resp({"results": [{"id": "p1"}, {"id": "p2"}]})

        result = _run(notion_search(TOKEN, query="roadmap"))

        self.assertEqual(result, [{"id": "p1"}, {"id": "p2"}])
        url = mock_post.call_args.args[0]
        self.assertTrue(url.endswith("/search"))
        self.assertEqual(mock_post.call_args.kwargs["json"], {"query": "roadmap"})

    @patch("tools.notion.api._requests.post")
    def test_search_applies_object_filter(self, mock_post):
        from tools.notion.api import notion_search

        mock_post.return_value = _resp({"results": []})

        _run(notion_search(TOKEN, query="x", filter_type="database"))

        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["filter"], {"property": "object", "value": "database"})

    @patch("tools.notion.api._requests.post")
    def test_search_sends_bearer_and_version_headers(self, mock_post):
        from tools.notion.api import notion_search

        mock_post.return_value = _resp({"results": []})

        _run(notion_search(TOKEN, query="x"))

        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer secret-token")
        self.assertEqual(headers["Notion-Version"], "2022-06-28")


class NotionGetPageTests(TestCase):
    @patch("tools.notion.api._requests.get")
    def test_get_page_returns_page_and_blocks(self, mock_get):
        from tools.notion.api import notion_get_page

        mock_get.side_effect = [
            _resp({"id": "page1", "object": "page"}),
            _resp({"results": [{"id": "b1"}]}),
        ]

        result = _run(notion_get_page(TOKEN, page_id="page1"))

        self.assertEqual(result["page"]["id"], "page1")
        self.assertEqual(result["blocks"], [{"id": "b1"}])
        self.assertEqual(mock_get.call_count, 2)


class NotionCreatePageTests(TestCase):
    @patch("tools.notion.api._requests.post")
    def test_create_page_under_page_parent(self, mock_post):
        from tools.notion.api import notion_create_page

        mock_post.return_value = _resp({"id": "new-page"})

        result = _run(notion_create_page(TOKEN, parent_id="parent1", title="Hello"))

        self.assertEqual(result["id"], "new-page")
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["parent"], {"page_id": "parent1"})
        self.assertIn("title", body["properties"])
        self.assertEqual(
            body["properties"]["title"]["title"][0]["text"]["content"], "Hello"
        )

    @patch("tools.notion.api._requests.post")
    def test_create_page_with_content_adds_paragraph_blocks(self, mock_post):
        from tools.notion.api import notion_create_page

        mock_post.return_value = _resp({"id": "new-page"})

        _run(notion_create_page(TOKEN, parent_id="parent1", title="T", content="a\nb"))

        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(len(body["children"]), 2)
        self.assertEqual(body["children"][0]["type"], "paragraph")

    @patch("tools.notion.api._requests.post")
    @patch("tools.notion.api._requests.get")
    def test_create_database_row_resolves_title_property_name(self, mock_get, mock_post):
        from tools.notion.api import notion_create_page

        mock_get.return_value = _resp(
            {"properties": {"Name": {"type": "title"}, "Status": {"type": "select"}}}
        )
        mock_post.return_value = _resp({"id": "row1"})

        _run(
            notion_create_page(
                TOKEN, parent_id="db1", title="Task", is_database=True
            )
        )

        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["parent"], {"database_id": "db1"})
        self.assertIn("Name", body["properties"])
        self.assertNotIn("title", body["properties"])

    @patch("tools.notion.api._requests.post")
    @patch("tools.notion.api._requests.get")
    def test_create_database_row_falls_back_to_title_key(self, mock_get, mock_post):
        from tools.notion.api import notion_create_page

        mock_get.return_value = _resp({"properties": {"Status": {"type": "select"}}})
        mock_post.return_value = _resp({"id": "row1"})

        _run(notion_create_page(TOKEN, parent_id="db1", title="T", is_database=True))

        body = mock_post.call_args.kwargs["json"]
        self.assertIn("title", body["properties"])


class NotionUpdatePageTests(TestCase):
    @patch("tools.notion.api._requests.patch")
    def test_update_page_sets_title(self, mock_patch):
        from tools.notion.api import notion_update_page

        mock_patch.return_value = _resp({"id": "page1"})

        result = _run(notion_update_page(TOKEN, page_id="page1", title="New"))

        self.assertEqual(result["id"], "page1")
        url = mock_patch.call_args.args[0]
        self.assertTrue(url.endswith("/pages/page1"))
        props = mock_patch.call_args.kwargs["json"]["properties"]
        self.assertEqual(props["title"]["title"][0]["text"]["content"], "New")

    @patch("tools.notion.api._requests.patch")
    def test_update_page_merges_raw_properties(self, mock_patch):
        from tools.notion.api import notion_update_page

        mock_patch.return_value = _resp({"id": "page1"})

        _run(
            notion_update_page(
                TOKEN, page_id="page1", properties={"Status": {"select": {"name": "Done"}}}
            )
        )

        props = mock_patch.call_args.kwargs["json"]["properties"]
        self.assertIn("Status", props)
        self.assertNotIn("title", props)


class NotionAppendBlocksTests(TestCase):
    @patch("tools.notion.api._requests.patch")
    def test_append_blocks_passes_children_verbatim(self, mock_patch):
        from tools.notion.api import notion_append_blocks

        mock_patch.return_value = _resp({"results": [{"id": "b1"}]})
        blocks = [{"object": "block", "type": "paragraph"}]

        result = _run(notion_append_blocks(TOKEN, page_id="page1", blocks=blocks))

        self.assertEqual(result["results"], [{"id": "b1"}])
        url = mock_patch.call_args.args[0]
        self.assertTrue(url.endswith("/blocks/page1/children"))
        self.assertEqual(mock_patch.call_args.kwargs["json"], {"children": blocks})


class NotionListDatabasesTests(TestCase):
    @patch("tools.notion.api._requests.post")
    def test_list_databases_filters_to_database_objects(self, mock_post):
        from tools.notion.api import notion_list_databases

        mock_post.return_value = _resp({"results": [{"id": "db1"}]})

        result = _run(notion_list_databases(TOKEN))

        self.assertEqual(result, [{"id": "db1"}])
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["filter"], {"property": "object", "value": "database"})

    @patch("tools.notion.api._requests.post")
    def test_list_databases_clamps_page_size(self, mock_post):
        from tools.notion.api import notion_list_databases

        mock_post.return_value = _resp({"results": []})

        _run(notion_list_databases(TOKEN, page_size=500))

        self.assertEqual(mock_post.call_args.kwargs["json"]["page_size"], 100)


class NotionQueryDatabaseTests(TestCase):
    @patch("tools.notion.api._requests.post")
    def test_query_database_returns_rows(self, mock_post):
        from tools.notion.api import notion_query_database

        mock_post.return_value = _resp({"results": [{"id": "row1"}]})

        result = _run(notion_query_database(TOKEN, database_id="db1"))

        self.assertEqual(result, [{"id": "row1"}])
        url = mock_post.call_args.args[0]
        self.assertTrue(url.endswith("/databases/db1/query"))

    @patch("tools.notion.api._requests.post")
    def test_query_database_passes_filter_and_sorts(self, mock_post):
        from tools.notion.api import notion_query_database

        mock_post.return_value = _resp({"results": []})
        flt = {"property": "Done", "checkbox": {"equals": True}}
        sorts = [{"property": "Name", "direction": "ascending"}]

        _run(notion_query_database(TOKEN, database_id="db1", filter=flt, sorts=sorts))

        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["filter"], flt)
        self.assertEqual(body["sorts"], sorts)


# ---------------------------------------------------------------------------
# Error handling — 401 (not connected), 404, generic API error
# ---------------------------------------------------------------------------

class NotionErrorHandlingTests(TestCase):
    @patch("tools.notion.api._requests.post")
    def test_401_raises_plugin_not_connected(self, mock_post):
        from tools.notion.api import notion_search

        mock_post.return_value = _resp(status=401, text="unauthorized")

        with self.assertRaises(PluginNotConnectedError) as ctx:
            _run(notion_search(TOKEN, query="x"))
        self.assertEqual(ctx.exception.plugin_id, "notion")

    @patch("tools.notion.api._requests.get")
    def test_404_raises_http_error_with_status(self, mock_get):
        from tools.notion.api import notion_get_page

        mock_get.return_value = _resp(status=404, text="object not found")

        with self.assertRaises(requests.HTTPError) as ctx:
            _run(notion_get_page(TOKEN, page_id="missing"))
        self.assertIn("404", str(ctx.exception))

    @patch("tools.notion.api._requests.post")
    def test_500_raises_http_error_with_status(self, mock_post):
        from tools.notion.api import notion_query_database

        mock_post.return_value = _resp(status=500, text="server error")

        with self.assertRaises(requests.HTTPError) as ctx:
            _run(notion_query_database(TOKEN, database_id="db1"))
        self.assertIn("500", str(ctx.exception))

    @patch("tools.notion.api._requests.patch")
    def test_401_on_patch_raises_plugin_not_connected(self, mock_patch):
        from tools.notion.api import notion_append_blocks

        mock_patch.return_value = _resp(status=401)

        with self.assertRaises(PluginNotConnectedError):
            _run(notion_append_blocks(TOKEN, page_id="p1", blocks=[]))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class NotionRegistrationTests(TestCase):
    TOOLS = [
        "notion.search",
        "notion.get_page",
        "notion.create_page",
        "notion.update_page",
        "notion.append_blocks",
        "notion.list_databases",
        "notion.query_database",
    ]

    def test_all_seven_tools_registered(self):
        import tools.notion.api  # noqa: F401
        from tools.registry import _REGISTRY

        for name in self.TOOLS:
            self.assertIn(name, _REGISTRY, f"{name} not registered")

    def test_tools_require_notion_credentials(self):
        import tools.notion.api  # noqa: F401
        from tools.registry import _REGISTRY

        for name in self.TOOLS:
            tool = _REGISTRY[name]
            self.assertTrue(tool.requires_creds, f"{name} should require creds")
            self.assertEqual(tool.plugin_id, "notion", f"{name} plugin_id")

    def test_write_tools_require_confirmation(self):
        import tools.notion.api  # noqa: F401
        from tools.registry import _REGISTRY

        for name in ("notion.create_page", "notion.update_page", "notion.append_blocks"):
            self.assertTrue(
                _REGISTRY[name].requires_confirmation, f"{name} should confirm"
            )

    def test_read_tools_do_not_require_confirmation(self):
        import tools.notion.api  # noqa: F401
        from tools.registry import _REGISTRY

        for name in (
            "notion.search",
            "notion.get_page",
            "notion.list_databases",
            "notion.query_database",
        ):
            self.assertFalse(
                _REGISTRY[name].requires_confirmation, f"{name} should not confirm"
            )


# ---------------------------------------------------------------------------
# Notion-specific OAuth wiring (basic_json exchange + account_id headers)
# ---------------------------------------------------------------------------

@override_settings(**NOTION_SETTINGS)
class NotionOAuthWiringTests(TestCase):
    @patch("plugins.services.credentials.requests.post")
    def test_exchange_code_uses_basic_auth_and_json_body(self, mock_post):
        from plugins.services.credentials import CredentialService

        mock_post.return_value = _resp({"access_token": "tok", "bot_id": "bot1"})

        result = CredentialService.exchange_code(
            "notion", code="auth-code", redirect_uri="https://cb/notion/"
        )

        self.assertEqual(result["access_token"], "tok")
        self.assertEqual(
            mock_post.call_args.kwargs["auth"], ("test-client-id", "test-client-secret")
        )
        body = mock_post.call_args.kwargs["json"]
        self.assertEqual(body["grant_type"], "authorization_code")
        self.assertEqual(body["code"], "auth-code")
        self.assertNotIn("data", mock_post.call_args.kwargs)

    @patch("plugins.services.credentials.requests.get")
    def test_fetch_account_id_sends_notion_version_header(self, mock_get):
        from plugins.services.credentials import CredentialService

        mock_get.return_value = _resp({"id": "bot-user-1"})

        account_id = CredentialService.fetch_account_id("notion", "tok")

        self.assertEqual(account_id, "bot-user-1")
        headers = mock_get.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(headers["Notion-Version"], "2022-06-28")
