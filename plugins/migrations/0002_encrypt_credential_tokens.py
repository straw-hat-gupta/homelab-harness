from django.db import migrations, models
import plugins.fields


def encrypt_existing_tokens(apps, schema_editor):
    """Encrypt any plaintext access_token / refresh_token rows before the AlterField."""
    from django.conf import settings
    from cryptography.fernet import Fernet, InvalidToken

    key = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "")
    if not key:
        return  # fresh install or test env — nothing to migrate

    f = Fernet(key.encode() if isinstance(key, str) else key)
    Credentials = apps.get_model("plugins", "Credentials")

    for cred in Credentials.objects.all():
        changed = False

        # access_token — always present
        try:
            f.decrypt(cred.access_token.encode())
            # Successful decrypt → already encrypted, skip
        except (InvalidToken, Exception):
            cred.access_token = f.encrypt(cred.access_token.encode()).decode()
            changed = True

        # refresh_token — optional
        if cred.refresh_token:
            try:
                f.decrypt(cred.refresh_token.encode())
            except (InvalidToken, Exception):
                cred.refresh_token = f.encrypt(cred.refresh_token.encode()).decode()
                changed = True

        if changed:
            cred.save()


class Migration(migrations.Migration):

    dependencies = [
        ("plugins", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(encrypt_existing_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="credentials",
            name="access_token",
            field=plugins.fields.EncryptedTextField(),
        ),
        migrations.AlterField(
            model_name="credentials",
            name="refresh_token",
            field=plugins.fields.EncryptedTextField(blank=True, null=True),
        ),
    ]
