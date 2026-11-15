"""Qt-рендерер mgmt view-документов."""

import os
import base64

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTextBrowser, QProgressBar, QLineEdit, QSpinBox,
    QComboBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QDialog, QTextEdit,
    QFileDialog, QGroupBox, QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QFont, QPixmap


STRETCH_PROP = "mgmt_stretch"


def _mark_stretch(widget):
    widget.setProperty(STRETCH_PROP, True)
    widget.setSizePolicy(QSizePolicy.Expanding,
                         QSizePolicy.Expanding)
    return widget


def _has_stretch(node):
    if not isinstance(node, dict):
        return False
    if node.get("stretch"):
        return True
    return node.get("type") == "mgmt_table"


class MgmtRenderer(QWidget):
    action_clicked = Signal(str, str, object, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(12)
        self._fields = {}
        self._tables = {}
        self._dialogs = []

    def set_document(self, doc):
        focused_fid = None
        cursor_pos = 0
        fw = QApplication.focusWidget()
        if fw:
            for fid, w in self._fields.items():
                if w == fw:
                    focused_fid = fid
                    if hasattr(w, 'cursorPosition'):
                        cursor_pos = w.cursorPosition()
                    break

        for dlg in self._dialogs:
            try:
                dlg.blockSignals(True)
                dlg.close()
                dlg.deleteLater()
            except Exception:
                pass
        self._dialogs = []
        self._fields = {}
        self._tables = {}

        while self._layout.count():
            it = self._layout.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

        page = doc.get("page") if isinstance(doc, dict) else None
        if not isinstance(page, dict):
            self._layout.addWidget(QLabel("(пустой документ)"))
            return

        children = page.get("children") or []
        any_stretch = any(_has_stretch(c) for c in children)

        for c in children:
            w = self._render(c)
            if w is None:
                continue
            stretch = 1 if _has_stretch(c) else 0
            self._layout.addWidget(w, stretch)

        if not any_stretch:
            self._layout.addStretch()

        for c in children:
            if isinstance(c, dict) and c.get("type") == "mgmt_dialog":
                self._open_dialog(c)

        if focused_fid and focused_fid in self._fields:
            new_w = self._fields[focused_fid]
            def _restore():
                try:
                    new_w.setFocus(Qt.OtherFocusReason)
                    if hasattr(new_w, 'setCursorPosition'):
                        new_w.setCursorPosition(cursor_pos)
                except Exception:
                    pass
            QTimer.singleShot(0, _restore)

    def collect_values(self):
        values = {}
        for fid, w in self._fields.items():
            try:
                if isinstance(w, QComboBox):
                    values[fid] = w.currentData()
                elif isinstance(w, QSpinBox):
                    values[fid] = w.value()
                elif isinstance(w, QCheckBox):
                    values[fid] = w.isChecked()
                elif isinstance(w, QTextEdit):
                    values[fid] = w.toPlainText()
                elif isinstance(w, QLineEdit):
                    values[fid] = w.text()
            except Exception:
                pass

        for fid, (table, n) in self._tables.items():
            cols = n.get("columns") or []
            rows = []
            for r in range(table.rowCount()):
                row = {}
                for c_idx, c in enumerate(cols):
                    key = c.get("key") or ""
                    item = table.item(r, c_idx)
                    row[key] = item.text() if item else ""
                rows.append(row)
            values[fid] = rows

            selected = []
            sel_model = table.selectionModel()
            if sel_model:
                for idx in sel_model.selectedRows():
                    row_dict = {}
                    for c_idx, c in enumerate(cols):
                        key = c.get("key") or ""
                        item = table.item(idx.row(), c_idx)
                        row_dict[key] = item.text() if item else ""
                    selected.append(row_dict)
            values[fid + "_selected"] = selected

        return values

    def _render(self, node):
        if not isinstance(node, dict):
            return None
        t = node.get("type")
        try:
            if t == "text":            return self._node_text(node)
            if t == "heading":         return self._node_heading(node)
            if t == "caption":         return self._node_caption(node)
            if t == "card":            return self._node_card(node)
            if t == "group":           return self._node_group(node)
            if t == "divider":         return self._node_divider()
            if t == "spacer":          return self._node_spacer(node)
            if t == "progress":        return self._node_progress(node)
            if t == "button":          return self._node_button(node)
            if t == "mgmt_html":       return self._node_html(node)
            if t == "mgmt_image":      return self._node_image(node)
            if t == "mgmt_badge":      return self._node_badge(node)
            if t == "mgmt_toolbar":    return self._node_toolbar(node)
            if t == "mgmt_header":     return self._node_header(node)
            if t == "mgmt_form_field": return self._node_form_field(node)
            if t == "mgmt_table":      return self._node_table(node)
            if t == "mgmt_breadcrumb": return self._node_breadcrumb(node)
            if t == "mgmt_file_trigger":
                return self._node_file_trigger(node)
            if t == "mgmt_dialog":
                return None
        except Exception as e:
            print(f"[mgmt_render] {t}: {e}")
        return QLabel(f"[{t}]")

    def _node_header(self, n):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)

        title = QLabel(n.get("title", ""))
        f = QFont("Arial", 16)
        f.setBold(True)
        title.setFont(f)
        h.addWidget(title)
        h.addStretch()

        for action in n.get("actions") or []:
            aw = self._render(action)
            if aw is not None:
                h.addWidget(aw)
        return w

    def _node_text(self, n):
        style = n.get("style") or {}
        lbl = QLabel(str(n.get("value", "")))
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        f = QFont("Arial")
        if style.get("bold"):
            f.setBold(True)
        size = int(style.get("size") or 0)
        if size > 0:
            f.setPointSize(size)
        lbl.setFont(f)
        if style.get("color"):
            lbl.setStyleSheet(f"color:{style['color']};")

        align = style.get("align")
        if align == "center":
            lbl.setAlignment(Qt.AlignCenter)
        elif align == "right":
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        w = int(n.get("width") or 0)
        if w > 0:
            lbl.setFixedWidth(w)

        return lbl

    def _node_heading(self, n):
        lbl = QLabel(str(n.get("value", "")))
        lbl.setWordWrap(True)
        level = int(n.get("level") or 1)
        size = 16 if level == 1 else 14 if level == 2 else 12
        f = QFont("Arial", size)
        f.setBold(True)
        lbl.setFont(f)
        return lbl

    def _node_caption(self, n):
        lbl = QLabel(str(n.get("value", "")))
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#7f8c8d; font-size:11px;")
        return lbl

    def _node_card(self, n):
        title = n.get("title") or ""
        frame = QGroupBox(title)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        children = n.get("children") or []
        any_stretch = any(_has_stretch(c) for c in children)
        for c in children:
            w = self._render(c)
            if w is None:
                continue
            stretch = 1 if _has_stretch(c) else 0
            layout.addWidget(w, stretch)

        if _has_stretch(n) and not any_stretch:
            layout.addStretch()
        return frame

    def _node_group(self, n):
        w = QWidget()
        is_horiz = n.get("orientation") == "horizontal"
        layout = QHBoxLayout(w) if is_horiz else QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(int(n.get("spacing") or 8))

        children = n.get("children") or []
        any_stretch = any(_has_stretch(c) for c in children)
        for c in children:
            cw = self._render(c)
            if cw is None:
                continue
            stretch = 1 if _has_stretch(c) else 0
            layout.addWidget(cw, stretch)

        if is_horiz and not any_stretch:
            layout.addStretch()

        return w

    def _node_divider(self):
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color:#dcdcdc;")
        return line

    def _node_spacer(self, n):
        w = QWidget()
        w.setFixedHeight(int(n.get("size") or 8))
        return w

    def _node_progress(self, n):
        pb = QProgressBar()
        mx = int(n.get("max") or 0) or 100
        pb.setRange(0, mx)
        pb.setValue(int(n.get("value") or 0))
        label = n.get("label")
        if label:
            pb.setFormat(label)
        pb.setTextVisible(bool(label))
        return pb

    def _node_button(self, n):
        btn = QPushButton(n.get("label") or "OK")
        btn.setEnabled(bool(n.get("enabled", True)))
        btn.setCursor(Qt.PointingHandCursor)
        style = n.get("style") or "default"
        if style == "primary":
            btn.setObjectName("primary_btn")
        elif style == "danger":
            btn.setObjectName("danger_btn")
        action = n.get("action") or "tap"
        action_id = n.get("id") or ""
        value = n.get("value")

        def _on_click():
            self._emit_action(action, action_id, value)

        btn.clicked.connect(_on_click)
        return btn

    def _emit_action(self, action, action_id, value):
        values = self.collect_values()
        try:
            self.action_clicked.emit(action, action_id, value, values)
        except Exception as e:
            print(f"[mgmt_render] emit: {e}")

    def _node_html(self, n):
        browser = QTextBrowser()
        browser.document().setDocumentMargin(0)
        browser.setHtml(n.get("html") or "")
        # Безопасность: внешние ссылки не открываются автоматически
        # (фишинг/утечка Referer). Ссылки внутри документа не
        # навигируют.
        browser.setOpenExternalLinks(False)
        browser.setOpenLinks(False)
        browser.setStyleSheet(
            "QTextBrowser { background-color: transparent; "
            "border: none; padding: 0; }")

        w = int(n.get("width") or 0)
        h = int(n.get("height") or 0)
        if w > 0 and h > 0:
            browser.setFixedSize(w, h)
        elif w > 0:
            browser.setFixedWidth(w)
        elif h > 0:
            browser.setFixedHeight(h)

        browser.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        browser.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return browser

    def _node_image(self, n):
        src = n.get("src") or ""
        width = int(n.get("width") or 0)
        height = int(n.get("height") or 0)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        lbl.setStyleSheet("background: transparent;")
        pm = _load_pixmap(src)
        if pm and not pm.isNull():
            if width > 0 and height > 0:
                pm = pm.scaled(width, height, Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
            elif width > 0:
                pm = pm.scaledToWidth(width,
                                       Qt.SmoothTransformation)
            elif height > 0:
                pm = pm.scaledToHeight(height,
                                        Qt.SmoothTransformation)
            lbl.setPixmap(pm)
            lbl.setFixedSize(pm.size())
        else:
            lbl.setText("(изображение недоступно)")
            lbl.setStyleSheet("color:#95a5a6; font-size:11px;")
        return lbl

    def _node_badge(self, n):
        accent = n.get("accent") or "info"
        cmap = {
            "info": ("#e3f2fd", "#1565c0"),
            "success": ("#e8f5e9", "#2e7d32"),
            "warning": ("#fff8e1", "#e65100"),
            "error": ("#ffebee", "#c62828"),
        }
        bg, fg = cmap.get(accent, cmap["info"])
        lbl = QLabel(n.get("label") or "")
        lbl.setStyleSheet(
            f"background:{bg}; color:{fg}; border-radius:4px; "
            f"padding:4px 10px; font-weight:bold; font-size:12px;")
        lbl.setAlignment(Qt.AlignCenter)
        return lbl

    def _node_toolbar(self, n):
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        for b in n.get("buttons") or []:
            bw = self._render(b)
            if bw is not None:
                h.addWidget(bw)
        h.addStretch()
        return w

    def _node_form_field(self, n):
        fid = n.get("id") or ""
        kind = n.get("kind") or "text"
        label = n.get("label")
        value = n.get("value")
        read_only = bool(n.get("read_only"))
        on_change = n.get("on_change")
        min_v = int(n.get("min") or 0)
        max_v = int(n.get("max") or 999999)
        label_pos = n.get("label_position") or "top"
        stretch = bool(n.get("stretch"))
        width = int(n.get("width") or 0)
        label_width = int(n.get("label_width") or 0)

        if kind == "checkbox":
            cb = QCheckBox(label or "")
            cb.setChecked(bool(value))
            cb.setEnabled(not read_only)
            self._fields[fid] = cb
            if on_change == "input_submit":
                cb.stateChanged.connect(
                    lambda _s, fid=fid, cb=cb:
                    self._emit_change(fid, cb.isChecked()))
            return cb

        widget = None
        if kind == "select":
            combo = QComboBox()
            for opt in n.get("options") or []:
                combo.addItem(
                    str(opt.get("label") or opt.get("value") or ""),
                    opt.get("value"))
            if value is not None:
                idx = combo.findData(value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.setEnabled(not read_only)
            widget = combo
            if on_change == "input_submit":
                combo.currentIndexChanged.connect(
                    lambda _i, fid=fid, c=combo:
                    self._emit_change(fid, c.currentData()))
        elif kind == "number":
            sp = QSpinBox()
            sp.setRange(min_v, max_v)
            try:
                sp.setValue(int(value or 0))
            except Exception:
                sp.setValue(min_v)
            sp.setEnabled(not read_only)
            widget = sp
            if on_change == "input_submit":
                sp.valueChanged.connect(
                    lambda v, fid=fid:
                    self._emit_change(fid, int(v)))
        elif kind == "password":
            le = QLineEdit(str(value or ""))
            le.setEchoMode(QLineEdit.Password)
            le.setPlaceholderText(n.get("placeholder") or "")
            le.setReadOnly(read_only)
            widget = le
            if on_change == "input_submit":
                _wire_debounce(le, lambda fid=fid, le=le:
                                self._emit_change(fid, le.text()))
            elif on_change == "instant":
                _wire_debounce(
                    le,
                    lambda fid=fid, le=le:
                    self._emit_change(fid, le.text()),
                    interval=350)
        elif kind == "textarea":
            te = QTextEdit(str(value or ""))
            te.setReadOnly(read_only)
            te.setMinimumHeight(80)
            widget = te
        else:
            le = QLineEdit(str(value or ""))
            le.setPlaceholderText(n.get("placeholder") or "")
            le.setReadOnly(read_only)
            widget = le
            if on_change == "input_submit":
                _wire_debounce(le, lambda fid=fid, le=le:
                                self._emit_change(fid, le.text()))
            elif on_change == "instant":
                _wire_debounce(
                    le,
                    lambda fid=fid, le=le:
                    self._emit_change(fid, le.text()),
                    interval=350)

        if widget is not None:
            self._fields[fid] = widget
            if width > 0:
                widget.setFixedWidth(width)
            elif not stretch:
                widget.setMaximumWidth(400)
                widget.setSizePolicy(QSizePolicy.Maximum,
                                     QSizePolicy.Fixed)

        if label_pos == "left":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            if label:
                lbl_w = QLabel(label)
                if label_width > 0:
                    lbl_w.setFixedWidth(label_width)
                h.addWidget(lbl_w)
            if stretch:
                h.addWidget(widget, 1)
            else:
                h.addWidget(widget)
                w.setSizePolicy(QSizePolicy.Maximum,
                                 QSizePolicy.Fixed)
            return w
        else:
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.setSpacing(4)
            if label:
                v.addWidget(QLabel(label))
            if stretch:
                v.addWidget(widget, 1)
                _mark_stretch(w)
            else:
                v.addWidget(widget)
                w.setSizePolicy(QSizePolicy.Maximum,
                                 QSizePolicy.Preferred)
            return w

    def _emit_change(self, fid, value):
        values = self.collect_values()
        values[fid] = value
        try:
            self.action_clicked.emit(
                "input_submit", fid, value, values)
        except Exception as e:
            print(f"[mgmt_render] change emit: {e}")

    def _node_table(self, n):
        cols = n.get("columns") or []
        rows = n.get("rows") or []
        on_dbl = n.get("on_double_click") or {}
        selection_mode = n.get("selection_mode") or "single"
        searchable = n.get("searchable", True)

        wrap = QWidget()
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        if searchable:
            search_edit = QLineEdit()
            search_edit.setPlaceholderText(
                n.get("search_placeholder") or "Поиск...")
            v.addWidget(search_edit)

        table = QTableWidget()
        table.setColumnCount(len(cols))
        table.setHorizontalHeaderLabels(
            [str(c.get("label") or c.get("key") or "") for c in cols])
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        if selection_mode == "multi":
            table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        else:
            table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setShowGrid(True)
        table.setAlternatingRowColors(False)
        table.verticalHeader().setVisible(True)
        table.verticalHeader().setDefaultSectionSize(28)
        table.verticalHeader().setSectionResizeMode(
            QHeaderView.Fixed)
        table.setMinimumHeight(200)
        table.setSizePolicy(QSizePolicy.Expanding,
                             QSizePolicy.Expanding)

        header = table.horizontalHeader()
        header.setSectionsClickable(False)
        header.setSectionsMovable(False)
        header.setHighlightSections(False)
        header.setMinimumSectionSize(60)
        header.setSectionResizeMode(QHeaderView.Stretch)

        if n.get("editable"):
            table.setEditTriggers(
                QAbstractItemView.DoubleClicked |
                QAbstractItemView.EditKeyPressed |
                QAbstractItemView.AnyKeyPressed)
        else:
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        fid = n.get("field_id") or f"table_{len(self._tables)}"
        self._tables[fid] = (table, n)

        table.setRowCount(len(rows))
        for r_idx, row in enumerate(rows):
            for c_idx, c in enumerate(cols):
                key = c.get("key") or ""
                ctype = c.get("type") or "text"
                val = row.get(key, "")
                if ctype == "image":
                    pm = _load_pixmap(str(val))
                    if pm and not pm.isNull():
                        lbl = QLabel()
                        lbl.setPixmap(pm.scaled(
                            40, 40, Qt.KeepAspectRatio,
                            Qt.SmoothTransformation))
                        lbl.setAlignment(Qt.AlignCenter)
                        lbl.setStyleSheet("background: transparent;")
                        table.setCellWidget(r_idx, c_idx, lbl)
                        it = QTableWidgetItem("")
                    else:
                        it = QTableWidgetItem("—")
                else:
                    it = QTableWidgetItem(
                        str(val) if val is not None else "")
                    if ctype == "number":
                        it.setTextAlignment(
                            Qt.AlignRight | Qt.AlignVCenter)

                    if n.get("editable") and c.get("key") == "qty":
                        it.setFlags(Qt.ItemIsEnabled |
                                    Qt.ItemIsSelectable |
                                    Qt.ItemIsEditable)
                    else:
                        it.setFlags(Qt.ItemIsEnabled |
                                    Qt.ItemIsSelectable)

                table.setItem(r_idx, c_idx, it)

        v.addWidget(table, 1)

        if searchable:
            search_edit.textChanged.connect(
                lambda t: _filter_table(table, t))

        if on_dbl.get("id"):
            value_field = on_dbl.get("value_field") or "id"

            def _on_dbl(idx, of=on_dbl, vf=value_field,
                        rows_data=rows):
                r = idx.row()
                if r < 0 or r >= len(rows_data):
                    return
                v = rows_data[r].get(vf)
                self._emit_action(
                    of.get("action") or "tap",
                    of.get("id") or "", v)

            table.doubleClicked.connect(_on_dbl)

        return _mark_stretch(wrap)

    def _node_breadcrumb(self, n):
        items = n.get("items") or []
        on_nav = n.get("on_navigate") or {}
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        for i, item in enumerate(items):
            last = (i == len(items) - 1)
            label = str(item.get("label", ""))
            if last:
                lbl = QLabel(label)
                lbl.setStyleSheet(
                    "font-weight:bold; font-size:13px;")
                h.addWidget(lbl)
            else:
                btn = QPushButton(label)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setStyleSheet(
                    "QPushButton { background:transparent; "
                    "border:none; color:#3498db; padding:0; "
                    "font-size:13px; text-decoration:underline; }"
                    "QPushButton:hover { color:#1abc9c; }")
                nav_action = on_nav.get("action") or "tap"
                nav_id = on_nav.get("id") or "navigate"
                nav_value = item.get("value")

                def _nav(_x=False, a=nav_action, nid=nav_id,
                         v=nav_value):
                    self._emit_action(a, nid, v)
                btn.clicked.connect(_nav)
                h.addWidget(btn)
                arrow = QLabel("→")
                arrow.setStyleSheet("color:#95a5a6;")
                h.addWidget(arrow)
        return w

    def _node_file_trigger(self, n):
        btn = QPushButton(n.get("label") or "Файл")
        btn.setCursor(Qt.PointingHandCursor)

        if n.get("style") == "primary":
            btn.setObjectName("primary_btn")
        elif n.get("style") == "danger":
            btn.setObjectName("danger_btn")

        kind = n.get("action") or "download"

        if kind == "download":
            def _save():
                b64 = n.get("download_b64") or ""
                filename = n.get("filename") or "file.bin"
                try:
                    data = base64.b64decode(b64)
                except Exception:
                    return
                path, _ = QFileDialog.getSaveFileName(
                    self, "Сохранить", filename)
                if not path:
                    return
                try:
                    with open(path, "wb") as f:
                        f.write(data)
                except Exception as e:
                    print(f"[mgmt_render] save: {e}")
            btn.clicked.connect(_save)
        else:
            accept = n.get("accept") or ""
            action_id = n.get("action_id") or n.get("id") or ""

            def _upload():
                path, _ = QFileDialog.getOpenFileName(
                    self, "Выбрать файл", "", accept)
                if not path:
                    return
                try:
                    with open(path, "rb") as f:
                        raw = f.read()
                except Exception as e:
                    print(f"[mgmt_render] open: {e}")
                    return
                b64 = base64.b64encode(raw).decode("ascii")
                self._emit_action(
                    "upload", action_id,
                    {"b64": b64,
                     "filename": os.path.basename(path)})
            btn.clicked.connect(_upload)
        return btn

    def _open_dialog(self, node):
        dlg = QDialog(self)
        dlg.setWindowTitle(str(node.get("title") or ""))
        dlg.setMinimumWidth(520)
        panel_kind = node.get("panel_kind") or "dialog"
        dlg.setModal(panel_kind == "dialog")

        v = QVBoxLayout(dlg)
        v.setSpacing(8)

        for c in node.get("children") or []:
            w = self._render(c)
            if w is not None:
                v.addWidget(w)

        v.addStretch()

        btns = node.get("buttons") or []
        if btns:
            row = QHBoxLayout()
            left_row = QHBoxLayout()
            right_row = QHBoxLayout()

            right_row.addStretch()
            for b in btns:
                bw = self._render(b)
                if bw is not None:
                    if b.get("align") == "left":
                        left_row.addWidget(bw)
                    else:
                        right_row.addWidget(bw)

            row.addLayout(left_row)
            row.addStretch()
            row.addLayout(right_row)
            v.addLayout(row)

        dlg.show()
        self._dialogs.append(dlg)


def _filter_table(table, text):
    text = (text or "").lower()
    for r in range(table.rowCount()):
        if not text:
            table.setRowHidden(r, False)
            continue
        match = False
        for c in range(table.columnCount()):
            item = table.item(r, c)
            if item and text in item.text().lower():
                match = True
                break
        table.setRowHidden(r, not match)


def _wire_debounce(line_edit, on_flush, interval=400):
    timer = QTimer(line_edit)
    timer.setSingleShot(True)
    timer.setInterval(int(interval))
    timer.timeout.connect(on_flush)

    def _on_text(_t):
        timer.stop()
        timer.start()

    line_edit.textChanged.connect(_on_text)


def _load_pixmap(src):
    """Загружает QPixmap.

    Безопасность (SSRF): разрешены только `data:` и локальные
    файлы. `http(s)://` отключено — плагин или MITM не должны
    заставлять клиент ходить по произвольным URL.
    """
    if not src:
        return None
    pm = QPixmap()
    if src.startswith("data:"):
        try:
            _, _, b64 = src.partition(",")
            raw = base64.b64decode(b64)
            if pm.loadFromData(raw):
                return pm
        except Exception:
            return None
        return None
    if src.startswith("http://") or src.startswith("https://"):
        return None
    if os.path.exists(src):
        try:
            if pm.load(src):
                return pm
        except Exception:
            pass
    return None