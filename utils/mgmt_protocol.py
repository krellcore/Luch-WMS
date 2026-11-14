"""Протокол view-модели для ПК-клиента управления складом."""

PROTOCOL_VERSION = "1.0"

BASE_TYPES = {
    "text", "heading", "caption",
    "card", "group", "divider", "spacer",
    "progress", "button",
}

MGMT_TYPES = {
    "mgmt_page", "mgmt_sidebar", "mgmt_toolbar",
    "mgmt_table", "mgmt_form_field", "mgmt_dialog",
    "mgmt_breadcrumb", "mgmt_file_trigger", "mgmt_badge",
    "mgmt_html", "mgmt_image", "mgmt_header",
}

MGMT_WIDGETS = sorted(BASE_TYPES | MGMT_TYPES)


class MgmtError(ValueError):
    pass


def text(value, bold=False, color=None, size=0, align=None, width=0):
    d = {"type": "text", "value": str(value)}
    style = {}
    if bold:
        style["bold"] = True
    if color:
        style["color"] = str(color)
    if size:
        style["size"] = int(size)
    if align:
        style["align"] = str(align)
    if style:
        d["style"] = style
    if width > 0:
        d["width"] = int(width)
    return d


def heading(value, level=1):
    return {"type": "heading", "value": str(value),
            "level": int(level)}


def caption(value):
    return {"type": "caption", "value": str(value)}


def card(children, title=None, accent=None):
    d = {"type": "card", "children": list(children or [])}
    if title:
        d["title"] = str(title)
    if accent:
        d["accent"] = str(accent)
    return d


def group(children, orientation="vertical", spacing=8, stretch=False):
    d = {
        "type": "group",
        "orientation": str(orientation),
        "spacing": int(spacing),
        "children": list(children or []),
    }
    if stretch:
        d["stretch"] = True
    return d


def divider():
    return {"type": "divider"}


def spacer(size=8):
    return {"type": "spacer", "size": int(size)}


def progress(value, max_value, label=None):
    d = {"type": "progress",
         "value": int(value), "max": int(max_value)}
    if label:
        d["label"] = str(label)
    return d


def button(label, action, action_id=None, value=None,
           style="default", enabled=True, align="right"):
    d = {
        "type": "button",
        "label": str(label),
        "action": str(action),
        "style": str(style),
        "enabled": bool(enabled),
        "align": str(align),
    }
    if action_id is not None:
        d["id"] = str(action_id)
    if value is not None:
        d["value"] = value
    return d


def mgmt_header(title, actions=None):
    return {
        "type": "mgmt_header",
        "title": str(title),
        "actions": list(actions or []),
    }


def mgmt_badge(label, accent="info"):
    return {
        "type": "mgmt_badge",
        "label": str(label),
        "accent": str(accent),
    }


def mgmt_sidebar(items):
    return {
        "type": "mgmt_sidebar",
        "items": [
            {
                "key": it.get("key", ""),
                "title": it.get("title", ""),
                "badge": int(it.get("badge") or 0),
                "enabled": bool(it.get("enabled", True)),
            }
            for it in (items or [])
        ],
    }


def mgmt_page(key, title, children):
    return {
        "type": "mgmt_page",
        "key": str(key),
        "title": str(title),
        "children": list(children or []),
    }


def mgmt_toolbar(buttons):
    return {
        "type": "mgmt_toolbar",
        "buttons": list(buttons or []),
    }


def mgmt_table(columns, rows, on_double_click=None,
               selection_mode="single", searchable=True,
               row_key=None, empty_label="(пусто)", editable=False,
               field_id=None, search_placeholder=None):
    d = {
        "type": "mgmt_table",
        "columns": list(columns or []),
        "rows": list(rows or []),
        "on_double_click": on_double_click or {},
        "selection_mode": str(selection_mode),
        "searchable": bool(searchable),
        "row_key": str(row_key or "id"),
        "empty_label": str(empty_label),
        "editable": bool(editable),
        "field_id": str(field_id or ""),
    }
    if search_placeholder:
        d["search_placeholder"] = str(search_placeholder)
    return d


def mgmt_form_field(field_id, kind="text", label=None, value=None,
                    options=None, required=False, read_only=False,
                    placeholder=None, on_change=None,
                    min_value=None, max_value=None,
                    label_position="top", stretch=False, width=0,
                    label_width=0):
    d = {
        "type": "mgmt_form_field",
        "id": str(field_id),
        "kind": str(kind),
        "required": bool(required),
        "read_only": bool(read_only),
        "label_position": str(label_position),
        "stretch": bool(stretch),
    }
    if label is not None:
        d["label"] = str(label)
    if value is not None:
        d["value"] = value
    if options is not None:
        d["options"] = list(options)
    if placeholder is not None:
        d["placeholder"] = str(placeholder)
    if on_change:
        d["on_change"] = str(on_change)
    if min_value is not None:
        d["min"] = int(min_value)
    if max_value is not None:
        d["max"] = int(max_value)
    if width > 0:
        d["width"] = int(width)
    if label_width > 0:
        d["label_width"] = int(label_width)
    return d


def mgmt_dialog(dialog_id, title, children,
                panel_kind="dialog", buttons=None):
    return {
        "type": "mgmt_dialog",
        "id": str(dialog_id),
        "title": str(title),
        "panel_kind": str(panel_kind),
        "buttons": list(buttons or []),
        "children": list(children or []),
    }


def mgmt_breadcrumb(items=None, on_navigate=None, parts=None):
    if items is None:
        items = [{"label": str(p)} for p in (parts or [])]
    return {
        "type": "mgmt_breadcrumb",
        "items": [
            {
                "label": str(it.get("label", "")),
                "value": it.get("value"),
            }
            for it in items
        ],
        "on_navigate": on_navigate or {
            "action": "tap", "id": "navigate"},
    }


def mgmt_file_trigger(trigger_id, label, accept=None,
                      action="upload", action_id=None,
                      download_b64=None, filename=None,
                      style="default"):
    d = {
        "type": "mgmt_file_trigger",
        "id": str(trigger_id),
        "label": str(label),
        "action": str(action),
        "style": str(style),
    }
    if accept:
        d["accept"] = str(accept)
    if action_id is not None:
        d["action_id"] = str(action_id)
    if download_b64 is not None:
        d["download_b64"] = str(download_b64)
    if filename is not None:
        d["filename"] = str(filename)
    return d


def mgmt_html(html, width=0, height=0):
    d = {
        "type": "mgmt_html",
        "html": str(html),
    }
    if width:
        d["width"] = int(width)
    if height:
        d["height"] = int(height)
    return d


def mgmt_image(src, width=0, height=0):
    d = {"type": "mgmt_image", "src": str(src)}
    if width:
        d["width"] = int(width)
    if height:
        d["height"] = int(height)
    return d


def make_mgmt_document(page, sidebar=None, extra=None):
    doc = {
        "protocol": PROTOCOL_VERSION,
        "screen": "mgmt_page",
        "page": page,
    }
    if sidebar is not None:
        doc["sidebar"] = sidebar
    if extra:
        doc.update(extra)
    return doc


def make_login_document(login, role, sidebar=None):
    doc = {
        "protocol": PROTOCOL_VERSION,
        "screen": "mgmt_login_ok",
        "login": str(login),
        "role": str(role),
    }
    if sidebar is not None:
        doc["sidebar"] = sidebar
    return doc


def _validate_node(node):
    if not isinstance(node, dict):
        raise MgmtError(f"узел не dict: {type(node)}")
    t = node.get("type")
    if t not in BASE_TYPES and t not in MGMT_TYPES:
        raise MgmtError(f"неизвестный тип узла: {t}")
    for c in node.get("children", []) or []:
        _validate_node(c)
    for b in node.get("buttons", []) or []:
        if isinstance(b, dict):
            _validate_node(b)
    for a in node.get("actions", []) or []:
        if isinstance(a, dict):
            _validate_node(a)


def validate_document(doc):
    if not isinstance(doc, dict):
        raise MgmtError("документ не dict")
    if doc.get("protocol") != PROTOCOL_VERSION:
        raise MgmtError(
            f"protocol mismatch: {doc.get('protocol')}")
    screen = doc.get("screen")
    if screen not in ("mgmt_page", "mgmt_login_ok"):
        raise MgmtError(f"неизвестный screen: {screen}")
    page = doc.get("page")
    if screen == "mgmt_page":
        if not isinstance(page, dict) or \
                page.get("type") != "mgmt_page":
            raise MgmtError("mgmt_page отсутствует")
        _validate_node(page)
    sb = doc.get("sidebar")
    if sb is not None and isinstance(sb, dict):
        if sb.get("type") != "mgmt_sidebar":
            raise MgmtError("sidebar должен быть mgmt_sidebar")
    return True