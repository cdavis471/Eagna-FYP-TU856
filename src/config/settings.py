import os
from pathlib import Path

# /srv/eagna/src/config/settings.py -> BASE_DIR = /srv/eagna/src
BASE_DIR = Path(__file__).resolve().parent.parent

# --- ENV helpers ---
def env(name: str, default=None, required: bool = False):
    val = os.environ.get(name, default)
    if required and (val is None or val == ""):
        raise RuntimeError(f"Missing required environment variable: {name}")
    return val


# --- Core ---
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
DEBUG = env("DJANGO_DEBUG", "False").lower() in ("1", "true", "yes", "on")

# Comma-separated in .env
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

# If you're running behind Nginx + HTTPS, keep these (once HTTPS is active):
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Applications ---
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
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

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
# ASGI_APPLICATION = "config.asgi.application"  # only if you're actually using ASGI

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Centralized templates directory: /srv/eagna/src/templates
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.accounts.context_processors.notifications_context",
            ],
        },
    }
]

# --- Database (via env) ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", required=True),
        "USER": env("DB_USER", required=True),
        "PASSWORD": env("DB_PASSWORD", required=True),
        "HOST": env("DB_HOST", required=True),
        "PORT": env("DB_PORT", "5432"),
    }
}

# --- Auth ---
AUTH_USER_MODEL = "accounts.User"

# --- Internationalization ---
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static & Media (new layout) ---
STATIC_URL = "/static/"
# Static *sources* live in /srv/eagna/src/static
STATICFILES_DIRS = [BASE_DIR / "static"]
# Collected static goes to /srv/eagna/var/static
STATIC_ROOT = BASE_DIR.parent / "var" / "static"

MEDIA_URL = "/media/"
# Uploads go to /srv/eagna/var/media
MEDIA_ROOT = BASE_DIR.parent / "var" / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Login handling ---
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"

# --- Optional production security toggles (enable once HTTPS is working) ---
# SECURE_SSL_REDIRECT = True
# SESSION_COOKIE_SECURE = True
# CSRF_COOKIE_SECURE = True
# SECURE_HSTS_SECONDS = 3600
# SECURE_HSTS_INCLUDE_SUBDOMAINS = True
