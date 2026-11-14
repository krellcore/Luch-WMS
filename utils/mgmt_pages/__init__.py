"""Реестр серверных builder'ов mgmt-страниц."""

_BUILDERS = {}
_HANDLERS = {}


def register(key, builder, handler=None):
    _BUILDERS[key] = builder
    if handler is not None:
        _HANDLERS[key] = handler


def get_builder(key):
    return _BUILDERS.get(key)


def get_handler(key):
    return _HANDLERS.get(key)


def has(key):
    return key in _BUILDERS


def list_keys():
    return list(_BUILDERS.keys())


# ---------- Регистрация встроенных ----------

from . import about              # noqa: E402,F401
from . import settings           # noqa: E402,F401
from . import plugins_page       # noqa: E402,F401
from . import employees          # noqa: E402,F401
from . import notifications      # noqa: E402,F401
from . import drop_points        # noqa: E402,F401
from . import items              # noqa: E402,F401
from . import containers         # noqa: E402,F401
from . import managers           # noqa: E402,F401
from . import tasks              # noqa: E402,F401
from . import viewer             # noqa: E402,F401

register("about", about.build_view, about.handle_action)
register("settings", settings.build_view, settings.handle_action)
register("plugins", plugins_page.build_view, plugins_page.handle_action)
register("employees", employees.build_view, employees.handle_action)
register("notifications",
         notifications.build_view, notifications.handle_action)
register("drop_points",
         drop_points.build_view, drop_points.handle_action)
register("items", items.build_view, items.handle_action)
register("containers",
         containers.build_view, containers.handle_action)
register("managers", managers.build_view, managers.handle_action)
register("tasks", tasks.build_view, tasks.handle_action)
register("viewer", viewer.build_view, viewer.handle_action)