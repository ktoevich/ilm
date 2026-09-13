"""Shared HTTP session for outbound service calls."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def build_session(user_agent):
    session = requests.Session()
    session.headers.update({'User-Agent': user_agent, 'Accept': 'application/json'})
    return session


def get_json(session, url, params=None, timeout=None, service='upstream'):
    """GET and decode JSON, returning ``None`` on any failure.

    Every failure is logged with its cause -- silently swallowing the exception
    is what made the previous version impossible to debug in production.
    """
    timeout = timeout or settings.HTTP_TIMEOUT_SECONDS
    try:
        response = session.get(url, params=params, timeout=timeout)
    except requests.Timeout:
        logger.warning('%s timed out after %.1fs (%s)', service, timeout, url)
        return None
    except requests.RequestException as exc:
        logger.warning('%s request failed: %s', service, exc)
        return None

    if response.status_code != 200:
        logger.warning('%s returned HTTP %s for %s', service, response.status_code, url)
        return None

    try:
        return response.json()
    except ValueError:
        logger.warning('%s returned a non-JSON body', service)
        return None
