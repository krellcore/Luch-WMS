"""Реестр пунктов меню для тонких клиентов (ТСД).

Пункт = id + title + builder (функция рендера view-документа).
Список уходит клиенту через /ui_config (config.menu.items).
По клику клиент шлёт POST /menu/{id}/view, получает view-документ,
который рендерит стандартным ViewRenderer.

Встроенные: about, help.
Плагины регистрируют свои через context.register_menu_item().

ВАЖНО: builder'ы НЕ должны возвращать ViewNode.heading с тем же
текстом, что и title пункта меню. Клиент сам рендерит заголовок
из config.menu.items[].title. Иначе заголовок дублируется.

Версия приложения в About — APP_VERSION (1.1.0).
"""

import traceback

from i18n import tr
from view_protocol import make_document, ViewNode


APP_VERSION = "1.1.0"

_ITEMS = {}          # id -> dict
_ORDER_COUNTER = [0]


def _next_order():
    _ORDER_COUNTER[0] += 1
    return _ORDER_COUNTER[0]


def register(item_id, title=None, builder=None, roles=None,
             plugin_name="", title_key=None):
    if not item_id:
        return
    _ITEMS[item_id] = {
        "id": item_id,
        "title": title or item_id,
        "title_key": title_key,
        "builder": builder,
        "roles": tuple(roles) if roles else None,
        "plugin_name": plugin_name or "",
        "order": _next_order(),
    }


def unregister(item_id):
    _ITEMS.pop(item_id, None)


def unregister_plugin(plugin_name):
    if not plugin_name:
        return
    for k in [k for k, v in _ITEMS.items()
              if v.get("plugin_name") == plugin_name]:
        _ITEMS.pop(k, None)


def has(item_id):
    return item_id in _ITEMS


def get(item_id):
    return _ITEMS.get(item_id)


def list_items():
    """Полный список пунктов для /ui_config.

    Отдаём всё; фильтрацию по ролям выполняет клиент (для UI) и
    сервер при /menu/{id}/view (для безопасности).
    """
    out = []
    for item in sorted(_ITEMS.values(), key=lambda v: v["order"]):
        title = item["title"]
        if item.get("title_key"):
            title = tr(item["title_key"], title)
        rl = item.get("roles")
        out.append({
            "id": item["id"],
            "title": title,
            "kind": "view",
            "roles": list(rl) if rl else [],
        })
    return out


def _role_allowed(allowed, user_roles):
    if not allowed:
        return True
    if "any" in allowed:
        return True
    if isinstance(user_roles, (list, tuple)):
        return any(r in allowed for r in user_roles)
    return user_roles in allowed


def build_view(item_id, login, user_roles, context):
    item = _ITEMS.get(item_id)
    if not item:
        return None
    if not _role_allowed(item.get("roles"), user_roles):
        return None
    builder = item.get("builder")
    if not builder:
        return make_document([], screen_id=f"menu_{item_id}")
    try:
        return builder(login=login, user_roles=user_roles,
                       context=context)
    except Exception:
        traceback.print_exc()
        return make_document([
            ViewNode.text(
                tr("client.menu_build_error",
                   "Не удалось построить страницу")),
        ], screen_id=f"menu_{item_id}_error")


# ================================================================
# Встроенные пункты
#
# Заголовок рендерится клиентом из config.menu.items[].title —
# в самом view-документе heading не нужен (иначе дублирование).
# ================================================================

def _build_about(login, user_roles, context):
    parts = [
        ViewNode.text(tr("client.about_text",
                         "Луч — WMS для адресного хранения.")),
        ViewNode.caption(f"Version {APP_VERSION}"),
        ViewNode.spacer(8),
        ViewNode.caption(tr("client.about_user",
                            "Пользователь: {login}",
                            login=login or "—")),
    ]
    return make_document(parts, screen_id="menu_about")


def _build_help(login, user_roles, context):
    parts = [
        ViewNode.text(tr("client.help_text",
                         "Обратитесь к руководителю склада.")),
    ]
    return make_document(parts, screen_id="menu_help")


register("about",
         title="О программе",
         title_key="client.about_title",
         builder=_build_about,
         roles=("any",))
register("help",
         title="Помощь",
         title_key="client.help_title",
         builder=_build_help,
         roles=("any",))