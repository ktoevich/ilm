"""Anonymous, per-device identity.

The product has no sign-up flow: a browser generates a UUID once, stores it in
localStorage and sends it as ``X-Device-Id``. Each device maps to a real
``User`` row so every existing per-user filter, foreign key and admin screen
keeps working unchanged.

Trade-off, stated plainly: whoever holds the UUID holds the account. Clearing
site data or switching browsers means starting over. That is acceptable for
anonymous usage and is the reason no sensitive data should be stored here.
"""

import logging
import re

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from rest_framework import authentication, exceptions

logger = logging.getLogger(__name__)

DEVICE_HEADER = 'HTTP_X_DEVICE_ID'
USERNAME_PREFIX = 'device_'

# Canonical UUID v4, as produced by crypto.randomUUID() in the browser.
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

# Registering a brand new device is the only write an unauthenticated caller can
# trigger, so it gets its own budget per client address.
NEW_DEVICE_LIMIT_PER_HOUR = 20


class DeviceAuthentication(authentication.BaseAuthentication):
    """Resolve ``X-Device-Id`` into a User, creating one on first sight."""

    def authenticate(self, request):
        device_id = request.META.get(DEVICE_HEADER, '').strip()
        if not device_id:
            return None

        if not _UUID_RE.match(device_id):
            raise exceptions.AuthenticationFailed(
                'Некорректный идентификатор устройства (ожидается UUID)'
            )

        username = USERNAME_PREFIX + device_id.lower()

        user = User.objects.filter(username=username).first()
        if user is None:
            user = self._create_device_user(request, username)

        if not user.is_active:
            raise exceptions.AuthenticationFailed('Устройство заблокировано')

        return (user, None)

    def _create_device_user(self, request, username):
        if not self._allow_new_device(request):
            raise exceptions.AuthenticationFailed(
                'Слишком много новых устройств с этого адреса. Попробуйте позже.'
            )

        try:
            with transaction.atomic():
                user = User.objects.create_user(username=username)
                user.set_unusable_password()
                user.save(update_fields=['password'])
        except IntegrityError:
            # Two concurrent first requests from the same device.
            user = User.objects.get(username=username)
        else:
            logger.info('Registered new anonymous device %s', username)

        return user

    def _allow_new_device(self, request):
        client_ip = _client_ip(request)
        if not client_ip:
            return True

        key = f'device-registrations:{client_ip}'
        # add() only succeeds the first time, which is what starts the window.
        cache.add(key, 0, timeout=3600)
        try:
            count = cache.incr(key)
        except ValueError:  # key expired between add() and incr()
            cache.set(key, 1, timeout=3600)
            count = 1

        return count <= NEW_DEVICE_LIMIT_PER_HOUR

    def authenticate_header(self, request):
        return 'X-Device-Id'


def _client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
