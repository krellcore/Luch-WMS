package com.wms.client.api

import com.google.gson.JsonArray
import com.google.gson.JsonObject

data class ThemeConfig(
    val primary: String = "#27ae60",
    val onPrimary: String = "#ffffff",
    val secondary: String = "#2c3e50",
    val onSecondary: String = "#ecf0f1",
    val background: String = "#f0f0f0",
    val onBackground: String = "#2c3e50",
    val surface: String = "#ffffff",
    val onSurface: String = "#2c3e50",
    val error: String = "#e74c3c",
    val onError: String = "#ffffff"
)

data class BrandingConfig(
    val appName: String = "WMS",
    val taskScreenTitle: String = "Задания",
    val logoBase64: String? = null
)

data class RoleItem(val key: String, val label: String)

data class TasksScreenConfig(
    val roles: List<RoleItem> = listOf(
        RoleItem("picker", "Подбор"),
        RoleItem("putaway", "Размещение"),
        RoleItem("inventory", "Инвентаризация")
    ),
    val showProgressBars: Boolean = true,
    val taskRowFormat: String = "{task_number}  {task_type}  {processed_a}/{target_a}",
    val refreshLabel: String = "Обновить",
    val logoutLabel: String = "Выйти",
    val getTaskLabel: String = "Получить задание",
    val emptyLabel: String = "Нет доступных заданий",
    val selectHint: String = "Выберите задание из списка",
    val serverErrorLabel: String = "Ошибка сервера"
)

data class ExecScreenConfig(
    val finishEarlyLabel: String = "Завершить досрочно",
    val cancelLabel: String = "Отмена",
    val notFoundLabel: String = "Не найден",
    val confirmLabel: String = "Подтвердить шаг",
    val showStepProgress: Boolean = true,
    val showEmulator: Boolean = false,
    val emulatorHint: String = "Штрихкод",
    val emulatorLabel: String = "Эмулятор (для отладки):",
    val loadStepError: String = "Не удалось загрузить план задания",
    val stepNotAcceptScan: String = "Текущий шаг не принимает сканы"
)

data class LoginScreenConfig(
    val serverPrompt: String = "Отсканируйте QR-код сервера",
    val serverHint: String = "QR-код сервера — в разделе «Задания» на ПК",
    val employeePrompt: String = "Отсканируйте QR с пропуска",
    val changeServerLabel: String = "Сменить сервер",
    val scanServerLabel: String = "Сканировать QR сервера",
    val scanEmployeeLabel: String = "Сканировать пропуск"
)

data class ScreensConfig(
    val tasks: TasksScreenConfig = TasksScreenConfig(),
    val exec: ExecScreenConfig = ExecScreenConfig(),
    val login: LoginScreenConfig = LoginScreenConfig()
)

/** Один язык, полученный с сервера через /ui_config. */
data class ServerLocale(
    val code: String = "",
    val name: String = "",
    val rtl: Boolean = false,
    val fallback: String? = null,
    val data: Map<String, String> = emptyMap()
)

/** Пункт бокового меню, приходящий с сервера. */
data class MenuItem(
    val id: String = "",
    val title: String = "",
    val kind: String = "view",
    val content: String = "",
    val url: String = "",
    val roles: List<String> = emptyList()
)

/** Роль сотрудника (встроенная или от плагина). */
data class RoleInfo(
    val key: String = "",
    val title: String = "",
    val titleKey: String = ""
)

data class UiConfig(
    val version: String = "",
    val theme: ThemeConfig = ThemeConfig(),
    val branding: BrandingConfig = BrandingConfig(),
    val screens: ScreensConfig = ScreensConfig(),
    val locales: Map<String, ServerLocale> = emptyMap(),
    val menu: List<MenuItem> = emptyList(),
    val roles: List<RoleInfo> = emptyList()
)


object UiConfigParser {

    fun parse(root: JsonObject): UiConfig {
        val theme = root.getAsJsonObject("theme")
        val branding = root.getAsJsonObject("branding")
        val screens = root.getAsJsonObject("screens")
        val tasks = screens?.getAsJsonObject("tasks")
        val exec = screens?.getAsJsonObject("exec")
        val login = screens?.getAsJsonObject("login")

        return UiConfig(
            version = str(root, "version", ""),
            theme = ThemeConfig(
                primary = str(theme, "primary", "#27ae60"),
                onPrimary = str(theme, "onPrimary", "#ffffff"),
                secondary = str(theme, "secondary", "#2c3e50"),
                onSecondary = str(theme, "onSecondary", "#ecf0f1"),
                background = str(theme, "background", "#f0f0f0"),
                onBackground = str(theme, "onBackground", "#2c3e50"),
                surface = str(theme, "surface", "#ffffff"),
                onSurface = str(theme, "onSurface", "#2c3e50"),
                error = str(theme, "error", "#e74c3c"),
                onError = str(theme, "onError", "#ffffff")
            ),
            branding = BrandingConfig(
                appName = str(branding, "appName", "WMS"),
                taskScreenTitle = str(branding, "taskScreenTitle", "Задания"),
                logoBase64 = strOrNull(branding, "logoBase64")
            ),
            screens = ScreensConfig(
                tasks = TasksScreenConfig(
                    roles = roles(tasks?.getAsJsonArray("roles")),
                    showProgressBars = bool(tasks, "showProgressBars", true),
                    taskRowFormat = str(
                        tasks, "taskRowFormat",
                        "{task_number}  {task_type}  {processed_a}/{target_a}"
                    ),
                    refreshLabel = str(tasks, "refreshLabel", "Обновить"),
                    logoutLabel = str(tasks, "logoutLabel", "Выйти"),
                    getTaskLabel = str(tasks, "getTaskLabel",
                        "Получить задание"),
                    emptyLabel = str(tasks, "emptyLabel",
                        "Нет доступных заданий"),
                    selectHint = str(tasks, "selectHint",
                        "Выберите задание из списка"),
                    serverErrorLabel = str(tasks, "serverErrorLabel",
                        "Ошибка сервера")
                ),
                exec = ExecScreenConfig(
                    finishEarlyLabel = str(exec, "finishEarlyLabel",
                        "Завершить досрочно"),
                    cancelLabel = str(exec, "cancelLabel", "Отмена"),
                    notFoundLabel = str(exec, "notFoundLabel", "Не найден"),
                    confirmLabel = str(exec, "confirmLabel",
                        "Подтвердить шаг"),
                    showStepProgress = bool(exec, "showStepProgress", true),
                    showEmulator = bool(exec, "showEmulator", false),
                    emulatorHint = str(exec, "emulatorHint", "Штрихкод"),
                    emulatorLabel = str(exec, "emulatorLabel",
                        "Эмулятор (для отладки):"),
                    loadStepError = str(exec, "loadStepError",
                        "Не удалось загрузить план задания"),
                    stepNotAcceptScan = str(exec, "stepNotAcceptScan",
                        "Текущий шаг не принимает сканы")
                ),
                login = LoginScreenConfig(
                    serverPrompt = str(login, "serverPrompt",
                        "Отсканируйте QR-код сервера"),
                    serverHint = str(login, "serverHint",
                        "QR-код сервера — в разделе «Задания» на ПК"),
                    employeePrompt = str(login, "employeePrompt",
                        "Отсканируйте QR с пропуска"),
                    changeServerLabel = str(login, "changeServerLabel",
                        "Сменить сервер"),
                    scanServerLabel = str(login, "scanServerLabel",
                        "Сканировать QR сервера"),
                    scanEmployeeLabel = str(login, "scanEmployeeLabel",
                        "Сканировать пропуск")
                )
            ),
            locales = parseLocales(root.getAsJsonObject("locales")),
            menu = parseMenu(root.getAsJsonObject("menu")),
            roles = parseRoleInfo(root.getAsJsonArray("roles"))
        )
    }

    private fun parseLocales(el: JsonObject?): Map<String, ServerLocale> {
        if (el == null) return emptyMap()
        val available = el.getAsJsonArray("available") ?: return emptyMap()
        val dataEl = el.getAsJsonObject("data")
        val out = mutableMapOf<String, ServerLocale>()
        for (it in available) {
            if (!it.isJsonObject) continue
            val o = it.asJsonObject
            val code = str(o, "code", "")
            if (code.isEmpty()) continue
            val dict = mutableMapOf<String, String>()
            val d = dataEl?.getAsJsonObject(code)
            if (d != null) {
                for ((k, v) in d.entrySet()) {
                    if (v != null && !v.isJsonNull) {
                        try { dict[k] = v.asString }
                        catch (_: Exception) {}
                    }
                }
            }
            out[code] = ServerLocale(
                code = code,
                name = str(o, "name", code.uppercase()),
                rtl = bool(o, "rtl", false),
                fallback = strOrNull(o, "fallback"),
                data = dict
            )
        }
        return out
    }

    private fun parseMenu(el: JsonObject?): List<MenuItem> {
        if (el == null) return emptyList()
        val arr = el.getAsJsonArray("items") ?: return emptyList()
        val out = mutableListOf<MenuItem>()
        for (it in arr) {
            if (!it.isJsonObject) continue
            val o = it.asJsonObject
            val id = str(o, "id", "")
            if (id.isEmpty()) continue
            val roles = mutableListOf<String>()
            val rolesArr = o.getAsJsonArray("roles")
            if (rolesArr != null) {
                for (r in rolesArr) {
                    if (r.isJsonPrimitive) {
                        try { roles.add(r.asString) }
                        catch (_: Exception) {}
                    }
                }
            }
            out.add(MenuItem(
                id = id,
                title = str(o, "title", id),
                kind = str(o, "kind", "view"),
                content = str(o, "content", ""),
                url = str(o, "url", ""),
                roles = roles
            ))
        }
        return out
    }

    private fun parseRoleInfo(arr: JsonArray?): List<RoleInfo> {
        if (arr == null) return emptyList()
        val out = mutableListOf<RoleInfo>()
        for (el in arr) {
            if (!el.isJsonObject) continue
            val o = el.asJsonObject
            val key = str(o, "key", "")
            if (key.isEmpty()) continue
            out.add(RoleInfo(
                key = key,
                title = str(o, "title", key),
                titleKey = str(o, "title_key", "")
            ))
        }
        return out
    }

    private fun str(o: JsonObject?, key: String, def: String): String {
        if (o == null || !o.has(key)) return def
        val v = o.get(key)
        if (v.isJsonNull) return def
        return try { v.asString } catch (_: Exception) { def }
    }

    private fun strOrNull(o: JsonObject?, key: String): String? {
        if (o == null || !o.has(key)) return null
        val v = o.get(key)
        if (v.isJsonNull) return null
        return try { v.asString } catch (_: Exception) { null }
    }

    private fun bool(o: JsonObject?, key: String, def: Boolean): Boolean {
        if (o == null || !o.has(key)) return def
        val v = o.get(key)
        if (v.isJsonNull) return def
        return try { v.asBoolean } catch (_: Exception) { def }
    }

    private fun roles(arr: JsonArray?): List<RoleItem> {
        if (arr == null) return emptyList()
        val out = mutableListOf<RoleItem>()
        for (el in arr) {
            if (!el.isJsonObject) continue
            val o = el.asJsonObject
            val key = str(o, "key", "")
            val label = str(o, "label", key)
            if (key.isNotEmpty()) out.add(RoleItem(key, label))
        }
        return out
    }
}