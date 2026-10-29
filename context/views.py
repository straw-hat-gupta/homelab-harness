from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from projects.models import Projects
from .models import ProjectContext
from .serializers import ProjectContextSerializer
from backend.pagination import AivaPagination

class ProjectContextListView(APIView):
    """
    List or append context messages for a project.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, projectId):
        """List context messages for a project.

        Args:
            request: Authenticated DRF request.
            projectId: Project primary key.

        Returns:
            Response containing ordered context messages.
        """
        project = get_object_or_404(
            Projects,
            id=projectId,
            user=request.user
        )

        contexts = ProjectContext.objects.filter(
            project=project
        ).order_by("sequence")

        paginator = AivaPagination()
        page = paginator.paginate_queryset(contexts, request)
        serializer = ProjectContextSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, projectId):
        """Append one context message to a project.

        Args:
            request: Authenticated DRF request with context data.
            projectId: Project primary key.

        Returns:
            Response containing the created context message.
        """
        project = get_object_or_404(
            Projects,
            id=projectId,
            user=request.user
        )

        serializer = ProjectContextSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            last_entry = (
                ProjectContext.objects
                .filter(project=project)
                .select_for_update()
                .order_by("-sequence")
                .first()
            )
            next_sequence = (last_entry.sequence + 1) if last_entry else 1
            context = serializer.save(project=project, sequence=next_sequence)

        return Response(ProjectContextSerializer(context).data, status=status.HTTP_201_CREATED)

class ProjectContextClearView(APIView):
    """
    Clear all context for a project.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, projectId):
        """Delete all context messages for a project.

        Args:
            request: Authenticated DRF request.
            projectId: Project primary key.

        Returns:
            Empty 204 response.
        """
        project = get_object_or_404(
            Projects,
            id=projectId,
            user=request.user
        )

        ProjectContext.objects.filter(project=project).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ProjectContextTrimView(APIView):
    """
    Keep only the last N context messages.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, projectId):
        """Trim project context to the last N messages.

        Args:
            request: Authenticated DRF request with keep_last.
            projectId: Project primary key.

        Returns:
            Response containing the requested keep count.
        """
        project = get_object_or_404(
            Projects,
            id=projectId,
            user=request.user
        )

        try:
            keep_last = int(request.data.get("keep_last", 50))
        except (ValueError, TypeError):
            return Response(
                {"error": "keep_last must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if keep_last < 1:
            return Response(
                {"error": "keep_last must be at least 1"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        contexts = ProjectContext.objects.filter(
            project=project
        ).order_by("-sequence")

        ids_to_keep = contexts.values_list("id", flat=True)[:keep_last]

        ProjectContext.objects.filter(
            project=project
        ).exclude(id__in=ids_to_keep).delete()

        return Response(
            {"kept": keep_last},
            status=status.HTTP_200_OK
        )
