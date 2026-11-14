package com.wms.client

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.wms.client.api.ServerLocale

/**
 * Универсальная локализация.
 *
 * Встроенные языки ru/en доступны всегда.
 * После подключения к серверу клиент получает словари через
 * /ui_config и сохраняет их в SharedPreferences. Ключи с префиксом
 * "client." из серверных файлов применяются к клиентским текстам
 * (префикс снимается). Все остальные ключи (plugin.*, task.*,
 * common.*) тоже кладутся в словарь — чтобы плагины и роли
 * могли использовать свои переводы.
 */
object Lang {
    private const val PREFS = "wms_locales"
    private const val KEY_DATA = "data"
    private const val KEY_META = "meta"

    private val builtInRu: Map<String, String> = mapOf(
        "title" to "Луч",
        "login_server_prompt" to "Отсканируйте QR-код сервера",
        "login_server_hint" to "(QR находится в разделе «Задания» в панели «ШК сервера»)",
        "login_emp_prompt" to "Отсканируйте QR с пропуска",
        "login_emp_hint" to "Поднесите QR сотрудника к сканеру",
        "change_server" to "Сменить сервер",
        "user" to "Пользователь: {fio}",
        "logout" to "Выйти",
        "sessions" to "Сессии",
        "get_task" to "Получить задание",
        "loading" to "Загрузка задания…",
        "refresh" to "Обновить",
        "task_done" to "Задание выполнено",
        "to_modes" to "К режимам",
        "no_connection" to "Нет связи с сервером",
        "work_blocked" to "Работа заблокирована. Ожидание связи…",
        "last_contact" to "Последний контакт: {sec} сек назад",
        "attempt" to "Попытка: {n}",
        "reconnecting" to "Переподключение…",
        "notif_title" to "Уведомление",
        "notif_urgent" to "🔴 СРОЧНО",
        "notif_read" to "Прочитано",
        "not_found_relocated" to "Найдено рядом",
        "not_found_split" to "Найдено частично",
        "not_found_lost" to "Товар утерян",
        "not_found_result" to "Результат",
        "not_found_cell" to "Ячейка: {cell}",
        "not_found_task" to "Новое задание: {task}",
        "ok" to "ОК",
        "batch_block" to "Блок {bf}",
        "batch_part" to "Часть {pos} из {total}",
        "role_picker" to "Подбор",
        "role_receiver" to "Приёмка",
        "role_putaway" to "Размещение",
        "role_inventory" to "Инвентаризация",
        "close_session" to "Закрыть",
        "session_title" to "Сессия",
        "server" to "Сервер:",
        "from" to "От:",
        "no_tasks" to "Нет доступных заданий",
        "no_roles" to "Нет назначенных ролей, обратитесь к руководителю",
        "race" to "Кто-то уже забрал это задание",
        "error_start" to "Не удалось получить задание",
        "err_server_unavailable" to "Сервер недоступен. Проверьте, что сервер включён и сеть работает.",
        "err_server_timeout" to "Сервер не отвечает. Проверьте соединение.",
        "sidebar_brand" to "ЛУЧ",
        "menu_language" to "Язык",
        "menu_scanner_settings" to "Настройки сканера",
        "menu_back" to "Назад",
        "menu_about" to "О программе",
        "menu_logout" to "Выйти",
        "menu_open" to "Меню",
        "scanner_settings_title" to "Настройки сканера",
        "scanner_settings_intro" to "Выберите тип устройства. От этого зависит, как будут сканироваться штрихкоды.",
        "device_pda_title" to "ТСД — терминал сбора данных",
        "device_pda_desc" to "Сканирование через встроенный сканер. Камера не используется.",
        "device_pda_short" to "ТСД",
        "device_phone_title" to "Android-устройство без сканера",
        "device_phone_desc" to "Сканирование через встроенную камеру. Превью камеры появится внизу окна задания.",
        "device_phone_short" to "Телефон",
        "scan_with_camera" to "📷 Сканировать",
    )

    private val builtInEn: Map<String, String> = mapOf(
        "title" to "Luch",
        "login_server_prompt" to "Scan server QR code",
        "login_server_hint" to "(QR code is in «Tasks» section under «Server barcode»)",
        "login_emp_prompt" to "Scan employee badge QR",
        "login_emp_hint" to "Present employee QR to scanner",
        "change_server" to "Change server",
        "user" to "User: {fio}",
        "logout" to "Logout",
        "sessions" to "Sessions",
        "get_task" to "Get task",
        "loading" to "Loading task…",
        "refresh" to "Refresh",
        "task_done" to "Task completed",
        "to_modes" to "To modes",
        "no_connection" to "No connection to server",
        "work_blocked" to "Work blocked. Waiting for connection…",
        "last_contact" to "Last contact: {sec} sec ago",
        "attempt" to "Attempt: {n}",
        "reconnecting" to "Reconnecting…",
        "notif_title" to "Notification",
        "notif_urgent" to "🔴 URGENT",
        "notif_read" to "Read",
        "not_found_relocated" to "Found nearby",
        "not_found_split" to "Partially found",
        "not_found_lost" to "Item lost",
        "not_found_result" to "Result",
        "not_found_cell" to "Cell: {cell}",
        "not_found_task" to "New task: {task}",
        "ok" to "OK",
        "batch_block" to "Block {bf}",
        "batch_part" to "Part {pos} of {total}",
        "role_picker" to "Picker",
        "role_receiver" to "Receiver",
        "role_putaway" to "Putaway",
        "role_inventory" to "Inventory",
        "close_session" to "Close",
        "session_title" to "Session",
        "server" to "Server:",
        "from" to "From:",
        "no_tasks" to "No available tasks",
        "no_roles" to "No assigned roles, contact your supervisor",
        "race" to "Someone already took this task",
        "error_start" to "Failed to get task",
        "err_server_unavailable" to "Server is unreachable. Check that the server is running and the network works.",
        "err_server_timeout" to "Server is not responding. Check the connection.",
        "sidebar_brand" to "LUCH",
        "menu_language" to "Language",
        "menu_scanner_settings" to "Scanner settings",
        "menu_back" to "Back",
        "menu_about" to "About",
        "menu_logout" to "Logout",
        "menu_open" to "Menu",
        "scanner_settings_title" to "Scanner settings",
        "scanner_settings_intro" to "Choose your device type. This determines how barcodes are scanned.",
        "device_pda_title" to "PDA — data collection terminal",
        "device_pda_desc" to "Scanning via built-in hardware scanner. Camera is not used.",
        "device_pda_short" to "PDA",
        "device_phone_title" to "Android device without scanner",
        "device_phone_desc" to "Scanning via built-in camera. Camera preview appears at the bottom of the task screen.",
        "device_phone_short" to "Phone",
        "scan_with_camera" to "📷 Scan",
    )

    private val loaded = mutableMapOf<String, Map<String, String>>()
    private val meta = mutableMapOf<String, LocaleMeta>()
    private var initialized = false

    init {
        loaded["ru"] = builtInRu
        loaded["en"] = builtInEn
        meta["ru"] = LocaleMeta(name = "Русский", rtl = false, fallback = null)
        meta["en"] = LocaleMeta(name = "English", rtl = false, fallback = "ru")
    }

    fun init(ctx: Context) {
        if (initialized) return
        try {
            val prefs = ctx.applicationContext
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val dataJson = prefs.getString(KEY_DATA, null)
            val metaJson = prefs.getString(KEY_META, null)
            val gson = Gson()
            if (dataJson != null) {
                val t = object : TypeToken<Map<String, Map<String, String>>>() {}.type
                val stored: Map<String, Map<String, String>> =
                    gson.fromJson(dataJson, t)
                for ((code, dict) in stored) {
                    val base = loaded[code] ?: emptyMap()
                    loaded[code] = base + dict
                }
            }
            if (metaJson != null) {
                val t = object : TypeToken<Map<String, LocaleMeta>>() {}.type
                val stored: Map<String, LocaleMeta> = gson.fromJson(metaJson, t)
                for ((code, m) in stored) {
                    meta[code] = m
                }
            }
        } catch (_: Exception) {}
        initialized = true
    }

    fun loadFrom(ctx: Context, serverLocales: Map<String, ServerLocale>) {
        if (serverLocales.isEmpty()) return
        init(ctx)
        val persistData = mutableMapOf<String, Map<String, String>>()
        val persistMeta = mutableMapOf<String, LocaleMeta>()
        for ((code, sl) in serverLocales) {
            val base = when (code) {
                "ru" -> builtInRu
                "en" -> builtInEn
                else -> emptyMap()
            }
            val merged = base.toMutableMap()
            for ((rawKey, value) in sl.data) {
                if (rawKey.startsWith("client.")) {
                    merged[rawKey.removePrefix("client.")] = value
                } else {
                    merged[rawKey] = value
                }
            }
            loaded[code] = merged
            val m = LocaleMeta(
                name = sl.name.ifBlank { code.uppercase() },
                rtl = sl.rtl,
                fallback = sl.fallback
            )
            meta[code] = m
            persistData[code] = merged
            persistMeta[code] = m
        }
        try {
            val prefs = ctx.applicationContext
                .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val gson = Gson()
            prefs.edit()
                .putString(KEY_DATA, gson.toJson(persistData))
                .putString(KEY_META, gson.toJson(persistMeta))
                .apply()
        } catch (_: Exception) {}
    }

    fun availableLocales(): List<String> {
        val keys = loaded.keys.toMutableList()
        if (!keys.contains("ru")) keys.add(0, "ru")
        if (!keys.contains("en")) keys.add(1, "en")
        return keys.distinct().sorted()
    }

    fun displayName(code: String): String {
        val m = meta[code]
        if (m != null && m.name.isNotBlank()) return m.name
        val builtin = mapOf(
            "ru" to "Русский", "en" to "English", "de" to "Deutsch",
            "fr" to "Français", "es" to "Español", "it" to "Italiano",
            "pt" to "Português", "pl" to "Polski", "uk" to "Українська",
            "kk" to "Қазақша", "tr" to "Türkçe", "zh" to "中文",
            "ja" to "日本語", "ko" to "한국어", "ar" to "العربية",
            "he" to "עברית"
        )
        return builtin[code] ?: code.uppercase()
    }

    fun isRtl(code: String): Boolean = meta[code]?.rtl == true

    fun t(key: String, loc: String, vararg params: Pair<String, Any?>): String {
        val safe = if (loaded.containsKey(loc)) loc else "ru"
        val text: String =
            loaded[safe]?.get(key)
                ?: meta[safe]?.fallback?.let { loaded[it]?.get(key) }
                ?: loaded["ru"]?.get(key)
                ?: loaded["en"]?.get(key)
                ?: if (key.startsWith("role_")) {
                    val rest = key.removePrefix("role_")
                    if (rest.isEmpty()) key
                    else rest.replace('_', ' ')
                        .replaceFirstChar { it.uppercase() }
                } else {
                    key
                }
        if (params.isEmpty()) return text
        var result = text
        for ((k, v) in params) {
            result = result.replace("{$k}", v?.toString() ?: "")
        }
        return result
    }

    fun humanize(err: String, loc: String): String {
        if (err.isBlank()) return t("err_server_unavailable", loc)
        val low = err.lowercase()
        val networkMarkers = listOf(
            "connection refused", "connectionerror",
            "failed to establish", "no route to host",
            "getaddrinfo", "name or service not known",
            "network is unreachable", "connection aborted",
            "connection reset", "unknown host", "io error",
            "max retries exceeded", "connectexception"
        )
        if (networkMarkers.any { low.contains(it) }) {
            return t("err_server_unavailable", loc)
        }
        if (low.contains("timeout") || low.contains("timed out")) {
            return t("err_server_timeout", loc)
        }
        return err
    }
}

data class LocaleMeta(
    val name: String = "",
    val rtl: Boolean = false,
    val fallback: String? = null
)