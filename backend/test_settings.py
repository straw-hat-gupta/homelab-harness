"""
Minimal settings for running the test suite locally without a real database.
Inherits everything from settings.py and overrides the DB to SQLite.

Usage:
    python manage.py test --settings=backend.test_settings
"""

from backend.settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
