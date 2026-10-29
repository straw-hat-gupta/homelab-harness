from django.urls import path
from projects.views import ProjectsDetailView, ProjectsListView

urlpatterns = [
	# Projects
	path('', ProjectsListView.as_view(), name='projects-list'),
	path('<int:projectId>/', ProjectsDetailView.as_view(), name='projects-detail'),
]