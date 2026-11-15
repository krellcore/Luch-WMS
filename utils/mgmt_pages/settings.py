"""«Настройки склада» — серверная сборка view и handler действий."""

import json
import os
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

# Лимит на одну операцию создания диапазона: отсекает DoS
# «10^9 ячеек одним запросом», но пропускает реальные склады
# (5 этажей × 50 рядов × 50 секций × 40 ячеек = 500 000).
_MAX_RANGE_CELLS = 2_000_000
# Коммит каждые N ячеек — чтобы при сбое не терять уже вставленное.
_RANGE_COMMIT_CHUNK = 25_000
# Выше этого порога — диалог подтверждения.
_RANGE_CONFIRM_THRESHOLD = 50_000
# Выше этого порога — подсказка «создавайте по этажам».
_RANGE_SPLIT_HINT_THRESHOLD = 200_000


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


def _range_confirm_dialog(total_cells):
    children = [
        text(tr(
            "settings.range_confirm.text",
            "Будет создано {total} ячеек. Это может занять "
            "несколько секунд, в течение которых сервер будет "
            "занят — другие клиенты могут ждать.",
            total=total_cells)),
    ]
    if total_cells > _RANGE_SPLIT_HINT_THRESHOLD:
        children.append(caption(tr(
            "settings.range_confirm.hint",
            "Рекомендуем создавать по этажам: укажите "
            "«Этаж от = Этаж до» для одного этажа, затем "
            "повторите для следующего. Так сервер будет "
            "свободен между операциями.")))
    return mgmt_dialog(
        "range_confirm",
        tr("settings.range_confirm.title",
           "Подтверждение создания"),
        children,
        buttons=[
            button(tr("settings.range_confirm.yes", "Продолжить"),
                   "tap", "range_confirm_yes", style="primary"),
            button(tr("settings.range_confirm.no", "Отмена"),
                   "tap", "range_confirm_no"),
        ],
    )


def _save_range_pending(db_path, login, values, total_cells):
    key = f"_mgmt_range_pending_{login}"
    payload = json.dumps(
        {"values": values, "total_cells": int(total_cells)},
        ensure_ascii=False)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM settings WHERE key=?", (key,))
        if cur.fetchone():
            cur.execute("UPDATE settings SET value=? WHERE key=?",
                        (payload, key))
        else:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, payload))
        conn.commit()
    finally:
        conn.close()


def _load_range_pending(db_path, login):
    key = f"_mgmt_range_pending_{login}"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = cur.fetchone()
        if r and r[0]:
            try:
                return json.loads(r[0])
            except Exception:
                return None
        return None
    finally:
        conn.close()


def _drop_range_pending(db_path, login):
    key = f"_mgmt_range_pending_{login}"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))
        conn.commit()
    finally:
        conn.close()


def _security_card(db_path):
    """Карточка «Безопасность»: TLS, fingerprint, перевыпуск.

    Читает settings.tls_enabled и файлы сертификата. Кнопка
    «Перевыпустить» показывает диалог подтверждения (файлы
    перезапишутся, старый серт — в cert.pem.old).
    """
    warehouse_dir = os.path.dirname(os.path.abspath(db_path))
    conn = sqlite3.connect(db_path)
    try:
        s = _read_settings(conn)
    finally:
        conn.close()

    enabled = str(s.get("tls_enabled") or "0") == "1"

    try:
        from tls import has_cert, cert_fingerprint
        has = has_cert(warehouse_dir)
        fp = cert_fingerprint(warehouse_dir) if has else ""
    except Exception:
        has = False
        fp = ""

    if has:
        status_text = tr(
            "settings.security.status_ok",
            "Сертификат: установлен")
        status_accent = "success"
    else:
        status_text = tr(
            "settings.security.status_missing",
            "Сертификат: отсутствует")
        status_accent = "warning"

    if enabled:
        mode_text = tr(
            "settings.security.mode_on", "Режим: HTTPS (TLS)")
        mode_accent = "success"
    else:
        mode_text = tr(
            "settings.security.mode_off", "Режим: HTTP")
        mode_accent = "warning"

    children = [
        group([
            mgmt_badge(mode_text, accent=mode_accent),
            mgmt_badge(status_text, accent=status_accent),
        ], orientation="horizontal", spacing=8),
        caption(tr(
            "settings.security.fp_label",
            "Fingerprint (для QR):")),
        text(fp or "—",
             bold=True, size=11),
        spacer(8),
        caption(tr(
            "settings.security.restart_hint",
            "Включение/выключение TLS и перевыпуск "
            "сертификата требуют перезапуска сервера. "
            "После изменения перезапустите сервер вручную "
            "(остановить в окне статуса и запустить заново).")),
        spacer(8),
    ]

    tls_field = mgmt_form_field(
        "tls_enabled", kind="checkbox",
        label=tr("settings.security.tls_label",
                 "Использовать TLS (HTTPS)"),
        value=enabled,
        on_change="input_submit")

    regen_btn = button(
        tr("settings.security.regen_btn",
           "Перевыпустить сертификат"),
        "tap", "regen_tls_confirm",
        enabled=has,
        style="default")

    children.append(tls_field)
    children.append(mgmt_toolbar([regen_btn]))

    return card(children,
                title=tr("settings.security.title",
                         "Безопасность"))


def _regen_tls_confirm_dialog():
    return mgmt_dialog(
        "regen_tls_confirm",
        tr("settings.security.regen_confirm_title",
           "Перевыпустить сертификат"),
        [
            text(tr(
                "settings.security.regen_confirm_text",
                "Будет создан новый самоподписанный "
                "сертификат. Старый сохранится как "
                "cert.pem.old (30 дней). Все клиенты должны "
                "будут отсканировать новый QR с новым "
                "fingerprint. Перезапустите сервер после "
                "перевыпуска.")),
        ],
        buttons=[
            button(tr("settings.security.regen_yes",
                      "Перевыпустить"),
                   "tap", "regen_tls_apply", style="primary"),
            button(tr("settings.security.regen_no", "Отмена"),
                   "tap", "close_dialog"),
        ],
    )


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

    # --- Безопасность ---
    children.append(_security_card(db_path))

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
    elif dialog == "regen_tls_confirm":
        children.append(_regen_tls_confirm_dialog())
    elif isinstance(dialog, dict):
        kind = dialog.get("kind")
        if kind == "range_confirm":
            children.append(_range_confirm_dialog(
                int(dialog.get("total_cells") or 0)))

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

    if action == "input_submit" and action_id == "tls_enabled":
        new_val = "1" if value else "0"
        conn = sqlite3.connect(db_path)
        try:
            _save_setting(conn, "tls_enabled", new_val)
        finally:
            conn.close()
        msg = tr(
            "settings.msg.tls_changed",
            "Настройка TLS сохранена. Перезапустите сервер, "
            "чтобы изменения вступили в силу.")
        return {"ok": True, "view": _build(
            db_path, role,
            alert_dialog=_alert_dialog(
                tr("common.info", "Готово"), msg))}

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
            return _create_range_start(db_path, role, login, values)
        if action_id == "range_confirm_yes":
            return _range_confirm_apply(db_path, role, login)
        if action_id == "range_confirm_no":
            _drop_range_pending(db_path, login)
            return {"ok": True, "view": _build(db_path, role)}
        if action_id == "delete_range":
            return _delete_range(db_path, role, values)
        if action_id == "regen_tls_confirm":
            return {"ok": True, "view": _build(
                db_path, role, dialog="regen_tls_confirm")}
        if action_id == "regen_tls_apply":
            return _regen_tls_apply(db_path, role)

    return {"ok": False,
            "error": tr("settings.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _regen_tls_apply(db_path, role):
    warehouse_dir = os.path.dirname(os.path.abspath(db_path))
    try:
        from tls import generate_cert
        import shutil
        cert_path = os.path.join(warehouse_dir, "tls", "cert.pem")
        old_path = cert_path + ".old"
        if os.path.isfile(cert_path):
            try:
                shutil.copy2(cert_path, old_path)
            except Exception:
                pass
        fp = generate_cert(warehouse_dir)
    except Exception as e:
        return _err_view(db_path, role, tr(
            "settings.security.regen_failed",
            "Не удалось перевыпустить сертификат: {error}",
            error=str(e)))
    msg = tr(
        "settings.security.regen_done",
        "Сертификат перевыпущен. Новый fingerprint: {fp}. "
        "Перезапустите сервер, чтобы он начал использовать "
        "новый сертификат.", fp=fp)
    return {"ok": True, "view": _build(
        db_path, role,
        alert_dialog=_alert_dialog(
            tr("common.info", "Готово"), msg))}


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


def _err_view(db_path, role, msg):
    return {"ok": True, "view": _build(
        db_path, role,
        alert_dialog=_alert_dialog(
            tr("common.error", "Ошибка"), msg))}


def _validate_range_values(values, with_shelves=False):
    try:
        ff = int(values.get("floor_from") or 1)
        ft = int(values.get("floor_to") or 1)
        rf = int(values.get("row_from") or 1)
        rt = int(values.get("row_to") or 1)
        sf = int(values.get("sec_from") or 1)
        st = int(values.get("sec_to") or 1)
    except (ValueError, TypeError):
        return False, None, tr(
            "settings.err.numeric",
            "Проверьте числовые поля.")

    if not (1 <= ff <= 9 and 1 <= ft <= 9):
        return False, None, tr(
            "settings.err.floor_range",
            "Этаж «от» > «до».")
    if not (1 <= rf <= 99 and 1 <= rt <= 99):
        return False, None, tr(
            "settings.err.row_range",
            "Ряд «от» > «до».")
    if not (1 <= sf <= 99 and 1 <= st <= 99):
        return False, None, tr(
            "settings.err.section_range",
            "Секция «от» > «до».")
    if ff > ft:
        return False, None, tr(
            "settings.err.floor_range",
            "Этаж «от» > «до».")
    if rf > rt:
        return False, None, tr(
            "settings.err.row_range",
            "Ряд «от» > «до».")
    if sf > st:
        return False, None, tr(
            "settings.err.section_range",
            "Секция «от» > «до».")

    parsed = {"ff": ff, "ft": ft,
              "rf": rf, "rt": rt,
              "sf": sf, "st": st}

    if with_shelves:
        try:
            shelves_count = int(values.get("shelves_count") or 1)
        except (ValueError, TypeError):
            return False, None, tr(
                "settings.err.numeric",
                "Проверьте числовые поля.")
        if not (1 <= shelves_count <= 26):
            return False, None, tr(
                "settings.err.numeric",
                "Проверьте числовые поля.")

        per_shelf = []
        for i in range(shelves_count):
            try:
                per = int(values.get(f"shelf_{i}") or 1)
            except (ValueError, TypeError):
                return False, None, tr(
                    "settings.err.numeric",
                    "Проверьте числовые поля.")
            if not (1 <= per <= 99):
                return False, None, tr(
                    "settings.err.numeric",
                    "Проверьте числовые поля.")
            per_shelf.append(per)

        total_cells = ((ft - ff + 1) * (rt - rf + 1) *
                       (st - sf + 1) * sum(per_shelf))
        if total_cells > _MAX_RANGE_CELLS:
            return False, None, tr(
                "settings.err.range_too_big",
                "Слишком большой диапазон ({total} ячеек). "
                "Максимум {limit} за раз. Разбейте на "
                "несколько диапазонов (например, по этажам).",
                total=total_cells, limit=_MAX_RANGE_CELLS)
        parsed["shelves_count"] = shelves_count
        parsed["per_shelf"] = per_shelf
        parsed["total_cells"] = total_cells

    return True, parsed, None


def _create_range_start(db_path, role, login, values):
    bid = values.get("block_id")
    if bid is None:
        return _err_view(db_path, role, tr(
            "settings.err.no_block", "Выберите блок."))

    ok, parsed, err = _validate_range_values(
        values, with_shelves=True)
    if not ok:
        return _err_view(db_path, role, err)

    total_cells = parsed["total_cells"]

    if total_cells > _RANGE_CONFIRM_THRESHOLD:
        _save_range_pending(db_path, login, values, total_cells)
        return {"ok": True, "view": _build(
            db_path, role,
            dialog={"kind": "range_confirm",
                    "total_cells": total_cells})}

    return _create_range_apply(db_path, role, values, parsed)


def _range_confirm_apply(db_path, role, login):
    pending = _load_range_pending(db_path, login)
    if not pending:
        _drop_range_pending(db_path, login)
        return {"ok": True, "view": _build(db_path, role)}

    values_p = pending.get("values") or {}
    _drop_range_pending(db_path, login)

    ok, parsed, err = _validate_range_values(
        values_p, with_shelves=True)
    if not ok:
        return _err_view(db_path, role, err)

    return _create_range_apply(db_path, role, values_p, parsed)


def _create_range_apply(db_path, role, values, parsed):
    bid = values.get("block_id")
    ff = parsed["ff"]
    ft = parsed["ft"]
    rf = parsed["rf"]
    rt = parsed["rt"]
    sf = parsed["sf"]
    st = parsed["st"]
    shelves_count = parsed["shelves_count"]
    per_shelf = parsed["per_shelf"]

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM blocks WHERE id=?", (bid,))
        row = cur.fetchone()
        if not row:
            return _err_view(db_path, role, tr(
                "settings.err.block_not_found",
                "Блок не найден."))
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
        since_commit = 0

        for f in range(ff, ft + 1):
            bf = f"{bnum}{f}"
            for r in range(rf, rt + 1):
                for sec in range(sf, st + 1):
                    for i in range(shelves_count):
                        letter = chr(ord('A') + i)
                        per = per_shelf[i]
                        for n in range(1, per + 1):
                            cell = f"{letter}{n}"
                            addr = f"{bf}-{r:02d}-{sec:02d}-{cell}"
                            bc = (f"{pfx}{bf}{r:02d}{sec:02d}"
                                  f"{cell}{sfx}")
                            cur.execute(
                                "SELECT 1 FROM cells "
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
                            since_commit += 1
                            if since_commit >= _RANGE_COMMIT_CHUNK:
                                conn.commit()
                                since_commit = 0
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
        return _err_view(db_path, role, tr(
            "settings.err.no_block", "Выберите блок."))

    ok, parsed, err = _validate_range_values(
        values, with_shelves=False)
    if not ok:
        return _err_view(db_path, role, err)

    ff = parsed["ff"]
    ft = parsed["ft"]
    rf = parsed["rf"]
    rt = parsed["rt"]
    sf = parsed["sf"]
    st = parsed["st"]

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
            return _err_view(db_path, role, tr(
                "settings.err.cells_busy",
                "Есть товары в ячейках:\n{preview}",
                preview=preview))

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