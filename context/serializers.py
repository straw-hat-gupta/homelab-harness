from rest_framework import serializers
from .models import ProjectContext


MAX_CONTEXT_CONTENT_LENGTH = 10_000


class ProjectContextSerializer(serializers.ModelSerializer):
    content = serializers.CharField(max_length=MAX_CONTEXT_CONTENT_LENGTH)

    class Meta:
        model = ProjectContext
        fields = [
            "id",
            "role",
            "content",
            "sequence",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "sequence",
            "created_at",
        ]

    def validate_role(self, value):
        """Validate a project context role.

        Args:
            value: Role value from the request.

        Returns:
            Validated role value.
        """
        if value != "user":
            raise serializers.ValidationError("Only user context messages can be created through this endpoint")
        return value
