from django.urls import path
from context.views import (
    ProjectContextListView,
    ProjectContextClearView,
    ProjectContextTrimView,
)

urlpatterns = [
    path(
        '<int:projectId>/',
        ProjectContextListView.as_view(),
        name='context-list'
    ),
    path(
        '<int:projectId>/clear/',
        ProjectContextClearView.as_view(),
        name='context-clear'
    ),
    path(
        '<int:projectId>/trim/',
        ProjectContextTrimView.as_view(),
        name='context-trim'
    ),
]
