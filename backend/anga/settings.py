"""
Django settings for Anga - weather for Kenya.

All environment-specific and secret configuration is read from the environment
(12-factor). Nothing sensitive is hard-coded here. See .env.example.
"""

import logging
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load backend/.env for local development. In production (Render) the platform
# injects real environment variables and this file simply will not exist.
load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger(__name__)


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        # Development-only convenience. Unreachable in production because the
        # branch below hard-fails when DEBUG is False.
        SECRET_KEY = "django-insecure-dev-only-do-not-use-in-production"
        logger.warning("DJANGO_SECRET_KEY unset - using an insecure development key.")
    else:
        raise RuntimeError(
            "DJANGO_SECRET_KEY must be set when DEBUG=False. Generate one with: "
            "python -c 'from django.core.management.utils import get_random_secret_key as g; print(g())'"
        )

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")

# Render exposes the service's public hostname here; add it automatically so a
# deploy does not 400 on a forgotten ALLOWED_HOSTS entry.
RENDER_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_HOSTNAME)

ROOT_URLCONF = "anga.urls"
WSGI_APPLICATION = "anga.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "locations",
    "weather",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    # Required for X_FRAME_OPTIONS below to actually be emitted; the setting
    # alone does nothing without this middleware.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# security.W003 warns that CsrfViewMiddleware is absent. That is deliberate and
# safe here: this service exposes only GET/OPTIONS (see CORS_ALLOW_METHODS and
# the views, which implement no unsafe methods), has no sessions, no cookies,
# no authentication and no state-changing endpoint. There is no ambient
# credential for a cross-site request to abuse, so CSRF protection would guard
# nothing. Silenced explicitly rather than left as an unexplained warning.
SILENCED_SYSTEM_CHECKS = ["security.W003"]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# ---------------------------------------------------------------------------
# Database - PostgreSQL
# ---------------------------------------------------------------------------
# PostgreSQL holds the Kenya gazetteer (counties/towns + coordinates), which is
# the persistent relational data this app genuinely needs: Weather-AI resolves
# coordinates only, so location search has to be served by us.
#
# Weather responses are NOT stored here - they belong in the cache layer below.
#
# SQLite is a zero-setup fallback so the test suite runs anywhere. Production
# requires DATABASE_URL and fails loudly without it.

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=env_int("DB_CONN_MAX_AGE", 600),
            conn_health_checks=True,
            ssl_require=not DEBUG and "localhost" not in DATABASE_URL,
        )
    }
elif DEBUG:
    logger.warning("DATABASE_URL unset - falling back to local SQLite (development only).")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    raise RuntimeError("DATABASE_URL must be set when DEBUG=False.")

# ---------------------------------------------------------------------------
# Cache - Redis
# ---------------------------------------------------------------------------
# Redis is both the weather cache and the coordination primitive for request
# coalescing: Django's cache.add() compiles to an atomic Redis `SET NX EX`,
# which is what makes single-flight correct across multiple backend instances.
#
# LocMemCache is a development fallback only. It is per-process, so coalescing
# degrades to per-worker and cached weather is lost on restart. Documented in
# the README as a known limitation of running without Redis.

REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
            "KEY_PREFIX": os.environ.get("CACHE_KEY_PREFIX", "anga"),
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }
    }
    CACHE_BACKEND_NAME = "redis"
else:
    logger.warning(
        "REDIS_URL unset - falling back to LocMemCache. Request coalescing will be "
        "per-process only and cached weather will not survive a restart."
    )
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "anga-locmem",
            "KEY_PREFIX": os.environ.get("CACHE_KEY_PREFIX", "anga"),
        }
    }
    CACHE_BACKEND_NAME = "locmem"

# ---------------------------------------------------------------------------
# Weather-AI upstream integration
# ---------------------------------------------------------------------------

WEATHER_AI_API_KEY = os.environ.get("WEATHER_AI_API_KEY", "")
WEATHER_AI_BASE_URL = os.environ.get("WEATHER_AI_BASE_URL", "https://api.weather-ai.co")

# Pointing the base URL at a local mock is easy to do and very easy to forget:
# the app keeps serving plausible weather while the real provider records no
# usage at all. Say so loudly at startup rather than letting it look like the
# live integration is working.
if any(host in WEATHER_AI_BASE_URL for host in ("localhost", "127.0.0.1", "0.0.0.0")):
    logger.warning(
        "WEATHER_AI_BASE_URL points at %s - responses are coming from a LOCAL MOCK, "
        "not weather-ai.co. Your real API usage will stay at zero. Set "
        "WEATHER_AI_BASE_URL=https://api.weather-ai.co to use the live API.",
        WEATHER_AI_BASE_URL,
    )

if not WEATHER_AI_API_KEY:
    logger.warning(
        "WEATHER_AI_API_KEY is empty - every weather request will fail with a "
        "configuration error until a wai_ key is set in the environment."
    )
elif not WEATHER_AI_API_KEY.startswith("wai_"):
    # Never log the key itself - only the fact that its shape looks wrong.
    logger.warning(
        "WEATHER_AI_API_KEY does not start with 'wai_'. Weather-AI keys carry "
        "that prefix, so this key will most likely be rejected with a 401."
    )

# Seconds a cached response is considered FRESH and served as-is.
# 30 min: Weather-AI's free tier allows 1,000 requests per MONTH (~33/day across
# every location combined), so shorter TTLs are arithmetically impossible.
WEATHER_CACHE_TTL = env_int("WEATHER_CACHE_TTL", 1800)

# Seconds a cached response is RETAINED past its fresh TTL for use as a fallback
# when upstream fails. Long (6h) because Weather-AI's 429 is a monthly quota
# lockout that clears at X-RateLimit-Reset - potentially days away, not seconds.
WEATHER_STALE_TTL = env_int("WEATHER_STALE_TTL", 21600)

# Upstream HTTP timeouts in seconds. Kept tight so a hanging upstream degrades
# to stale cache quickly instead of holding a worker open.
WEATHER_CONNECT_TIMEOUT = env_int("WEATHER_CONNECT_TIMEOUT", 5)
WEATHER_READ_TIMEOUT = env_int("WEATHER_READ_TIMEOUT", 10)

# Request coalescing: how long the single-flight lock is held, and how long a
# follower waits for the leader's result before falling back to stale/error.
WEATHER_LOCK_TTL = env_int("WEATHER_LOCK_TTL", 15)
WEATHER_COALESCE_WAIT = env_int("WEATHER_COALESCE_WAIT", 12)

# Stop calling upstream once fewer than this many monthly requests remain, so
# ordinary traffic can never fully drain the quota.
WEATHER_QUOTA_RESERVE = env_int("WEATHER_QUOTA_RESERVE", 25)

# After a 5xx / timeout / connection failure, stop calling upstream for this
# many seconds. Short, because these failures are usually transient - unlike a
# 429, which is a monthly lockout and backs off until X-RateLimit-Reset.
WEATHER_FAILURE_BACKOFF = env_int("WEATHER_FAILURE_BACKOFF", 60)

# Upper bound on how long the circuit breaker may stay open, so a malformed or
# absurd X-RateLimit-Reset header cannot wedge the service indefinitely.
WEATHER_MAX_BREAKER_SECONDS = env_int("WEATHER_MAX_BREAKER_SECONDS", 86400)

# Fallback backoff when a 429 arrives without a usable X-RateLimit-Reset.
WEATHER_DEFAULT_429_BACKOFF = env_int("WEATHER_DEFAULT_429_BACKOFF", 900)

# Forecast days to request. The forecast arrives in the same response as
# current conditions, so 7 costs exactly the same single request as 1.
# Free plan allows 1-7; Pro 14; Scale 16.
WEATHER_FORECAST_DAYS = env_int("WEATHER_FORECAST_DAYS", 7)

# Weather-AI defaults to ai=true, which spends the much smaller AI quota
# (200/month on free). Verified against the live API: ai_summary returns null
# on a free-plan key even with ai=true, so we do not spend that quota by
# default. Set WEATHER_INCLUDE_AI=True if your plan returns summaries.
WEATHER_INCLUDE_AI = env_bool("WEATHER_INCLUDE_AI", False)

# Language for the AI summary only ('en', 'sw'). Has no effect on the numeric
# forecast, which carries no prose.
WEATHER_LANG = os.environ.get("WEATHER_LANG", "en")

# How long the upstream quota reading from GET /v1/usage is cached.
# The documented X-RateLimit-* response headers do NOT exist on the live API
# (verified across every header of several real responses), so /v1/usage is the
# only way to observe quota - and it costs a request itself. Polling it rarely
# is the point.
WEATHER_USAGE_TTL = env_int("WEATHER_USAGE_TTL", 86400)

# How long one worker's claim on the usage sync is held. This is what stops
# every worker/instance spending a request on /v1/usage at once, and it also
# bounds retries: a sync that fails is not attempted again until the claim
# expires. Default 1h, so a persistently failing sync costs at most ~24
# requests a day rather than one per cache miss.
WEATHER_USAGE_LOCK_TTL = env_int("WEATHER_USAGE_LOCK_TTL", 3600)

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
# Throttling protects OUR backend from abuse, which indirectly protects the
# Weather-AI quota: forcing misses on uncached locations is the only way a
# client can generate upstream traffic. Limits sit well above normal use.

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": (
        [
            "rest_framework.renderers.JSONRenderer",
            "rest_framework.renderers.BrowsableAPIRenderer",
        ]
        if DEBUG
        else ["rest_framework.renderers.JSONRenderer"]
    ),
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "weather": os.environ.get("THROTTLE_WEATHER", "60/min"),
        "locations": os.environ.get("THROTTLE_LOCATIONS", "120/min"),
        "meta": os.environ.get("THROTTLE_META", "30/min"),
    },
    "EXCEPTION_HANDLER": "weather.exceptions.api_exception_handler",
    # This API has no auth surface, so django.contrib.auth is not installed.
    # DRF's default UNAUTHENTICATED_USER (AnonymousUser) would import it, so we
    # disable the concept of a request user entirely.
    "UNAUTHENTICATED_USER": None,
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Explicit allow-list only. CORS_ALLOW_ALL_ORIGINS is never enabled.

CORS_ALLOWED_ORIGINS = env_list(
    "FRONTEND_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173" if DEBUG else "",
)
CORS_ALLOW_CREDENTIALS = False
CORS_ALLOW_METHODS = ["GET", "OPTIONS"]

# Allow Vercel preview deployments (https://<project>-<hash>.vercel.app) when a
# project slug is configured, without opening CORS to the world.
VERCEL_PROJECT_SLUG = os.environ.get("VERCEL_PROJECT_SLUG", "")
if VERCEL_PROJECT_SLUG:
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^https://" + VERCEL_PROJECT_SLUG + r"-[\w-]+\.vercel\.app$"
    ]

CSRF_TRUSTED_ORIGINS = [o for o in CORS_ALLOWED_ORIGINS if o.startswith("https://")]

# ---------------------------------------------------------------------------
# Production hardening
# ---------------------------------------------------------------------------

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", True)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# Static files / i18n
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = False
USE_TZ = True

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Structured, greppable events for the cache/upstream lifecycle. The API key is
# never logged - weather.client logs only the URL path and status code.

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"}
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {
        "weather": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "locations": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
