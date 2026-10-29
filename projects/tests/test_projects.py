import uuid

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Projects

User = get_user_model()


class ProjectTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="password123",
            supabase_uid=uuid.uuid4(),
        )
        self.client.force_authenticate(user=self.user)

        self.project = Projects.objects.create(
            user=self.user,
            name="Test Project",
            description="Test description",
            plugins={"pluginA": True},
        )

        self.list_url = reverse("projects-list")
        self.detail_url = reverse("projects-detail", kwargs={"projectId": self.project.id})

    # ---------- Auth ----------

    def test_unauthenticated_returns_4xx(self):
        self.client.force_authenticate(user=None)
        self.assertIn(
            self.client.get(self.list_url).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    # ---------- List ----------

    def test_get_projects(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_list_returns_only_own_projects(self):
        other = User.objects.create_user(
            email="other@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        Projects.objects.create(user=other, name="Other Project")
        response = self.client.get(self.list_url)
        names = [p["name"] for p in response.data["results"]]
        self.assertNotIn("Other Project", names)

    # ---------- Detail ----------

    def test_get_project(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Test Project")

    def test_projects_scoped_to_user(self):
        other = User.objects.create_user(
            email="other2@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        other_project = Projects.objects.create(user=other, name="Other Project")
        url = reverse("projects-detail", kwargs={"projectId": other_project.id})
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    # ---------- Create ----------

    def test_create_project(self):
        payload = {"name": "New Project", "description": "desc", "plugins": {"pluginB": True}}
        response = self.client.post(self.list_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "New Project")

    # ---------- Update ----------

    def test_update_project(self):
        payload = {"name": "Updated Name"}
        response = self.client.put(self.detail_url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "Updated Name")

    # ---------- Delete ----------

    def test_delete_project(self):
        self.assertEqual(self.client.delete(self.detail_url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get(self.detail_url).status_code, status.HTTP_404_NOT_FOUND)
