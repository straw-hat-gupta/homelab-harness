from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class PlannerUsage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="planner_usage")
    model = models.CharField(max_length=100)
    input_tokens = models.PositiveIntegerField()
    output_tokens = models.PositiveIntegerField()
    call_type = models.CharField(max_length=30)  # "plan", "revise", "intent"
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "planner_usage"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.model}:{self.call_type} in={self.input_tokens} out={self.output_tokens}"


class AgentAction(models.Model):
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_SUCCESS, "Success"), (STATUS_FAILED, "Failed")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="agent_actions")
    tool = models.CharField(max_length=255)
    params_summary = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SUCCESS)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_actions"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["user", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.tool}:{self.status}@{self.timestamp}"


class UserMemory(models.Model):
    SOURCE_MANUAL = "manual"
    SOURCE_AGENT = "agent"
    SOURCE_CHOICES = [(SOURCE_MANUAL, "Manual"), (SOURCE_AGENT, "Agent")]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memories")
    key = models.CharField(max_length=255)
    value = models.TextField()
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_memories"
        ordering = ["-updated_at"]
        unique_together = ("user", "key")
        indexes = [models.Index(fields=["user", "-updated_at"])]

    def __str__(self):
        return f"{self.user_id}:{self.key}"


