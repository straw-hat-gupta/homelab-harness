from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Projects(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    plugins = models.JSONField(default=dict)
    system_prompt = models.TextField(blank=True, default="")

    # Context window anchor
    active_context_from = models.BigIntegerField(default=0)

    # Pending plan awaiting user confirmation (null = no pending plan)
    pending_plan = models.JSONField(null=True, blank=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects"

    def __str__(self):
        return self.name
