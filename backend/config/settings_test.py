"""Settings used by ``manage.py test``.

The default settings read ``DATABASE_URL`` from ``.env``, which points at the
hosted Postgres. Running the suite against it made every test a network round
trip -- roughly three seconds each -- and would have created a throwaway
database on the production server. Tests run against in-memory SQLite instead.
"""

import os

# ``settings.py`` refuses to import in production mode without a secret key and
# a database URL. In CI there is no ``.env``, so without these defaults the
# import below raised ImproperlyConfigured before this module could override
# anything. Existing environment values still win.
os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-secret-key')

from .settings import *  # noqa: E402,F401,F403

DEBUG = False
SECRET_KEY = 'test-only-secret-key'
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'test',
    }
}

# Throttling is switched off by default: with it on, every test would share one
# rate-limit bucket and start failing depending on execution order. The
# throttle itself is exercised in ThrottlingTests via override_settings.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,  # noqa: F405
    'DEFAULT_THROTTLE_RATES': {'analysis': None, 'crud': None},
}

# Hashing passwords is pure overhead here.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Whitenoise warns about the missing STATIC_ROOT; tests never serve static files.
WHITENOISE_AUTOREFRESH = True

STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}

# HTTPS redirects turn every test request into a 301.
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0

LOGGING['loggers']['api']['level'] = 'ERROR'      # noqa: F405
LOGGING['loggers']['django']['level'] = 'ERROR'   # noqa: F405
