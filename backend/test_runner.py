import os
import unittest

from django.apps import apps
from django.test.runner import DiscoverRunner


class CustomTestRunner(DiscoverRunner):
    """
    Discovers tests from each installed app's tests/ directory automatically.
    Add a test file matching test*.py and it runs — no suite() registration needed.
    """

    def build_suite(self, test_labels=None, extra_tests=None, **kwargs):
        if test_labels:
            return super().build_suite(test_labels, extra_tests=extra_tests, **kwargs)

        suite = self.test_suite()
        loader = self.test_loader

        for app_config in apps.get_app_configs():
            tests_dir = os.path.join(app_config.path, "tests")
            if os.path.isdir(tests_dir):
                discovered = loader.discover(
                    start_dir=tests_dir,
                    pattern="test*.py",
                    top_level_dir=os.path.dirname(app_config.path),
                )
                suite.addTests(discovered)

        if extra_tests:
            for test in extra_tests:
                suite.addTest(test)

        return suite
