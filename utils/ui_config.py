"""Конфигурация UI (тема, брендинг, тексты, языки, меню, роли)."""
import os
import json
import hashlib


DEFAULT_CONFIG = {
    "theme": {
        "primary": "#27ae60",
        "onPrimary": "#ffffff",
        "secondary": "#2c3e50",
        "onSecondary": "#ecf0f1",
        "background": "#f0f0f0",
        "onBackground": "#2c3e50",
        "surface": "#ffffff",
        "onSurface": "#2c3e50",
        "error": "#e74c3c",
        "onError": "#ffffff",
    },
    "branding": {
        "appName": "WMS",
        "taskScreenTitle": "Задания",
        "logoBase64": None,
    },
    "screens": {
        "tasks": {
            "roles": [
                {"key": "picker", "label": "Подбор"},
                {"key": "putaway", "label": "Размещение"},
                {"key": "inventory", "label": "Инвентаризация"},
            ],
            "showProgressBars": True,
            "taskRowFormat": "{task_number}  {task_type}  "
                             "{processed_a}/{target_a}",
            "refreshLabel": "Обновить",
            "logoutLabel": "Выйти",
            "getTaskLabel": "Получить задание",
            "emptyLabel": "Нет доступных заданий",
            "selectHint": "Выберите задание из списка",
            "serverErrorLabel": "Ошибка сервера",
        },
        "exec": {
            "finishEarlyLabel": "Завершить досрочно",
            "cancelLabel": "Отмена",
            "notFoundLabel": "Не найден",
            "confirmLabel": "Подтвердить шаг",
            "showStepProgress": True,
            "showEmulator": False,
            "emulatorHint": "Штрихкод",
            "emulatorLabel": "Эмулятор (для отладки):",
            "loadStepError": "Не удалось загрузить план задания",
            "stepNotAcceptScan": "Текущий шаг не принимает сканы",
        },
        "login": {
            "serverPrompt": "Отсканируйте QR-код сервера",
            "serverHint": "QR-код сервера — в разделе «Задания» на ПК",
            "employeePrompt": "Отсканируйте QR с пропуска",
            "changeServerLabel": "Сменить сервер",
            "scanServerLabel": "Сканировать QR сервера",
            "scanEmployeeLabel": "Сканировать пропуск",
        },
    },
    "menu": {"items": []},
}


def config_path(db_path):
    return os.path.join(os.path.dirname(db_path), "ui.json")


def _deep_merge(base, over):
    result = dict(base)
    for k, v in over.items():
        if (k in result and isinstance(result[k], dict)
                and isinstance(v, dict)):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(db_path):
    path = config_path(db_path)
    if not os.path.exists(path):
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, user)
    except Exception as e:
        print(f"[ui_config] load error: {e}")
        return dict(DEFAULT_CONFIG)


def save_config(db_path, cfg):
    path = config_path(db_path)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ui_config] save error: {e}")
        return False


def compute_version(cfg):
    canon = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _attach_locales(cfg):
    """Добавляет языки сервера: available[] + data{}."""
    try:
        from i18n import all_locales_info, all_locales_data
        cfg["locales"] = {
            "available": all_locales_info(),
            "data": all_locales_data(),
        }
    except Exception as e:
        print(f"[ui_config] locales: {e}")
        cfg["locales"] = {"available": [], "data": {}}
    return cfg


def _attach_menu(cfg):
    """Добавляет динамические пункты меню для ТСД."""
    try:
        from menu import list_items
        cfg["menu"] = {"items": list_items()}
    except Exception as e:
        print(f"[ui_config] menu: {e}")
        cfg["menu"] = {"items": []}
    return cfg


def _attach_roles(cfg):
    """Добавляет реестр ролей из utils/roles.py.

    Формат:
      "roles": [
        {"key": "picker", "title": "Подбор",
         "title_key": "employees.role.picker"},
        {"key": "audit", "title": "Аудит ячеек",
         "title_key": "plugin.example_audit.audit.role_title"},
        ...
      ]
    """
    try:
        from roles import list_roles
        out = []
        for r in list_roles():
            out.append({
                "key": r.get("key") or "",
                "title": r.get("title") or r.get("key") or "",
                "title_key": r.get("title_key") or "",
            })
        cfg["roles"] = out
    except Exception as e:
        print(f"[ui_config] roles: {e}")
        cfg["roles"] = []
    return cfg


def get_versioned(db_path):
    cfg = load_config(db_path)
    _attach_locales(cfg)
    _attach_menu(cfg)
    _attach_roles(cfg)
    return compute_version(cfg), cfg