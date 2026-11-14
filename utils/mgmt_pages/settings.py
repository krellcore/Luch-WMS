"""«Настройки склада» — серверная сборка view и handler действий."""

import sqlite3

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_form_field, mgmt_dialog,
    heading, text, card, caption, spacer, button, group,
    make_mgmt_document, mgmt_header, mgmt_badge,
)
from mgmt_view_builder import build_sidebar
from i18n import (
    tr, current_locale, save_locale_for_manager, set_locale,
    available_locales, locale_display_name, locale_info,
    reload_locales,
)


_UI_DEFAULTS = {
    "ui_shelves_count": 1,
    "ui_floor_from": 1,
    "ui_floor_to": 1,
    "ui_row_from": 1,
    "ui_row_to": 1,
    "ui_sec_from": 1,
    "ui_sec_to": 1,
}


def _format_block_name(name):
    if not name:
        return ""
    s = str(name).strip()
    if s and s[0] in ("B", "b", "Б", "б"):
        s = s[1:]
    s = s.lstrip("0")
    if not s:
        return "0"
    try:
        return str(int(s))
    except ValueError:
        return str(name).strip()


def _read_settings(conn):
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        return {r[0]: r[1] for r in cur.fetchall()}
    except Exception:
        return {}


def _save_setting(conn, key, value):
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM settings WHERE key=?", (key,))
        if cur.fetchone():
            cur.execute("UPDATE settings SET value=? WHERE key=?",
                        (str(value), key))
        else:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)))
        conn.commit()
    except Exception as e:
        print(f"[settings] save {key}: {e}")


def _ui_settings(conn):
    raw = _read_settings(conn)
    out = dict(_UI_DEFAULTS)
    for k, default in _UI_DEFAULTS.items():
        if k in raw:
            try:
                out[k] = int(raw[k])
            except (ValueError, TypeError):
                out[k] = default
    return out


def _free_block_numbers(conn):
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM blocks")
        existing = {_format_block_name(r[0]) for r in cur.fetchall()}
    except Exception:
        existing = set()
    return [str(i) for i in range(1, 10) if str(i) not in existing]


def _blocks_for_combo(conn):
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM blocks ORDER BY name")
        return [(bid, _format_block_name(name))
                for bid, name in cur.fetchall()]
    except Exception:
        return []


def _alert_dialog(title, msg, dialog_id="alert"):
    return mgmt_dialog(
        dialog_id, title,
        [text(msg)],
        buttons=[button(tr("settings.btn.ok", "ОК"),
                        "tap", "close_dialog", style="primary")]
    )


def _language_options():
    """Опции для селекта языка.

    Формат label:
      "Русский (ru, 340/340)"
      "Deutsch (de, 312/340, fallback: ru)"
      "العربية (ar, 340/340, RTL)"
    """
    opts = []
    for code in available_locales():
        info = locale_info(code)
        total = info["total"] or info["translated"] or 0
        bits = [f"{code}, {info['translated']}/{total}"]
        if info["fallback"]:
            bits.append(tr("settings.language_fallback_short",
                           "fallback: {code}",
                           code=info["fallback"]))
        if info["rtl"]:
            bits.append("RTL")
        label = f"{info['name']} ({', '.join(bits)})"
        opts.append({"value": code, "label": label})
    return opts


def _language_info_card():
    """Карточка характеристик выбранного языка."""
    code = current_locale()
    info = locale_info(code)
    total = info["total"] or info["translated"] or 0
    complete = info["complete"]

    badge_accent = "success" if complete else "warning"
    badge_label = (
        tr("settings.language_complete", "полный")
        if complete
        else tr("settings.language_incomplete_short", "неполный")
    )

    children = [
        group([
            text(tr("settings.language_coverage",
                    "{done}/{total} ключей",
                    done=info["translated"], total=total)),
            mgmt_badge(badge_label, accent=badge_accent),
        ], orientation="horizontal", spacing=8),
    ]
    if info["fallback"]:
        children.append(caption(tr(
            "settings.language_fallback",
            "Fallback: {code}", code=info["fallback"])))
    if info["rtl"]:
        children.append(caption(tr(
            "settings.language_rtl",
            "Направление текста: RTL (справа налево)")))
    if not complete and info["missing"]:
        preview = ", ".join(info["missing"][:6])
        if len(info["missing"]) > 6:
            preview += " …"
        children.append(caption(tr(
            "settings.language_missing_preview",
            "Нет ключей: {list}", list=preview)))
    return card(children,
                title=tr("settings.language_details",
                         "Характеристики языка"))


def _build(db_path, role, *, dialog=None, alert_dialog=None,
           ui_overrides=None):
    conn = sqlite3.connect(db_path)
    try:
        ui = _ui_settings(conn)
        if ui_overrides:
            ui.update(ui_overrides)
        blocks = _blocks_for_combo(conn)
        free_numbers = _free_block_numbers(conn)
    finally:
        conn.close()

    children = [mgmt_header(tr("settings.title",
                               "Настройки склада"))]

    # --- Язык интерфейса ---
    children.append(card([
        group([
            mgmt_form_field(
                "locale", kind="select",
                label=tr("settings.language_label", "Язык"),
                label_position="left",
                width=420,
                value=current_locale(),
                options=_language_options(),
                on_change="input_submit",
            ),
            button(tr("settings.btn.reload_locales",
                      "Перечитать lang/"),
                   "tap", "reload_locales"),
        ], orientation="horizontal", spacing=8),
    ], title=tr("settings.language_title",
                "Язык интерфейса")))

    children.append(_language_info_card())

    # --- Блоки склада ---
    blocks_options = [
        {"value": bid, "label": name} for bid, name in blocks
    ]
    if blocks_options:
        blocks_field = mgmt_form_field(
            "block_id", kind="select",
            label="",
            width=250,
            value=blocks[0][0], options=blocks_options)
    else:
        blocks_field = caption(tr("settings.err.no_block",
                                  "Блоков ещё нет."))

    block_children = [
        blocks_field,
        mgmt_toolbar([
            button(tr("settings.add_block", "Создать блок"),
                   "tap", "add_block_open", style="primary",
                   enabled=bool(free_numbers)),
            button(tr("settings.del_block", "Удалить блок"),
                   "tap", "delete_block",
                   enabled=bool(blocks_options)),
        ]),
    ]
    if not free_numbers:
        block_children.append(caption(
            tr("settings.blocks.all_created",
               "Все блоки (1-9) уже созданы")))
    children.append(card(block_children,
                         title=tr("settings.blocks",
                                  "Блоки склада")))

    # --- Диапазон ячеек ---
    range_children = [
        caption(tr("settings.range.hint",
                   "Параметры создаваемого диапазона:")),
        group([
            text(tr("settings.label.floor_range",
                    "Этажи (от—до):")),
            mgmt_form_field("floor_from", kind="number",
                            value=ui["ui_floor_from"],
                            min_value=1, max_value=9, width=60),
            text(tr("settings.label.dash", "—")),
            mgmt_form_field("floor_to", kind="number",
                            value=ui["ui_floor_to"],
                            min_value=1, max_value=9, width=60),
        ], orientation="horizontal", spacing=8),
        group([
            text(tr("settings.label.row_range",
                    "Ряды (от—до):")),
            mgmt_form_field("row_from", kind="number",
                            value=ui["ui_row_from"],
                            min_value=1, max_value=99, width=60),
            text(tr("settings.label.dash", "—")),
            mgmt_form_field("row_to", kind="number",
                            value=ui["ui_row_to"],
                            min_value=1, max_value=99, width=60),
        ], orientation="horizontal", spacing=8),
        group([
            text(tr("settings.label.section_range",
                    "Секции (от—до):")),
            mgmt_form_field("sec_from", kind="number",
                            value=ui["ui_sec_from"],
                            min_value=1, max_value=99, width=60),
            text(tr("settings.label.dash", "—")),
            mgmt_form_field("sec_to", kind="number",
                            value=ui["ui_sec_to"],
                            min_value=1, max_value=99, width=60),
        ], orientation="horizontal", spacing=8),
    ]
    children.append(card(range_children,
                         title=tr("settings.range.title",
                                  "Диапазон ячеек")))

    # --- Структура ячеек в секции ---
    shelf_children = [
        caption(tr("settings.shelves.hint",
                   "Настройки полок и ячеек применяются "
                   "при создании диапазона:")),
        group([
            text(tr("settings.label.shelves_count",
                    "Количество полок")),
            mgmt_form_field(
                "shelves_count", kind="number",
                value=ui["ui_shelves_count"],
                min_value=1, max_value=26,
                on_change="input_submit", width=100
            ),
        ], orientation="horizontal", spacing=8),
    ]
    for i in range(ui["ui_shelves_count"]):
        letter = chr(ord('A') + i)
        shelf_children.append(group([
            text(tr("settings.label.shelf",
                    "Полка {letter}:", letter=letter)),
            mgmt_form_field(f"shelf_{i}", kind="number",
                            value=1, min_value=1, max_value=99, width=60)
        ], orientation="horizontal", spacing=8))

    children.append(card(shelf_children,
                         title=tr("settings.shelves.title",
                                  "Структура ячеек в секции")))

    children.append(mgmt_toolbar([
        button(tr("settings.create_range", "Создать диапазон"),
               "tap", "create_range", style="primary",
               enabled=bool(blocks_options)),
        button(tr("settings.del_range", "Удалить диапазон"),
               "tap", "delete_range",
               enabled=bool(blocks_options)),
    ]))

    if dialog == "add_block":
        children.append(_build_add_block_dialog(free_numbers))

    if alert_dialog:
        children.append(alert_dialog)

    page = mgmt_page("settings",
                     tr("settings.title", "Настройки склада"),
                     children)
    return make_mgmt_document(
        page, sidebar=build_sidebar(role), extra={"role": role})


def _build_add_block_dialog(free_numbers):
    options = [{"value": n, "label": n} for n in free_numbers]
    return mgmt_dialog(
        "add_block",
        tr("settings.add_block", "Новый блок"),
        [
            caption(tr("settings.blocks.choose",
                       "Выберите номер блока:")),
            mgmt_form_field(
                "selected", kind="select",
                value=free_numbers[0] if free_numbers else None,
                options=options,
            ),
        ],
        panel_kind="dialog",
        buttons=[
            button(tr("settings.btn.add_block", "Создать"),
                   "tap", "add_block_commit", style="primary"),
            button(tr("settings.btn.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def build_view(login, role, context):
    return _build(context.db_path, role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit" and action_id == "locale":
        code = str(value or "ru")
        if code not in available_locales():
            code = "ru"
        save_locale_for_manager(db_path, login, code)
        set_locale(code)
        info = locale_info(code)
        if not info["complete"]:
            total = info["total"] or info["translated"] or 0
            msg = tr(
                "settings.msg.locale_incomplete",
                "Язык «{name}» неполный: {done}/{total} ключей. "
                "Отсутствующие переводы будут показаны на языке "
                "по умолчанию ({fb}).",
                name=info["name"],
                done=info["translated"],
                total=total,
                fb=(info["fallback"] or "ru"),
            )
            return {"ok": True,
                    "view": _build(
                        db_path, role,
                        alert_dialog=_alert_dialog(
                            tr("common.warning", "Внимание"), msg))}
        return {"ok": True, "view": _build(db_path, role)}

    if action == "tap" and action_id == "reload_locales":
        reload_locales()
        cur = current_locale()
        if cur not in available_locales():
            cur = "ru"
            save_locale_for_manager(db_path, login, cur)
            set_locale(cur)
        return {"ok": True,
                "message": tr("settings.msg.locales_reloaded",
                              "Список языков перечитан"),
                "view": _build(db_path, role)}

    if action == "input_submit" and action_id == "shelves_count":
        try:
            n = int(value or 1)
        except (ValueError, TypeError):
            n = 1
        n = max(1, min(26, n))
        conn = sqlite3.connect(db_path)
        try:
            _save_setting(conn, "ui_shelves_count", n)
        finally:
            conn.close()
        return {"ok": True,
                "view": _build(db_path, role,
                               ui_overrides={
                                   "ui_shelves_count": n})}

    if action == "input_submit":
        _persist_range_settings(db_path, values)
        return {"ok": True, "view": _build(db_path, role)}

    if action == "tap":
        if action_id == "close_dialog":
            return {"ok": True, "view": _build(db_path, role)}
        if action_id == "add_block_open":
            return {"ok": True,
                    "view": _build(db_path, role,
                                   dialog="add_block")}
        if action_id == "dialog_cancel":
            return {"ok": True, "view": _build(db_path, role)}
        if action_id == "add_block_commit":
            return _add_block(db_path, role, values)
        if action_id == "delete_block":
            return _delete_block(db_path, role, values)
        if action_id == "create_range":
            return _create_range(db_path, role, values)
        if action_id == "delete_range":
            return _delete_range(db_path, role, values)

    return {"ok": False,
            "error": tr("settings.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _persist_range_settings(db_path, values):
    mapping = {
        "floor_from": "ui_floor_from",
        "floor_to": "ui_floor_to",
        "row_from": "ui_row_from",
        "row_to": "ui_row_to",
        "sec_from": "ui_sec_from",
        "sec_to": "ui_sec_to",
    }
    conn = sqlite3.connect(db_path)
    try:
        for src, dst in mapping.items():
            if src in values and values[src] is not None:
                try:
                    _save_setting(conn, dst, int(values[src]))
                except (ValueError, TypeError):
                    pass
    finally:
        conn.close()


def _add_block(db_path, role, values):
    num = str(values.get("selected", "")).strip()
    if not num:
        return {"ok": True,
                "view": _build(
                    db_path, role,
                    alert_dialog=_alert_dialog(
                        tr("common.error", "Ошибка"),
                        tr("settings.err.no_block",
                           "Выберите блок.")))}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM blocks WHERE name=?", (num,))
        if cur.fetchone():
            return {"ok": True,
                    "view": _build(
                        db_path, role,
                        alert_dialog=_alert_dialog(
                            tr("common.error", "Ошибка"),
                            tr("settings.err.block_exists",
                               "Блок {num} уже есть.",
                               num=num)))}
        cur.execute("INSERT INTO blocks (name) VALUES (?)", (num,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "view": _build(
                db_path, role,
                alert_dialog=_alert_dialog(
                    tr("common.info", "Готово"),
                    tr("settings.msg.block_created",
                       "Блок {num} создан.", num=num)))}


def _delete_block(db_path, role, values):
    bid = values.get("block_id")
    if bid is None:
        return {"ok": True,
                "view": _build(
                    db_path, role,
                    alert_dialog=_alert_dialog(
                        tr("common.error", "Ошибка"),
                        tr("settings.err.no_block",
                           "Выберите блок.")))}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM cells WHERE block_id=?",
                    (bid,))
        cnt = cur.fetchone()[0]
        if cnt:
            return {"ok": True,
                    "view": _build(
                        db_path, role,
                        alert_dialog=_alert_dialog(
                            tr("common.error", "Ошибка"),
                            tr("settings.err.block_has_cells",
                               "В блоке {count} ячеек. "
                               "Сначала удалите их.",
                               count=cnt)))}
        cur.execute("DELETE FROM blocks WHERE id=?", (bid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "view": _build(
                db_path, role,
                alert_dialog=_alert_dialog(
                    tr("common.info", "Готово"),
                    tr("settings.msg.block_deleted",
                       "Блок удалён.")))}


def _create_range(db_path, role, values):
    bid = values.get("block_id")
    if bid is None:
        return {"ok": True,
                "view": _build(
                    db_path, role,
                    alert_dialog=_alert_dialog(
                        tr("common.error", "Ошибка"),
                        tr("settings.err.no_block",
                           "Выберите блок.")))}
    try:
        ff = int(values.get("floor_from") or 1)
        ft = int(values.get("floor_to") or 1)
        rf = int(values.get("row_from") or 1)
        rt = int(values.get("row_to") or 1)
        sf = int(values.get("sec_from") or 1)
        st = int(values.get("sec_to") or 1)
        shelves_count = int(values.get("shelves_count") or 1)
    except (ValueError, TypeError):
        return {"ok": True,
                "view": _build(
                    db_path, role,
                    alert_dialog=_alert_dialog(
                        tr("common.error", "Ошибка"),
                        tr("settings.err.numeric",
                           "Проверьте числовые поля.")))}

    if ff > ft:
        return {"ok": True, "view": _build(
            db_path, role,
            alert_dialog=_alert_dialog(
                tr("common.error", "Ошибка"),
                tr("settings.err.floor_range",
                   "Этаж «от» > «до».")))}
    if rf > rt:
        return {"ok": True, "view": _build(
            db_path, role,
            alert_dialog=_alert_dialog(
                tr("common.error", "Ошибка"),
                tr("settings.err.row_range",
                   "Ряд «от» > «до».")))}
    if sf > st:
        return {"ok": True, "view": _build(
            db_path, role,
            alert_dialog=_alert_dialog(
                tr("common.error", "Ошибка"),
                tr("settings.err.section_range",
                   "Секция «от» > «до».")))}

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM blocks WHERE id=?", (bid,))
        row = cur.fetchone()
        if not row:
            return {"ok": True,
                    "view": _build(
                        db_path, role,
                        alert_dialog=_alert_dialog(
                            tr("common.error", "Ошибка"),
                            tr("settings.err.block_not_found",
                               "Блок не найден.")))}
        bname = row[0]
        try:
            bnum = int(_format_block_name(bname))
        except (ValueError, TypeError):
            bnum = bid

        cur.execute("SELECT key, value FROM settings")
        s = dict(cur.fetchall())
        pfx = s.get("prefix_cell", "")
        sfx = s.get("suffix_cell", "")

        created = skipped = 0
        for f in range(ff, ft + 1):
            bf = f"{bnum}{f}"
            for r in range(rf, rt + 1):
                for sec in range(sf, st + 1):
                    for i in range(shelves_count):
                        letter = chr(ord('A') + i)
                        try:
                            per_shelf = int(
                                values.get(f"shelf_{i}") or 1)
                        except (ValueError, TypeError):
                            per_shelf = 1
                        for n in range(1, per_shelf + 1):
                            cell = f"{letter}{n}"
                            addr = f"{bf}-{r:02d}-{sec:02d}-{cell}"
                            bc = (f"{pfx}{bf}{r:02d}{sec:02d}"
                                  f"{cell}{sfx}")
                            cur.execute("SELECT 1 FROM cells "
                                        "WHERE address=?", (addr,))
                            if cur.fetchone():
                                skipped += 1
                                continue
                            cur.execute("""
                                INSERT INTO cells
                                    (block_id, floor, row, section,
                                     cell, address, barcode,
                                     cell_type)
                                VALUES (?, ?, ?, ?, ?, ?, ?,
                                        'standart')
                            """, (bid, f, r, sec, cell, addr, bc))
                            created += 1
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "view": _build(
        db_path, role,
        alert_dialog=_alert_dialog(
            tr("common.info", "Готово"),
            tr("settings.msg.range_created",
               "Создано: {created}. Пропущено: {skipped}.",
               created=created, skipped=skipped)))}


def _delete_range(db_path, role, values):
    bid = values.get("block_id")
    if bid is None:
        return {"ok": True,
                "view": _build(
                    db_path, role,
                    alert_dialog=_alert_dialog(
                        tr("common.error", "Ошибка"),
                        tr("settings.err.no_block",
                           "Выберите блок.")))}
    try:
        ff = int(values.get("floor_from") or 1)
        ft = int(values.get("floor_to") or 1)
        rf = int(values.get("row_from") or 1)
        rt = int(values.get("row_to") or 1)
        sf = int(values.get("sec_from") or 1)
        st = int(values.get("sec_to") or 1)
    except (ValueError, TypeError):
        return {"ok": True,
                "view": _build(
                    db_path, role,
                    alert_dialog=_alert_dialog(
                        tr("common.error", "Ошибка"),
                        tr("settings.err.numeric",
                           "Проверьте числовые поля.")))}

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM settings WHERE key='accounting'")
        r = cur.fetchone()
        accounting = r[0] if r else ""

        busy = []
        for f in range(ff, ft + 1):
            for row in range(rf, rt + 1):
                for sec in range(sf, st + 1):
                    cur.execute("""
                        SELECT address, barcode FROM cells
                        WHERE block_id=? AND floor=?
                          AND row=? AND section=?
                    """, (bid, f, row, sec))
                    for addr, bc in cur.fetchall():
                        if accounting == "Экземплярный":
                            cur.execute("""
                                SELECT 1 FROM placed_instances
                                WHERE cell_or_container_barcode=?
                                LIMIT 1
                            """, (bc,))
                        else:
                            cur.execute("""
                                SELECT 1 FROM placed_instances
                                WHERE cell_barcode=? LIMIT 1
                            """, (bc,))
                        if cur.fetchone():
                            busy.append(addr)

        if busy:
            preview = "\n".join(busy[:10])
            return {"ok": True, "view": _build(
                db_path, role,
                alert_dialog=_alert_dialog(
                    tr("common.error", "Ошибка"),
                    tr("settings.err.cells_busy",
                       "Есть товары в ячейках:\n{preview}",
                       preview=preview)))}

        deleted = 0
        for f in range(ff, ft + 1):
            for row in range(rf, rt + 1):
                for sec in range(sf, st + 1):
                    cur.execute("""
                        DELETE FROM cells
                        WHERE block_id=? AND floor=?
                          AND row=? AND section=?
                    """, (bid, f, row, sec))
                    deleted += cur.rowcount
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "view": _build(
        db_path, role,
        alert_dialog=_alert_dialog(
            tr("common.info", "Готово"),
            tr("settings.msg.range_deleted",
               "Удалено: {count}.", count=deleted)))}