"""Headless-сервер склада (без Qt-виджетов)."""

import argparse
import os
import sys
import time

# 4.12: На Linux без дисплея QGuiApplication падает при создании.
# barcodes.py / mgmt_pages/* рисуют через QPixmap/QPainter — им
# нужен QGuiApplication. offscreen позволяет работать без X11.
# ВАЖНО: на Windows/macOS offscreen не нужен и ломает загрузку
# системных шрифтов (из-за чего вместо текста появляются квадраты).
if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication

from db import run_all_migrations, read_settings
from plugins import PluginManager
from server import start_server, set_host, stop_server
from tls import has_cert, generate_cert


def _configure_stdio():
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class HeadlessHost:
    def __init__(self, db_path, safe_mode=False):
        self.db_path = db_path
        self.safe_mode = safe_mode
        self.plugin_manager = None

        self._mgmt_plugin_pages = {}
        self._mgmt_plugin_endpoints = []

        self._plugin_endpoints = []
        self._plugin_step_handlers = []
        self._plugin_barcode_callbacks = []

    def _apply_plugin_barcode_buttons(self):
        pass

    def _register_plugin_page(self, plugin_name, key, title,
                              widget_class):
        print(f"[headless] плагин {plugin_name} пытается "
              f"зарегистрировать Qt-страницу '{key}' — "
              f"пропущено (headless)")

    def _remove_plugin_page(self, plugin_name):
        pass

    def _register_step_handler(self, plugin_name, step_type,
                               handler, priority):
        self._plugin_step_handlers.append(
            (plugin_name, step_type, handler, priority))

    def _remove_step_handlers(self, plugin_name):
        self._plugin_step_handlers = [
            t for t in self._plugin_step_handlers
            if t[0] != plugin_name
        ]

    def _register_plugin_endpoint(self, plugin_name, path,
                                  handler, methods):
        self._plugin_endpoints.append(
            (plugin_name, path, handler, tuple(methods)))

    def _remove_plugin_endpoints(self, plugin_name):
        self._plugin_endpoints = [
            t for t in self._plugin_endpoints
            if t[0] != plugin_name
        ]

    def _register_mgmt_page(self, plugin_name, key, title,
                            builder, handler=None, roles=None):
        full_key = f"plugin:{plugin_name}:{key}"
        self._mgmt_plugin_pages[full_key] = {
            "title": title,
            "roles": tuple(roles) if roles else None,
            "builder": builder,
            "handler": handler,
            "plugin": plugin_name,
        }

    def _remove_mgmt_page(self, plugin_name):
        to_remove = [k for k, v in self._mgmt_plugin_pages.items()
                     if v.get("plugin") == plugin_name]
        for k in to_remove:
            self._mgmt_plugin_pages.pop(k, None)

    def _register_mgmt_endpoint(self, plugin_name, path,
                                handler, methods):
        self._mgmt_plugin_endpoints.append(
            (plugin_name, path, handler, tuple(methods)))

    def _remove_mgmt_endpoints(self, plugin_name):
        self._mgmt_plugin_endpoints = [
            t for t in self._mgmt_plugin_endpoints
            if t[0] != plugin_name
        ]


def _resolve_tls(warehouse_dir, force_tls):
    """Определяет, включать ли TLS.

    force_tls=True  — всегда.
    force_tls=False — читаем settings.tls_enabled ("1" → True).
    Если включено, но серта нет — генерируем.
    """
    if force_tls:
        enabled = True
    else:
        s = read_settings(
            os.path.join(warehouse_dir, "warehouse.db")) or {}
        enabled = str(s.get("tls_enabled") or "0") == "1"
    if enabled and not has_cert(warehouse_dir):
        print("[headless] TLS: сертификат не найден — генерирую")
        try:
            fp = generate_cert(warehouse_dir)
            print(f"[headless] TLS fp: {fp}")
        except Exception as e:
            print(f"[headless] TLS: не удалось создать сертификат: {e}")
            print("[headless] стартуем без TLS")
            return False
    return enabled


def main():
    _configure_stdio()

    parser = argparse.ArgumentParser(
        description="Headless-сервер склада Луч")
    parser.add_argument("warehouse_folder",
                        help="Папка склада (где лежит warehouse.db)")
    parser.add_argument("--port", type=int, default=8765,
                        help="Порт (по умолчанию 8765)")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Адрес (по умолчанию 0.0.0.0)")
    parser.add_argument("--safe", action="store_true",
                        help="Safe mode: без плагинов")
    parser.add_argument("--tls", action="store_true",
                        help="Включить TLS (HTTPS) принудительно")
    args = parser.parse_args()

    wh_path = args.warehouse_folder
    if not os.path.isdir(wh_path):
        print(f"Папка склада не найдена: {wh_path}")
        sys.exit(1)
    db_path = os.path.join(wh_path, "warehouse.db")
    if not os.path.isfile(db_path):
        print(f"warehouse.db не найден в папке: {wh_path}")
        sys.exit(1)

    # Важно: НЕ передаём sys.argv в QGuiApplication — Qt начнёт
    # парсить путь к складу и может крэшнуться.
    app = QGuiApplication([sys.argv[0]])
    app.setApplicationName("Luch Headless")

    run_all_migrations(db_path)

    tls_enabled = _resolve_tls(wh_path, args.tls)

    host = HeadlessHost(db_path, safe_mode=args.safe)

    if not args.safe:
        base_dir = os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))
        pm = PluginManager(base_dir, db_path, host)
        host.plugin_manager = pm
        set_host(host)
        try:
            pm.activate_all()
        except Exception as e:
            print(f"[headless] плагины: {e}")
    else:
        set_host(host)
        print("[headless] SAFE MODE: плагины не активируются")

    try:
        start_server(db_path, host=args.host, port=args.port,
                     tls=tls_enabled)
    except Exception as e:
        print(f"[headless] сервер не запущен: {e}")
        sys.exit(1)

    print("=" * 60)
    print("[headless] сервер запущен. Ctrl+C для остановки.")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[headless] остановка…")
    finally:
        try:
            stop_server()
        except Exception:
            pass


if __name__ == "__main__":
    main()