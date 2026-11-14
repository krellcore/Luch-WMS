"""«Тары» — серверная сборка view и действия."""

import sqlite3
import base64
import secrets

from PySide6.QtCore import QBuffer, QIODevice

from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_dialog, heading, text, card, caption, button,
    mgmt_file_trigger, mgmt_image, make_mgmt_document, mgmt_header,
    group
)
from mgmt_view_builder import build_sidebar
from barcodes import make_label_image, make_barcode_pixmap
from i18n import tr


def _status_label(st):
    key = f"containers.status.{st or 'free'}"
    default = {
        "free": "свободна", "accepting": "приёмка",
        "placing": "к размещению", "picking": "подбор",
        "waiting": "ожидает", "closed": "закрыта",
        "dropped": "сброшена",
        "unknown_scan": "неизвестные ШК",
    }.get(st or "free", st or "")
    return tr(key, default)


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
        extra={"role": role})


def _barcode_preview_b64(code):
    try:
        pix = make_barcode_pixmap(code)
    except Exception:
        return None
    if pix is None or pix.isNull():
        return None
    qb = QBuffer()
    qb.open(QIODevice.WriteOnly)
    pix.save(qb, "PNG")
    raw = bytes(qb.data())
    qb.close()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _label_png_b64(title, subtitle, code):
    try:
        png = make_label_image(title, subtitle, code)
        return base64.b64encode(png).decode("ascii")
    except Exception:
        return None


def _display_placed_in(cur, placed_in):
    if not placed_in:
        return tr("common.dash", "—")
    cur.execute("SELECT name FROM drop_points WHERE barcode=?",
                (placed_in,))
    dp = cur.fetchone()
    if dp:
        name = dp[0] or ""
        if name:
            return f"{name} ({placed_in})"
    return placed_in


def _list_rows(db_path, search="", status_filter=""):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.barcode, COALESCE(c.status,'free'),
                   c.placed_in,
                   COALESCE((SELECT SUM(quantity)
                     FROM placed_instances
                     WHERE cell_or_container_barcode=c.barcode), 0)
            FROM containers c ORDER BY c.barcode
        """)
        rows = []
        s = (search or "").lower()
        for bc, st, p, qty in cur.fetchall():
            if status_filter and st != status_filter:
                continue
            placed_display = _display_placed_in(cur, p)
            contents = tr("containers.contents_fmt",
                          "{qty} шт", qty=qty)
            if s and s not in (bc or "").lower() \
                    and s not in placed_display.lower() \
                    and s not in contents.lower():
                continue
            rows.append({
                "id": bc,
                "barcode": bc or "",
                "status": _status_label(st),
                "placed_in": placed_display,
                "contents": contents,
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, search="", status_filter="",
                message=None, error=None, dialog=None):
    header_actions = [
        button(tr("containers.manual_receive.button",
                  "Приёмка без задания"),
               "tap", "manual_receive_open"),
        button(tr("containers.add", "+ Создать тару"),
               "tap", "add_open", style="primary"),
        button(tr("containers.withdraw",
                  "Вывести из оборота"),
               "tap", "withdraw"),
        button(tr("common.delete", "Удалить"),
               "tap", "delete"),
    ]
    children = [mgmt_header(
        tr("containers.title", "Рабочие тары"), header_actions)]
    
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    status_options = [
        {"value": "", "label": tr("common.all", "Все")},
    ] + [
        {"value": k, "label": tr(f"containers.status.{k}", k)}
        for k in ("free", "accepting", "placing",
                  "picking", "waiting", "closed",
                  "dropped", "unknown_scan")
    ]

    children.append(group([
        mgmt_form_field(
            "search", kind="text",
            label=tr("common.search", "Поиск:"),
            label_position="left", stretch=True,
            value=search,
            on_change="input_submit"),
        mgmt_form_field(
            "status_filter", kind="select",
            label=tr("containers.filter.status", "Статус"),
            label_position="left",
            value=status_filter,
            options=status_options,
            on_change="input_submit"),
        button(tr("common.refresh", "Обновить"),
               "tap", "refresh")
    ], orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "barcode",
             "label": tr("containers.col.barcode", "ШК тары")},
            {"key": "status",
             "label": tr("containers.col.status", "Статус")},
            {"key": "placed_in",
             "label": tr("containers.col.placed_in",
                         "Размещена в")},
            {"key": "contents",
             "label": tr("containers.col.contents",
                         "Содержимое")},
        ],
        rows=_list_rows(db_path, search=search,
                        status_filter=status_filter),
        on_double_click={
            "action": "tap", "id": "open_panel",
            "value_field": "id"},
        row_key="id",
        empty_label="",
        searchable=False,
    ))

    if isinstance(dialog, dict):
        kind = dialog.get("kind")
        if kind == "withdraw_confirm":
            children.append(_withdraw_confirm_dialog(
                db_path, dialog.get("bc", "")))
    elif dialog == "add":
        children.append(_add_dialog())
    elif dialog == "manual_receive":
        children.append(_manual_receive_dialog(db_path))

    return mgmt_page("containers",
                     tr("containers.title", "Рабочие тары"),
                     children)


def _add_dialog():
    return mgmt_dialog(
        "add",
        tr("containers.add_dialog.title", "Новая тара"),
        [
            mgmt_form_field(
                "barcode", kind="text",
                label=tr("containers.add_dialog.barcode",
                         "ШК тары:"),
                placeholder=tr(
                    "containers.add_dialog.placeholder",
                    "Оставьте пусто — сгенерировать"),
                stretch=True),
            caption(tr(
                "containers.add_dialog.hint",
                "Тара создаётся свободной. К введённому ШК "
                "будут добавлены префикс и суффикс склада.")),
        ],
        buttons=[
            button(tr("containers.add_dialog.create", "Создать"),
                   "tap", "add_commit", style="primary"),
            button(tr("common.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def _withdraw_confirm_dialog(db_path, bc):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT ic.item_code, ic.name,
                   COALESCE(SUM(pi.quantity), 0) AS qty
            FROM placed_instances pi
            LEFT JOIN item_characteristics ic
                   ON ic.item_code = pi.item_code
            WHERE pi.cell_or_container_barcode=?
            GROUP BY ic.item_code, ic.name
        """, (bc,))
        rows = cur.fetchall()
    finally:
        conn.close()

    lines = [f"  {name or code} ({code}): {qty}"
             for code, name, qty in rows]
    total = sum(qty for _, _, qty in rows)
    body = tr(
        "containers.withdraw.confirm",
        "Вывести тару {bc} из оборота?\n\n"
        "Будет удалено товаров: {total}\n\n{lines}\n\n"
        "Тара станет свободной. Продолжить?",
        bc=bc, total=total,
        lines="\n".join(lines) if lines else "")

    return mgmt_dialog(
        "withdraw_confirm",
        tr("containers.withdraw.title", "Вывод из оборота"),
        [text(body)],
        buttons=[
            button(tr("containers.btn.withdraw_force",
                      "Освободить принудительно"),
                   "tap", "withdraw_force",
                   value={"id": bc}, style="danger"),
            button(tr("common.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def _manual_receive_dialog(db_path):
    """Приёмка без задания: таблица тар (с поиском) + таблица
    товаров (с поиском и редактируемым количеством).

    Контейнер выбирается кликом по строке в таблице тар
    (field_id='table_containers'); количество товаров
    редактируется в таблице товаров (field_id='table_items').
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT barcode, COALESCE(status,'free')
            FROM containers
            WHERE COALESCE(status,'free') IN ('free','accepting')
            ORDER BY barcode
        """)
        containers = [
            {"barcode": bc, "status": _status_label(st)}
            for bc, st in cur.fetchall()
        ]
        cur.execute("""
            SELECT item_code, name FROM item_characteristics
            ORDER BY name COLLATE NOCASE
        """)
        items = [{"code": c or "", "name": n or "", "qty": 0}
                 for c, n in cur.fetchall()]
    finally:
        conn.close()

    children = [
        caption(tr(
            "containers.manual_receive.hint_table",
            "Выберите тару в таблице ниже, затем укажите "
            "количество для нужных артикулов и нажмите "
            "«Принять». После приёмки тара перейдёт в статус "
            "«к размещению» без создания задания.")),
        mgmt_table(
            columns=[
                {"key": "barcode",
                 "label": tr("containers.col.barcode", "ШК тары"),
                 "width": 0.65},
                {"key": "status",
                 "label": tr("containers.col.status", "Статус"),
                 "width": 0.35},
            ],
            rows=containers,
            row_key="barcode",
            field_id="table_containers",
            searchable=True,
            search_placeholder=tr(
                "containers.manual_receive.search_containers",
                "Поиск по ШК или статусу…"),
            empty_label=tr(
                "containers.manual_receive.no_containers",
                "Нет свободных тар"),
        ),
        spacer_or_caption(),
        mgmt_table(
            columns=[
                {"key": "code",
                 "label": tr("items.col.code", "Артикул")},
                {"key": "name",
                 "label": tr("items.col.name", "Название")},
                {"key": "qty",
                 "label": tr("common.qty", "Количество")},
            ],
            rows=items,
            row_key="code",
            field_id="table_items",
            searchable=True,
            search_placeholder=tr("common.search_placeholder",
                                  "Поиск..."),
            editable=True,
        ),
    ]
    return mgmt_dialog(
        "manual_receive",
        tr("containers.manual_receive.title",
           "Приёмка без задания"),
        children,
        buttons=[
            button(tr("containers.manual_receive.accept",
                      "Принять"),
                   "tap", "manual_receive_apply",
                   style="primary"),
            button(tr("common.cancel", "Отмена"),
                   "tap", "dialog_cancel"),
        ],
    )


def spacer_or_caption():
    # маленький отступ между таблицами
    from mgmt_protocol import spacer
    return spacer(8)


def _build_panel(db_path, role, barcode, message=None, error=None):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT barcode, COALESCE(status,'free'), placed_in
            FROM containers WHERE barcode=?
        """, (barcode,))
        r = cur.fetchone()
        if not r:
            return _build_list(
                db_path, role,
                error=tr("containers.err.not_found",
                         "Тара не найдена."))
        bc, st, placed_in = r
        placed_text = _display_placed_in(cur, placed_in or "")
        cur.execute("""
            SELECT ic.item_code, ic.name,
                   COALESCE(SUM(pi.quantity), 0)
            FROM placed_instances pi
            LEFT JOIN item_characteristics ic
                ON ic.item_code = pi.item_code
            WHERE pi.cell_or_container_barcode = ?
            GROUP BY ic.item_code, ic.name
        """, (barcode,))
        contents = [
            {"id": code, "code": code or "",
             "name": name or "", "qty": qty or 0}
            for code, name, qty in cur.fetchall()
        ]
    finally:
        conn.close()

    preview = _barcode_preview_b64(bc)
    label_b64 = _label_png_b64(
        tr("containers.label.title", "РАБОЧАЯ ТАРА"), bc, bc)

    children = []
    
    header_children = [
        button(tr("common.back", "← Назад"), "tap", "back"),
        heading(tr("containers.panel.title_num",
                   "Тара {barcode}", barcode=bc)),
        {"type": "text", "value": "", "stretch": True},
    ]
    if label_b64:
        header_children.append(mgmt_file_trigger(
            "container_barcode",
            tr("containers.panel.download",
               "Скачать ШК тары"),
            action="download",
            download_b64=label_b64,
            filename=f"{bc}.png",
            style="primary"
        ))
    children.append(group(header_children, orientation="horizontal"))
    
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))
        
    left_col = []
    if preview:
        left_col.append(mgmt_image(preview, width=380, height=100))
    left_col.append(text(f"<b>{bc}</b>", size=14, align="center"))
    
    right_col = card([
        text(tr("containers.panel.barcode",
                "<b>ШК:</b> {barcode}", barcode=bc)),
        text(tr("containers.panel.status",
                "<b>Статус:</b> {status}",
                status=_status_label(st))),
        text(tr("containers.panel.placed_in",
                "<b>Размещена в:</b> {placed_in}",
                placed_in=placed_text)),
    ], title=tr("containers.panel.characteristics",
                "Характеристики"))
    right_col["stretch"] = True
    
    children.append(group([
        group(left_col, orientation="vertical"),
        right_col
    ], orientation="horizontal", spacing=20))
    
    children.append(mgmt_table(
        columns=[
            {"key": "code",
             "label": tr("containers.col.code", "Артикул")},
            {"key": "name",
             "label": tr("containers.col.name", "Название")},
            {"key": "qty",
             "label": tr("containers.col.qty", "Количество")},
        ],
        rows=contents,
        row_key="code",
        empty_label="",
    ))
    return mgmt_page("containers",
                     tr("containers.title", "Рабочие тары"),
                     children)


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit":
        search = str(values.get("search") or "")
        sf = str(values.get("status_filter") or "")
        return {"ok": True, "view": _doc(
            _build_list(db_path, role, search=search,
                        status_filter=sf), role)}

    if action == "tap":
        if action_id == "refresh":
            search = str(values.get("search") or "")
            sf = str(values.get("status_filter") or "")
            return {"ok": True, "view": _doc(
                _build_list(db_path, role, search=search,
                            status_filter=sf), role)}
        if action_id == "add_open":
            return {"ok": True, "view": _doc(_build_list(
                db_path, role, dialog="add"), role)}
        if action_id == "manual_receive_open":
            return {"ok": True, "view": _doc(_build_list(
                db_path, role, dialog="manual_receive"), role)}
        if action_id == "dialog_cancel":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "add_commit":
            return _add_commit(db_path, role, values)
        if action_id == "manual_receive_apply":
            return _manual_receive_apply(db_path, role, values)
        if action_id == "open_panel":
            return {"ok": True, "view": _doc(_build_panel(
                db_path, role, str(value or "")), role)}
        if action_id == "back":
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "withdraw":
            bc = _sel_barcode(value)
            if not bc:
                return {"ok": False,
                        "error": tr("containers.err.select",
                                    "Выберите тару.")}
            return _withdraw(db_path, role, bc, force=False)
        if action_id == "withdraw_force":
            bc = _sel_barcode(value)
            if not bc:
                return {"ok": False,
                        "error": tr("containers.err.select",
                                    "Выберите тару.")}
            return _withdraw(db_path, role, bc, force=True)
        if action_id == "delete":
            bc = _sel_barcode(value)
            if not bc:
                return {"ok": False,
                        "error": tr("containers.err.select",
                                    "Выберите тару.")}
            return _delete_container(db_path, role, bc)
    return {"ok": False,
            "error": tr("containers.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _sel_barcode(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id")
    return None


def _add_commit(db_path, role, values):
    user_code = str(values.get("barcode") or "").strip()
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        s = dict(cur.fetchall())
        prefix = s.get("prefix_container", "")
        suffix = s.get("suffix_container", "")
        if not user_code:
            code = ""
            for _ in range(100):
                cand = (f"{prefix}"
                        f"{secrets.randbelow(10**12):012d}{suffix}")
                cur.execute(
                    "SELECT 1 FROM containers WHERE barcode=?",
                    (cand,))
                if not cur.fetchone():
                    code = cand
                    break
            if not code:
                return {"ok": True, "view": _doc(_build_list(
                    db_path, role,
                    error=tr("containers.err.gen_failed",
                             "Не удалось сгенерировать ШК"),
                    dialog="add"), role)}
        else:
            code = f"{prefix}{user_code}{suffix}"
            cur.execute(
                "SELECT 1 FROM containers WHERE barcode=?", (code,))
            if cur.fetchone():
                return {"ok": True, "view": _doc(_build_list(
                    db_path, role,
                    error=tr("containers.add_dialog.err_exists",
                             "Такой ШК уже существует: {code}",
                             code=code),
                    dialog="add"), role)}
        cur.execute(
            "INSERT INTO containers (barcode, type, placed_in, "
            "status) VALUES (?, 'standart', '', 'free')",
            (code,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("containers.msg.created",
                          "Создана тара {barcode}", barcode=code),
            "view": _doc(_build_list(db_path, role), role)}


def _manual_receive_apply(db_path, role, values):
    """Принять товары в тару без создания задания.

    Контейнер берётся из выделения в таблице контейнеров
    (table_containers_selected). Количество — из таблицы товаров
    (table_items, поле 'qty').
    """
    sel_containers = values.get("table_containers_selected", [])
    if not sel_containers:
        return {"ok": False,
                "error": tr(
                    "containers.manual_receive.err_no_container",
                    "Выберите тару в таблице.")}
    container = str(sel_containers[0].get("barcode") or "").strip()
    if not container:
        return {"ok": False,
                "error": tr(
                    "containers.manual_receive.err_no_container",
                    "Выберите тару в таблице.")}

    rows = []
    for row in values.get("table_items", []):
        code = str(row.get("code") or "")
        try:
            q = int(row.get("qty") or 0)
        except (ValueError, TypeError):
            q = 0
        if code and q > 0:
            rows.append((code, q))

    if not rows:
        return {"ok": False,
                "error": tr(
                    "containers.manual_receive.err_no_qty",
                    "Введите количество хотя бы "
                    "для одного артикула.")}

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(status,'free') FROM containers "
            "WHERE barcode=?", (container,))
        r = cur.fetchone()
        if not r:
            return {"ok": False,
                    "error": tr(
                        "containers.err.not_found",
                        "Тара не найдена.")}
        st = r[0] or "free"
        if st not in ("free", "accepting"):
            return {"ok": False,
                    "error": tr(
                        "containers.manual_receive.err_bad_status",
                        "Тара {bc} в статусе {st}. "
                        "Ожидается free или accepting.",
                        bc=container, st=st)}
        for code, qty in rows:
            cur.execute("""
                SELECT id FROM placed_instances
                WHERE item_code=? AND cell_or_container_barcode=?
            """, (code, container))
            existing = cur.fetchone()
            if existing:
                cur.execute(
                    "UPDATE placed_instances SET quantity=quantity+?"
                    " WHERE id=?", (qty, existing[0]))
            else:
                cur.execute("""
                    INSERT INTO placed_instances
                        (item_code, cell_or_container_barcode,
                         quantity) VALUES (?, ?, ?)
                """, (code, container, qty))
        cur.execute(
            "UPDATE containers SET status='placing', placed_in='' "
            "WHERE barcode=?", (container,))
        conn.commit()
    finally:
        conn.close()
    total = sum(q for _, q in rows)
    return {"ok": True,
            "message": tr(
                "containers.manual_receive.done",
                "Принято {total} ед. в тару {bc}. "
                "Тара переведена в статус «к размещению».",
                total=total, bc=container),
            "view": _doc(_build_list(db_path, role), role)}


def _withdraw(db_path, role, bc, force=False):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(status,'free'), placed_in "
            "FROM containers WHERE barcode=?", (bc,))
        r = cur.fetchone()
        st = r[0] if r else "free"
        placed_in = r[1] if r else ""
        if placed_in:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("containers.err.on_drop_point",
                         "Тара {bc} сброшена на точку {placed_in}. "
                         "Освободите её через раздел "
                         "«📍 Точки сброса».",
                         bc=bc, placed_in=placed_in)), role)}
        if st == "picking":
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("containers.err.in_work",
                         "Тара в работе (статус: {status}). "
                         "Сначала завершите или отмените задание.",
                         status=st)), role)}
        if st == "accepting" and not force:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                dialog={"kind": "withdraw_confirm", "bc": bc}),
                role)}

        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (bc,))
        qty = cur.fetchone()[0] or 0
        if qty == 0 and not force:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("containers.empty.hint",
                         "В таре нет товаров. "
                         "Для удаления используйте «Удалить».")),
                role)}
        cur.execute("""
            DELETE FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (bc,))
        cur.execute(
            "UPDATE containers SET status='free', placed_in='' "
            "WHERE barcode=?", (bc,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("containers.msg.withdrawn",
                          "Тара {barcode} выведена из оборота",
                          barcode=bc),
            "view": _doc(_build_list(db_path, role), role)}


def _delete_container(db_path, role, bc):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(status,'free'), placed_in "
            "FROM containers WHERE barcode=?", (bc,))
        r = cur.fetchone()
        st = r[0] if r else "free"
        placed_in = r[1] if r else ""
        if placed_in:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("containers.delete.err.placed",
                         "Тара размещена в ячейке "
                         "или сброшена на точку.")), role)}

        can_delete_status = (
            st == "free"
            or (st == "accepting" and not placed_in))
        if not can_delete_status:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("containers.delete.err.status",
                         "Удалять можно только свободные тары. "
                         "Текущий статус: {status}. "
                         "Используйте «Вывести из оборота».",
                         status=st)),
                role)}
        cur.execute("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM placed_instances
            WHERE cell_or_container_barcode=?
        """, (bc,))
        qty = cur.fetchone()[0] or 0
        if qty > 0:
            return {"ok": True, "view": _doc(_build_list(
                db_path, role,
                error=tr("containers.delete.err.not_empty",
                         "Тара не пуста ({qty} шт). "
                         "Используйте «Вывести из оборота».",
                         qty=qty)), role)}
        cur.execute(
            "DELETE FROM containers WHERE barcode=?", (bc,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True,
            "message": tr("containers.msg.deleted", "Удалена"),
            "view": _doc(_build_list(db_path, role), role)}