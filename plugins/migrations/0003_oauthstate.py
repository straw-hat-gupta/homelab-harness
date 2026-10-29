import django.db.models.deletion
from django.conf import settings
import plugins.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0002_encrypt_credential_tokens"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OAuthState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plugin", models.CharField(db_index=True, max_length=255)),
                ("nonce", models.CharField(max_length=128, unique=True)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("finalize_nonce", models.CharField(blank=True, db_index=True, max_length=128, null=True, unique=True)),
                ("finalized_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("account_id", models.CharField(blank=True, max_length=255, null=True)),
                ("access_token", plugins.fields.EncryptedTextField(blank=True, null=True)),
                ("refresh_token", plugins.fields.EncryptedTextField(blank=True, null=True)),
                ("scopes", models.JSONField(blank=True, null=True)),
                ("token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="oauth_states",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "PluginOAuthStates",
            },
        ),
    ]
