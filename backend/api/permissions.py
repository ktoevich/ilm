"""Object level permissions."""

from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """Allow access only to the user that owns the object.

    Records created before device identity existed have ``user = NULL``; those
    are treated as nobody's and stay invisible through the API.
    """

    message = 'Этот объект принадлежит другому пользователю.'

    def has_object_permission(self, request, view, obj):
        owner = getattr(obj, 'user', None)
        return owner is not None and owner == request.user


class IsOwnerOfField(permissions.BasePermission):
    """Same check, for objects that reach their owner through ``field``."""

    message = 'Этот участок принадлежит другому пользователю.'

    def has_object_permission(self, request, view, obj):
        field = getattr(obj, 'field', None)
        owner = getattr(field, 'user', None)
        return owner is not None and owner == request.user
