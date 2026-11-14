"""Реестр обработчиков типов заданий.

Каждый тип задания — это класс-наследник TaskHandler.
Регистрация встроенных типов — в конце файла (после импорта
модулей). Плагины регистрируют свои через
context.register_task_handler(handler_instance) — см.
utils/api_public.py.
"""

from .base import TaskHandler

_HANDLERS = {}


def register(handler_cls):
    """Зарегистрировать класс handler'а. Возвращает класс
    (для использования как декоратор)."""
    instance = handler_cls()
    _HANDLERS[instance.task_type] = instance
    return handler_cls


def register_instance(handler):
    """Зарегистрировать готовый экземпляр (для плагинов)."""
    _HANDLERS[handler.task_type] = handler
    return handler


def unregister(task_type):
    _HANDLERS.pop(task_type, None)


def get_handler(task_type):
    return _HANDLERS.get(task_type)


def has_handler(task_type):
    return task_type in _HANDLERS


def list_task_types():
    """dict: task_type -> title."""
    return {k: v.title for k, v in _HANDLERS.items()}


def list_handlers():
    return list(_HANDLERS.values())


# Импорт встроенных модулей (определяет классы PickHandler и т.д.)
from . import pick, receive, putaway, inventory  # noqa: E402,F401

# Регистрация встроенных handlers.
# ВАЖНО: без этих вызовов _HANDLERS останется пустым,
# и get_handler("pick")/("receive")/... вернёт None.
register(pick.PickHandler)
register(receive.ReceiveHandler)
register(putaway.PutawayHandler)
register(inventory.InventoryHandler)