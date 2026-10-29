import uuid

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Projects
from tasks.models import Task, SubTask

User = get_user_model()


class TaskTests(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="password123",
            supabase_uid=uuid.uuid4(),
        )
        self.client.force_authenticate(user=self.user)

        self.project = Projects.objects.create(user=self.user, name="Test Project")

        self.task = Task.objects.create(project=self.project, title="Fetch Gmail + Send Slack")

        SubTask.objects.create(
            task=self.task, action="Read Gmail", plugin="gmail", recipients=[], order=1
        )

        self.task_list_url = reverse("task-list", kwargs={"projectId": self.project.id})
        self.task_detail_url = reverse(
            "task-detail", kwargs={"projectId": self.project.id, "taskId": self.task.id}
        )
        self.subtask_url = reverse(
            "subtask-create", kwargs={"projectId": self.project.id, "taskId": self.task.id}
        )

    # ---------- Auth ----------

    def test_unauthenticated_returns_4xx(self):
        self.client.force_authenticate(user=None)
        self.assertIn(
            self.client.get(self.task_list_url).status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    # ---------- Cross-user isolation ----------

    def test_tasks_scoped_to_user(self):
        other = User.objects.create_user(
            email="other@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        other_project = Projects.objects.create(user=other, name="Other Project")
        other_task = Task.objects.create(project=other_project, title="Other Task")
        url = reverse(
            "task-detail", kwargs={"projectId": other_project.id, "taskId": other_task.id}
        )
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    def test_list_tasks_scoped_to_user(self):
        other = User.objects.create_user(
            email="other2@example.com",
            password="pass",
            supabase_uid=uuid.uuid4(),
        )
        other_project = Projects.objects.create(user=other, name="Other Project")
        Task.objects.create(project=other_project, title="Other Task")
        response = self.client.get(self.task_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    # ---------- CRUD ----------

    def test_list_tasks(self):
        response = self.client.get(self.task_list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["results"]), 1)

    def test_create_task(self):
        response = self.client.post(self.task_list_url, {"title": "New Task"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["title"], "New Task")

    def test_get_task_detail(self):
        response = self.client.get(self.task_detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], self.task.title)

    def test_delete_task(self):
        self.assertEqual(self.client.delete(self.task_detail_url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get(self.task_detail_url).status_code, status.HTTP_404_NOT_FOUND)

    def test_create_subtask(self):
        response = self.client.post(
            self.subtask_url, {"action": "Summarize Email", "plugin": "llm", "order": 2}
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["action"], "Summarize Email")

    def test_subtask_has_no_execution_state_fields(self):
        """Removed fields should not appear in subtask responses."""
        response = self.client.get(self.task_detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        subtask = response.data["sub_tasks"][0]
        for field in ("dependencyRequired", "confirmationRequired", "confirmationStatus", "status", "result"):
            self.assertNotIn(field, subtask)

    def test_patch_task_status(self):
        response = self.client.patch(self.task_detail_url, {"status": "completed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "completed")

    def test_patch_task_title(self):
        response = self.client.patch(self.task_detail_url, {"title": "Updated Title"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Updated Title")
