"""Локализация. Универсальный движок.

- Сканирует папку lang/*.json при первом обращении.
- Сканирует plugins/*/lang/*.json; ключи оттуда попадают
  в общий словарь с префиксом plugin.<plugin_name>.<key>.
- Формат JSON: {"_meta": {...}, "ключ": "значение", ...}.
- _meta: {"code": "ru", "name": "Русский", "version": "1.0.0",
          "rtl": false, "fallback": null}.
- Fallback перевода: _meta.fallback → ru.
- all_locales_info() / all_locales_data() — сериализация для /ui_config.
"""

import os
import json
import sqlite3
import threading

_local = threading.local()
_cache = {}
_meta = {}
_loaded = False
_default = "ru"


def _project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _scan_locales():
    base = _project_root()
    lang_dir = os.path.join(base, "lang")
    found = {}
    if not os.path.isdir(lang_dir):
        return found
    for fname in sorted(os.listdir(lang_dir)):
        if not fname.endswith(".json"):
            continue
        code = fname[:-5].strip()
        if not code or not code.replace("_", "").isalnum():
            continue
        path = os.path.join(lang_dir, fname)
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            print(f"i18n: пропуск {path}: {e}")
            continue
        if not isinstance(raw, dict):
            print(f"i18n: пропуск {path}: корень не объект")
            continue
        data = dict(raw)
        meta_raw = data.pop("_meta", None)
        meta = meta_raw if isinstance(meta_raw, dict) else {}
        actual_code = (meta.get("code") or code).strip() or code
        found[actual_code] = {"meta": meta, "data": data}
    return found


def _scan_plugin_locales():
    base = _project_root()
    plugins_dir = os.path.join(base, "plugins")
    out = {}
    if not os.path.isdir(plugins_dir):
        return out
    for pentry in sorted(os.listdir(plugins_dir)):
        if pentry.startswith("_") or pentry.startswith("."):
            continue
        pfull = os.path.join(plugins_dir, pentry)
        if not os.path.isdir(pfull):
            continue
        lang_dir = os.path.join(pfull, "lang")
        if not os.path.isdir(lang_dir):
            continue
        for fname in sorted(os.listdir(lang_dir)):
            if not fname.endswith(".json"):
                continue
            code = fname[:-5].strip()
            if not code or not code.replace("_", "").isalnum():
                continue
            path = os.path.join(lang_dir, fname)
            try:
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception as e:
                print(f"i18n: плагин {pentry} {path}: {e}")
                continue
            if not isinstance(raw, dict):
                continue
            data = dict(raw)
            meta_raw = data.pop("_meta", None)
            meta = meta_raw if isinstance(meta_raw, dict) else {}
            scoped = {f"plugin.{pentry}.{k}": v
                      for k, v in data.items()
                      if isinstance(k, str)}
            entry = out.setdefault(code, {"meta": {}, "data": {}})
            if meta and not entry["meta"]:
                entry["meta"] = meta
            entry["data"].update(scoped)
    return out


def _load_all():
    global _loaded, _cache, _meta
    if _loaded:
        return
    found = _scan_locales()
    if not found:
        found = {"ru": {"meta": {}, "data": {}}}
    plugin_found = _scan_plugin_locales()
    for code, pdata in plugin_found.items():
        if code in found:
            found[code]["data"].update(pdata["data"])
        else:
            found[code] = {
                "meta": pdata["meta"] or {"code": code},
                "data": pdata["data"],
            }
    _cache = {code: v["data"] for code, v in found.items()}
    _meta = {code: v["meta"] for code, v in found.items()}
    _loaded = True


def reload_locales():
    global _loaded
    _loaded = False
    _load_all()


def available_locales():
    if not _loaded:
        _load_all()
    return list(_cache.keys())


def locale_display_name(code):
    if not _loaded:
        _load_all()
    meta = _meta.get(code) or {}
    name = (meta.get("name") or "").strip()
    if name:
        return name
    builtin = {
        "ru": "Русский", "en": "English", "de": "Deutsch",
        "fr": "Français", "es": "Español", "it": "Italiano",
        "pt": "Português", "pl": "Polski", "uk": "Українська",
        "kk": "Қазақша", "tr": "Türkçe", "zh": "中文",
        "ja": "日本語", "ko": "한국어", "ar": "العربية",
        "he": "עברית",
    }
    return builtin.get(code, code.upper())


def _reference_keys():
    if not _loaded:
        _load_all()
    ref = _cache.get(_default) or {}
    if ref:
        return set(ref.keys())
    best = {}
    for d in _cache.values():
        if len(d) > len(best):
            best = d
    return set(best.keys())


def locale_info(code):
    if not _loaded:
        _load_all()
    meta = _meta.get(code) or {}
    data = _cache.get(code) or {}
    ref = _reference_keys()
    have = set(data.keys())
    missing = sorted(ref - have)
    extra = sorted(have - ref)
    total = len(ref)
    translated = len(ref & have)
    return {
        "code": code,
        "name": locale_display_name(code),
        "version": (meta.get("version") or ""),
        "rtl": bool(meta.get("rtl") or False),
        "fallback": meta.get("fallback"),
        "total": total,
        "translated": translated,
        "missing": missing,
        "extra": extra,
        "complete": (total == 0) or (translated == total),
    }


def validate_locale(code):
    info = locale_info(code)
    return {
        "ok": info["complete"],
        "missing": info["missing"],
        "extra": info["extra"],
    }


def all_locales_info():
    if not _loaded:
        _load_all()
    out = []
    for code in available_locales():
        meta = _meta.get(code) or {}
        out.append({
            "code": code,
            "name": locale_display_name(code),
            "rtl": bool(meta.get("rtl") or False),
            "fallback": meta.get("fallback"),
        })
    return out


def all_locales_data():
    if not _loaded:
        _load_all()
    return {code: dict(data) for code, data in _cache.items()}


def set_locale(code):
    global _loaded
    if not _loaded:
        _load_all()
    if code not in _cache:
        code = _default if _default in _cache else next(
            iter(_cache), "ru")
    _local.locale = code


def current_locale():
    return getattr(_local, "locale", _default)


def _resolve(loc, key):
    if not _loaded:
        _load_all()
    if loc not in _cache:
        loc = _default if _default in _cache else next(
            iter(_cache), "ru")
    text = _cache.get(loc, {}).get(key)
    if text is not None:
        return text
    fb = (_meta.get(loc) or {}).get("fallback")
    if fb and fb in _cache:
        text = _cache[fb].get(key)
        if text is not None:
            return text
    return _cache.get(_default, {}).get(key)


def _format(text, kwargs):
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except Exception:
        return text


def tr(key, default=None, **kwargs):
    text = _resolve(current_locale(), key)
    if text is None:
        text = default if default is not None else key
    return _format(text, kwargs)


def tr_in(locale, key, default=None, **kwargs):
    text = _resolve(locale, key)
    if text is None:
        text = default if default is not None else key
    return _format(text, kwargs)


def tr_fallback(keys, **kwargs):
    loc = current_locale()
    for key in keys:
        text = _resolve(loc, key)
        if text is not None:
            return _format(text, kwargs)
    return keys[-1] if keys else ""


def load_locale_from_db(db_path):
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='locale'")
        r = cur.fetchone()
        conn.close()
        return r[0] if r else None
    except Exception:
        return None


def load_locale_for_manager(db_path, login):
    if not db_path or not login:
        return None
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key=?",
                    (f"_mgmt_locale_{login}",))
        r = cur.fetchone()
        conn.close()
        if r and r[0]:
            if not _loaded:
                _load_all()
            if r[0] in _cache:
                return r[0]
    except Exception:
        pass
    return None


def save_locale_for_manager(db_path, login, code):
    if not _loaded:
        _load_all()
    if code not in _cache:
        code = _default
    if not db_path or not login:
        return False
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        key = f"_mgmt_locale_{login}"
        cur.execute("SELECT 1 FROM settings WHERE key=?", (key,))
        if cur.fetchone():
            cur.execute("UPDATE settings SET value=? WHERE key=?",
                        (code, key))
        else:
            cur.execute("INSERT INTO settings (key, value) VALUES (?, ?)",
                        (key, code))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print("save_locale_for_manager:", e)
        return False