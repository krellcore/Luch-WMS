# Луч — Структура проекта

Версия **1.1.0**

```
корень_проекта/
├── main.py                       запуск списка складов;
│                                 выбор способа запуска
│                                 (сервер+клиент / только сервер);
│                                 ServerStatusWindow — метрики сервера
│                                 (по HTTPS, если сервер с TLS);
│                                 кнопка «↗» — удалённый клиент;
│                                 селектор языка из available_locales()
├── requirements.txt              зависимости серверной части
│                                 (включая cryptography для TLS)
├── README.md                     общее описание системы
├── USER_GUIDE.md                 руководство пользователя
├── LICENSE                       текст лицензии MIT (Krellcore)
├── PLUGINS.md                    плагины: установка и разработка
├── PLUGIN_API.md                 API плагинов (для разработчиков, 1.0)
├── VIEW_PROTOCOL.md              протокол клиент-сервер (v1.0)
├── structure.md                  этот файл
├── icon.png                      иконка приложения
├── logo_horizontal.png           горизонтальный логотип
├── config.json                   (создаётся автоматически;
│                                 last_server, locale)
│
├── lang/
│   ├── ru.json                   словарь русского языка
│   ├── en.json                   словарь английского языка
│   └── de.json                   словарь немецкого языка
│
├── plugins/
│   ├── __init__.py               (пустой)
│   │
│   ├── _template/                шаблон для нового плагина
│   │   ├── plugin.json
│   │   ├── plugin.py
│   │   └── lang/
│   │       └── ru.json
│   │
│   ├── example_printer/          пример: hook on_scan_after
│   │   ├── plugin.json
│   │   └── plugin.py
│   │
│   ├── example_hooks/            пример: перехват ШК + свой
│   │   ├── plugin.json           TaskHandler + helpers.py
│   │   ├── plugin.py
│   │   └── helpers.py
│   │
│   └── example_audit/            пример: mgmt-страница + меню ТСД
│       ├── plugin.json           + свой TaskHandler + роль + lang/
│       ├── plugin.py
│       ├── handlers.py
│       ├── admin_page.py
│       ├── pda_menu.py
│       └── lang/
│           ├── ru.json
│           ├── en.json
│           └── de.json
│
├── warehouses/                   (создаётся автоматически)
│   └── <name>/                   папка склада
│       ├── warehouse.db
│       ├── ui.json               (опционально)
│       ├── tls/                  (создаётся при TLS)
│       │   ├── cert.pem
│       │   ├── key.pem           (права 0600)
│       │   └── fingerprint.txt
│       └── badges/
│           └── <login>_badge.png
│
├── utils/
│   ├── __init__.py               (пустой)
│   ├── i18n.py                   локализация (потокобезопасная);
│   │                             сканирует lang/ и plugins/*/lang/
│   ├── db.py                     инициализация схемы БД, резервы,
│   │                             auth_sessions, PBKDF2-хеши
│   ├── barcodes.py               генерация ШК и QR
│   ├── ui_helpers.py             утилиты таблиц (legacy)
│   ├── roles.py                  реестр ролей сотрудников
│   │                             (встроенные + от плагинов)
│   │
│   ├── plugins.py                загрузчик плагинов (папки + legacy .py);
│   │                             PLUGIN_INFO читается через ast;
│   │                             entry валидируется на path traversal
│   ├── plugin_hooks.py           реестр hooks (chain/event/filter)
│   ├── api_public.py             публичный API для плагинов (v1.0)
│   │
│   ├── menu.py                   реестр пунктов меню ТСД
│   │                             (встроенные + от плагинов)
│   │
│   ├── view_protocol.py          примитивы view-модели (терминалы)
│   ├── view_builder.py           сборка view-документов (терминалы)
│   ├── capabilities.py           согласование возможностей клиента
│   │
│   ├── mgmt_protocol.py          примитивы mgmt-view-модели
│   ├── mgmt_view_builder.py      сайдбар + заглушки + роли
│   ├── mgmt_render.py            Qt-рендерер mgmt-документов
│   ├── mgmt_client_base.py       MgmtPageBase (тонкий клиент),
│   │                             поддерживает cert_path (TLS)
│   ├── mgmt_pages/               СЕРВЕРНЫЕ builder'ы mgmt-страниц
│   │   ├── __init__.py           реестр builder'ов
│   │   ├── about.py              APP_VERSION 1.1.0
│   │   ├── settings.py           диапазон ячеек с серверной
│   │   │                         валидацией; раздел «Безопасность»
│   │   ├── plugins_page.py
│   │   ├── employees.py          динамические роли из roles.py;
│   │   │                         regen_badge отзывает сессии
│   │   ├── notifications.py      динамические роли из roles.py;
│   │   │                         _translate_row_msg для legacy-payload
│   │   ├── drop_points.py
│   │   ├── items.py
│   │   ├── containers.py         manual_receive — таблица тар + товаров
│   │   ├── managers.py           PBKDF2, пароль ≥8, отзыв сессий
│   │   ├── tasks.py              список + панель + отчёт + wizard;
│   │   │                         отчёты по типам (pick/receive/
│   │   │                         putaway/inventory)
│   │   └── viewer.py             список ячеек + карточка + ручные операции
│   │
│   ├── server.py                 HTTP/HTTPS-сервер (протокол v1.0):
│   │                             /tasks/next, /tasks/{id}/view|action|
│   │                             status|report|finish, /sessions/*,
│   │                             /notifications/inbox|mark_read,
│   │                             /ui_config/*, /capabilities/hello,
│   │                             /employees/me, /settings, /login,
│   │                             /logout, /mgmt/login|me|logout|pages,
│   │                             /mgmt/page/{key}[/action],
│   │                             /menu/{id}/view,
│   │                             /status (метрики, только с loopback).
│   │                             Opaque-токены (auth_sessions),
│   │                             rate-limit на логин, Content-Length
│   │                             ≤ 2 МБ, таймаут сокета 15 сек,
│   │                             TLS через ssl.wrap_socket.
│   │                             Приёмка: /tasks/* для receive
│   │                             заблокирован, работает только
│   │                             /sessions/receive/*.
│   ├── tls.py                    TLS/HTTPS: генерация самоподписанного
│   │                             сертификата, fingerprint, SSLContext
│   │                             для сервера и клиента, fetch_peer_cert
│   │                             (только stdlib: ssl, cryptography)
│   ├── ui_config.py              конфиг темы, текстов, языков,
│   │                             меню, ролей (для /ui_config)
│   │
│   ├── wms.py                    окно склада (mgmt-клиент).
│   │                             Режимы:
│   │                               wms.py <папка>  — сервер+клиент
│   │                               wms.py --server URL [<папка>]
│   │                                                — удалённо
│   │                               --tls — принудительно HTTPS
│   │                             При активации плагина mgmt-страница
│   │                             сразу добавляется в сайдбар;
│   │                             _refresh_pages_from_server подтягивает
│   │                             список с /mgmt/pages в удалённом режиме.
│   ├── wms_server.py             headless-сервер (без Qt-виджетов):
│   │                               python utils/wms_server.py <папка>
│   │                               --tls — принудительно HTTPS
│   │                             QT_QPA_PLATFORM=offscreen по умолчанию
│   │                             (работает без X11, только Linux).
│   ├── setup.py                  мастер создания склада (с галочкой
│   │                             «Включить TLS», по умолчанию для новых)
│   │
│   ├── tasks/                    ОБРАБОТЧИКИ ТИПОВ ЗАДАНИЙ
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── utils.py
│   │   ├── pick.py               bf_prefix из адреса ячейки
│   │   ├── receive.py            ТОЛЬКО handle_scan; используется
│   │   │                         сессией приёмки; поток /tasks/*
│   │   │                         для receive заблокирован в server.py
│   │   ├── putaway.py
│   │   └── inventory.py
│   │
│   └── sessions/                 ДОЛГОЖИВУЩИЕ СЕССИИ
│       ├── __init__.py
│       ├── base.py
│       ├── utils.py
│       └── receive.py            приёмка на ПК-терминале
│
├── client_desktop/               ПК-терминал (PySide6, тонкий
│                                 клиент на view-протоколе v1.0)
│   ├── main.py                   кэш ui_config и settings;
│   │                             _apply_locales без фильтра client.*;
│   │                             tr() с null-safe fallback;
│   │                             #fp= в QR, TOFU, tls_badge
│   ├── api.py                    ui_config_version(), ui_config(),
│   │                             load_settings() → bool,
│   │                             set_base(url, fp), TLS pinning
│   ├── tls_client.py             TOFU, fingerprint_of_pem,
│   │                             fetch_peer_cert (только stdlib)
│   ├── config.py                 get_ui_cache/set_ui_cache,
│   │                             get_settings_cache/set_settings_cache,
│   │                             get_tls_cache/set_tls_cache
│   ├── scanner.py
│   ├── icon.png
│   ├── logo_horizontal.png
│   ├── config.json               (создаётся; ui_cache, settings_cache,
│   │                             tls_certs, locale, server)
│   └── requirements.txt
│
└── WMSClient/                    Android-клиент (Kotlin, Compose)
    ├── build.gradle.kts          versionCode 110, versionName "1.1.0"
    ├── settings.gradle.kts
    ├── gradle.properties
    ├── how-to-build.txt
    └── app/
        ├── build.gradle.kts
        ├── proguard-rules.pro
        └── src/main/
            ├── AndroidManifest.xml     allowBackup=false,
            │                           networkSecurityConfig
            ├── res/
            │   ├── drawable/logo_horizontal.png
            │   ├── mipmap-*/ic_launcher*
            │   ├── values/strings.xml
            │   ├── values/themes.xml
            │   └── xml/network_security_config.xml
            └── java/com/wms/client/
                ├── MainActivity.kt         Compose-UI + dispatchKeyEvent
                │                           для HID-сканера + AppTheme +
                │                           все экраны + EmbeddedCameraScanner
                ├── WmsViewModel.kt         roleLabel(), кэш settings,
                │                           setServer(url, fp)
                ├── UiConfigStore.kt
                ├── ActionDispatcher.kt
                ├── Heartbeat.kt
                ├── NotificationsPoller.kt
                ├── Lang.kt                 универсальная локализация
                │                           (без фильтра client.*);
                │                           t() с null-safe fallback
                ├── api/
                │   ├── Api.kt              loadSettings() → bool;
                │   │                       TLS pinning (X509TrustManager),
                │   │                       doTofu, needsTofu
                │   └── UiConfig.kt         RoleInfo, uiConfig.roles
                └── view/
                    ├── ViewNode.kt
                    └── ViewRenderer.kt
```

---

## Способы запуска

- **Сервер + клиент (на одном ПК).** `main.py` → склад → «Сервер +
  клиент». Запускает `wms_server.py` в фоне, открывает окно статуса
  сервера и клиент управления. Все разделы доступны.
- **Только сервер (headless).** `main.py` → склад → «Только сервер».
  Запускает `wms_server.py`, открывает окно статуса. Клиент не
  запускается. Клиенты — с других ПК. Или напрямую:
  `python utils/wms_server.py <папка>`.
- **Удалённый клиент.** С другого ПК: `main.py` → «↗» (адрес
  вводится в диалоге логина) или
  `wms.py --server http://<ip>:8765` (или `https://` при TLS).

Везде доступны все разделы (11 + разделы от плагинов) и wizard
создания задач. Приёмка (`receive`) — только через сессию на
ПК-терминале, не через поток заданий.

## Окно статуса сервера

Открывается при запуске сервера. Данные с `POST /status` раз в 2 сек:
- 🟢/🔴 состояние, uptime;
- название БД;
- клиенты (admin_total / workers_total / by_device);
- нагрузка (threads, requests per_sec / per_hour / per_day);
- трафик (in/out per_sec / per_hour / per_day / total).

Кнопка «Остановить сервер» — kill процесса. Крестик — закрывает
окно, сервер продолжает работать. При TLS окно статуса ходит на
`/status` по HTTPS с сертификатом из `warehouses/<name>/tls/cert.pem`.

## Версии

- Программа: **1.1.0**
- Протокол view: **1.0**
- Протокол mgmt: **1.0**
- API плагинов: **1.0**
- Примеры плагинов: **1.0.0**

## Принципы

- **Тонкие клиенты.** Все клиенты (терминалы, ПК-клиент управления)
  рендерят дерево компонентов, не зная предметной области.
- **Сервер — единственный источник истины.** Вся бизнес-логика в
  `utils/tasks/`, `utils/sessions/`, `utils/mgmt_pages/`.
  `server.py` — тонкий роутер.
- **TLS/HTTPS с pinning.** Самоподписанный сертификат на склад,
  fingerprint в QR (`WMS://ip:port#fp=<base64url(sha256(der))>`),
  TOFU при первом скане, pinning на всех последующих запросах.
  HTTP-режим сохранён для старых складов. TLS включается в мастере
  склада (галочка, по умолчанию для новых) или в
  «Настройки → Безопасность».
- **Opaque-токены сессий.** `/login` и `/mgmt/login` выдают
  случайный токен, не содержащий логин/пароль. Хранится в
  `auth_sessions` как `sha256(token)`. TTL 12 ч, продлевается
  при активности. `logout` реально отзывает.
- **Пароли — только PBKDF2-SHA256.** 600k итераций, соль 16
  байт. Legacy SHA-256 автоматически перехешируется при первом
  успешном логине. Минимум 8 символов.
- **Приёмка — только через сессию.** `receive` не создаётся wizard'ом
  и не выдаётся через `/tasks/next`. Реализация —
  `utils/sessions/receive.py`; `utils/tasks/receive.py` оставлен
  как shared helper (сессия вызывает `handle_scan`).
- **Локализация независима на клиенте.** Язык передаётся в каждом
  POST (`locale`), сервер возвращает `locale` в каждом ответе.
  `task_plan` хранит `prompt_key` + `prompt_params`, перевод — при
  рендере.
- **Безопасность задач.** `/tasks/{id}/view|action|report|finish|status`
  проверяют `assignee_login == login` (чужое задание выглядит как
  «не существует»).
- **Нет миграций.** Программа выпускается как новая.
- **Safe mode.** Запуск без плагинов; сервер работает;
  mgmt-разделы доступны (включая headless — билдеры страниц
  не зависят от `plugin_manager`).
- **Плагины — папки.** Плагин = папка в `plugins/` с `plugin.json`,
  точкой входа (`plugin.py`), (опционально) `lang/` и доп. файлами.
  Папка грузится как пакет `luch_plugin_<name>`, поэтому внутри
  работают относительные импорты (`from . import helpers`). Старый
  формат (один `.py` файл) поддерживается для совместимости.
  `PLUGIN_INFO` из legacy-файла читается через `ast.literal_eval`
  (без `exec_module`).
- **Плагины: языки рядом с плагином.** `plugins/<name>/lang/*.json`
  сканируется при загрузке; ключи попадают в общий словарь с
  префиксом `plugin.<name>.`. В коде плагина — `context.tr("key")`.
- **Плагины: свои роли.** `context.register_role(key, title_key=,
  title=, task_types=)` — роль появляется в карточке сотрудника,
  в фильтрах и в `/tasks/next`. Реестр ролей отдаётся клиентам
  в `/ui_config.roles`. Никаких «дописываний в JSON».
- **Плагины: mgmt-страницы в сайдбаре сразу.** При активации
  страница появляется в сайдбаре ПК-клиента (если роль
  подходит). `server.py::_mgmt_page_action` уважает
  `result["view"]`, возвращённый handler'ом — иначе открытый
  диалог терялся бы и «кнопки не работали».
- **Плагины: настоящий context в builder/handler.** Для
  mgmt-страниц и menu-пунктов сервер передаёт
  `PublicContext` активированного плагина (с `db()`, `tr()`,
  `query()`). Fallback `_Ctx` (когда плагин не активирован)
  предоставляет тот же минимальный API.
- **Кэш `ui_config` и `settings`.** Оба клиента кэшируют `/ui_config`
  (тема, экраны, меню, языки, роли) и `/settings`. Проверка
  актуальности — только при подключении к серверу (старт / скан
  QR). В сессии сеть для этих запросов не дёргается.
- **Метрики.** `_ServerStats` в `server.py` собирает запросы,
  трафик и клиентов; `/status` отдаёт срез для окна статуса
  (только с loopback).
- **Headless на Linux.** `wms_server.py` выставляет
  `QT_QPA_PLATFORM=offscreen` до создания `QGuiApplication` —
  работает без X11.
- **ПК-клиент управления.** Все страницы — экземпляры
  `MgmtPageBase` (`utils/mgmt_client_base.py`); `PAGE_KEY` задаётся
  в конструкторе. Отдельные Qt-классы под каждый раздел не нужны —
  вёрстка и логика на сервере (`utils/mgmt_pages/`).
- **Android-сканер.** Два режима (`device_type` в
  `SharedPreferences`): `pda` — HID-сканер перехватывается в
  `MainActivity.dispatchKeyEvent` (без `AndroidView`/`EditText`);
  `phone` — встроенное превью камеры (`EmbeddedCameraScanner` на
  `DecoratedBarcodeView`) в окне задания/сессии, с кулдауном
  1 секунда. Полноэкранный `CaptureActivity` (zxing) остаётся
  только на экранах логина. Release APK обязателен — debug-сборка
  Compose в разы медленнее на слабых ТСД.