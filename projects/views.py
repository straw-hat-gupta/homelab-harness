from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import Projects
from .serializers import ProjectsSerializer
from backend.pagination import AivaPagination


class ProjectsListView(APIView):
    """
    Handle bulk project operations.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        List all projects for the authenticated user.
        """
        projects = Projects.objects.filter(user=request.user)
        paginator = AivaPagination()
        page = paginator.paginate_queryset(projects, request)
        serializer = ProjectsSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        """
        Create a new project for the authenticated user.
        """
        serializer = ProjectsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = serializer.save(user=request.user)
        return Response(ProjectsSerializer(project).data, status=201)


class ProjectsDetailView(APIView):
    """
    Handle individual project operations.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, projectId):
        """
        Retrieve a project by ID.
        """
        project = get_object_or_404(
            Projects,
            user=request.user,
            id=projectId,
        )
        serializer = ProjectsSerializer(project)
        return Response(serializer.data, status=200)

    def put(self, request, projectId):
        """
        Update a project by ID.
        """
        data = request.data

        project = get_object_or_404(
            Projects,
            user=request.user,
            id=projectId,
        )

        project.name = data.get("name", project.name)
        project.description = data.get("description", project.description)
        project.system_prompt = data.get("system_prompt", project.system_prompt)
        if "plugins" in data:
            plugins_data = data["plugins"]
            if not isinstance(plugins_data, dict) or not all(
                isinstance(k, str) and isinstance(v, bool) for k, v in plugins_data.items()
            ):
                return Response(
                    {"error": "plugins must be a mapping of plugin IDs to booleans"},
                    status=400,
                )
            project.plugins = plugins_data
        project.active_context_from = data.get(
            "active_context_from",
            project.active_context_from,
        )
        project.save()

        serializer = ProjectsSerializer(project)
        return Response(serializer.data, status=200)

    def delete(self, request, projectId):
        """
        Delete a project by ID.
        """
        project = get_object_or_404(
            Projects,
            user=request.user,
            id=projectId,
        )
        project.delete()
        return Response(status=204)
