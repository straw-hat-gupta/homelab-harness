from django.db import models


class Task(models.Model):
    project = models.ForeignKey(
        'projects.Projects',
        on_delete=models.CASCADE,
        related_name='tasks'
    )

    title = models.TextField()
    description = models.TextField(blank=True)

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks'
        ordering = ['created_at']

    def __str__(self):
        return f"Task {self.id}: {self.title}"


class SubTask(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='sub_tasks'
    )

    action = models.TextField()
    detail = models.TextField(blank=True)
    plugin = models.TextField()

    recipients = models.JSONField(default=list)

    order = models.PositiveIntegerField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sub_tasks'
        ordering = ['order']
        unique_together = ('task', 'order')

    def __str__(self):
        return f"SubTask {self.order} for Task {self.task_id}"
