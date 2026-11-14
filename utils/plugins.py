"""Загрузчик плагинов.

Плагин — это ПАПКА в plugins/, внутри которой:
  - plugin.json    — характеристики
  - plugin.py      — код (имя настраивается через "entry")
  - lang/*.json    — языки плагина (опционально)
  - ...            — любые доп. файлы (helpers.py, шаблоны и т.п.)

Папка загружается как Python-пакет `luch_plugin_<name>`, поэтому
внутри плагина работают относительные импорты:
    from . import helpers

Старый формат (один .py-файл) поддерживается для совместимости.
Папка приоритетнее: если есть и папка, и .py с тем же именем,
выигрывает папка.
"""

import os
import re
import sys
import json
import importlib.util
import sqlite3
import traceback

from plugin_hooks import registry
from api_public import PublicContext, API_VERSION
from menu import unregister_plugin as unregister_menu_plugin


def _safe_mod_name(name: str) -> str:
    return "luch_plugin_" + re.sub(r"[^a-zA-Z0-9_]", "_", name or "")


class PluginManager:
    def __init__(self, base_dir, db_path, host):
        self.base_dir = base_dir
        self.plugins_dir = os.path.join(base_dir, "plugins")
        self.db_path = db_path
        self.host = host
        self.loaded = {}
        self.contexts = {}

    def scan(self):
        found = {}
        if not os.path.isdir(self.plugins_dir):
            return found

        for entry in sorted(os.listdir(self.plugins_dir)):
            full = os.path.join(self.plugins_dir, entry)
            if entry.startswith("_") or entry.startswith("."):
                continue
            if not os.path.isdir(full):
                continue
            info = self._peek_folder(full)
            if not info:
                continue
            name = info["name"]
            found[name] = {
                "info": info,
                "folder": full,
                "kind": "folder",
                "entry_path": os.path.join(
                    full, info.get("entry") or "plugin.py"),
            }

        for entry in sorted(os.listdir(self.plugins_dir)):
            full = os.path.join(self.plugins_dir, entry)
            if entry.startswith("_") or entry.startswith("."):
                continue
            if not entry.endswith(".py"):
                continue
            if not os.path.isfile(full):
                continue
            info = self._peek_flat_file(full)
            if not info or "name" not in info:
                continue
            name = info["name"]
            if name in found:
                print(f"[plugins] {entry}: пропуск, есть папка "
                      f"с именем '{name}'")
                continue
            found[name] = {
                "info": info,
                "folder": None,
                "kind": "file",
                "entry_path": full,
            }

        return found

    def _peek_folder(self, folder):
        folder_name = os.path.basename(folder)
        manifest_path = os.path.join(folder, "plugin.json")
        if not os.path.isfile(manifest_path):
            print(f"[plugins] пропуск {folder}: нет plugin.json")
            return None
        try:
            with open(manifest_path, encoding="utf-8") as f:
                info = json.load(f)
        except Exception as e:
            print(f"[plugins] {manifest_path}: {e}")
            return None
        if not isinstance(info, dict):
            print(f"[plugins] {manifest_path}: корень не объект")
            return None
        declared = info.get("name")
        if declared and declared != folder_name:
            print(f"[plugins] {folder}: name='{declared}' не "
                  f"совпадает с папкой '{folder_name}'; "
                  f"используется имя папки")
        info["name"] = folder_name
        return info

    def _peek_flat_file(self, path):
        try:
            mod_name = ("_peek_"
                        + os.path.splitext(os.path.basename(path))[0])
            spec = importlib.util.spec_from_file_location(mod_name, path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return getattr(mod, "PLUGIN_INFO", None)
        except Exception as e:
            print(f"[plugins] peek failed for {path}: {e}")
            return None

    def get_active(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT value FROM settings "
                        "WHERE key='active_plugins'")
            r = cur.fetchone()
            conn.close()
            if r and r[0]:
                return json.loads(r[0])
        except Exception:
            pass
        return []

    def set_active(self, names):
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM settings "
                        "WHERE key='active_plugins'")
            if cur.fetchone():
                cur.execute(
                    "UPDATE settings SET value=? "
                    "WHERE key='active_plugins'",
                    (json.dumps(names),))
            else:
                cur.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    ("active_plugins", json.dumps(names)))
            conn.commit()
            conn.close()
        except Exception as e:
            print("set_active:", e)

    def _load_module(self, name, entry, folder):
        mod_full = _safe_mod_name(name)
        if folder:
            spec = importlib.util.spec_from_file_location(
                mod_full, entry,
                submodule_search_locations=[folder],
            )
        else:
            spec = importlib.util.spec_from_file_location(
                mod_full, entry,
            )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_full] = mod
        spec.loader.exec_module(mod)
        return mod

    def _unload_module(self, name):
        mod_full = _safe_mod_name(name)
        sys.modules.pop(mod_full, None)
        prefix = mod_full + "."
        for k in list(sys.modules.keys()):
            if k.startswith(prefix):
                sys.modules.pop(k, None)

    def activate(self, name):
        found = self.scan()
        if name not in found:
            raise RuntimeError(f"Плагин {name} не найден")
        entry = found[name]
        info = entry["info"]
        entry_path = entry["entry_path"]
        folder = entry["folder"]

        api_req = info.get("api_version")
        if api_req and api_req.split(".")[0] != API_VERSION.split(".")[0]:
            raise RuntimeError(
                f"Плагин требует API {api_req}, "
                f"ядро предоставляет {API_VERSION}"
            )

        if not os.path.isfile(entry_path):
            raise RuntimeError(
                f"Файл {entry_path} не найден")

        try:
            mod = self._load_module(name, entry_path, folder)
        except Exception as e:
            traceback.print_exc()
            self._unload_module(name)
            raise RuntimeError(f"Ошибка импорта плагина {name}: {e}")

        ctx = PublicContext(name, self.db_path, self.host, info=info)
        self.loaded[name] = mod
        self.contexts[name] = ctx

        if hasattr(mod, "register"):
            try:
                mod.register(ctx)
            except Exception as e:
                traceback.print_exc()
                self.loaded.pop(name, None)
                self.contexts.pop(name, None)
                registry.unregister_plugin(name)
                self._unload_module(name)
                raise RuntimeError(f"register() упал: {e}")

        if hasattr(self.host, "_apply_plugin_barcode_buttons"):
            try:
                self.host._apply_plugin_barcode_buttons()
            except Exception as e:
                print(f"[plugins] _apply_plugin_barcode_buttons: {e}")

        for (key, title, widget_class) in list(ctx._pages):
            try:
                self.host._register_plugin_page(name, key, title,
                                                widget_class)
            except Exception as e:
                print(f"[plugins] register_page({key}): {e}")

        for (key, title, builder, handler, roles) in list(
                ctx._mgmt_pages):
            try:
                if hasattr(self.host, "_register_mgmt_page"):
                    self.host._register_mgmt_page(
                        name, key, title, builder, handler, roles)
            except Exception as e:
                print(f"[plugins] register_mgmt_page({key}): {e}")

        for (path_m, handler_m, methods_m) in list(
                ctx._mgmt_endpoints):
            try:
                if hasattr(self.host, "_register_mgmt_endpoint"):
                    self.host._register_mgmt_endpoint(
                        name, path_m, handler_m, methods_m)
            except Exception as e:
                print(f"[plugins] register_mgmt_endpoint"
                      f"({path_m}): {e}")

        active = self.get_active()
        if name not in active:
            active.append(name)
            self.set_active(active)

        registry.call_event("on_plugin_activate", plugin=name,
                            info=info, context=ctx)

    def deactivate(self, name):
        mod = self.loaded.get(name)
        ctx = self.contexts.get(name)
        if mod and hasattr(mod, "unregister") and ctx:
            try:
                mod.unregister(ctx)
            except Exception as e:
                print(f"[plugins] unregister({name}): {e}")

        registry.unregister_plugin(name)
        registry.call_event("on_plugin_deactivate", plugin=name)

        try:
            unregister_menu_plugin(name)
        except Exception as e:
            print(f"[plugins] unregister_menu({name}): {e}")

        if hasattr(self.host, "_remove_plugin_page"):
            self.host._remove_plugin_page(name)
        if hasattr(self.host, "_remove_plugin_endpoints"):
            try:
                self.host._remove_plugin_endpoints(name)
            except Exception:
                pass
        if hasattr(self.host, "_remove_step_handlers"):
            try:
                self.host._remove_step_handlers(name)
            except Exception:
                pass
        if hasattr(self.host, "_remove_mgmt_page"):
            try:
                self.host._remove_mgmt_page(name)
            except Exception:
                pass
        if hasattr(self.host, "_remove_mgmt_endpoints"):
            try:
                self.host._remove_mgmt_endpoints(name)
            except Exception:
                pass

        try:
            from roles import unregister_plugin as _unreg_roles
            _unreg_roles(name)
        except Exception as e:
            print(f"[plugins] unregister_roles({name}): {e}")

        self.loaded.pop(name, None)
        self.contexts.pop(name, None)
        self._unload_module(name)

        active = [n for n in self.get_active() if n != name]
        self.set_active(active)

        if hasattr(self.host, "_apply_plugin_barcode_buttons"):
            try:
                self.host._apply_plugin_barcode_buttons()
            except Exception:
                pass

    def activate_all(self):
        for name in self.get_active():
            try:
                self.activate(name)
            except Exception as e:
                print(f"[plugins] не удалось активировать {name}: {e}")

    def call_chain(self, name, **kwargs):
        return registry.call_chain(name, **kwargs)

    def call_event(self, name, **kwargs):
        return registry.call_event(name, **kwargs)

    def call_filter(self, name, initial, **kwargs):
        return registry.call_filter(name, initial, **kwargs)