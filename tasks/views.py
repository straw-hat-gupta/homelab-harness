from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Task
from projects.models import Projects
from .serializers import TaskSerializer, SubTaskSerializer
from backend.pagination import AivaPagination

class TaskListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, projectId):
        """List tasks for a project.

        Args:
            request: Authenticated DRF request.
            projectId: Project primary key.

        Returns:
            Response containing project tasks.
        """
        tasks = Task.objects.filter(
            project__id=projectId,
            project__user=request.user
        ).prefetch_related('sub_tasks')
        paginator = AivaPagination()
        page = paginator.paginate_queryset(tasks, request)
        serializer = TaskSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, projectId):
        """Create a task in a project.

        Args:
            request: Authenticated DRF request with task data.
            projectId: Project primary key.

        Returns:
            Response containing the created task.
        """
        project = get_object_or_404(Projects, id=projectId, user=request.user)
        serializer = TaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        task = serializer.save(project=project)
        return Response(TaskSerializer(task).data, status=201)


class TaskDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, projectId, taskId):
        """Retrieve one task.

        Args:
            request: Authenticated DRF request.
            projectId: Project primary key.
            taskId: Task primary key.

        Returns:
            Response containing task data.
        """
        task = get_object_or_404(
            Task.objects.prefetch_related('sub_tasks'),
            id=taskId,
            project__id=projectId,
            project__user=request.user
        )
        serializer = TaskSerializer(task)
        return Response(serializer.data, status=200)

    def patch(self, request, projectId, taskId):
        """Partially update one task.

        Args:
            request: Authenticated DRF request with task updates.
            projectId: Project primary key.
            taskId: Task primary key.

        Returns:
            Response containing updated task data.
        """
        task = get_object_or_404(
            Task,
            id=taskId,
            project__id=projectId,
            project__user=request.user
        )
        serializer = TaskSerializer(task, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=200)

    def delete(self, request, projectId, taskId):
        """Delete one task.

        Args:
            request: Authenticated DRF request.
            projectId: Project primary key.
            taskId: Task primary key.

        Returns:
            Empty 204 response.
        """
        task = get_object_or_404(
            Task,
            id=taskId,
            project__id=projectId,
            project__user=request.user
        )
        task.delete()
        return Response(status=204)

class SubTaskListView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, projectId, taskId):
        """Create a subtask for a task.

        Args:
            request: Authenticated DRF request with subtask data.
            projectId: Project primary key.
            taskId: Task primary key.

        Returns:
            Response containing the created subtask.
        """
        task = get_object_or_404(
            Task,
            id=taskId,
            project__id=projectId,
            project__user=request.user
        )
        serializer = SubTaskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        subtask = serializer.save(task=task)
        return Response(SubTaskSerializer(subtask).data, status=201)
