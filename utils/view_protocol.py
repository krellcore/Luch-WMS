"""View model protocol for clients.

Client knows nothing about the domain. It receives a tree of
components (ViewNode) and renders it. Each node is a simple dict:
{"type": "...", ...fields}.

Actions (client -> server):
  {"action": "scan", "value": "BC-..."}
  {"action": "tap", "id": "btn_confirm"}
  {"action": "input_submit", "id": "input_qty", "value": "3"}
  {"action": "cancel"}
  {"action": "custom:my_id", "value": ...}

Protocol version: 1.0
"""

PROTOCOL_VERSION = "1.0"

NODE_TYPES = {
    "text", "heading", "caption",
    "card", "group", "divider", "spacer",
    "progress", "button", "input",
    "list", "tiles", "image", "barcode",
    "slot", "webview", "table",
}

ACTION_TYPES = {
    "scan", "tap", "input_submit", "cancel",
}

FEATURE_NAMES = {
    "camera", "hardware_scan", "vibrate", "beep",
    "flash", "webview", "assets",
}


class ViewError(ValueError):
    pass


class ViewNode:
    __slots__ = ("type", "data", "children")

    def __init__(self, node_type, data=None, children=None):
        if node_type not in NODE_TYPES:
            raise ViewError(f"неизвестный тип узла: {node_type}")
        self.type = node_type
        self.data = dict(data or {})
        self.children = list(children or [])

    def to_dict(self):
        out = {"type": self.type}
        out.update(self.data)
        if self.children:
            out["children"] = [c.to_dict() for c in self.children
                               if isinstance(c, ViewNode)]
        return out

    @staticmethod
    def text(value, style=None):
        d = {"value": str(value)}
        if style:
            d["style"] = dict(style)
        return ViewNode("text", d)

    @staticmethod
    def heading(value, level=1):
        return ViewNode("heading", {"value": str(value),
                                    "level": int(level)})

    @staticmethod
    def caption(value):
        return ViewNode("caption", {"value": str(value)})

    @staticmethod
    def card(children, title=None, accent=None):
        d = {}
        if title:
            d["title"] = str(title)
        if accent:
            d["accent"] = str(accent)
        return ViewNode("card", d, children)

    @staticmethod
    def group(children, orientation="vertical", spacing=None):
        d = {"orientation": orientation}
        if spacing is not None:
            d["spacing"] = int(spacing)
        return ViewNode("group", d, children)

    @staticmethod
    def divider():
        return ViewNode("divider")

    @staticmethod
    def spacer(size=8):
        return ViewNode("spacer", {"size": int(size)})

    @staticmethod
    def progress(value, max_value, label=None):
        d = {"value": int(value), "max": int(max_value)}
        if label:
            d["label"] = str(label)
        return ViewNode("progress", d)

    @staticmethod
    def button(label, action, action_id=None, value=None,
               style="default", enabled=True):
        d = {
            "label": str(label),
            "action": str(action),
            "enabled": bool(enabled),
            "style": str(style),
        }
        if action_id is not None:
            d["id"] = str(action_id)
        if value is not None:
            d["value"] = value
        return ViewNode("button", d)

    @staticmethod
    def input(field_id, input_type="text", label=None,
              value=None, options=None):
        d = {"id": str(field_id), "input_type": str(input_type)}
        if label:
            d["label"] = str(label)
        if value is not None:
            d["value"] = value
        if options is not None:
            d["options"] = list(options)
        return ViewNode("input", d)

    @staticmethod
    def list_items(items, item_renderer="default"):
        return ViewNode("list", {"item_renderer": item_renderer},
                        [ViewNode("text", {"value": str(x)})
                         for x in items])

    @staticmethod
    def tiles(items):
        return ViewNode("tiles", {"items": list(items)})

    @staticmethod
    def table(columns, rows, title=None):
        d = {"columns": list(columns), "rows": list(rows)}
        if title:
            d["title"] = str(title)
        return ViewNode("table", d)

    @staticmethod
    def image(url, width=None, height=None):
        d = {"url": str(url)}
        if width:
            d["width"] = int(width)
        if height:
            d["height"] = int(height)
        return ViewNode("image", d)

    @staticmethod
    def barcode(code, label=None):
        d = {"value": str(code)}
        if label:
            d["label"] = str(label)
        return ViewNode("barcode", d)

    @staticmethod
    def slot(slot_id, children=None):
        return ViewNode("slot", {"id": str(slot_id)},
                        children or [])

    @staticmethod
    def webview(html, height=None):
        d = {"html": str(html)}
        if height:
            d["height"] = int(height)
        return ViewNode("webview", d)


def make_document(nodes, screen_id=None, title=None):
    doc = {
        "protocol": PROTOCOL_VERSION,
        "screen": screen_id or "default",
        "children": [n.to_dict() if isinstance(n, ViewNode) else n
                     for n in nodes],
    }
    if title:
        doc["title"] = str(title)
    return doc


def validate(node):
    if isinstance(node, ViewNode):
        for c in node.children:
            validate(c)
        return True
    if isinstance(node, dict):
        t = node.get("type")
        if t not in NODE_TYPES:
            raise ViewError(f"неизвестный тип узла в дереве: {t}")
        for c in node.get("children", []) or []:
            validate(c)
        return True
    raise ViewError(f"неподдерживаемый узел: {type(node)}")


def degrade(node, capabilities):
    if isinstance(node, dict):
        node = dict(node)
        t = node.get("type")
        if t == "tiles" and not capabilities.supports("tiles"):
            items = node.get("items", [])
            labels = [it.get("label") or it.get("barcode", "")
                      for it in items]
            return {"type": "list",
                    "item_renderer": "default",
                    "children": [{"type": "text", "value": str(x)}
                                 for x in labels]}
        if t == "table" and not capabilities.supports("table"):
            cols = node.get("columns", [])
            rows = node.get("rows", [])
            out = []
            for r in rows:
                parts = []
                for c in cols:
                    key = c.get("key")
                    label = c.get("label", key)
                    val = r.get(key, "")
                    if c.get("type") == "image":
                        continue
                    parts.append(f"{label}: {val}")
                out.append({"type": "text",
                            "value": " / ".join(parts)})
            return {"type": "list",
                    "item_renderer": "default",
                    "children": out}
        if t == "webview" and not capabilities.supports("webview"):
            return {"type": "text",
                    "value": "(webview недоступен)"}
        if t == "barcode" and not capabilities.supports("barcode"):
            return {"type": "text",
                    "value": node.get("value", "")}
        if t == "image" and not capabilities.supports("image"):
            return {"type": "text",
                    "value": node.get("url", "(изображение)")}
        if "children" in node and node["children"]:
            node["children"] = [degrade(c, capabilities)
                                for c in node["children"]]
        return node
    if isinstance(node, ViewNode):
        return degrade(node.to_dict(), capabilities)
    return node


def degrade_document(doc, capabilities):
    if not isinstance(doc, dict):
        return doc
    out = dict(doc)
    out["children"] = [degrade(c, capabilities)
                       for c in doc.get("children", [])]
    return out