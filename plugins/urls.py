from django.urls import path
from . import views

urlpatterns = [
    # Public / frontend-facing endpoints
    path("registry/", views.PluginRegistryView.as_view(), name="plugin-registry"),

    # Start OAuth connect (returns redirect URL or redirects straight)
    path("oauth/connect/", views.StartConnectView.as_view(), name="credentials-initiate-oauth"),
    path("oauth/finalize/", views.OAuthFinalizeView.as_view(), name="credentials-finalize-oauth"),

    # Callback endpoint (providers redirect here after auth)
    path("oauth/callback/<str:plugin_key>/", views.OAuthCallbackView.as_view(), name="credentials-callback-oauth"),

    # REST endpoints for credentials
    path("credentials/", views.CredentialListCreateView.as_view(), name="credentials-list"),
    path("credentials/<int:pk>/", views.CredentialDetailView.as_view(), name="credentials-detail"),
    path("credentials/<int:pk>/refresh/", views.CredentialRefreshView.as_view(), name="credentials-refresh"),
    path("credentials/<int:pk>/disconnect/", views.CredentialDisconnectView.as_view(), name="credentials-disconnect"),
]
