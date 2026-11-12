"""Django settings. All environment-specific values come from env vars (12-factor)."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
    LLM_PROVIDER=(str, "fake"),
    OPENAI_API_KEY=(str, ""),
    OPENAI_CHAT_MODEL=(str, "gpt-6-luna"),
    OPENAI_EMBEDDING_MODEL=(str, "text-embedding-3-small"),
    # USD per 1M tokens. Check current prices on the provider's pricing page.
    CHAT_INPUT_PRICE_PER_MTOK=(float, 0.10),
    CHAT_OUTPUT_PRICE_PER_MTOK=(float, 0.50),
    EMBEDDING_PRICE_PER_MTOK=(float, 0.02),
    MAX_UPLOAD_BYTES=(int, 2 * 1024 * 1024),
    RAG_TOP_K=(int, 5),
    RAG_MAX_DISTANCE=(float, 0.75),
    THROTTLE_ASK=(str, "30/hour"),
    THROTTLE_UPLOAD=(str, "20/day"),
    THROTTLE_GUEST=(str, "20/hour"),
    DEMO_DAILY_BUDGET_USD=(float, 0.50),
    ALLOWANCE_DAILY_USD=(float, 0.10),
    GUEST_ALLOWANCE_DAILY_USD=(float, 0.05),
    GUEST_MAX_DOCUMENTS=(int, 5),
    GUEST_MAX_UPLOAD_BYTES=(int, 500 * 1024),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key-do-not-use-in-production-0123456789")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# Render injects the public hostname; trust it automatically.
if render_host := env("RENDER_EXTERNAL_HOSTNAME", default=""):
    ALLOWED_HOSTS.append(render_host)
    CSRF_TRUSTED_ORIGINS.append(f"https://{render_host}")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.accounts",
    "apps.documents",
    "apps.qa",
    "apps.web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {"default": env.db("DATABASE_URL", default="postgres://app:app@localhost:5432/ragapi")}
DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "ask": env("THROTTLE_ASK"),
        "upload": env("THROTTLE_UPLOAD"),
        "register": "10/hour",
        "guest": env("THROTTLE_GUEST"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Django RAG API",
    "DESCRIPTION": "Upload documents and ask questions answered from them, with citations.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# RAG / LLM
EMBEDDING_DIM = 1536  # matches text-embedding-3-small; changing it needs a migration
LLM_PROVIDER = env("LLM_PROVIDER")
OPENAI_API_KEY = env("OPENAI_API_KEY")
OPENAI_CHAT_MODEL = env("OPENAI_CHAT_MODEL")
OPENAI_EMBEDDING_MODEL = env("OPENAI_EMBEDDING_MODEL")
CHAT_INPUT_PRICE_PER_MTOK = env("CHAT_INPUT_PRICE_PER_MTOK")
CHAT_OUTPUT_PRICE_PER_MTOK = env("CHAT_OUTPUT_PRICE_PER_MTOK")
EMBEDDING_PRICE_PER_MTOK = env("EMBEDDING_PRICE_PER_MTOK")
MAX_UPLOAD_BYTES = env("MAX_UPLOAD_BYTES")
RAG_TOP_K = env("RAG_TOP_K")
RAG_MAX_DISTANCE = env("RAG_MAX_DISTANCE")
DEMO_DAILY_BUDGET_USD = env("DEMO_DAILY_BUDGET_USD")  # 0 disables the cap
# Each Owner's share of the Demo budget per UTC day; 0 disables it.
ALLOWANCE_DAILY_USD = env("ALLOWANCE_DAILY_USD")
GUEST_ALLOWANCE_DAILY_USD = env("GUEST_ALLOWANCE_DAILY_USD")
GUEST_MAX_DOCUMENTS = env("GUEST_MAX_DOCUMENTS")
GUEST_MAX_UPLOAD_BYTES = env("GUEST_MAX_UPLOAD_BYTES")

LOGIN_URL = "web:login"
LOGIN_REDIRECT_URL = "web:app"
LOGOUT_REDIRECT_URL = "web:landing"

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$"]  # platform health checks use plain HTTP
    SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
}
