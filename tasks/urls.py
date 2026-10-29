from django.urls import path
from .views import (
    TaskListView,
    TaskDetailView,
    SubTaskListView,
)

urlpatterns = [
    path(
        '<int:projectId>/',
        TaskListView.as_view(),
        name='task-list'
    ),
    path(
        '<int:projectId>/<int:taskId>/',
        TaskDetailView.as_view(),
        name='task-detail'
    ),
    path(
        '<int:projectId>/<int:taskId>/subtasks/',
        SubTaskListView.as_view(),
        name='subtask-create'
    ),
]
