"""«Плагины» — серверная сборка view и действия."""

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_badge,
    heading, text, card, caption, button, make_mgmt_document,
    mgmt_header, group, mgmt_form_field,
)
from mgmt_view_builder import build_sidebar
from i18n import tr


def _pm(context):
    host = getattr(context, "host", None)
    return getattr(host, "plugin_manager", None) if host else None


def _safe(context):
    host = getattr(context, "host", None)
    return bool(getattr(host, "safe_mode", False)) if host else False


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
        extra={"role": role})


def _build(context, role, search="", status_filter="",
           message=None, error=None):
    pm = _pm(context)
    safe = _safe(context)

    children = [
        mgmt_header(
            tr("plugins.title", "Плагины"),
            [button(tr("common.refresh", "Обновить"),
                    "tap", "refresh")])
    ]
    if safe:
        children.append(mgmt_badge(
            tr("plugins.safe_banner",
               "Программа запущена в безопасном режиме, "
               "все плагины временно деактивированы."),
            accent="warning"))
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(caption(tr(
        "plugins.hint",
        "Плагины — это .py файлы в папке plugins/. "
        "Двойной клик по строке — панель плагина.")))

    filters = [
        mgmt_form_field(
            "search", kind="text",
            label=tr("common.search", "Поиск:"),
            label_position="left", stretch=True,
            value=search,
            placeholder=tr("plugins.search_placeholder",
                           "Фильтр по имени, названию, автору…"),
            on_change="input_submit"),
        mgmt_form_field(
            "status_filter", kind="select",
            label=tr("plugins.filter.status", "Статус:"),
            label_position="left",
            value=status_filter,
            options=[
                {"value": "",
                 "label": tr("common.all", "Все")},
                {"value": "active",
                 "label": tr("plugins.status.active", "активен")},
                {"value": "inactive",
                 "label": tr("plugins.status.inactive",
                             "выключен")},
            ],
            on_change="input_submit"),
    ]
    children.append(group(filters, orientation="horizontal"))

    if not pm:
        children.append(card(
            [text(tr("plugins.err.no_manager",
                     "Менеджер плагинов недоступен."))],
            accent="error"))
        return mgmt_page("plugins",
                         tr("plugins.title", "Плагины"),
                         children)

    plugins = pm.scan()
    active = set(pm.get_active())

    rows = []
    s = (search or "").lower()
    for name, entry in sorted(plugins.items()):
        info = entry.get("info") or {}
        is_active = name in active
        title = info.get("title") or ""
        author = info.get("author") or ""
        if s and s not in name.lower() \
                and s not in title.lower() \
                and s not in author.lower():
            continue
        if status_filter == "active" and not is_active:
            continue
        if status_filter == "inactive" and is_active:
            continue
        rows.append({
            "id": name,
            "name": name,
            "title": title,
            "version": info.get("version") or "",
            "author": author,
            "status": tr("plugins.status.active", "активен")
                      if is_active
                      else tr("plugins.status.inactive",
                              "выключен"),
        })

    children.append(mgmt_table(
        columns=[
            {"key": "name",
             "label": tr("plugins.col.name", "Имя")},
            {"key": "title",
             "label": tr("plugins.col.title", "Название")},
            {"key": "version",
             "label": tr("plugins.col.version", "Версия")},
            {"key": "author",
             "label": tr("plugins.col.author", "Автор")},
            {"key": "status",
             "label": tr("plugins.col.status", "Статус")},
        ],
        rows=rows,
        on_double_click={
            "action": "tap", "id": "open_panel",
            "value_field": "id"},
        row_key="id",
        empty_label="",
        searchable=False,
    ))
    return mgmt_page("plugins",
                     tr("plugins.title", "Плагины"),
                     children)


def _build_panel(context, role, name, message=None, error=None):
    pm = _pm(context)
    if not pm:
        return _build(context, role,
                      error=tr("plugins.err.no_manager",
                               "Менеджер недоступен."))
    safe = _safe(context)
    plugins = pm.scan()
    if name not in plugins:
        return _build(context, role,
                      error=tr("plugins.err.not_found",
                               "Плагин {name} не найден.",
                               name=name))

    entry = plugins[name]
    info = entry.get("info") or {}
    active = set(pm.get_active())
    is_active = name in active

    children = [
        mgmt_header(
            tr("plugins.dialog.title", "Плагин: {name}",
               name=info.get('title', name)),
            [button(tr("common.back", "← Назад"),
                    "tap", "back_to_list")]),
    ]
    if error:
        children.append(card([text(error)], accent="error"))
    if message:
        children.append(card([text(message)], accent="success"))

    info_children = []
    for label, value in [
        (tr("plugins.field.name", "Имя"), name),
        (tr("plugins.field.title", "Название"),
         info.get("title") or ""),
        (tr("plugins.field.version", "Версия"),
         info.get("version") or ""),
        (tr("plugins.field.author", "Автор"),
         info.get("author") or ""),
        (tr("plugins.field.description", "Описание"),
         info.get("description") or ""),
    ]:
        info_children.append(
            text(f"<b>{label}:</b> {value}"))
    children.append(card(
        info_children,
        title=tr("plugins.info_title", "Характеристики")))

    section_map = [
        ("creates_tables",
         tr("plugins.section.creates_tables",
            "Создаёт таблицы")),
        ("reads_tables",
         tr("plugins.section.reads_tables",
            "Читает таблицы")),
        ("writes_tables",
         tr("plugins.section.writes_tables",
            "Пишет в таблицы")),
        ("hooks",
         tr("plugins.section.hooks", "Hooks")),
        ("dependencies",
         tr("plugins.section.dependencies",
            "Зависимости")),
    ]
    for key, label in section_map:
        v = info.get(key)
        if v:
            children.append(caption(
                f"{label}: " + ", ".join(map(str, v))))

    children.append(mgmt_badge(
        tr("plugins.status.active", "активен")
        if is_active
        else tr("plugins.status.inactive", "выключен"),
        accent="success" if is_active else "info"))

    if safe:
        children.append(caption(tr(
            "plugins.safe_no_activate",
            "В безопасном режиме активация плагинов "
            "запрещена. Запустите программу без флага --safe.")))

    toggle_label = (
        tr("plugins.btn.deactivate", "Деактивировать")
        if is_active
        else tr("plugins.btn.activate", "Активировать"))
    toggle_enabled = (is_active or not safe)

    children.append(mgmt_toolbar([
        button(toggle_label, "tap", "toggle",
               value={"plugin": name},
               style="primary" if not is_active else "default",
               enabled=toggle_enabled),
    ]))
    return mgmt_page("plugins",
                     tr("plugins.panel_title", "Плагин"),
                     children)


def build_view(login, role, context):
    return _doc(_build(context, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}

    if action == "input_submit":
        return {"ok": True, "view": _doc(_build(
            context, role,
            search=str(values.get("search") or ""),
            status_filter=str(
                values.get("status_filter") or "")), role)}

    if action == "tap":
        if action_id in ("refresh", "back_to_list"):
            return {"ok": True,
                    "view": _doc(_build(context, role), role)}
        if action_id == "open_panel":
            return {"ok": True,
                    "view": _doc(_build_panel(
                        context, role, str(value or "")), role)}
        if action_id == "toggle":
            plugin = ""
            if isinstance(value, dict):
                plugin = value.get("plugin") or ""
            if not plugin:
                return {"ok": False,
                        "error": tr("plugins.err.no_plugin_name",
                                    "имя плагина отсутствует")}
            pm = _pm(context)
            if not pm:
                return {"ok": False,
                        "error": tr("plugins.err.no_manager",
                                    "менеджер недоступен")}
            try:
                is_active = plugin in pm.get_active()
                if is_active:
                    pm.deactivate(plugin)
                    msg = tr("plugins.msg.deactivated",
                             "Плагин деактивирован")
                else:
                    pm.activate(plugin)
                    msg = tr("plugins.msg.activated",
                             "Плагин активирован")
            except Exception as e:
                return {"ok": True,
                        "view": _doc(_build_panel(
                            context, role, plugin,
                            error=str(e)), role)}
            return {"ok": True, "message": msg,
                    "view": _doc(_build_panel(
                        context, role, plugin), role)}
    return {"ok": False,
            "error": tr("plugins.err.unknown_action",
                        "unknown action: {id}", id=action_id)}