"""Django settings for the Favorable Soil backend.

Configuration is driven entirely by environment variables. In production
(``DJANGO_DEBUG=False``) the settings refuse to start unless the security
critical values are supplied explicitly -- see ``.env.example``.
"""

import os
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Load a local .env for development convenience. Never required at runtime:
# on a real deployment the variables come from the platform.
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / '.env')
except ImportError:  # pragma: no cover - dotenv is a dev-only convenience
    pass


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('true', '1', 't', 'yes', 'on')


def env_list(name, default=()):
    raw = os.environ.get(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(',') if item.strip()]


# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------
DEBUG = env_bool('DJANGO_DEBUG', False)

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            'DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is False. '
            'Generate one with: python -c "from django.core.management.utils '
            'import get_random_secret_key; print(get_random_secret_key())"'
        )
    # Development only. Never reached in production because of the check above.
    SECRET_KEY = 'django-insecure-development-only-do-not-deploy-with-this-key'

ALLOWED_HOSTS = env_list('DJANGO_ALLOWED_HOSTS')
if not ALLOWED_HOSTS:
    if DEBUG:
        ALLOWED_HOSTS = ['localhost', '127.0.0.1', '[::1]', 'testserver']
    else:
        raise ImproperlyConfigured(
            'DJANGO_ALLOWED_HOSTS must list the hostnames this site is served '
            'from, e.g. "example.com,www.example.com".'
        )

CSRF_TRUSTED_ORIGINS = env_list('DJANGO_CSRF_TRUSTED_ORIGINS')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework.authtoken',
    'corsheaders',
    'api',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

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

# --------------------------------------------------------------------------
# CORS
# --------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list('DJANGO_CORS_ALLOWED_ORIGINS')
if DEBUG and not CORS_ALLOWED_ORIGINS:
    # Vite dev server / file:// previews.
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    if not CORS_ALLOWED_ORIGINS:
        # Same-origin deployment (frontend served from the same host).
        CORS_ALLOWED_ORIGINS = []

# The frontend identifies an anonymous device with this header.
CORS_ALLOW_HEADERS = (
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-device-id',
)

# --------------------------------------------------------------------------
# REST framework
# --------------------------------------------------------------------------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'api.authentication.DeviceAuthentication',
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        # Satellite tile downloads + CV/ML work. Deliberately tight.
        'analysis': os.environ.get('THROTTLE_ANALYSIS', '30/hour'),
        # Ordinary CRUD on the user's own records.
        'crud': os.environ.get('THROTTLE_CRUD', '600/hour'),
    },
}

# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------
db_url = os.environ.get('DATABASE_URL')
if db_url:
    DATABASES = {
        'default': dj_database_url.parse(db_url, conn_max_age=600, ssl_require=not DEBUG)
    }
else:
    if not DEBUG:
        raise ImproperlyConfigured(
            'DATABASE_URL must be set in production. SQLite on an ephemeral '
            'filesystem loses every write between requests.'
        )
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# --------------------------------------------------------------------------
# Caching -- used for satellite tiles and SoilGrids lookups
# --------------------------------------------------------------------------
redis_url = os.environ.get('REDIS_URL')
if redis_url:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': redis_url,
            'TIMEOUT': 60 * 60 * 24,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'favorable-soil',
            'TIMEOUT': 60 * 60 * 6,
            'OPTIONS': {'MAX_ENTRIES': 2000},
        }
    }

# --------------------------------------------------------------------------
# External services
# --------------------------------------------------------------------------
# Nominatim's usage policy requires a contact address in the User-Agent.
GEOCODER_CONTACT = os.environ.get('GEOCODER_CONTACT', '')
TILE_SERVER_URL = os.environ.get(
    'TILE_SERVER_URL',
    'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
)
# Hard ceiling on how many 256px tiles a single analysis may download.
MAX_TILES_PER_REQUEST = int(os.environ.get('MAX_TILES_PER_REQUEST', '64'))
HTTP_TIMEOUT_SECONDS = float(os.environ.get('HTTP_TIMEOUT_SECONDS', '8'))

SOIL_MODEL_PATH = os.environ.get(
    'SOIL_MODEL_PATH', str(REPO_ROOT / 'ai model' / 'soil_model.pth')
)

# --------------------------------------------------------------------------
# Security (production only -- these break plain-HTTP local development)
# --------------------------------------------------------------------------
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SECURE_SSL_REDIRECT = env_bool('DJANGO_SECURE_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = int(os.environ.get('DJANGO_HSTS_SECONDS', '31536000'))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
LOG_LEVEL = os.environ.get('DJANGO_LOG_LEVEL', 'DEBUG' if DEBUG else 'INFO')

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
        'django.db.backends': {
            'handlers': ['console'],
            # Query logging is extremely noisy; opt in explicitly.
            'level': os.environ.get('DJANGO_SQL_LOG_LEVEL', 'WARNING'),
            'propagate': False,
        },
        'api': {
            'handlers': ['console'],
            'level': LOG_LEVEL,
            'propagate': False,
        },
    },
}

# --------------------------------------------------------------------------
# I18N / static
# --------------------------------------------------------------------------
LANGUAGE_CODE = 'ru'
TIME_ZONE = os.environ.get('DJANGO_TIME_ZONE', 'UTC')
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
