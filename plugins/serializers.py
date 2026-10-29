# plugins/serializers.py
from rest_framework import serializers

from .models import Credentials


class CredentialReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = Credentials
        fields = [
            "id",
            "plugin",
            "account_id",
            "scopes",
            "metadata",
            "expires_at",
            "status",
            "created_at",
            "updated_at",
            "last_used_at",
            "last_error",
        ]
        read_only_fields = fields


class CredentialWriteSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Credentials
        fields = [
            "id",
            "user",
            "plugin",
            "account_id",
            "access_token",
            "refresh_token",
            "scopes",
            "metadata",
            "expires_at",
            "status",
        ]
        read_only_fields = ["id"]


class ConnectSerializer(serializers.Serializer):
    plugin = serializers.CharField()


class OAuthFinalizeSerializer(serializers.Serializer):
    plugin = serializers.CharField()
    completion_token = serializers.CharField()


class DisconnectSerializer(serializers.Serializer):
    id = serializers.IntegerField()
