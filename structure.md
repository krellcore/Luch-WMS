# Луч — Структура проекта

Версия **1.0.0**

```
корень_проекта/
├── main.py                       запуск списка складов;
│                                 выбор способа запуска
│                                 (сервер+клиент / только сервер);
│                                 ServerStatusWindow — метрики сервера;
│                                 кнопка «↗» — удалённый клиент
├── requirements.txt              зависимости серверной части
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
│                                 last_server для pre-fill)
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
│       └── badges/
│           └── <login>_badge.png
│
├── utils/
│   ├── __init__.py               (пустой)
│   ├── i18n.py                   локализация (потокобезопасная);
│   │                             сканирует lang/ и plugins/*/lang/
│   ├── db.py                     инициализация схемы БД, резервы
│   ├── barcodes.py               генерация ШК и QR
│   ├── ui_helpers.py             утилиты таблиц (legacy)
│   ├── roles.py                  реестр ролей сотрудников
│   │                             (встроенные + от плагинов)
│   │
│   ├── plugins.py                загрузчик плагинов (папки + legacy .py)
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
│   ├── mgmt_client_base.py       MgmtPageBase (тонкий клиент)
│   ├── mgmt_pages/               СЕРВЕРНЫЕ builder'ы mgmt-страниц
│   │   ├── __init__.py           реестр builder'ов
│   │   ├── about.py
│   │   ├── settings.py
│   │   ├── plugins_page.py
│   │   ├── employees.py          динамические роли из roles.py
│   │   ├── notifications.py      динамические роли из roles.py
│   │   ├── drop_points.py
│   │   ├── items.py
│   │   ├── containers.py
│   │   ├── managers.py
│   │   ├── tasks.py              список + панель + отчёт + wizard
│   │   └── viewer.py             список ячеек + карточка + ручные операции
│   │
│   ├── server.py                 HTTP-сервер (протокол v1.0):
│   │                             /tasks/next, /tasks/{id}/view|action|
│   │                             status|report|finish, /sessions/*,
│   │                             /notifications/inbox|mark_read,
│   │                             /ui_config/*, /capabilities/hello,
│   │                             /employees/me, /settings, /login, /ping,
│   │                             /mgmt/login|me|logout|pages,
│   │                             /mgmt/page/{key}[/action],
│   │                             /menu/{id}/view,
│   │                             /status (метрики сервера).
│   │                             Сбор метрик: requests, traffic,
│   │                             clients (admin/worker),
│   │                             per_sec/per_min срезы.
│   │                             Приёмка: /tasks/* для receive
│   │                             заблокирован, работает только
│   │                             /sessions/receive/*.
│   ├── ui_config.py              конфиг темы, текстов, языков,
│   │                             меню (для /ui_config)
│   │
│   ├── wms.py                    окно склада (mgmt-клиент).
│   │                             Режимы:
│   │                               wms.py <папка>  — сервер+клиент
│   │                               wms.py --server URL [<папка>]
│   │                                                — удалённо
│   ├── wms_server.py             headless-сервер (без Qt-виджетов):
│   │                               python utils/wms_server.py <папка>
│   │                             QT_QPA_PLATFORM=offscreen по умолчанию
│   │                             (работает без X11, только Linux).
│   ├── setup.py                  мастер создания склада
│   │
│   ├── tasks/                    ОБРАБОТЧИКИ ТИПОВ ЗАДАНИЙ
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── utils.py
│   │   ├── pick.py
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
│   ├── main.py
│   ├── api.py
│   ├── scanner.py
│   ├── config.py
│   ├── icon.png
│   ├── logo_horizontal.png
│   └── requirements.txt
│
└── WMSClient/                    Android-клиент (Kotlin, Compose)
    ├── build.gradle.kts
    ├── settings.gradle.kts
    ├── gradle.properties
    ├── how-to-build.txt
    └── app/
        ├── build.gradle.kts
        ├── proguard-rules.pro
        └── src/main/
            ├── AndroidManifest.xml
            ├── java/com/wms/client/
            │   ├── MainActivity.kt         Compose-UI + dispatchKeyEvent
            │   │                           для HID-сканера + AppTheme +
            │   │                           все экраны + EmbeddedCameraScanner
            │   ├── WmsViewModel.kt
            │   ├── UiConfigStore.kt
            │   ├── ActionDispatcher.kt
            │   ├── Heartbeat.kt
            │   ├── NotificationsPoller.kt
            │   ├── Lang.kt                универсальная локализация
            │   │                           (встроенные ru/en + сервер)
            │   ├── api/
            │   │   ├── Api.kt
            │   │   └── UiConfig.kt
            │   └── view/
            │       ├── ViewNode.kt
            │       └── ViewRenderer.kt
            └── res/
                ├── drawable/
                │   └── logo_horizontal.png
                ├── mipmap-*/
                │   └── ic_launcher*
                └── values/
                    ├── strings.xml
                    └── themes.xml
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
  `wms.py --server http://<ip>:8765`.

Везде доступны все разделы (11) и wizard создания задач.
Приёмка (`receive`) — только через сессию на ПК-терминале, не
через поток заданий.

## Окно статуса сервера

Открывается при запуске сервера. Данные с `POST /status` раз в 2 сек:
- 🟢/🔴 состояние, uptime;
- название БД;
- клиенты (admin_total / workers_total / by_device);
- нагрузка (threads, requests per_sec / per_hour / per_day);
- трафик (in/out per_sec / per_hour / per_day / total).

Кнопка «Остановить сервер» — kill процесса. Крестик — закрывает
окно, сервер продолжает работать.

## Версии

- Программа: **1.0.0**
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
- **Приёмка — только через сессию.** `receive` не создаётся wizard'ом
  и не выдаётся через `/tasks/next`. Реализация —
  `utils/sessions/receive.py`; `utils/tasks/receive.py` оставлен
  как shared helper (сессия вызывает `handle_scan`).
- **Локализация независима на клиенте.** Язык передаётся в каждом
  POST (`locale`), сервер возвращает `locale` в каждом ответе.
  `task_plan` хранит `prompt_key` + `prompt_params`, перевод — при
  рендере.
- **Безопасность паролей.** В БД хранятся только `pass_hash`.
- **Безопасность задач.** `/tasks/{id}/view|action|report|finish`
  проверяют `assignee_login == login`.
- **Нет миграций.** Программа выпускается как новая.
- **Safe mode.** Запуск без плагинов; сервер работает;
  mgmt-разделы доступны (включая headless — билдеры страниц
  не зависят от `plugin_manager`).
- **Плагины — папки.** Плагин = папка в `plugins/` с `plugin.json`,
  точкой входа (`plugin.py`), (опционально) `lang/` и доп. файлами.
  Папка грузится как пакет `luch_plugin_<name>`, поэтому внутри
  работают относительные импорты (`from . import helpers`). Старый
  формат (один `.py` файл) поддерживается для совместимости.
- **Плагины: языки рядом с плагином.** `plugins/<name>/lang/*.json`
  сканируется при загрузке; ключи попадают в общий словарь с
  префиксом `plugin.<name>.`. В коде плагина — `context.tr("key")`.
- **Плагины: свои роли.** `context.register_role(key, title_key=,
  title=, task_types=)` — роль появляется в карточке сотрудника,
  в фильтрах и в `/tasks/next`. Никаких «дописываний в JSON».
- **Метрики.** `_ServerStats` в `server.py` собирает запросы,
  трафик и клиентов; `/status` отдаёт срез для окна статуса.
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