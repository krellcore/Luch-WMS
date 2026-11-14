import sys
import os
import json
import sqlite3
import hashlib
import traceback
from datetime import datetime
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QStackedWidget, QWidget,
    QFormLayout, QGroupBox, QMessageBox, QScrollArea, QFrame,
    QProgressBar
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon

from db import run_all_migrations
from i18n import set_locale, tr


_HERE = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(
    os.path.dirname(_HERE), "config.json")


def _configure_stdio():
    """Переключить stdout/stderr на UTF-8.
    На Windows консоль должна быть в chcp 65001."""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _load_config_locale():
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        code = cfg.get("locale")
        if code in ("ru", "en"):
            return code
    except Exception:
        pass
    return "ru"


class SetupWizard(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("setup.wizard.title",
                               "Мастер создания склада"))
        self.setMinimumSize(620, 560)
        self.setModal(True)

        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        ic = os.path.join(base, "icon.png")
        if os.path.exists(ic):
            self.setWindowIcon(QIcon(ic))

        self.params = {}
        self.db_path = None
        self.warehouse_dir = None

        main_layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack)

        self.page1 = QWidget()
        self.page_owner = QWidget()
        self.page2 = QWidget()
        self.page3 = QWidget()
        for p in (self.page1, self.page_owner,
                  self.page2, self.page3):
            self.stack.addWidget(p)

        # ---------- Страница 1: параметры ----------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        l1 = QVBoxLayout(content)
        l1.setSpacing(10)

        g = QGroupBox(tr("setup.wizard.main_group",
                         "Основные параметры"))
        f = QFormLayout(g)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr(
            "setup.wizard.name_placeholder",
            "Только латиница, цифры и _"))
        f.addRow(tr("setup.wizard.name",
                    "Наименование:"), self.name_edit)

        l1.addWidget(g)

        self.addr_group = QGroupBox(tr(
            "setup.wizard.addr_group",
            "Параметры адресного склада"))
        af = QFormLayout(self.addr_group)

        self.prefix_container_edit = QLineEdit()
        self.suffix_container_edit = QLineEdit()
        self.prefix_cell_edit = QLineEdit()
        self.suffix_cell_edit = QLineEdit()
        for w in (self.prefix_container_edit,
                  self.suffix_container_edit,
                  self.prefix_cell_edit,
                  self.suffix_cell_edit):
            w.setPlaceholderText(tr(
                "setup.wizard.optional", "Необязательно"))

        self.blocks_edit = QLineEdit()
        self.blocks_edit.setPlaceholderText("1..9")
        self.floors_edit = QLineEdit()
        self.floors_edit.setPlaceholderText("1..9")
        self.rows_edit = QLineEdit()
        self.rows_edit.setPlaceholderText("1..99")
        self.sections_edit = QLineEdit()
        self.sections_edit.setPlaceholderText("1..99")

        af.addRow(tr("setup.wizard.prefix_container",
                     "Префикс рабочей тары:"),
                  self.prefix_container_edit)
        af.addRow(tr("setup.wizard.suffix_container",
                     "Суффикс рабочей тары:"),
                  self.suffix_container_edit)
        af.addRow(tr("setup.wizard.prefix_cell",
                     "Префикс ШК ячейки:"),
                  self.prefix_cell_edit)
        af.addRow(tr("setup.wizard.suffix_cell",
                     "Суффикс ШК ячейки:"),
                  self.suffix_cell_edit)
        af.addRow(tr("setup.wizard.blocks",
                     "Количество блоков:"),
                  self.blocks_edit)
        af.addRow(tr("setup.wizard.floors",
                     "Количество этажей:"),
                  self.floors_edit)
        af.addRow(tr("setup.wizard.rows",
                     "Количество рядов:"),
                  self.rows_edit)
        af.addRow(tr("setup.wizard.sections",
                     "Количество секций:"),
                  self.sections_edit)
        l1.addWidget(self.addr_group)

        nav = QHBoxLayout()
        nav.addStretch()
        self.btn_next = QPushButton(
            tr("setup.wizard.btn.next", "Далее"))
        self.btn_cancel = QPushButton(
            tr("common.cancel", "Отмена"))
        nav.addWidget(self.btn_next)
        nav.addWidget(self.btn_cancel)
        l1.addLayout(nav)

        scroll.setWidget(content)
        p1l = QVBoxLayout(self.page1)
        p1l.setContentsMargins(0, 0, 0, 0)
        p1l.addWidget(scroll)

        # ---------- Страница owner ----------
        ol = QVBoxLayout(self.page_owner)
        ol.setSpacing(10)

        owner_title = QLabel(tr("setup.wizard.owner_title",
                                "Руководитель склада (владелец)"))
        owner_title.setFont(QFont("Arial", 12, QFont.Bold))
        ol.addWidget(owner_title)

        owner_hint = QLabel(tr(
            "setup.wizard.owner_hint",
            "Создаётся один аккаунт владельца. Через него "
            "впоследствии можно будет добавлять других "
            "руководителей (admin/operator). Пароль хранится "
            "только как SHA-256 хэш."))
        owner_hint.setWordWrap(True)
        owner_hint.setStyleSheet("color:#7f8c8d;")
        ol.addWidget(owner_hint)

        og = QGroupBox(tr("setup.wizard.owner_group",
                          "Аккаунт владельца"))
        of = QFormLayout(og)

        self.owner_login_edit = QLineEdit()
        self.owner_login_edit.setPlaceholderText(tr(
            "setup.wizard.owner_login_placeholder",
            "Логин (a-z, 0-9, _, .)"))
        self.owner_password_edit = QLineEdit()
        self.owner_password_edit.setEchoMode(QLineEdit.Password)
        self.owner_password_edit.setPlaceholderText(tr(
            "setup.wizard.owner_password_placeholder",
            "Пароль (мин. 4 символа)"))
        self.owner_password2_edit = QLineEdit()
        self.owner_password2_edit.setEchoMode(QLineEdit.Password)
        self.owner_password2_edit.setPlaceholderText(tr(
            "setup.wizard.owner_password2_placeholder",
            "Повторите пароль"))

        of.addRow(tr("setup.wizard.owner_login",
                     "Логин*:"), self.owner_login_edit)
        of.addRow(tr("setup.wizard.owner_password",
                     "Пароль*:"), self.owner_password_edit)
        of.addRow(tr("setup.wizard.owner_password2",
                     "Повтор*:"), self.owner_password2_edit)
        ol.addWidget(og)

        ol.addStretch()

        nav_o = QHBoxLayout()
        nav_o.addStretch()
        self.btn_back_owner = QPushButton(
            tr("common.back", "← Назад"))
        self.btn_next_owner = QPushButton(
            tr("setup.wizard.btn.next", "Далее"))
        self.btn_cancel_o = QPushButton(
            tr("common.cancel", "Отмена"))
        nav_o.addWidget(self.btn_back_owner)
        nav_o.addWidget(self.btn_next_owner)
        nav_o.addWidget(self.btn_cancel_o)
        ol.addLayout(nav_o)

        # ---------- Страница 2: подтверждение ----------
        l2 = QVBoxLayout(self.page2)
        t = QLabel(tr("setup.wizard.confirm_title",
                      "Подтвердите параметры:"))
        t.setFont(QFont("Arial", 12, QFont.Bold))
        l2.addWidget(t)
        self.confirm_label = QLabel()
        self.confirm_label.setWordWrap(True)
        l2.addWidget(self.confirm_label)

        nav2 = QHBoxLayout()
        nav2.addStretch()
        self.btn_back = QPushButton(
            tr("common.back", "← Назад"))
        self.btn_ok = QPushButton(
            tr("setup.wizard.btn.confirm", "Подтвердить"))
        self.btn_cancel2 = QPushButton(
            tr("common.cancel", "Отмена"))
        nav2.addWidget(self.btn_back)
        nav2.addWidget(self.btn_ok)
        nav2.addWidget(self.btn_cancel2)
        l2.addLayout(nav2)

        # ---------- Страница 3: прогресс ----------
        l3 = QVBoxLayout(self.page3)
        self.status_label = QLabel(
            tr("setup.wizard.status.creating",
               "Создание БД..."))
        self.status_label.setAlignment(Qt.AlignCenter)
        l3.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        l3.addWidget(self.progress)

        self.result_label = QLabel()
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setWordWrap(True)
        l3.addWidget(self.result_label)

        nav3 = QHBoxLayout()
        nav3.addStretch()
        self.btn_close = QPushButton(
            tr("common.close", "Закрыть"))
        self.btn_close.setEnabled(False)
        nav3.addWidget(self.btn_close)
        l3.addLayout(nav3)

        # ---------- Навигация ----------
        self.btn_next.clicked.connect(self._go_owner)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_back_owner.clicked.connect(
            lambda: self.stack.setCurrentIndex(0))
        self.btn_next_owner.clicked.connect(self._go_confirm)
        self.btn_cancel_o.clicked.connect(self.reject)
        self.btn_back.clicked.connect(
            lambda: self.stack.setCurrentIndex(1))
        self.btn_ok.clicked.connect(self._create)
        self.btn_cancel2.clicked.connect(self.reject)
        self.btn_close.clicked.connect(self.accept)

    # ---------- Валидация страницы 1 ----------
    def _validate(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.name_required",
                   "Введите наименование."))
            return False
        for ch in name:
            if not ((ch.isascii() and ch.isalnum()) or ch == "_"):
                QMessageBox.warning(
                    self,
                    tr("common.error", "Ошибка"),
                    tr("setup.wizard.err.name_format",
                       "Наименование: только латиница, цифры "
                       "и подчёркивания (без пробелов "
                       "и спецсимволов)."))
                return False
        try:
            n = int(self.blocks_edit.text().strip())
            f = int(self.floors_edit.text().strip())
            r = int(self.rows_edit.text().strip())
            s = int(self.sections_edit.text().strip())
        except ValueError:
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.numeric",
                   "Все значения — целые числа."))
            return False
        if not (1 <= n <= 9):
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.blocks_range",
                   "Блоков может быть от 1 до 9."))
            return False
        if not (1 <= f <= 9):
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.floors_range",
                   "Этажей может быть от 1 до 9."))
            return False
        if not (1 <= r <= 99 and 1 <= s <= 99):
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.rows_sections_range",
                   "Рядов и секций — от 1 до 99."))
            return False
        return True

    def _validate_owner(self):
        login = self.owner_login_edit.text().strip()
        pwd = self.owner_password_edit.text()
        pwd2 = self.owner_password2_edit.text()
        if not login:
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.owner_login_required",
                   "Введите логин владельца."))
            return False
        # '-' запрещён: формат токена <login>-<secret>.
        for ch in login:
            if not ((ch.isascii() and ch.isalnum()) or ch in "_."):
                QMessageBox.warning(
                    self,
                    tr("common.error", "Ошибка"),
                    tr("setup.wizard.err.owner_login_format",
                       "Логин: только латиница, цифры, _ и ."))
                return False
        if len(pwd) < 4:
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.password_short",
                   "Пароль должен содержать минимум 4 символа."))
            return False
        if pwd != pwd2:
            QMessageBox.warning(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.password_mismatch",
                   "Пароли не совпадают."))
            return False
        return True

    def _go_owner(self):
        if not self._validate():
            return
        self._collect()
        self.stack.setCurrentIndex(1)

    def _go_confirm(self):
        if not self._validate_owner():
            return
        # FIX: обновить owner_login из поля перед показом сводки
        # и созданием БД. Без этой строки self.params["owner_login"]
        # остаётся пустым, и в managers вставляется пустой login.
        self.params["owner_login"] = \
            self.owner_login_edit.text().strip()
        self.confirm_label.setText("\n".join(self._summary()))
        self.stack.setCurrentIndex(2)

    def _collect(self):
        p = self.params
        p["name"] = self.name_edit.text().strip()
        p["created_at"] = datetime.now().isoformat()
        p["prefix_container"] = \
            self.prefix_container_edit.text().strip()
        p["suffix_container"] = \
            self.suffix_container_edit.text().strip()
        p["prefix_cell"] = self.prefix_cell_edit.text().strip()
        p["suffix_cell"] = self.suffix_cell_edit.text().strip()
        p["blocks_count"] = int(self.blocks_edit.text().strip())
        p["floors"] = int(self.floors_edit.text().strip())
        p["rows"] = int(self.rows_edit.text().strip())
        p["sections"] = int(self.sections_edit.text().strip())
        p["owner_login"] = self.owner_login_edit.text().strip()

    def _summary(self):
        p = self.params
        return [
            tr("setup.wizard.summary.name",
               "Наименование: {name}", name=p['name']),
            tr("setup.wizard.summary.blocks",
               "Блоков: {n}", n=p['blocks_count']),
            tr("setup.wizard.summary.floors",
               "Этажей: {n}", n=p['floors']),
            tr("setup.wizard.summary.rows",
               "Рядов: {n}", n=p['rows']),
            tr("setup.wizard.summary.sections",
               "Секций: {n}", n=p['sections']),
            tr("setup.wizard.summary.owner",
               "Владелец: {login}", login=p['owner_login']),
        ]

    def _create(self):
        self.stack.setCurrentIndex(3)
        self.progress.setValue(0)
        QApplication.processEvents()
        try:
            self._create_db()
            self.status_label.setText(tr(
                "setup.wizard.status.created",
                "База данных успешно создана."))
            self.result_label.setText(tr(
                "setup.wizard.result.folder",
                "Папка склада: warehouses/{name}/",
                name=self.params['name']))
            self.btn_close.setEnabled(True)
        except Exception as e:
            tb = traceback.format_exc()
            print(tb, file=sys.stderr)
            self.status_label.setText(tr(
                "setup.wizard.status.error",
                "Ошибка при создании БД"))
            self.result_label.setText(str(e))
            QMessageBox.critical(
                self,
                tr("common.error", "Ошибка"),
                tr("setup.wizard.err.create_failed",
                   "{error}\n\n{traceback_tail}",
                   error=str(e),
                   traceback_tail=tb[-1000:]))
            self.btn_close.setEnabled(True)

    def _create_db(self):
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        wh_root = os.path.join(base, "warehouses")
        os.makedirs(wh_root, exist_ok=True)

        self.warehouse_dir = os.path.join(
            wh_root, self.params['name'])
        os.makedirs(self.warehouse_dir, exist_ok=True)

        self.db_path = os.path.join(
            self.warehouse_dir, "warehouse.db")
        if os.path.exists(self.db_path):
            raise RuntimeError(tr(
                "setup.wizard.err.exists",
                "Склад «{name}» уже существует.",
                name=self.params['name']))

        # Защита от пустого логина (на случай, если пользователь
        # дошёл сюда в обход _go_confirm).
        if not self.params.get("owner_login"):
            raise RuntimeError(tr(
                "setup.wizard.err.owner_login_empty",
                "Логин владельца пуст. Пройдите страницу "
                "«Руководитель склада» и заполните логин."))

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("CREATE TABLE settings "
                  "(key TEXT PRIMARY KEY, value TEXT)")
        c.execute("INSERT INTO settings (key, value) "
                  "VALUES ('locale', 'ru')")
        c.execute("INSERT INTO settings (key, value) "
                  "VALUES ('active_plugins', '[]')")
        for k, v in self.params.items():
            if k == "owner_login":
                continue
            c.execute("INSERT INTO settings (key, value) "
                      "VALUES (?, ?)", (k, str(v)))
        c.execute("INSERT INTO settings (key, value) "
                  "VALUES ('owner_login', ?)",
                  (self.params["owner_login"],))

        conn.commit()
        conn.close()

        run_all_migrations(self.db_path)

        pwd = self.owner_password_edit.text()
        pass_hash = hashlib.sha256(
            pwd.encode("utf-8")).hexdigest()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO managers (login, pass_hash, role, created_at)
            VALUES (?, ?, 'owner', ?)
        """, (self.params["owner_login"], pass_hash,
              datetime.now().isoformat()))
        conn.commit()
        conn.close()

        prefix_cell = self.params.get("prefix_cell", "")
        suffix_cell = self.params.get("suffix_cell", "")
        n_blocks = self.params["blocks_count"]
        floors = self.params["floors"]
        rows = self.params["rows"]
        sections = self.params["sections"]

        total = n_blocks * floors * rows * sections
        done = 0
        self.progress.setValue(0)
        self.status_label.setText(tr(
            "setup.wizard.status.generating",
            "Генерация ячеек (всего {total})...",
            total=total))
        QApplication.processEvents()

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        for b in range(1, n_blocks + 1):
            bname = str(b)
            c.execute("INSERT INTO blocks (name) VALUES (?)",
                      (bname,))
            block_id = c.lastrowid
            for f in range(1, floors + 1):
                bf = f"{b}{f}"
                for r in range(1, rows + 1):
                    for s in range(1, sections + 1):
                        cell = "A1"
                        addr = f"{bf}-{r:02d}-{s:02d}-{cell}"
                        bc = (f"{prefix_cell}{bf}{r:02d}{s:02d}"
                              f"{cell}{suffix_cell}")
                        c.execute("""INSERT INTO cells
                            (block_id, floor, row, section, cell,
                             address, barcode, cell_type)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (block_id, f, r, s, cell, addr, bc,
                             "standart"))
                        done += 1
                        if done % 200 == 0 or done == total:
                            pct = int(done * 100 / max(total, 1))
                            self.progress.setValue(pct)
                            self.status_label.setText(tr(
                                "setup.wizard.status.generating_progress",
                                "Генерация ячеек: {done}/{total}",
                                done=done, total=total))
                            QApplication.processEvents()

        conn.commit()
        conn.close()
        self.progress.setValue(100)
        QApplication.processEvents()


def main():
    _configure_stdio()
    try:
        app = QApplication(sys.argv)
        base = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        ic = os.path.join(base, "icon.png")
        if os.path.exists(ic):
            app.setWindowIcon(QIcon(ic))

        set_locale(_load_config_locale())

        w = SetupWizard()
        w.show()
        w.raise_()
        w.activateWindow()
        sys.exit(app.exec())
    except Exception:
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()