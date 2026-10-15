import os

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "Set DJANGO_SECRET_KEY before starting outside debug mode."
        )
    SECRET_KEY = "unsafe-local-development-only"
if not DEBUG and SECRET_KEY in {
    "unsafe-local-development-only",
    "replace-with-a-generated-secret",
}:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a unique production secret.")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS", ".onrender.com,localhost,127.0.0.1,*"
    ).split(",")
    if host.strip()
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
INSTALLED_APPS = [
    "django.contrib.staticfiles",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
]

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
os.makedirs(STATIC_ROOT, exist_ok=True)
FRONTEND_DIST = os.path.abspath(os.path.join(BASE_DIR, "../dist/public"))
if os.path.exists(FRONTEND_DIST):
    WHITENOISE_ROOT = FRONTEND_DIST
    WHITENOISE_INDEX_FILE = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "weather-routing-cache",
        "TIMEOUT": 600,
    }
}

ROUTING_BASE_URL = os.environ.get(
    "ROUTING_BASE_URL", "https://router.project-osrm.org"
).rstrip("/")
GEOCODING_BASE_URL = os.environ.get(
    "GEOCODING_BASE_URL", "https://nominatim.openstreetmap.org"
).rstrip("/")
WEATHER_BASE_URL = os.environ.get(
    "WEATHER_BASE_URL", "https://api.open-meteo.com/v1/forecast"
)
EXTERNAL_API_TIMEOUT_SECONDS = float(
    os.environ.get("EXTERNAL_API_TIMEOUT_SECONDS", "18")
)
