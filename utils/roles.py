"""Реестр ролей сотрудников.

Встроенные: picker, receiver, putaway, inventory.
Плагины добавляют свои через context.register_role(...).

Роль = key + title (для UI) + task_types (для /tasks/next).
"""

_ROLES = {}
_COUNTER = [0]


def _next_order():
    _COUNTER[0] += 1
    return 100 + _COUNTER[0]


def register(key, title_key=None, title=None, task_types=(),
             order=None, plugin_name=""):
    if not key:
        return
    _ROLES[key] = {
        "key": key,
        "title_key": title_key,
        "title": title or key,
        "task_types": tuple(task_types or ()),
        "order": order if order is not None else _next_order(),
        "plugin_name": plugin_name or "",
    }


def unregister(key):
    _ROLES.pop(key, None)


def unregister_plugin(plugin_name):
    if not plugin_name:
        return
    for k in [k for k, v in _ROLES.items()
              if v.get("plugin_name") == plugin_name]:
        _ROLES.pop(k, None)


def get(key):
    return _ROLES.get(key)


def list_roles():
    return sorted(_ROLES.values(),
                  key=lambda v: (v["order"], v["key"]))


def task_types_for_roles(roles):
    out = []
    for r in roles or []:
        info = _ROLES.get(r)
        if not info:
            continue
        for t in info["task_types"]:
            if t not in out:
                out.append(t)
    return out


# ---------- Встроенные роли ----------

register("picker",
         title_key="employees.role.picker",
         title="Подбор",
         task_types=("pick",),
         order=10)
register("receiver",
         title_key="employees.role.receiver",
         title="Приёмка",
         task_types=(),
         order=20)
register("putaway",
         title_key="employees.role.putaway",
         title="Размещение",
         task_types=("putaway",),
         order=30)
register("inventory",
         title_key="employees.role.inventory",
         title="Инвентаризация",
         task_types=("inventory",),
         order=40)