"""
Django settings for DealFlow360.

Stack is settled by ADR-001 (Django 5) and ADR-002 (SQLite). See docs/DECISIONS.md.

The one thing in this file that must never be changed after the first migration runs is
AUTH_USER_MODEL. See ADR-003 and tasks/CURRENT.md (T-01).
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env if present. Optional: the app runs on defaults without one.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # pragma: no cover - dotenv is a convenience, not a requirement
    pass


def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------- core

# Dev fallback only. Set DJANGO_SECRET_KEY in .env for anything that is not a laptop.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY", "dev-only-insecure-key-do-not-use-outside-localhost"
)

DEBUG = _env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",")
    if h.strip()
]

# Django 4+ requires the FULL scheme here, not a bare hostname:
# "https://dealflow360.onrender.com", not "dealflow360.onrender.com". A bare host is
# silently ignored and every POST then fails CSRF verification behind the proxy.
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

INSTALLED_APPS = [
    # core comes FIRST so its templates/admin/*.html override Django's own. With
    # APP_DIRS the first app in this list that has a matching template wins, and the
    # admin app ships an index.html and base_site.html of its own.
    "core",
    # Our AdminConfig subclass, which installs core.admin_site.DealFlowAdminSite as
    # the default admin site. Replaces "django.contrib.admin" — do not list both.
    "core.admin_apps.DealFlowAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# WhiteNoise serves the vendored Tailwind, HTMX and theme CSS when DEBUG is False,
# because there is no separate static file server in front of the app.
#
# The import guard is deliberate, not defensive habit: the demo runs from a local venv
# that may not have whitenoise installed, and an unguarded MIDDLEWARE entry would crash
# runserver on startup with a ModuleNotFoundError. Guarded, a machine without it simply
# falls back to Django's own static handling, which works in DEBUG.
#
# It must sit directly after SecurityMiddleware — hence insert(1) rather than append.
try:
    import whitenoise  # noqa: F401
except ImportError:
    _HAS_WHITENOISE = False
else:
    _HAS_WHITENOISE = True
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

ROOT_URLCONF = "config.urls"

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
                "core.context_processors.roles",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------- database

# ADR-002: SQLite, one local file. Rebuilt from migrations + the seed script, so it is
# gitignored and safe to delete when it gets into a bad state.
# The path is overridable so the database can be migrated or seeded somewhere other than
# the working tree — a network-mounted checkout, for instance, where SQLite's locking
# fails. Unset, it is the file beside manage.py, which is what every instruction assumes.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("DJANGO_DB_PATH") or BASE_DIR / "db.sqlite3",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------- auth

# ADR-003. MUST be set before the first migration runs — changing it afterwards means
# deleting the database and every migration and starting again.
AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/workspace/"
LOGOUT_REDIRECT_URL = "/login/"

# T-04 acceptance asks for these explicitly; they cost nothing to set correctly now.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# ---------------------------------------------------------------- i18n / static

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# collectstatic gathers core/static/ (vendored Tailwind, HTMX, theme-light.css) here.
# Gitignored: it is a build artefact, rebuilt by build.sh on every deploy.
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Compressed + manifest hashing when whitenoise is present; Django's plain
        # backend otherwise, so a venv without it still collects and serves static
        # files rather than failing at startup. Same guard as the middleware above.
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if _HAS_WHITENOISE
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}


# ---------------------------------------------------------------- deployment

# Only when DEBUG is off, so local development over plain HTTP is untouched.
# Render terminates TLS at its proxy and forwards the original scheme in a header;
# without SECURE_PROXY_SSL_HEADER Django sees http, and SECURE_SSL_REDIRECT would
# then loop forever. See ADR-018.
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
