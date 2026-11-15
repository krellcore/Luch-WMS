"""«Артикулы» — серверная сборка view и действия."""

import sqlite3
import base64
import json

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont

from db import (
    load_photo_bytes, save_photo_bytes, delete_photo,
    detect_mime,
)
from mgmt_protocol import (
    mgmt_page, mgmt_toolbar, mgmt_table, mgmt_form_field,
    mgmt_dialog, mgmt_header, heading, text, card, caption, button,
    mgmt_file_trigger, make_mgmt_document, group, mgmt_image
)
from mgmt_view_builder import build_sidebar
from barcodes import make_barcode_pixmap
from i18n import tr


def _doc(page, role):
    return make_mgmt_document(
        page, sidebar=build_sidebar(role),
        extra={"role": role})


def _num_to_float(s):
    """Строка → float. Принимает запятую как разделитель.
    Пустое/нечисловое → 0.0."""
    if s is None:
        return 0.0
    s = str(s).strip().replace(",", ".")
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _is_number_or_empty(s):
    """True, если строка — число (в т.ч. с запятой) или пустая."""
    if s is None:
        return True
    s = str(s).strip().replace(",", ".")
    if not s:
        return True
    try:
        float(s)
        return True
    except ValueError:
        return False


def _fmt_dim(v):
    """Форматирует размер: '100' для целых, '100.5' для дробных."""
    try:
        if v == int(v):
            return str(int(v))
    except (ValueError, OverflowError):
        pass
    return f"{v:g}"


def _list_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT item_code, name, barcode, dimensions_mm,
                   volume, weight_g
            FROM item_characteristics ORDER BY name COLLATE NOCASE
        """)
        rows = []
        for code, name, bc, dims, vol, w in cur.fetchall():
            rows.append({
                "id": code,
                "code": code or "",
                "name": name or "",
                "barcode": bc or "",
                "dims": dims or "",
                "volume": f"{vol:.3f}" if vol is not None else "",
                "weight": f"{w:g}" if w is not None else "",
            })
        return rows
    finally:
        conn.close()


def _build_list(db_path, role, message=None, error=None):
    children = [
        mgmt_header(
            tr("items.title", "Артикулы"),
            [
                button(tr("items.add", "+ Добавить артикул"),
                       "tap", "add_open", style="primary"),
                button(tr("items.btn.refresh", "Обновить"),
                       "tap", "refresh"),
            ]
        )
    ]
    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    children.append(group([
        mgmt_form_field(
            "search", kind="text",
            label=tr("common.search", "Поиск:"),
            label_position="left",
            placeholder=tr("items.search_placeholder",
                           "Фильтр по артикулу, названию, "
                           "штрихкоду…"),
            on_change="input_submit", stretch=True)
    ], orientation="horizontal"))

    children.append(mgmt_table(
        columns=[
            {"key": "code",
             "label": tr("items.col.code", "Артикул"),
             "width": 0.15},
            {"key": "name",
             "label": tr("items.col.name", "Название"),
             "width": 0.3},
            {"key": "barcode",
             "label": tr("items.col.barcode", "Штрихкод"),
             "width": 0.2},
            {"key": "dims",
             "label": tr("items.col.dims", "Габариты"),
             "width": 0.15},
            {"key": "volume",
             "label": tr("items.col.volume", "Объём"),
             "width": 0.1},
            {"key": "weight",
             "label": tr("items.col.weight", "Вес"),
             "width": 0.1},
        ],
        rows=_list_rows(db_path),
        on_double_click={
            "action": "tap", "id": "open_card",
            "value_field": "id"},
        row_key="id",
        empty_label="",
        searchable=False,
    ))
    return mgmt_page("items",
                     tr("items.title", "Артикулы"),
                     children)


def _make_placeholder_image(w, h, txt, bg, fg, border=None):
    pm = QPixmap(w, h)
    pm.fill(QColor(bg))
    painter = QPainter(pm)
    if border:
        painter.setPen(QColor(border))
        painter.drawRect(0, 0, w - 1, h - 1)

    if txt:
        font = QFont()
        font.setPointSize(18 if w > 100 else 14)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(fg))
        painter.drawText(pm.rect(), Qt.AlignCenter, txt)
    painter.end()

    qb = QBuffer()
    qb.open(QIODevice.WriteOnly)
    pm.save(qb, "PNG")
    raw = bytes(qb.data())
    qb.close()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def _get_state(db_path, login):
    key = f"_mgmt_items_edit_state_{login}"
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?", (key,))
        r = cur.fetchone()
        if r and r[0]:
            return json.loads(r[0])
    except Exception:
        pass
    finally:
        conn.close()
    return {"mode": "create", "code": ""}


def _set_state(db_path, login, state):
    key = f"_mgmt_items_edit_state_{login}"
    conn = sqlite3.connect(db_path)
    try:
        val = json.dumps(state)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM settings WHERE key=?", (key,))
        if cur.fetchone():
            cur.execute("UPDATE settings SET value=? WHERE key=?",
                        (val, key))
        else:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?)",
                (key, val))
        conn.commit()
    finally:
        conn.close()


def _temp_save(db_path, b64):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM settings WHERE key='_mgmt_temp_photo'")
        if cur.fetchone():
            cur.execute(
                "UPDATE settings SET value=? "
                "WHERE key='_mgmt_temp_photo'", (b64,))
        else:
            cur.execute(
                "INSERT INTO settings (key, value) "
                "VALUES ('_mgmt_temp_photo', ?)", (b64,))
        conn.commit()
    finally:
        conn.close()


def _temp_take(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM settings "
            "WHERE key='_mgmt_temp_photo'")
        r = cur.fetchone()
        cur.execute(
            "DELETE FROM settings WHERE key='_mgmt_temp_photo'")
        conn.commit()
        if r and r[0]:
            try:
                return base64.b64decode(r[0])
            except Exception:
                return None
        return None
    finally:
        conn.close()


def _temp_clear(db_path):
    _temp_take(db_path)


def _get_photo_b64(db_path, code, login):
    # Temp photo показываем только когда открыт тот же item_code,
    # что и в state, и mode=create/edit. Раньше temp от одного
    # товара «протекал» в карточку другого.
    state = _get_state(db_path, login)
    editing_this = (
        state.get("mode") in ("create", "edit")
        and state.get("code", "") == code
    )
    if editing_this:
        temp_photo = _temp_take(db_path)
        if temp_photo:
            _temp_save(db_path,
                       base64.b64encode(temp_photo).decode("ascii"))
            return ("data:image/png;base64,"
                    + base64.b64encode(temp_photo).decode("ascii"))

    if code:
        blob = load_photo_bytes(db_path, code)
        if blob:
            return ("data:image/png;base64,"
                    + base64.b64encode(blob).decode("ascii"))
    return None


def _build_card(db_path, role, code, login, message=None, error=None,
                mode="view", values=None):
    values = values or {}

    if mode == "create":
        row = (None, None, None, None, None, None)
        title = tr("items.card.new", "Новый артикул")
    else:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT name, description, barcode, dimensions_mm,
                       volume, weight_g
                FROM item_characteristics WHERE item_code=?
            """, (code,))
            row = cur.fetchone()
        finally:
            conn.close()
        if not row:
            return _build_list(
                db_path, role,
                error=tr("items.err.not_found",
                         "Артикул не найден."))
        title = tr("items.card.view",
                   "Артикул: {code}", code=code)

    (name, desc, bc, dims, vol, w) = (row if row else
                                       (None, None, None,
                                        None, None, None))
    L = W = H = ""
    if dims:
        parts = str(dims).lower().replace("х", "x").split("x")
        if len(parts) == 3:
            L, W, H = [p.strip() for p in parts]

    children = []

    header_children = [
        button(tr("items.btn.back", "← Назад"),
               "tap", "back"),
        heading(title),
        {"type": "text", "value": "", "stretch": True},
    ]
    if mode in ("create", "edit"):
        header_children.extend([
            button(tr("items.btn.save", "Сохранить"),
                   "tap", "save", style="primary"),
            button(tr("items.btn.cancel", "Отмена"),
                   "tap", "cancel"),
        ])
    else:
        header_children.extend([
            button(tr("items.btn.edit", "Редактировать"),
                   "tap", "edit", value={"code": code},
                   style="primary"),
            button(tr("items.btn.change_photo", "Сменить фото"),
                   "tap", "photo_upload_click",
                   value={"code": code}),
        ])
    children.append(group(header_children, orientation="horizontal"))

    if message:
        children.append(card([text(message)], accent="success"))
    if error:
        children.append(card([text(error)], accent="error"))

    photo_b64 = _get_photo_b64(db_path, code, login)

    left_col = []
    if photo_b64:
        left_col.append(mgmt_image(photo_b64, width=300, height=300))
    else:
        ph_b64 = _make_placeholder_image(
            300, 300,
            tr("items.card.no_photo", "НЕТ ФОТО"),
            "#34495e", "#95a5a6", "#5d7288")
        left_col.append(mgmt_image(ph_b64, width=300, height=300))

    if mode in ("create", "edit"):
        left_col.append(group([
            mgmt_file_trigger(
                "photo",
                tr("items.btn.upload_photo", "Загрузить фото"),
                accept="Images (*.png *.jpg *.jpeg *.bmp)",
                action="upload",
                action_id="photo_upload"),
            button(tr("items.btn.delete_photo", "Удалить фото"),
                   "tap", "photo_remove"),
        ], orientation="horizontal", spacing=8))

    left_col.append(group([], orientation="vertical", stretch=True))

    right_col = []
    if mode in ("create", "edit"):
        def get_val(k, default):
            return values.get(k, default)

        current_bc = get_val("barcode", bc or "")

        bc_img_b64 = None
        if current_bc:
            pix = make_barcode_pixmap(current_bc, 280, 80)
            if pix:
                qb = QBuffer()
                qb.open(QIODevice.WriteOnly)
                pix.save(qb, "PNG")
                raw = bytes(qb.data())
                qb.close()
                bc_img_b64 = ("data:image/png;base64,"
                              + base64.b64encode(raw).decode("ascii"))

        if bc_img_b64:
            bc_widget = mgmt_image(bc_img_b64, width=280, height=80)
        else:
            ph_b64 = _make_placeholder_image(
                280, 80, "—", "white", "#95a5a6", "#ddd")
            bc_widget = mgmt_image(ph_b64, width=280, height=80)

        # FIX: объём считается в реальном времени.
        # Если пользователь редактирует хотя бы одно из полей
        # (length/width/height), используем ТОЛЬКО values — иначе
        # при очистке поля показывалось бы старое значение из БД.
        # Если values пусто — берём из БД (view/edit initial).
        _editing_dims = any(
            k in values for k in ("length", "width", "height")
        )
        if _editing_dims:
            current_vol = None
        else:
            current_vol = vol

        Lf = _num_to_float(get_val("length", L))
        Wf = _num_to_float(get_val("width", W))
        Hf = _num_to_float(get_val("height", H))
        if Lf and Wf and Hf:
            current_vol = Lf * Wf * Hf / 1_000_000.0

        fields = [
            mgmt_form_field(
                "name", kind="text",
                label=tr("items.card.name", "Название*:"),
                label_position="left", label_width=150,
                stretch=True,
                value=get_val("name", name or "")),
            mgmt_form_field(
                "item_code", kind="text",
                label=tr("items.card.code", "Артикул*:"),
                label_position="left", label_width=150,
                stretch=True,
                value=get_val("item_code", code or "")
                      if mode == "create" else code,
                read_only=(mode == "edit")),
            mgmt_form_field(
                "barcode", kind="text",
                label=tr("items.card.barcode", "Штрихкод*:"),
                label_position="left", label_width=150,
                stretch=True,
                value=current_bc, on_change="instant"),
            group([
                text(tr("items.card.barcode_img",
                        "ШК<br>(изображение):"),
                     size=13, width=150),
                bc_widget
            ], orientation="horizontal", spacing=8),
            mgmt_form_field(
                "length", kind="text",
                label=tr("items.card.length", "Длина (мм):"),
                label_position="left", label_width=150,
                stretch=True,
                value=get_val("length", L),
                on_change="instant"),
            mgmt_form_field(
                "width", kind="text",
                label=tr("items.card.width", "Ширина (мм):"),
                label_position="left", label_width=150,
                stretch=True,
                value=get_val("width", W),
                on_change="instant"),
            mgmt_form_field(
                "height", kind="text",
                label=tr("items.card.height", "Высота (мм):"),
                label_position="left", label_width=150,
                stretch=True,
                value=get_val("height", H),
                on_change="instant"),
            mgmt_form_field(
                "weight", kind="text",
                label=tr("items.card.weight", "Вес (г):"),
                label_position="left", label_width=150,
                stretch=True,
                value=get_val("weight",
                              str(w) if w is not None else "")),
        ]

        fields.append(group([
            text(tr("items.card.volume", "<b>Объём (л):</b>"),
                 width=150),
            text(f"{current_vol:.3f}"
                 if current_vol is not None else "-")
        ], orientation="horizontal", spacing=8))

        right_col.append(card(fields,
                              title=tr("items.card.params",
                                       "Параметры")))

        desc_card = card([
            mgmt_form_field(
                "description", kind="textarea",
                label=None, stretch=True,
                value=get_val("description", desc or ""))
        ], title=tr("items.card.desc", "Описание"))
        right_col.append(desc_card)
    else:
        bc_img_b64 = None
        if bc:
            pix = make_barcode_pixmap(bc, 280, 80)
            if pix:
                qb = QBuffer()
                qb.open(QIODevice.WriteOnly)
                pix.save(qb, "PNG")
                raw = bytes(qb.data())
                qb.close()
                bc_img_b64 = ("data:image/png;base64,"
                              + base64.b64encode(raw).decode("ascii"))

        if bc_img_b64:
            bc_widget = mgmt_image(bc_img_b64, width=280, height=80)
        else:
            ph_b64 = _make_placeholder_image(
                280, 80, "—", "white", "#95a5a6", "#ddd")
            bc_widget = mgmt_image(ph_b64, width=280, height=80)

        fields = [
            mgmt_form_field(
                "name", kind="text",
                label=tr("items.card.name", "Название:"),
                label_position="left", label_width=150,
                stretch=True, value=name or "", read_only=True),
            mgmt_form_field(
                "item_code", kind="text",
                label=tr("items.card.code", "Артикул:"),
                label_position="left", label_width=150,
                stretch=True, value=code, read_only=True),
            mgmt_form_field(
                "barcode", kind="text",
                label=tr("items.card.barcode", "Штрихкод:"),
                label_position="left", label_width=150,
                stretch=True, value=bc or "", read_only=True),
            group([
                text(tr("items.card.barcode_img",
                        "ШК<br>(изображение):"),
                     size=13, width=150),
                bc_widget
            ], orientation="horizontal", spacing=8),
            mgmt_form_field(
                "length", kind="text",
                label=tr("items.card.length", "Длина (мм):"),
                label_position="left", label_width=150,
                stretch=True, value=L, read_only=True),
            mgmt_form_field(
                "width", kind="text",
                label=tr("items.card.width", "Ширина (мм):"),
                label_position="left", label_width=150,
                stretch=True, value=W, read_only=True),
            mgmt_form_field(
                "height", kind="text",
                label=tr("items.card.height", "Высота (мм):"),
                label_position="left", label_width=150,
                stretch=True, value=H, read_only=True),
            mgmt_form_field(
                "weight", kind="text",
                label=tr("items.card.weight", "Вес (г):"),
                label_position="left", label_width=150,
                stretch=True,
                value=str(w) if w is not None else "",
                read_only=True),
            group([
                text(tr("items.card.volume", "<b>Объём (л):</b>"),
                     width=150),
                text(f"{vol:.3f}" if vol is not None else "-")
            ], orientation="horizontal", spacing=8)
        ]
        right_col.append(card(fields,
                              title=tr("items.card.params",
                                       "Параметры")))

        desc_card = card([
            mgmt_form_field(
                "description", kind="textarea",
                label=None, stretch=True,
                value=desc or "", read_only=True)
        ], title=tr("items.card.desc", "Описание"))
        right_col.append(desc_card)

    body = group([
        group(left_col, orientation="vertical"),
        group(right_col, orientation="vertical", stretch=True)
    ], orientation="horizontal", spacing=20)

    children.append(body)

    return mgmt_page("items", title, children)


def build_view(login, role, context):
    return _doc(_build_list(context.db_path, role), role)


def handle_action(action, action_id, value, login, role,
                  context, values=None):
    values = values or {}
    db_path = context.db_path

    if action == "input_submit" and action_id == "search":
        return {"ok": True, "view": _doc(
            _build_list(db_path, role), role)}

    # FIX: пересчитываем объём при вводе в любое из размерных полей
    # (и при вводе ШК — чтобы превью ШК обновлялось).
    if action == "input_submit" and action_id in (
            "barcode", "length", "width", "height"):
        state = _get_state(db_path, login)
        mode = state.get("mode", "create")
        code = state.get("code", "")
        return {"ok": True, "view": _doc(_build_card(
            db_path, role, code, login,
            mode=mode, values=values), role)}

    if action == "upload" and action_id == "photo_upload":
        if isinstance(value, dict) and value.get("b64"):
            _temp_save(db_path, value["b64"])
        state = _get_state(db_path, login)
        mode = state.get("mode", "create")
        code = state.get("code", "")
        return {"ok": True,
                "message": tr("items.msg.photo_loaded",
                              "Фото загружено"),
                "view": _doc(_build_card(
                    db_path, role, code, login, mode=mode,
                    values=values), role)}

    if action == "tap":
        if action_id == "add_open":
            _set_state(db_path, login,
                       {"mode": "create", "code": ""})
            _temp_clear(db_path)
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, "", login, mode="create"), role)}
        if action_id in ("refresh", "back", "cancel"):
            _temp_clear(db_path)
            return {"ok": True, "view": _doc(
                _build_list(db_path, role), role)}
        if action_id == "open_card":
            _temp_clear(db_path)
            code = str(value or "")
            _set_state(db_path, login,
                       {"mode": "view", "code": code})
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, code, login), role)}
        if action_id == "edit":
            _temp_clear(db_path)
            code = value.get("code") if isinstance(value, dict) else None
            if not code:
                return {"ok": False,
                        "error": tr("items.err.bad_id",
                                    "bad code")}
            _set_state(db_path, login,
                       {"mode": "edit", "code": code})
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, code, login, mode="edit",
                values=values), role)}
        if action_id == "photo_upload_click":
            code = value.get("code") if isinstance(value, dict) else None
            if code:
                _set_state(db_path, login,
                           {"mode": "edit", "code": code})
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, code, login, mode="edit",
                values=values), role)}
        if action_id == "photo_remove":
            _temp_clear(db_path)
            state = _get_state(db_path, login)
            mode = state.get("mode", "create")
            code = state.get("code", "")
            if mode == "edit" and code:
                delete_photo(db_path, code)
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, code, login, mode=mode,
                values=values), role)}
        if action_id == "save":
            state = _get_state(db_path, login)
            mode = state.get("mode", "create")
            code = state.get("code", "")
            return _save(db_path, role, values, mode, code,
                         login)

    return {"ok": False,
            "error": tr("items.err.unknown_action",
                        "unknown action: {id}", id=action_id)}


def _save(db_path, role, values, mode, original_code, login):
    code = str(values.get("item_code") or "").strip()
    name = str(values.get("name") or "").strip()
    bc = str(values.get("barcode") or "").strip()
    L = str(values.get("length") or "").strip()
    W = str(values.get("width") or "").strip()
    H = str(values.get("height") or "").strip()
    weight_raw = str(values.get("weight") or "").strip()
    desc = str(values.get("description") or "").strip()

    if not name or not code or not bc:
        return {"ok": True, "view": _doc(_build_card(
            db_path, role, original_code, login, mode=mode,
            values=values,
            error=tr(
                "items.err.fill_required",
                "Заполните обязательные поля "
                "(Название, Артикул, Штрихкод)")), role)}

    weight = None
    if weight_raw:
        try:
            weight = float(weight_raw.replace(",", "."))
        except ValueError:
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, original_code, login,
                mode=mode, values=values,
                error=tr("items.err.weight_number",
                         "Вес должен быть числом.")), role)}

    # FIX: проверяем, что размеры — числа (раньше молча писался
    # volume=NULL, пользователь не понимал, почему объёма нет).
    if not all(_is_number_or_empty(x) for x in (L, W, H)):
        return {"ok": True, "view": _doc(_build_card(
            db_path, role, original_code, login,
            mode=mode, values=values,
            error=tr("items.err.dim_number",
                     "Длина, ширина и высота должны быть "
                     "числами.")), role)}

    Lf = _num_to_float(L)
    Wf = _num_to_float(W)
    Hf = _num_to_float(H)

    if Lf and Wf and Hf:
        dims = f"{_fmt_dim(Lf)}x{_fmt_dim(Wf)}x{_fmt_dim(Hf)}"
        volume = Lf * Wf * Hf / 1_000_000.0
    elif L or W or H:
        dims = f"{L or 0}x{W or 0}x{H or 0}"
        volume = None
    else:
        dims = ""
        volume = None

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()

        if mode == "create":
            cur.execute(
                "SELECT 1 FROM item_characteristics "
                "WHERE item_code=?", (code,))
            if cur.fetchone():
                return {"ok": True, "view": _doc(_build_card(
                    db_path, role, code, login,
                    mode="create", values=values,
                    error=tr("items.err.code_exists",
                             "Такой артикул уже существует.")),
                    role)}
        else:
            if code != original_code:
                return {"ok": True, "view": _doc(_build_card(
                    db_path, role, original_code, login,
                    mode="edit", values=values,
                    error=tr(
                        "items.err.cant_change_code",
                        "Нельзя изменить артикул "
                        "при редактировании")), role)}

        cur.execute(
            "SELECT item_code FROM item_characteristics "
            "WHERE barcode=?", (bc,))
        r = cur.fetchone()
        if r and r[0] != original_code:
            return {"ok": True, "view": _doc(_build_card(
                db_path, role, original_code, login,
                mode=mode, values=values,
                error=tr(
                    "items.err.barcode_exists",
                    "Этот штрихкод уже используется "
                    "другим артикулом")), role)}

        if mode == "create":
            cur.execute("""
                INSERT INTO item_characteristics
                    (name, description, barcode, dimensions_mm,
                     volume, weight_g, item_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, desc, bc, dims, volume, weight, code))
        else:
            cur.execute("""
                UPDATE item_characteristics SET
                    name=?, description=?, barcode=?,
                    dimensions_mm=?, volume=?, weight_g=?
                WHERE item_code=?
            """, (name, desc, bc, dims, volume, weight,
                  original_code))
        conn.commit()
    finally:
        conn.close()

    temp_photo = _temp_take(db_path)
    if temp_photo:
        try:
            save_photo_bytes(db_path, code,
                             detect_mime(temp_photo), temp_photo)
        except Exception:
            pass

    _set_state(db_path, login, {"mode": "view", "code": code})
    return {"ok": True,
            "message": tr("items.msg.saved",
                          "Сохранён {code}", code=code),
            "view": _doc(_build_card(db_path, role, code, login),
                         role)}