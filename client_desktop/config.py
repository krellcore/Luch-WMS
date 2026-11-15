import json
import os


CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "config.json")


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


# ================================================================
# ui_cache — полный /ui_config по каждому серверу.
# ================================================================

def get_ui_cache(cfg, server_url):
    if not server_url:
        return "", None
    entry = (cfg.get("ui_cache") or {}).get(server_url) or {}
    return entry.get("version") or "", entry.get("config")


def set_ui_cache(cfg, server_url, version, config):
    if not server_url:
        return cfg
    cache = cfg.get("ui_cache") or {}
    cache[server_url] = {
        "version": version or "",
        "config": config or {},
    }
    cfg["ui_cache"] = cache
    return cfg


# ================================================================
# settings_cache — /settings по паре (server, login).
# ================================================================

def get_settings_cache(cfg, server_url, login):
    if not server_url or not login:
        return {}
    key = f"{server_url}|{login}"
    entry = (cfg.get("settings_cache") or {}).get(key) or {}
    return entry.get("settings") or {}


def set_settings_cache(cfg, server_url, login, settings):
    if not server_url or not login:
        return cfg
    cache = cfg.get("settings_cache") or {}
    key = f"{server_url}|{login}"
    cache[key] = {"settings": dict(settings or {})}
    cfg["settings_cache"] = cache
    return cfg


# ================================================================
# tls_certs — сохранённые сертификаты серверов (pinning).
#
#   "tls_certs": {
#     "https://192.168.1.10:8765": {
#        "fp":  "<base64url(sha256(der))>",
#        "pem": "-----BEGIN CERTIFICATE-----\n..."
#     }
#   }
# ================================================================

def get_tls_cache(cfg, server_url):
    if not server_url:
        return None
    entry = (cfg.get("tls_certs") or {}).get(server_url)
    if not entry or not isinstance(entry, dict):
        return None
    return entry


def set_tls_cache(cfg, server_url, fp, pem):
    if not server_url:
        return cfg
    cache = cfg.get("tls_certs") or {}
    cache[server_url] = {"fp": fp or "", "pem": pem or ""}
    cfg["tls_certs"] = cache
    return cfg


def del_tls_cache(cfg, server_url):
    if not server_url:
        return cfg
    cache = cfg.get("tls_certs") or {}
    cache.pop(server_url, None)
    cfg["tls_certs"] = cache
    return cfg