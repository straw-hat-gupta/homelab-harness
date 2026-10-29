"""Tests for memory CRUD endpoints."""
import uuid

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from agent.models import UserMemory

User = get_user_model()


def _uid():
    return str(uuid.uuid4())


class MemoryListViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="mem@example.com",
            password="pw",
            supabase_uid=_uid(),
        )
        self.client.force_authenticate(user=self.user)

    def test_list_empty(self):
        resp = self.client.get("/agent/memory/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["memories"], [])

    def test_list_returns_user_memories(self):
        UserMemory.objects.create(user=self.user, key="city", value="NYC")
        UserMemory.objects.create(user=self.user, key="lang", value="English")
        resp = self.client.get("/agent/memory/")
        self.assertEqual(resp.status_code, 200)
        keys = {m["key"] for m in resp.json()["memories"]}
        self.assertEqual(keys, {"city", "lang"})

    def test_list_does_not_return_other_users_memories(self):
        other = User.objects.create_user(
            email="other@example.com", password="pw", supabase_uid=_uid()
        )
        UserMemory.objects.create(user=other, key="secret", value="hidden")
        resp = self.client.get("/agent/memory/")
        self.assertEqual(resp.json()["memories"], [])

    def test_post_creates_memory(self):
        resp = self.client.post("/agent/memory/", {"key": "home_city", "value": "Seattle"}, format="json")
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["key"], "home_city")
        self.assertEqual(data["value"], "Seattle")
        self.assertEqual(data["source"], UserMemory.SOURCE_MANUAL)
        self.assertTrue(UserMemory.objects.filter(user=self.user, key="home_city").exists())

    def test_post_upserts_existing_key(self):
        UserMemory.objects.create(user=self.user, key="home_city", value="Portland")
        resp = self.client.post("/agent/memory/", {"key": "home_city", "value": "Seattle"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(UserMemory.objects.filter(user=self.user, key="home_city").count(), 1)
        self.assertEqual(UserMemory.objects.get(user=self.user, key="home_city").value, "Seattle")

    def test_post_requires_auth(self):
        self.client.force_authenticate(user=None)
        resp = self.client.post("/agent/memory/", {"key": "k", "value": "v"}, format="json")
        self.assertIn(resp.status_code, [401, 403])

    def test_post_missing_fields(self):
        resp = self.client.post("/agent/memory/", {"key": "k"}, format="json")
        self.assertEqual(resp.status_code, 400)


class MemoryDetailViewTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="memdetail@example.com",
            password="pw",
            supabase_uid=_uid(),
        )
        self.client.force_authenticate(user=self.user)
        self.mem = UserMemory.objects.create(user=self.user, key="city", value="NYC")

    def test_delete_removes_memory(self):
        resp = self.client.delete(f"/agent/memory/{self.mem.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertFalse(UserMemory.objects.filter(pk=self.mem.pk).exists())

    def test_put_updates_memory(self):
        resp = self.client.put(
            f"/agent/memory/{self.mem.pk}/",
            {"key": "city", "value": "Boston"},
            format="json",
        )
        self.assertEqual(resp.status_code, 200)
        self.mem.refresh_from_db()
        self.assertEqual(self.mem.value, "Boston")

    def test_cannot_access_other_users_memory(self):
        other = User.objects.create_user(
            email="other2@example.com", password="pw", supabase_uid=_uid()
        )
        other_mem = UserMemory.objects.create(user=other, key="secret", value="nope")
        resp = self.client.delete(f"/agent/memory/{other_mem.pk}/")
        self.assertEqual(resp.status_code, 404)

    def test_put_missing_value(self):
        resp = self.client.put(f"/agent/memory/{self.mem.pk}/", {"key": "city"}, format="json")
        self.assertEqual(resp.status_code, 400)
