"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from agent.views import agent_view, agent_stream_view, reset_view, actions_view, memory_list_view, memory_detail_view
from tools.views import tools_view
from workflows.scheduled_views import (
    scheduled_run_detail_view,
    scheduled_run_executions_view,
    scheduled_run_list_view,
    scheduled_run_now_view,
)
from workflows.views import workflow_list_view, workflow_detail_view, workflow_run_view, workflow_validate_view

urlpatterns = [
    path('admin/', admin.site.urls),
    # Agent — conversational interface
    path('agent/', agent_view, name='agent'),
    path('agent/stream/', agent_stream_view, name='agent-stream'),
    path('agent/actions/', actions_view, name='agent-actions'),
    path('agent/reset/<int:project_id>/', reset_view, name='agent-reset'),
    path('agent/memory/', memory_list_view, name='agent-memory-list'),
    path('agent/memory/<int:memory_id>/', memory_detail_view, name='agent-memory-detail'),
    # Platform — tools & workflows (not scoped to the chat agent)
    path('tools/', tools_view, name='tools-list'),
    path('workflows/', workflow_list_view, name='workflow-list'),
    path('workflows/validate/', workflow_validate_view, name='workflow-validate'),
    path('workflows/<int:workflow_id>/', workflow_detail_view, name='workflow-detail'),
    path('workflows/<int:workflow_id>/run/', workflow_run_view, name='workflow-run'),
    path('scheduled-runs/', scheduled_run_list_view, name='scheduled-run-list'),
    path('scheduled-runs/<int:scheduled_run_id>/', scheduled_run_detail_view, name='scheduled-run-detail'),
    path('scheduled-runs/<int:scheduled_run_id>/run-now/', scheduled_run_now_view, name='scheduled-run-now'),
    path('scheduled-runs/<int:scheduled_run_id>/executions/', scheduled_run_executions_view, name='scheduled-run-executions'),
    path('contacts/', include('contacts.urls')),
    path('plugins/', include('plugins.urls')),
    path('projects/', include('projects.urls')),
    path('project-context/', include('context.urls')),
    path('tasks/', include('tasks.urls')),
]
