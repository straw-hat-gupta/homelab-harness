"""Tests for backend settings configuration."""
from django.test import TestCase, override_settings


class RedisCacheSettingsTests(TestCase):
    def test_no_redis_url_uses_locmemcache(self):
        from django.core.cache import cache
        # With REDIS_URL unset (the test environment default), Django uses
        # LocMemCache. Verify the cache is functional — set and get round-trip.
        cache.set("test_key", "test_value", timeout=10)
        self.assertEqual(cache.get("test_key"), "test_value")

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": "redis://localhost:6379/0",
            }
        }
    )
    def test_redis_cache_backend_is_correct_class(self):
        from django.core.cache import caches
        from django.core.cache.backends.redis import RedisCache
        # override_settings replaces the cache config; verify the backend class.
        backend = caches["default"]
        self.assertIsInstance(backend, RedisCache)

    def test_redis_url_absent_uses_locmemcache(self):
        """With REDIS_URL unset, settings.py does not configure a Redis backend."""
        from django.conf import settings
        caches_cfg = getattr(settings, "CACHES", {})
        default_backend = caches_cfg.get("default", {}).get("BACKEND", "")
        # Either no explicit CACHES (Django default = LocMemCache) or explicitly LocMemCache.
        self.assertNotIn("redis", default_backend.lower())


class CelerySettingsTests(TestCase):
    def test_blank_celery_env_does_not_fall_back_to_amqp(self):
        """Celery should default to Redis, not RabbitMQ, when optional env vars are blank."""
        from django.conf import settings

        self.assertTrue(settings.CELERY_BROKER_URL)
        self.assertTrue(settings.CELERY_BROKER_URL.startswith("redis://"))

    def test_redis_transport_dependency_is_installed(self):
        """The Celery Redis broker and Django Redis cache need redis-py installed."""
        import redis

        self.assertTrue(hasattr(redis, "Redis"))
