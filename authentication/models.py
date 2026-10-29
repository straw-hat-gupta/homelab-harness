from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager

class UserManager(BaseUserManager):
    """
    Manager for the custom User model.
    """

    def create_user(self, email, password=None, **extra_fields):
        """Create a local user linked to Supabase Auth.

        Args:
            email: User email address.
            password: Optional local password.
            **extra_fields: Additional user fields, including required supabase_uid.

        Returns:
            Created user instance.
        """
        if not email:
            raise ValueError("Users must have an email address")
        if not extra_fields.get("supabase_uid"):
            raise ValueError("Users must have a Supabase UID")
        email = self.normalize_email(email)

        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        """Create a Django admin superuser.

        Args:
            email: Superuser email address.
            password: Optional local password.
            **extra_fields: Additional user fields.

        Returns:
            Created superuser instance.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)  # Keep for admin access

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser):
    """
    Custom User model that syncs with Supabase Auth, without Django permissions/groups tables.
    """

    supabase_uid = models.UUIDField(unique=True)
    email = models.EmailField(unique=True)

    # Profile fields
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    display_name = models.CharField(max_length=200, blank=True)

    # Django auth flags
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_superuser = models.BooleanField(default=False)  # Needed for admin access

    # Manager
    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["supabase_uid"]

    class Meta:
        db_table = "Users"

    def __str__(self):
        return self.email

    # Optional: implement these methods so Django admin still works
    def has_perm(self, perm, obj=None):
        """Check whether the user has a permission.

        Args:
            perm: Permission codename.
            obj: Optional object being checked.

        Returns:
            True for superusers, otherwise False.
        """
        return self.is_superuser

    def has_module_perms(self, app_label):
        """Check whether the user can access an app module.

        Args:
            app_label: Django app label.

        Returns:
            True for superusers, otherwise False.
        """
        return self.is_superuser
