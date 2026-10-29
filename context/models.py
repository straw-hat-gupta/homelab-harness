# projects/models.py (or context/models.py if split)

from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class ProjectContext(models.Model):
    project = models.ForeignKey(
        "projects.Projects",
        on_delete=models.CASCADE,
        related_name="contexts"
    )

    # system | user | assistant | tool
    role = models.CharField(max_length=20)

    content = models.TextField()

    # Monotonic ordering (DO NOT reset)
    sequence = models.BigIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "project_context"
        ordering = ["sequence"]
        indexes = [
            models.Index(fields=["project", "sequence"]),
        ]

    def __str__(self):
        return f"{self.project_id}:{self.sequence}:{self.role}"
