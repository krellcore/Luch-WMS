"""Сборка mgmt-документов. Тонкий слой над mgmt_protocol."""

from mgmt_protocol import (
    mgmt_page, mgmt_sidebar, mgmt_toolbar, mgmt_badge,
    text, heading, caption, card, spacer,
    make_mgmt_document,
)


# Список разделов для сайдбара. roles=None — доступно всем.
# Позже, если понадобится, этот список будет обогащаться
# плагинами (register_mgmt_page).
MGMT_PAGES = [
    {"key": "viewer",        "title": "Просмотр склада",
     "roles": None},
    {"key": "tasks",         "title": "Задания",
     "roles": None},
    {"key": "items",         "title": "Артикулы",
     "roles": None},
    {"key": "containers",    "title": "Тары",
     "roles": None},
    {"key": "drop_points",   "title": "Точки сброса",
     "roles": None},
    {"key": "notifications", "title": "Уведомления",
     "roles": None},
    {"key": "settings",      "title": "Настройки",
     "roles": ("owner", "admin")},
    {"key": "employees",     "title": "Сотрудники",
     "roles": ("owner", "admin")},
    {"key": "managers",      "title": "Руководители",
     "roles": ("owner",)},
    {"key": "plugins",       "title": "Плагины",
     "roles": ("owner", "admin")},
    {"key": "about",         "title": "О программе",
     "roles": None},
]


def _page_role_ok(page, role):
    roles = page.get("roles")
    if roles is None:
        return True
    return role in roles


def pages_for_role(role, extra_pages=None):
    """Список пунктов сайдбара для роли.

    extra_pages — dict {full_key: {"title": ..., "roles": ...}}
    от плагинов (register_mgmt_page). full_key имеет вид
    plugin:<name>:<key>.
    """
    items = []
    all_pages = list(MGMT_PAGES)
    if extra_pages:
        for k, meta in extra_pages.items():
            all_pages.append({
                "key": k,
                "title": meta.get("title", k),
                "roles": meta.get("roles"),
            })
    for p in all_pages:
        if not _page_role_ok(p, role):
            continue
        items.append({"key": p["key"], "title": p["title"]})
    return items


def build_sidebar(role, extra_pages=None):
    return mgmt_sidebar(pages_for_role(role,
                                        extra_pages=extra_pages))


def placeholder_view(page_key, role, notice=None,
                     extra_pages=None):
    """Пустая заглушка для немигрированного раздела.

    В Фазе 7 каждый раздел заменится на реальный builder.
    """
    if notice is None:
        notice = (
            "Раздел «{key}» будет доступен в mgmt-режиме "
            "после миграции. Сейчас используйте legacy-раздел "
            "в локальном клиенте."
        ).format(key=page_key)
    children = [
        heading(_title_for(page_key)),
        card([
            text(notice),
            spacer(8),
            caption("Раздел пока не мигрирован на mgmt-протокол."),
        ], accent="warning"),
    ]
    page = mgmt_page(page_key, _title_for(page_key), children)
    return make_mgmt_document(
        page,
        sidebar=build_sidebar(role, extra_pages=extra_pages),
        extra={"role": role, "placeholder": True},
    )


def _title_for(key):
    for p in MGMT_PAGES:
        if p["key"] == key:
            return p["title"]
    return key


def build_error_document(page_key, role, error_text,
                         extra_pages=None):
    children = [
        heading(_title_for(page_key)),
        card([text(error_text)], accent="error"),
    ]
    page = mgmt_page(page_key, _title_for(page_key), children)
    return make_mgmt_document(
        page,
        sidebar=build_sidebar(role, extra_pages=extra_pages),
        extra={"role": role, "error": error_text},
    )