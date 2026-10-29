from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import models
import logging


logger = logging.getLogger(__name__)


def _get_fernet():
    """Build the configured Fernet encryption helper.

    Returns:
        MultiFernet instance using configured credential keys.
    """
    keys = getattr(settings, "CREDENTIAL_ENCRYPTION_KEYS", None)
    if not keys:
        primary = getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "")
        if not primary:
            raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is not configured")
        keys = [primary]
    return MultiFernet([Fernet(k) for k in keys])


class EncryptedTextField(models.TextField):
    def from_db_value(self, value, expression, connection):
        """Decrypt a database value when loading the model.

        Args:
            value: Raw database value.
            expression: Django query expression.
            connection: Database connection.

        Returns:
            Decrypted text or original value during migration fallback.
        """
        if value is None:
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except Exception as exc:
            if getattr(settings, "CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK", False):
                logger.warning(
                    "Credential encryption plaintext fallback used for %s.%s: %s",
                    getattr(self.model, "__name__", "unknown_model"),
                    self.name,
                    exc.__class__.__name__,
                )
                return value
            raise

    def to_python(self, value):
        """Return the Python representation for field values.

        Args:
            value: Field value.

        Returns:
            Unchanged field value.
        """
        return value

    def get_prep_value(self, value):
        """Encrypt a value before saving it to the database.

        Args:
            value: Plaintext field value.

        Returns:
            Encrypted database value.
        """
        if value is None:
            return value
        return _get_fernet().encrypt(value.encode()).decode()
