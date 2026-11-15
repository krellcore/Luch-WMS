# pyright: reportMissingImports=false
import sys
import os
import json
import sqlite3
import ssl
import time
import urllib.request
import urllib.error

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame, QMessageBox, QComboBox,
    QGridLayout, QGroupBox, QFormLayout,
)
from PySide6.QtCore import Qt, QProcess, QProcessEnvironment, QTimer
from PySide6.QtGui import QFont, QIcon

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "utils"))

from i18n import (  # type: ignore
    set_locale, tr, current_locale, tr_in,
    available_locales, locale_display_name,
)


CONFIG_PATH = os.path.join(_HERE, "config.json")


def _configure_stdio():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _child_env():
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONUTF8", "1")
    env.insert("PYTHONIOENCODING", "utf-8")
    return env


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("save_config:", e)


def _fmt_uptime(seconds):
    seconds = int(seconds or 0)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_bytes(n):
    try:
        n = int(n or 0)
    except Exception:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


def _detect_tls(wh_path):
    """Читает settings.tls_enabled из warehouse.db склада.

    Возвращает True, если сервер должен работать по HTTPS.
    """
    if not wh_path:
        return False
    db = os.path.join(wh_path, "warehouse.db")
    if not os.path.isfile(db):
        return False
    try:
        conn = sqlite3.connect(db)
        cur = conn.cursor()
        cur.execute(
            "SELECT value FROM settings WHERE key='tls_enabled'")
        r = cur.fetchone()
        conn.close()
        return bool(r) and str(r[0]) == "1"
    except Exception:
        return False


def _cert_path_for(wh_path):
    """Путь к tls/cert.pem склада (или None)."""
    if not wh_path:
        return None
    p = os.path.join(wh_path, "tls", "cert.pem")
    return p if os.path.isfile(p) else None


def _client_ssl_ctx(cert_path):
    """SSLContext для клиента (только указанный серт).

    Используется для:
      - окна статуса (loopback, серт лежит в папке склада);
      - запуска wms.py (лаунчер передаёт URL, wms.py сам
        берёт серт из папки склада).

    Возвращает None, если cert_path не задан (обычный HTTP).
    """
    if not cert_path or not os.path.isfile(cert_path):
        return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cafile=cert_path)
        return ctx
    except Exception as e:
        print(f"[main] ssl ctx: {e}")
        return None


class ServerStatusWindow(QWidget):
    """Окно статуса сервера.

    Локаль фиксируется при создании: смена языка лаунчера
    не влияет на это окно до его пересоздания.
    """

    def __init__(self, server_url, on_stop, parent=None,
                 cert_path=None):
        super().__init__(parent)
        self._locale = current_locale()
        self.setWindowTitle(tr_in(self._locale,
                                  "status.window_title",
                                  "Луч — Статус сервера"))
        self.setMinimumSize(560, 560)
        self.server_url = server_url.rstrip("/")
        self._on_stop = on_stop
        self._stopped = False
        self._ssl_ctx = _client_ssl_ctx(cert_path)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 20, 20, 20)
        v.setSpacing(12)

        title = QLabel(tr_in(self._locale, "status.title",
                             "Статус сервера"))
        title.setFont(QFont("Arial", 16, QFont.Bold))
        v.addWidget(title)

        self.url_label = QLabel(f"URL: {self.server_url}")
        self.url_label.setWordWrap(True)
        self.url_label.setStyleSheet(
            "color:#7f8c8d; font-size:12px;")
        v.addWidget(self.url_label)

        self.state_label = QLabel(
            tr_in(self._locale, "status.checking",
                  "Проверка соединения…"))
        f = QFont("Arial", 12, QFont.Bold)
        self.state_label.setFont(f)
        v.addWidget(self.state_label)

        clients_box = QGroupBox(
            tr_in(self._locale, "status.clients_box",
                  "Подключённые устройства"))
        cf = QFormLayout(clients_box)
        self.admin_label = QLabel("—")
        self.worker_label = QLabel("—")
        self.device_label = QLabel("—")
        self.device_label.setWordWrap(True)
        cf.addRow(tr_in(self._locale, "status.clients.admin",
                        "Админ-клиенты:"),
                  self.admin_label)
        cf.addRow(tr_in(self._locale, "status.clients.workers",
                        "Рабочие клиенты:"),
                  self.worker_label)
        cf.addRow(tr_in(self._locale, "status.clients.by_device",
                        "По устройствам:"),
                  self.device_label)
        v.addWidget(clients_box)

        load_box = QGroupBox(
            tr_in(self._locale, "status.load_box", "Нагрузка"))
        lf = QFormLayout(load_box)
        self.db_label = QLabel("—")
        self.uptime_label = QLabel("—")
        self.threads_label = QLabel("—")
        self.req_sec_label = QLabel("—")
        self.req_hour_label = QLabel("—")
        self.req_day_label = QLabel("—")
        lf.addRow(tr_in(self._locale, "status.load.db",
                        "База данных:"), self.db_label)
        lf.addRow(tr_in(self._locale, "status.load.uptime",
                        "Uptime:"), self.uptime_label)
        lf.addRow(tr_in(self._locale, "status.load.threads",
                        "Потоков:"), self.threads_label)
        lf.addRow(tr_in(self._locale, "status.load.req_sec",
                        "Запросов/сек:"), self.req_sec_label)
        lf.addRow(tr_in(self._locale, "status.load.req_hour",
                        "Запросов за час:"), self.req_hour_label)
        lf.addRow(tr_in(self._locale, "status.load.req_day",
                        "Запросов за день:"), self.req_day_label)
        v.addWidget(load_box)

        traf_box = QGroupBox(
            tr_in(self._locale, "status.traffic_box", "Трафик"))
        tf = QFormLayout(traf_box)
        self.in_sec = QLabel("—")
        self.out_sec = QLabel("—")
        self.in_hour = QLabel("—")
        self.out_hour = QLabel("—")
        self.in_day = QLabel("—")
        self.out_day = QLabel("—")
        self.total_in = QLabel("—")
        self.total_out = QLabel("—")
        tf.addRow(tr_in(self._locale, "status.traf.in_sec",
                        "Принято/сек:"), self.in_sec)
        tf.addRow(tr_in(self._locale, "status.traf.out_sec",
                        "Отправлено/сек:"), self.out_sec)
        tf.addRow(tr_in(self._locale, "status.traf.in_hour",
                        "Принято за час:"), self.in_hour)
        tf.addRow(tr_in(self._locale, "status.traf.out_hour",
                        "Отправлено за час:"), self.out_hour)
        tf.addRow(tr_in(self._locale, "status.traf.in_day",
                        "Принято за день:"), self.in_day)
        tf.addRow(tr_in(self._locale, "status.traf.out_day",
                        "Отправлено за день:"), self.out_day)
        tf.addRow(tr_in(self._locale, "status.traf.total_in",
                        "Всего принято:"), self.total_in)
        tf.addRow(tr_in(self._locale, "status.traf.total_out",
                        "Всего отправлено:"), self.total_out)
        v.addWidget(traf_box)

        v.addStretch()

        btns = QHBoxLayout()
        btns.addStretch()
        self.stop_btn = QPushButton(
            tr_in(self._locale, "status.btn.stop",
                  "Остановить сервер"))
        self.stop_btn.setObjectName("danger_btn")
        self.stop_btn.clicked.connect(self._stop_server)
        btns.addWidget(self.stop_btn)
        v.addLayout(btns)

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _refresh(self):
        try:
            req = urllib.request.Request(
                self.server_url + "/status",
                data=b"{}",
                headers={"Content-Type":
                         "application/json; charset=utf-8"},
                method="POST",
            )
            if self._ssl_ctx is not None:
                with urllib.request.urlopen(
                        req, timeout=3,
                        context=self._ssl_ctx) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            else:
                with urllib.request.urlopen(req, timeout=3) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if not self._stopped:
                self.state_label.setText(
                    tr_in(self._locale, "status.state.unreachable",
                          "🔴 Сервер недоступен"))
                self.state_label.setStyleSheet(
                    "color:#c0392b; font-size:12pt; "
                    "font-weight:bold;")
                self.state_label.setToolTip(str(e))
            return

        if not data.get("ok"):
            self.state_label.setText(
                tr_in(self._locale, "status.state.error",
                      "🔴 Ошибка сервера"))
            self.state_label.setStyleSheet(
                "color:#c0392b; font-size:12pt; font-weight:bold;")
            return

        self.state_label.setText(
            tr_in(self._locale, "status.state.running",
                  "🟢 Работает · {uptime}",
                  uptime=_fmt_uptime(data.get('uptime', 0))))
        self.state_label.setStyleSheet(
            "color:#27ae60; font-size:12pt; font-weight:bold;")

        self.db_label.setText(data.get("warehouse") or "—")

        clients = data.get("clients") or {}
        admin_total = int(clients.get("admin_total") or 0)
        workers_total = int(clients.get("workers_total") or 0)
        self.admin_label.setText(str(admin_total))
        self.worker_label.setText(str(workers_total))
        by_device = clients.get("by_device") or {}
        if by_device:
            self.device_label.setText(", ".join(
                f"{k}: {v}" for k, v in sorted(by_device.items())))
        else:
            self.device_label.setText("—")

        load = data.get("load") or {}
        req = data.get("requests") or {}
        self.uptime_label.setText(
            _fmt_uptime(data.get("uptime", 0)))
        self.threads_label.setText(str(load.get("threads") or 0))
        self.req_sec_label.setText(str(req.get("per_sec") or 0))
        self.req_hour_label.setText(str(req.get("per_hour") or 0))
        self.req_day_label.setText(str(req.get("per_day") or 0))

        traf = data.get("traffic") or {}
        self.in_sec.setText(_fmt_bytes(traf.get("in_per_sec")))
        self.out_sec.setText(_fmt_bytes(traf.get("out_per_sec")))
        self.in_hour.setText(_fmt_bytes(traf.get("in_per_hour")))
        self.out_hour.setText(_fmt_bytes(traf.get("out_per_hour")))
        self.in_day.setText(_fmt_bytes(traf.get("in_per_day")))
        self.out_day.setText(_fmt_bytes(traf.get("out_per_day")))
        self.total_in.setText(_fmt_bytes(traf.get("in_total")))
        self.total_out.setText(_fmt_bytes(traf.get("out_total")))

    def _stop_server(self):
        r = QMessageBox.question(
            self,
            tr_in(self._locale, "status.stop.title",
                  "Остановить сервер"),
            tr_in(self._locale, "status.stop.confirm",
                  "Остановить сервер? Все клиенты потеряют связь."),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._stopped = True
        if self._timer:
            self._timer.stop()
        try:
            if self._on_stop:
                self._on_stop()
        except Exception as e:
            print(f"[status] stop: {e}")
        self.close()

    def closeEvent(self, event):
        if self._timer:
            self._timer.stop()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(420, 320)
        self.resize(460, 360)

        icon_path = os.path.join(_HERE, "icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._setup_process = None
        self._viewer_process = None
        self._server_process = None
        self._status_window = None
        self._server_stopping = False
        self._last_output = {"setup": "", "wms": "", "server": ""}

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        top_layout = QHBoxLayout()
        top_layout.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.title_label = QLabel(tr("app.list", "Список складов"))
        self.title_label.setFont(QFont("Arial", 14, QFont.Bold))
        top_layout.addWidget(self.title_label)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("add_btn")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setFont(QFont("Arial", 16, QFont.Bold))
        self.add_btn.clicked.connect(self.create_warehouse)
        top_layout.addWidget(self.add_btn)

        self.remote_btn = QPushButton("↗")
        self.remote_btn.setObjectName("remote_btn")
        self.remote_btn.setFixedSize(30, 30)
        self.remote_btn.setFont(QFont("Arial", 14, QFont.Bold))
        self.remote_btn.clicked.connect(self.open_remote_client)
        top_layout.addWidget(self.remote_btn)

        top_layout.addStretch()

        self.lang_label = QLabel(tr("app.language", "Язык:"))
        top_layout.addWidget(self.lang_label)
        self.lang_combo = QComboBox()
        for code in available_locales():
            self.lang_combo.addItem(locale_display_name(code), code)
        idx = self.lang_combo.findData(current_locale())
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(
            self._on_lang_changed)
        top_layout.addWidget(self.lang_combo)
        main_layout.addLayout(top_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        main_layout.addWidget(self.scroll_area)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignTop)
        self.container_layout.setSpacing(8)
        self.scroll_area.setWidget(self.container)

        self.setStyleSheet("""
            QPushButton#add_btn {
                background-color: #27ae60; color: white;
                border: none; border-radius: 15px; font-weight: bold;
            }
            QPushButton#add_btn:hover { background-color: #2ecc71; }
            QPushButton#add_btn:pressed { background-color: #1e8449; }
            QPushButton#remote_btn {
                background-color: #2980b9; color: white;
                border: none; border-radius: 15px; font-weight: bold;
            }
            QPushButton#remote_btn:hover { background-color: #3498db; }
            QPushButton#remote_btn:pressed { background-color: #1c5980; }
            QPushButton#file_btn {
                background-color: #2c3e50; color: white;
                border: none; border-radius: 8px;
                padding: 12px; font-size: 14px; font-weight: bold;
                text-align: left; padding-left: 20px;
            }
            QPushButton#file_btn:hover { background-color: #34495e; }
            QPushButton#file_btn:pressed { background-color: #1a252f; }
            QPushButton#danger_btn {
                background-color: #e74c3c; color: white;
                border: none; border-radius: 6px;
                padding: 8px 14px; font-weight: bold;
            }
            QPushButton#danger_btn:hover { background-color: #f05b4f; }
            QLabel#no_files_label { color: #7f8c8d; font-size: 16px; }
        """)

        self._retranslate()
        self.update_list()

    def _retranslate(self):
        self.setWindowTitle(tr("launcher.list_title",
                               "Луч — Список складов"))
        self.title_label.setText(tr("app.list", "Список складов"))
        self.add_btn.setToolTip(
            tr("app.new", "Создать новый склад"))
        self.remote_btn.setToolTip(
            tr("launcher.remote_tooltip",
               "Подключиться к удалённому серверу"))
        self.lang_label.setText(tr("app.language", "Язык:"))
        self.update_list()

    def _on_lang_changed(self, _index):
        code = self.lang_combo.currentData()
        if code not in available_locales():
            code = "ru"
        set_locale(code)
        cfg = load_config()
        cfg["locale"] = code
        save_config(cfg)
        self._retranslate()

    def update_list(self):
        self.clear_layout(self.container_layout)
        folder_path = os.path.join(_HERE, "warehouses")
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)

        warehouses = []
        try:
            for name in os.listdir(folder_path):
                full = os.path.join(folder_path, name)
                if os.path.isdir(full) and os.path.isfile(
                        os.path.join(full, "warehouse.db")):
                    warehouses.append(name)
        except (PermissionError, FileNotFoundError):
            warehouses = []

        if warehouses:
            warehouses.sort()
            for name in warehouses:
                btn = QPushButton(name)
                btn.setObjectName("file_btn")
                full_path = os.path.join(folder_path, name)
                btn.clicked.connect(
                    lambda checked=False, path=full_path:
                    self.on_warehouse_clicked(path)
                )
                self.container_layout.addWidget(btn)
        else:
            label = QLabel(
                tr("app.empty", "Нет созданных складов!"))
            label.setObjectName("no_files_label")
            label.setAlignment(Qt.AlignCenter)
            self.container_layout.addWidget(label)

    def clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _process_running(self, process):
        return (process is not None
                and process.state() != QProcess.NotRunning)

    def _wire_process(self, process, tag):
        process.setProcessChannelMode(QProcess.MergedChannels)

        def _read():
            raw = process.readAllStandardOutput()
            try:
                text = bytes(raw).decode("utf-8", "replace")
            except Exception:
                text = str(raw)
            if text:
                self._last_output[tag] += text
                print(f"[{tag}] {text}", end="")

        process.readyReadStandardOutput.connect(_read)

    def _bring_to_front(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def on_warehouse_clicked(self, wh_path):
        if self._process_running(self._viewer_process):
            return
        msg = QMessageBox(self)
        msg.setWindowTitle(tr("launcher.open.title",
                              "Открыть склад"))
        msg.setText(tr(
            "launcher.open.text",
            "Склад: {name}\n\nКак открыть?",
            name=os.path.basename(wh_path)))
        btn_server = msg.addButton(
            tr("launcher.open.server_client",
               "Сервер + клиент"),
            QMessageBox.ActionRole)
        btn_server_only = msg.addButton(
            tr("launcher.open.server_only", "Только сервер"),
            QMessageBox.ActionRole)
        msg.addButton(tr("common.cancel", "Отмена"),
                      QMessageBox.RejectRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_server:
            self.open_warehouse_with_server(wh_path)
        elif clicked == btn_server_only:
            self.open_server_only(wh_path)

    def _start_server_process(self, wh_path):
        self._server_stopping = False
        server_script = os.path.join(_HERE, "utils", "wms_server.py")
        if not os.path.exists(server_script):
            QMessageBox.critical(
                self,
                tr("common.error", "Ошибка"),
                tr("launcher.err.no_wms_server",
                   "Не найден wms_server.py в папке utils"))
            return False
        self._last_output["server"] = ""
        self._server_process = QProcess(self)
        self._server_process.setProcessEnvironment(_child_env())
        self._wire_process(self._server_process, "server")
        self._server_process.errorOccurred.connect(
            self.on_server_error)
        self._server_process.start(
            sys.executable, [server_script, wh_path])
        return True

    def _server_url_for(self, wh_path):
        """Определяет схему/URL и cert_path для склада.

        https, если settings.tls_enabled=1 и серт существует.
        Иначе http.
        """
        tls = _detect_tls(wh_path)
        cert_path = _cert_path_for(wh_path) if tls else None
        if tls and cert_path is None:
            tls = False
        scheme = "https" if tls else "http"
        return f"{scheme}://127.0.0.1:8765", cert_path

    def open_warehouse_with_server(self, wh_path):
        if self._process_running(self._viewer_process):
            return
        if self._process_running(self._server_process):
            QMessageBox.warning(
                self,
                tr("launcher.server_already_running.title",
                   "Сервер уже запущен"),
                tr("launcher.server_already_running.text",
                   "Сервер уже работает. Остановите его "
                   "перезапуском main.py или закройте процесс."))
            return
        if not self._start_server_process(wh_path):
            return
        url, cert_path = self._server_url_for(wh_path)
        self._wait_for_server(
            url,
            lambda: self._on_server_ready(
                wh_path, launch_client=True,
                url=url, cert_path=cert_path),
            attempts=30, cert_path=cert_path)

    def open_server_only(self, wh_path):
        if self._process_running(self._server_process):
            QMessageBox.warning(
                self,
                tr("launcher.server_already_running.title",
                   "Сервер уже запущен"),
                tr("launcher.server_already_running.text",
                   "Сервер уже работает. Остановите его "
                   "перезапуском main.py или закройте процесс."))
            return
        if not self._start_server_process(wh_path):
            return
        url, cert_path = self._server_url_for(wh_path)
        self._wait_for_server(
            url,
            lambda: self._on_server_ready(
                wh_path, launch_client=False,
                url=url, cert_path=cert_path),
            attempts=30, cert_path=cert_path)

    def _on_server_ready(self, wh_path, launch_client,
                         url, cert_path):
        self._open_status_window(url, wh_path, cert_path)
        if launch_client:
            self._launch_remote_client(wh_path, url)
        else:
            self.hide()

    def _open_status_window(self, url, wh_path, cert_path=None):
        if self._status_window is not None:
            try:
                self._status_window.close()
            except Exception:
                pass
        self._status_window = ServerStatusWindow(
            url, on_stop=self._stop_server_from_window,
            cert_path=cert_path)
        self._status_window.destroyed.connect(
            self._on_status_window_closed)
        self._status_window.show()

    def _on_status_window_closed(self, *_args):
        self._status_window = None
        if not self.isVisible():
            self._bring_to_front()

    def _stop_server_from_window(self):
        self._server_stopping = True
        try:
            if self._process_running(self._server_process):
                self._server_process.kill()
                self._server_process.waitForFinished(3000)
        except Exception as e:
            print(f"[main] stop server: {e}")
        self._status_window = None
        self._bring_to_front()
        self.update_list()

    def _wait_for_server(self, url, callback, attempts=30,
                         cert_path=None):
        try:
            req = urllib.request.Request(url + "/ping",
                                          data=b"{}",
                                          method="POST",
                                          headers={
                                              "Content-Type":
                                              "application/json"})
            ctx = _client_ssl_ctx(cert_path)
            if ctx is not None:
                with urllib.request.urlopen(
                        req, timeout=1, context=ctx) as resp:
                    resp.read()
            else:
                with urllib.request.urlopen(req, timeout=1) as resp:
                    resp.read()
            callback()
            return
        except Exception:
            pass
        if attempts <= 0:
            QMessageBox.critical(
                self,
                tr("launcher.server_not_started.title",
                   "Сервер не запустился"),
                tr("launcher.server_not_started.text",
                   "Сервер не ответил на {url}/ping.\n\n"
                   "Вывод сервера:\n{output}",
                   url=url,
                   output=self._last_output['server'][-1500:]))
            if self._process_running(self._server_process):
                self._server_process.kill()
                self._server_process.waitForFinished(3000)
            return
        QTimer.singleShot(
            300, lambda: self._wait_for_server(
                url, callback, attempts - 1, cert_path))

    def _launch_remote_client(self, wh_path, url):
        viewer_script = os.path.join(_HERE, "utils", "wms.py")
        if not os.path.exists(viewer_script):
            return
        self._last_output["wms"] = ""
        self._viewer_process = QProcess(self)
        self._viewer_process.setProcessEnvironment(_child_env())
        self._wire_process(self._viewer_process, "wms")
        self._viewer_process.finished.connect(self.on_viewer_finished)
        self._viewer_process.errorOccurred.connect(
            self.on_viewer_error)
        args = [viewer_script, "--server", url, wh_path,
                "--locale", current_locale()]
        if url.startswith("https://"):
            args.append("--tls")
        self._viewer_process.start(sys.executable, args)
        self.hide()

    def open_remote_client(self, wh_path=None):
        if self._process_running(self._viewer_process):
            return
        cfg = load_config()
        default_url = cfg.get("last_server",
                              "http://127.0.0.1:8765")
        viewer_script = os.path.join(_HERE, "utils", "wms.py")
        if not os.path.exists(viewer_script):
            QMessageBox.critical(
                self,
                tr("common.error", "Ошибка"),
                tr("launcher.err.no_wms_py",
                   "Не найден wms.py в папке utils"))
            return
        self._last_output["wms"] = ""
        self._viewer_process = QProcess(self)
        self._viewer_process.setProcessEnvironment(_child_env())
        self._wire_process(self._viewer_process, "wms")
        self._viewer_process.finished.connect(self.on_viewer_finished)
        self._viewer_process.errorOccurred.connect(
            self.on_viewer_error)
        args = [viewer_script, "--server", default_url,
                "--locale", current_locale()]
        if default_url.startswith("https://"):
            args.append("--tls")
            if wh_path:
                args.append(wh_path)
        elif wh_path:
            args.append(wh_path)
        self._viewer_process.start(sys.executable, args)
        self.hide()

    def on_viewer_finished(self, exit_code, _status):
        if exit_code != 0 and self._last_output["wms"].strip():
            QMessageBox.critical(
                self,
                tr("launcher.client_error.title",
                   "Ошибка клиента"),
                tr("launcher.client_error.text",
                   "Процесс wms.py завершился с ошибкой.\n\n"
                   "{output}",
                   output=self._last_output["wms"][-2000:])
            )
        self._bring_to_front()
        self.update_list()

    def on_viewer_error(self, error):
        QMessageBox.critical(
            self,
            tr("common.error", "Ошибка"),
            tr("launcher.launch_failed",
               "Не удалось запустить клиент (код {code}).",
               code=error)
        )
        self._bring_to_front()

    def on_server_error(self, error):
        if self._server_stopping:
            return
        QMessageBox.critical(
            self,
            tr("launcher.server_error.title",
               "Ошибка сервера"),
            tr("launcher.server_error.text",
               "Не удалось запустить сервер (код {code}).\n\n"
               "{output}",
               code=error,
               output=self._last_output['server'][-1500:])
        )
        self._bring_to_front()

    def create_warehouse(self):
        if self._process_running(self._setup_process):
            return
        setup_path = os.path.join(_HERE, "utils", "setup.py")
        if not os.path.exists(setup_path):
            QMessageBox.critical(
                self,
                tr("common.error", "Ошибка"),
                tr("launcher.err.no_setup_py",
                   "Файл setup.py не найден в папке utils"))
            return
        self._last_output["setup"] = ""
        self._setup_process = QProcess(self)
        self._setup_process.setProcessEnvironment(_child_env())
        self._wire_process(self._setup_process, "setup")
        self._setup_process.finished.connect(self.on_setup_finished)
        self._setup_process.errorOccurred.connect(self.on_setup_error)
        self._setup_process.start(sys.executable, [setup_path])
        self.hide()

    def on_setup_finished(self, exit_code, _status):
        if exit_code != 0 and self._last_output["setup"].strip():
            QMessageBox.critical(
                self,
                tr("launcher.wizard_error.title",
                   "Ошибка мастера"),
                tr("launcher.wizard_error.text",
                   "Процесс setup.py завершился с ошибкой.\n\n"
                   "{output}",
                   output=self._last_output["setup"][-2000:])
            )
        self._bring_to_front()
        self.update_list()

    def on_setup_error(self, error):
        QMessageBox.critical(
            self,
            tr("common.error", "Ошибка"),
            tr("launcher.launch_failed",
               "Не удалось запустить клиент (код {code}).",
               code=error)
        )
        self._bring_to_front()

    def closeEvent(self, event):
        self._server_stopping = True
        for proc in (self._setup_process, self._viewer_process,
                     self._server_process):
            try:
                if proc is not None and \
                        proc.state() != QProcess.NotRunning:
                    proc.kill()
                    proc.waitForFinished(3000)
            except Exception as e:
                print(f"[main] kill: {e}")
        if self._status_window is not None:
            try:
                self._status_window.blockSignals(True)
                self._status_window.close()
                self._status_window.deleteLater()
            except Exception:
                pass
            self._status_window = None
        super().closeEvent(event)


def main():
    _configure_stdio()
    app = QApplication(sys.argv)
    icon_path = os.path.join(_HERE, "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    cfg = load_config()
    set_locale(cfg.get("locale", "ru"))

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()