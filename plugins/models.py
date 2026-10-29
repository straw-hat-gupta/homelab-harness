# plugins/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta

from plugins.fields import EncryptedTextField

User = get_user_model()


class Credentials(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("revoked", "Revoked"),
        ("error", "Error"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="credentials")
    plugin = models.CharField(max_length=255, db_index=True)  # e.g. "gmail", "slack"
    account_id = models.CharField(
        max_length=255, null=True, blank=True
    )  # e.g. google email or slack workspace id

    access_token = EncryptedTextField(null=False, blank=False)
    refresh_token = EncryptedTextField(null=True, blank=True)

    # metadata
    scopes = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)

    expires_at = models.DateTimeField(null=True, blank=True)  # access token expiry
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    # auditing
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "PluginCredentials"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "plugin", "account_id"],
                name="unique_credential_per_account",
                nulls_distinct=False,  # treat NULL account_id as equal (PostgreSQL NULLS NOT DISTINCT)
            )
        ]

    def is_expired(self, margin_seconds=60):
        """Check whether the access token is expired or near expiry.

        Args:
            margin_seconds: Safety margin before actual expiry.

        Returns:
            True when the credential should be refreshed.
        """
        if not self.expires_at:
            return False
        return self.expires_at <= timezone.now() + timedelta(seconds=margin_seconds)

    def mark_used(self):
        """Update the last-used timestamp.

        Returns:
            None.
        """
        self.last_used_at = timezone.now()
        self.save(update_fields=["last_used_at"])

    def safe_dict(self):
        """Return public-safe info to show in APIs"""
        return {
            "id": self.id,
            "plugin": self.plugin,
            "account_id": self.account_id,
            "scopes": self.scopes,
            "status": self.status,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
        }

    def __str__(self):
        return f"{self.user} - {self.plugin} ({self.account_id})"


class OAuthState(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="oauth_states")
    plugin = models.CharField(max_length=255, db_index=True)
    nonce = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    finalize_nonce = models.CharField(max_length=128, unique=True, null=True, blank=True, db_index=True)
    finalized_at = models.DateTimeField(null=True, blank=True, db_index=True)
    account_id = models.CharField(max_length=255, null=True, blank=True)
    access_token = EncryptedTextField(null=True, blank=True)
    refresh_token = EncryptedTextField(null=True, blank=True)
    scopes = models.JSONField(null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "PluginOAuthStates"

    def is_expired(self):
        return self.expires_at <= timezone.now()
