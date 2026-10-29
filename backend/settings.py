import os
from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Initialize environment variables
env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env("SECRET_KEY")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS:
    if DEBUG:
        ALLOWED_HOSTS = ["localhost", "127.0.0.1"]
    else:
        raise ImproperlyConfigured("ALLOWED_HOSTS must be set when DEBUG is False.")

CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
_cors_default = ["http://localhost:3000", "http://localhost:5173"] if DEBUG else []
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=_cors_default)


# Application definition

INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'contacts',
    'plugins',
    'authentication',
    'projects',
    'context',
    'tasks',
    'agent',
    'tools',
    'workflows',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB"),
        "USER": env("POSTGRES_USER"),
        "PASSWORD": env("SUPABASE_DB_PW"),
        "HOST": env("POSTGRES_HOST"),
        "PORT": env("POSTGRES_PORT", default="5432"),
        "OPTIONS": {
            "sslmode": env("POSTGRES_SSLMODE", default="require"),
        },
    }
}


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'authentication.User'


SUPABASE_URL = env("SUPABASE_URL").rstrip("/")
SUPABASE_ANON_KEY = env("SUPABASE_ANON_KEY", default="")
SUPABASE_JWT_SECRET = env("SUPABASE_JWT_SECRET")
SUPABASE_JWT_ISSUER = f"{SUPABASE_URL}/auth/v1"
SUPABASE_JWT_AUDIENCE = env("SUPABASE_JWT_AUDIENCE", default="authenticated").strip() or "authenticated"

PUBLIC_BACKEND_URL = env("PUBLIC_BACKEND_URL", default="").rstrip("/")
PLUGIN_OAUTH_SUCCESS_REDIRECT = env(
    "PLUGIN_OAUTH_SUCCESS_REDIRECT",
    default="aiva://oauth/{plugin}/success",
)
PLUGIN_OAUTH_FAILURE_REDIRECT = env(
    "PLUGIN_OAUTH_FAILURE_REDIRECT",
    default="aiva://oauth/{plugin}/failure",
)

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = env("GOOGLE_CLIENT_SECRET")
MICROSOFT_CLIENT_ID = env("MICROSOFT_CLIENT_ID", default="")
MICROSOFT_CLIENT_SECRET = env("MICROSOFT_CLIENT_SECRET", default="")
NOTION_CLIENT_ID = env("NOTION_CLIENT_ID", default="")
NOTION_CLIENT_SECRET = env("NOTION_CLIENT_SECRET", default="")

CREDENTIAL_ENCRYPTION_KEY = env("CREDENTIAL_ENCRYPTION_KEY", default="")
CREDENTIAL_ENCRYPTION_KEYS = env.list("CREDENTIAL_ENCRYPTION_KEYS", default=[])
CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK = env.bool(
    "CREDENTIAL_ENCRYPTION_ALLOW_PLAINTEXT_FALLBACK",
    default=False,
)

# OpenAI API key
OPENAI_KEY = env("OPENAI_KEY")

# LLM model selection (override via environment variables)
PLANNER_MODEL = env("PLANNER_MODEL", default="gpt-4o-mini")
PROCESSING_LLM_MODEL = env("PROCESSING_LLM_MODEL", default="gpt-4o-mini")

# Cache
# Set REDIS_URL in production (e.g. redis://localhost:6379/0 or a managed Redis URL).
# Without it, Django falls back to LocMemCache which is per-process and not shared
# across Gunicorn workers — fine for local dev/tests but wrong for production.
_REDIS_URL = env("REDIS_URL", default="").strip()
if _REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": _REDIS_URL,
        }
    }
# else: Django default LocMemCache — sufficient for local dev and the test suite.

CELERY_BROKER_URL = (
    env("CELERY_BROKER_URL", default="").strip()
    or _REDIS_URL
    or "redis://localhost:6379/0"
)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_BEAT_SCHEDULE = {
    "dispatch-due-scheduled-runs-every-minute": {
        "task": "workflows.dispatch_due_scheduled_runs",
        "schedule": 60.0,
    },
}


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "authentication.authentication.SupabaseAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "backend": {
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "backend",
        },
    },
    "loggers": {
        "agent": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "orchestrator": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "planner": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "workflows": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
