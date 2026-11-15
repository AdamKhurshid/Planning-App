"""Django settings for the Tempo backend.

Everything environment-specific is read from environment variables or an
optional `backend/.env` file (loaded by _load_env below, no extra
dependency). See .env.example for the full list.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    """Tiny .env loader: KEY=VALUE lines, '#' comments, quotes stripped.

    Existing environment variables always win (setdefault).
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env(BASE_DIR / ".env")

def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    return os.environ.get(key, "1" if default else "0").lower() in ("1", "true", "yes", "on")


# --- Core -----------------------------------------------------------------
SECRET_KEY = env("TEMPO_SECRET_KEY", "insecure-dev-key-do-not-use-in-production")
DEBUG = env_bool("TEMPO_DEBUG", True)

if DEBUG:
    ALLOWED_HOSTS = ["*"]
else:
    ALLOWED_HOSTS = [h.strip() for h in env("TEMPO_ALLOWED_HOSTS").split(",") if h.strip()]
    if not ALLOWED_HOSTS:
        raise RuntimeError("TEMPO_ALLOWED_HOSTS must be set when TEMPO_DEBUG=0")

# --- Private single user ----------------------------------------------------
# The password lives ONLY as a Django-format hash (see manage.py hash_password).
TEMPO_USERNAME = env("TEMPO_USERNAME", "owner")
TEMPO_PASSWORD_HASH = env("TEMPO_PASSWORD_HASH")
TEMPO_TIMEZONE = env("TEMPO_TIMEZONE", "UTC")
TEMPO_CORS_ORIGINS = env("TEMPO_CORS_ORIGINS")

# --- Applications -----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "accounts",
    "planner",
    "projects",
    "scheduling",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.CORSMiddleware",
]

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ---------------------------------------------------------------
# SQLite during development; set TEMPO_DB_ENGINE=postgres (plus credentials)
# for production. No code changes needed to switch.
if env("TEMPO_DB_ENGINE") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("TEMPO_DB_NAME", "tempo"),
            "USER": env("TEMPO_DB_USER", "tempo"),
            "PASSWORD": env("TEMPO_DB_PASSWORD"),
            "HOST": env("TEMPO_DB_HOST", "localhost"),
            "PORT": env("TEMPO_DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# --- DRF --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    # Every endpoint is private by default; views must opt out explicitly.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": "10/min",
    },
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internationalization ---------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = TEMPO_TIMEZONE
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
