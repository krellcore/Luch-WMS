"""Реестр сессий.

Сессия — долгоживущий процесс (например, приёмка на ПК), который
может брать несколько заданий. Встроенная — receive.
Плагины регистрируют свои через context.register_session(...).
"""

from .base import SessionHandler

_HANDLERS = {}


def register(session_cls):
    instance = session_cls()
    _HANDLERS[instance.key] = instance
    return session_cls


def register_instance(handler):
    _HANDLERS[handler.key] = handler
    return handler


def unregister(key):
    _HANDLERS.pop(key, None)


def get_handler(key):
    return _HANDLERS.get(key)


def list_handlers():
    return list(_HANDLERS.values())


def list_sessions():
    return {k: v.title for k, v in _HANDLERS.items()}


# Автоматическая регистрация встроенной приёмки
from . import receive  # noqa: E402,F401