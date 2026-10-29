import uuid

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from context.models import ProjectContext
from projects.models import Projects

User = get_user_model()


class ProjectContextTests(APITestCase):

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

        ProjectContext.objects.create(project=self.project, role="user", content="Hello", sequence=1)
        ProjectContext.objects.create(project=self.project, role="assistant", content="Hi there", sequence=2)

        self.list_url = reverse("context-list", kwargs={"projectId": self.project.id})
        self.clear_url = reverse("context-clear", kwargs={"projectId": self.project.id})
        self.trim_url = reverse("context-trim", kwargs={"projectId": self.project.id})

    # ---------- Auth ----------

    def test_unauthenticated_returns_4xx(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # ---------- Read ----------

    def test_get_context(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 2)
        self.assertEqual(response.data["results"][0]["sequence"], 1)

    def test_context_is_user_scoped(self):
        other_user = User.objects.create_user(
            email="other@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        other_project = Projects.objects.create(user=other_user, name="Other Project", plugins={})
        url = reverse("context-list", kwargs={"projectId": other_project.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ---------- Create ----------

    def test_add_context_entry(self):
        response = self.client.post(self.list_url, {"role": "user", "content": "New message"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["sequence"], 3)

    def test_rejects_client_created_backend_owned_roles(self):
        for role in ["system", "assistant", "tool"]:
            response = self.client.post(
                self.list_url,
                {"role": role, "content": "Not client owned"},
                format="json",
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertIn("role", response.data)

    def test_rejects_oversized_context_content(self):
        response = self.client.post(
            self.list_url,
            {"role": "user", "content": "x" * 10001},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("content", response.data)

    # ---------- Clear ----------

    def test_clear_context(self):
        self.assertEqual(self.client.delete(self.clear_url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(ProjectContext.objects.filter(project=self.project).count(), 0)

    # ---------- Trim ----------

    def test_trim_context(self):
        response = self.client.post(self.trim_url, {"keep_last": 1}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        remaining = ProjectContext.objects.filter(project=self.project)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().sequence, 2)
