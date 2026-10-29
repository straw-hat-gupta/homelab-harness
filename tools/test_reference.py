from django.test import SimpleTestCase

from tools.management.commands.export_tool_reference import DOC_PATH, render


class ToolReferenceDocTests(SimpleTestCase):
    def test_docs_tools_md_matches_registry(self):
        self.assertTrue(DOC_PATH.exists(), "docs/tools.md is missing; run export_tool_reference")
        self.assertEqual(
            DOC_PATH.read_text(),
            render(),
            "docs/tools.md is out of date; run `python manage.py export_tool_reference`",
        )
