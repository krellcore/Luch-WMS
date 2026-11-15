package com.wms.client

import android.app.Application
import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.wms.client.api.Api
import com.wms.client.api.ApiException
import com.wms.client.api.MenuItem
import com.wms.client.api.RoleInfo
import com.wms.client.api.SessionInfo
import com.wms.client.api.UiConfig
import com.wms.client.api.UiConfigParser
import com.wms.client.view.NotFoundResult
import com.wms.client.view.NotificationItem
import com.wms.client.view.ViewMeta
import com.wms.client.view.ViewNode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext


sealed class Screen {
    object LoginServer : Screen()
    object LoginEmployee : Screen()
    object Modes : Screen()
    object SessionView : Screen()
    object TaskExec : Screen()
    object Done : Screen()
    object ScannerSettings : Screen()
    object MenuPage : Screen()
}


class WmsViewModel(app: Application) : AndroidViewModel(app) {
    val api = Api()

    var screen by mutableStateOf<Screen>(Screen.LoginServer)
        private set

    var previousScreen by mutableStateOf<Screen>(Screen.Modes)
        private set

    var forcedChoice by mutableStateOf(false)
        private set

    var serverUrl by mutableStateOf("")
    var userFio by mutableStateOf("—")
    var userRoles by mutableStateOf<List<String>>(emptyList())
    var myLogin by mutableStateOf("")
    var busy by mutableStateOf(false)

    var locale by mutableStateOf("ru")
        private set

    var deviceType by mutableStateOf("")
        private set

    var availableSessions by mutableStateOf<List<SessionInfo>>(emptyList())
    var currentSessionKey by mutableStateOf("")
    var currentSessionTitle by mutableStateOf("")
    var sessionNodes by mutableStateOf<List<ViewNode>>(emptyList())

    var currentNodes by mutableStateOf<List<ViewNode>>(emptyList())
    var currentMeta by mutableStateOf(ViewMeta())
    var lastTaskNumber by mutableStateOf("")
    var lastTaskType by mutableStateOf("")

    var online by mutableStateOf(true)
    var lastContactMs by mutableStateOf(0L)
    var failures by mutableStateOf(0)
    var offlineReason by mutableStateOf("")

    var snackbarText by mutableStateOf("")
    var snackbarId by mutableStateOf(0)

    var incomingNotifications by mutableStateOf<List<NotificationItem>>(emptyList())
    var activeNotification by mutableStateOf<NotificationItem?>(null)
    var unreadCount by mutableStateOf(0)

    var lastNotFoundResult by mutableStateOf<NotFoundResult?>(null)

    var uiConfig by mutableStateOf(UiConfig())
        private set

    var roleInfo by mutableStateOf<List<RoleInfo>>(emptyList())
        private set

    var availableLocales by mutableStateOf<List<String>>(listOf("ru", "en"))
        private set

    var menuItems by mutableStateOf<List<MenuItem>>(emptyList())
        private set

    var menuPageId by mutableStateOf("")
        private set
    var menuPageTitle by mutableStateOf("")
        private set
    var menuPageNodes by mutableStateOf<List<ViewNode>>(emptyList())
        private set
    var menuPageLoading by mutableStateOf(false)
        private set

    val batchId: String get() = currentMeta.batchId
    val blockBf: String get() = currentMeta.blockBf
    val batchPosition: Int get() = currentMeta.batchPosition
    val batchTotal: Int get() = currentMeta.batchTotal

    val visibleMenuItems: List<MenuItem>
        get() {
            val roles = userRoles.toSet()
            return menuItems.filter { item ->
                item.roles.isEmpty() ||
                    "any" in item.roles ||
                    item.roles.any { it in roles }
            }
        }

    private var heartbeat: Heartbeat? = null
    private var notifPoller: NotificationsPoller? = null
    private var taskWatchJob: Job? = null

    init {
        val prefs = app.getSharedPreferences("wms", Context.MODE_PRIVATE)
        Lang.init(app)
        availableLocales = Lang.availableLocales()
        val savedLoc = prefs.getString("locale", "ru") ?: "ru"
        changeLocale(savedLoc)

        val savedType = prefs.getString("device_type", null)
            ?: prefs.getString("input_mode", null)
        val normalized = when (savedType) {
            "pda", "scanner" -> "pda"
            "phone", "camera" -> "phone"
            else -> ""
        }
        if (normalized.isEmpty()) {
            deviceType = ""
            forcedChoice = true
            screen = Screen.ScannerSettings
        } else {
            deviceType = normalized
            screen = Screen.LoginServer
        }

        // Preload settings из кэша (если server сохранён).
        val savedServer = prefs.getString("server", "") ?: ""
        if (savedServer.isNotEmpty()) {
            api.base = savedServer
            val cached = loadSettingsCache(app, savedServer)
            if (cached.isNotEmpty()) {
                api.settings.clear()
                api.settings.putAll(cached)
            }
        }
    }

    fun roleLabel(key: String): String {
        val info = roleInfo.firstOrNull { it.key == key }
        if (info != null) {
            if (info.titleKey.isNotEmpty()) {
                val tr = Lang.t(info.titleKey, locale)
                if (tr != info.titleKey) return tr
            }
            if (info.title.isNotEmpty()) return info.title
        }
        return Lang.t("role_$key", locale)
    }

    fun changeDeviceType(mode: String) {
        val safe = if (mode == "phone") "phone" else "pda"
        deviceType = safe
        getApplication<Application>()
            .getSharedPreferences("wms", Context.MODE_PRIVATE)
            .edit().putString("device_type", safe).apply()
        if (forcedChoice) {
            forcedChoice = false
            screen = Screen.LoginServer
        }
    }

    fun openScannerSettings() {
        previousScreen = screen
        screen = Screen.ScannerSettings
    }

    fun closeScannerSettings() {
        if (forcedChoice) return
        screen = previousScreen
    }

    fun goToLoginServer() {
        screen = Screen.LoginServer
    }

    fun changeLocale(loc: String) {
        val safe = if (availableLocales.contains(loc)) loc else "ru"
        locale = safe
        api.locale = safe
        getApplication<Application>().getSharedPreferences("wms", 0)
            .edit().putString("locale", safe).apply()
    }

    fun setServer(url: String) {
        api.base = url
        serverUrl = url
        screen = Screen.LoginEmployee
        // Смена сервера = подключение к серверу: проверяем версию
        // ui_config. Если недоступен — используем кэш.
        loadUiConfigFromServer(getApplication())
        // Preload settings под новый сервер.
        val cached = loadSettingsCache(getApplication(), url)
        if (cached.isNotEmpty()) {
            api.settings.clear()
            api.settings.putAll(cached)
        }
    }

    fun loadUiConfig(ctx: Context) {
        val store = UiConfigStore(ctx)
        val local = store.version()
        uiConfig = store.load()
        roleInfo = uiConfig.roles
        menuItems = uiConfig.menu
        if (uiConfig.locales.isNotEmpty()) {
            Lang.loadFrom(ctx, uiConfig.locales)
            availableLocales = Lang.availableLocales()
            if (!availableLocales.contains(locale)) {
                changeLocale("ru")
            }
        }
        if (api.base.isNotEmpty()) {
            loadUiConfigFromServer(ctx, local)
        }
    }

    private fun loadUiConfigFromServer(ctx: Context, localVersion: String = "") {
        viewModelScope.launch {
            val (serverVersion, changed) = withContext(Dispatchers.IO) {
                try {
                    if (api.base.isEmpty()) null to false
                    else api.uiConfigVersion(localVersion)
                } catch (_: Exception) { null to false }
            }
            if (serverVersion == null || !changed) return@launch
            val full = withContext(Dispatchers.IO) {
                try { api.uiConfig() } catch (_: Exception) { null }
            }
            if (full == null) return@launch
            val store = UiConfigStore(ctx)
            store.save(full.second, full.first)
            val cfg = UiConfigParser.parse(full.second)
            uiConfig = cfg
            roleInfo = cfg.roles
            menuItems = cfg.menu
            if (cfg.locales.isNotEmpty()) {
                Lang.loadFrom(ctx, cfg.locales)
                availableLocales = Lang.availableLocales()
                if (!availableLocales.contains(locale)) {
                    changeLocale("ru")
                }
            }
        }
    }

    fun doLogin(qr: String, onResult: (Boolean, String?) -> Unit) {
        val parts = qr.split("-", limit = 2)
        if (parts.size < 2) {
            onResult(false, "Invalid QR")
            return
        }
        viewModelScope.launch {
            val res = withContext(Dispatchers.IO) {
                try { api.login(parts[0], parts[1]) }
                catch (e: Exception) {
                    false to (e.message ?: "network")
                }
            }
            if (res.first) {
                myLogin = parts[0]
                val me = withContext(Dispatchers.IO) { api.me() }
                userFio = me.fio
                userRoles = me.roles
                if (userRoles.isEmpty()) {
                    val msg = Lang.t("no_roles", locale)
                    notify(msg)
                    api.token = null
                    myLogin = ""
                    screen = Screen.LoginEmployee
                    onResult(false, msg)
                    return@launch
                }
                // Settings: пробуем сеть, при неудаче — кэш.
                val ctx = getApplication<Application>()
                val loadedOk = withContext(Dispatchers.IO) {
                    try { api.loadSettings(); true }
                    catch (_: Exception) { false }
                }
                if (loadedOk) {
                    saveSettingsCache(ctx, api.base, api.settings)
                } else {
                    val cached = loadSettingsCache(ctx, api.base)
                    if (cached.isNotEmpty()) {
                        api.settings.clear()
                        api.settings.putAll(cached)
                    }
                }
                sendCapabilities()
                startHeartbeat()
                startNotifications()
                loadModes()
            }
            onResult(res.first, res.second)
        }
    }

    // ----------------------------------------------------------------
    // Кэш /settings (SharedPreferences "wms_settings", ключ = URL сервера)
    // ----------------------------------------------------------------

    private fun loadSettingsCache(ctx: Context, serverUrl: String): Map<String, String> {
        if (serverUrl.isEmpty()) return emptyMap()
        val prefs = ctx.getSharedPreferences("wms_settings", Context.MODE_PRIVATE)
        val raw = prefs.getString(serverUrl, null) ?: return emptyMap()
        return try {
            val t = object : TypeToken<Map<String, String>>() {}.type
            Gson().fromJson(raw, t) ?: emptyMap()
        } catch (_: Exception) {
            emptyMap()
        }
    }

    private fun saveSettingsCache(ctx: Context, serverUrl: String, settings: Map<String, String>) {
        if (serverUrl.isEmpty()) return
        try {
            val prefs = ctx.getSharedPreferences("wms_settings", Context.MODE_PRIVATE)
            prefs.edit().putString(serverUrl, Gson().toJson(settings)).apply()
        } catch (_: Exception) {}
    }

    private fun sendCapabilities() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                try {
                    api.capabilitiesHello(
                        protocol = "1.0",
                        widgets = listOf(
                            "text", "heading", "caption",
                            "card", "group", "divider", "spacer",
                            "progress", "button", "input",
                            "list", "tiles", "image", "barcode",
                            "slot", "table"
                        ),
                        actions = listOf(
                            "scan", "tap", "input_submit",
                            "cancel", "custom"
                        ),
                        features = listOf(
                            "hardware_scan", "camera",
                            "vibrate", "beep"
                        ),
                        device = "android"
                    )
                } catch (_: Exception) {}
            }
        }
    }

    fun loadModes() {
        viewModelScope.launch {
            busy = true
            val sessions = withContext(Dispatchers.IO) {
                try { api.sessionsList() }
                catch (_: Exception) { emptyList<SessionInfo>() }
            }
            busy = false
            availableSessions = sessions
            screen = Screen.Modes
        }
    }

    fun getTask() {
        if (!online) {
            notify(Lang.t("no_connection", locale))
            return
        }
        viewModelScope.launch {
            busy = true
            var netErr: String? = null
            val pair = withContext(Dispatchers.IO) {
                try { api.nextTask("android") }
                catch (e: ApiException) {
                    netErr = e.message ?: "Network error"
                    if (e.isNetwork) heartbeat?.forceOffline()
                    null to null
                } catch (e: Exception) {
                    netErr = e.message ?: "Network error"
                    null to null
                }
            }
            busy = false
            val details = pair?.first
            if (details == null) {
                val errKey = pair?.second
                val msg = when (errKey) {
                    "no_roles" -> Lang.t("no_roles", locale)
                    "no_tasks" -> Lang.t("no_tasks", locale)
                    "race" -> Lang.t("race", locale)
                    "error_start" -> Lang.t("error_start", locale)
                    else -> netErr?.let { Lang.humanize(it, locale) }
                        ?: Lang.t("error_start", locale)
                }
                notify(msg)
                return@launch
            }

            lastTaskNumber = details.task.task_number
            lastTaskType = details.task.task_type

            currentMeta = ViewMeta(
                taskId = details.task.id,
                taskType = details.task.task_type,
                taskNumber = details.task.task_number,
                status = details.task.status,
                batchId = details.task.batch_id ?: "",
                blockBf = details.task.block_bf ?: "",
                progressA = details.task.processed_a,
                progressAMax = details.task.target_a,
                progressB = details.task.processed_b,
                progressBMax = details.task.target_b
            )
            currentNodes = emptyList()

            screen = Screen.TaskExec
            refreshCurrentView()
            startTaskWatch()
        }
    }

    fun startSession(key: String, title: String) {
        if (!online) {
            notify(Lang.t("no_connection", locale))
            return
        }
        viewModelScope.launch {
            busy = true
            try {
                val env = withContext(Dispatchers.IO) { api.sessionsStart(key) }
                currentSessionKey = key
                currentSessionTitle = title
                sessionNodes = env.nodes
                if (env.message.isNotEmpty()) notify(env.message)
                screen = Screen.SessionView
            } catch (e: ApiException) {
                if (e.isNetwork) {
                    heartbeat?.forceOffline()
                    notify(Lang.humanize(e.message ?: "", locale))
                } else {
                    notify(e.message ?: "Failed to open session")
                }
            } catch (e: Exception) {
                notify(e.message ?: "Failed to open session")
            }
            busy = false
        }
    }

    fun sessionAction(actionId: String, value: String?) {
        if (!online) {
            notify(Lang.t("no_connection", locale))
            return
        }
        val key = currentSessionKey
        if (key.isEmpty()) return
        viewModelScope.launch {
            try {
                val env = withContext(Dispatchers.IO) {
                    api.sessionsAction(key, actionId, value)
                }
                sessionNodes = env.nodes
                if (env.message.isNotEmpty()) notify(env.message)
            } catch (e: ApiException) {
                if (e.isNetwork) {
                    heartbeat?.forceOffline()
                    notify(Lang.humanize(e.message ?: "", locale))
                } else {
                    notify(e.message ?: "Session action error")
                }
            } catch (e: Exception) {
                notify(e.message ?: "Session action error")
            }
        }
    }

    fun closeSession() {
        val key = currentSessionKey
        if (key.isEmpty()) {
            backToModes()
            return
        }
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { api.sessionsClose(key) }
            } catch (_: Exception) {}
            currentSessionKey = ""
            currentSessionTitle = ""
            sessionNodes = emptyList()
            backToModes()
        }
    }

    fun backToModes() {
        currentNodes = emptyList()
        currentMeta = ViewMeta()
        stopTaskWatch()
        screen = Screen.Modes
        loadModes()
    }

    fun openMenuItem(item: MenuItem) {
        when (item.kind) {
            "text" -> {
                menuPageId = item.id
                menuPageTitle = item.title
                menuPageNodes = listOf(
                    ViewNode(
                        type = "text",
                        value = item.content
                    )
                )
                menuPageLoading = false
                screen = Screen.MenuPage
            }
            else -> {
                menuPageId = item.id
                menuPageTitle = item.title
                menuPageNodes = emptyList()
                menuPageLoading = true
                screen = Screen.MenuPage
                fetchMenuPage(item.id)
            }
        }
    }

    private fun fetchMenuPage(id: String) {
        viewModelScope.launch {
            try {
                val env = withContext(Dispatchers.IO) { api.menuView(id) }
                menuPageNodes = env.nodes
            } catch (e: ApiException) {
                if (e.isNetwork) {
                    heartbeat?.forceOffline()
                    notify(Lang.humanize(e.message ?: "", locale))
                } else {
                    notify(e.message ?: "Menu page error")
                }
                menuPageNodes = emptyList()
            } catch (e: Exception) {
                notify(e.message ?: "Menu page error")
                menuPageNodes = emptyList()
            } finally {
                menuPageLoading = false
            }
        }
    }

    fun closeMenuPage() {
        menuPageId = ""
        menuPageTitle = ""
        menuPageNodes = emptyList()
        menuPageLoading = false
        screen = Screen.Modes
    }

    private fun startHeartbeat() {
        heartbeat?.stop()
        heartbeat = Heartbeat(
            scope = viewModelScope,
            pingFn = { withContext(Dispatchers.IO) { api.ping() } },
            intervalMs = 10000L,
            offlineIntervalMs = 2000L,
            failureThreshold = 3,
            onStateChanged = { isOnline, lastMs, fails ->
                val wasOnline = online
                online = isOnline
                lastContactMs = lastMs
                failures = fails
                if (!isOnline && wasOnline) offlineReason = "No connection"
                if (isOnline && !wasOnline) {
                    offlineReason = ""
                    if (screen is Screen.TaskExec) refreshCurrentView()
                    else if (screen is Screen.SessionView) refreshSessionView()
                }
            }
        )
        heartbeat?.start()
    }

    fun stopHeartbeat() {
        heartbeat?.stop()
        heartbeat = null
    }

    private fun startNotifications() {
        notifPoller?.stop()
        notifPoller = NotificationsPoller(
            scope = viewModelScope,
            fetchFn = { withContext(Dispatchers.IO) { api.notificationsInbox() } },
            intervalMs = 10000L,
            onBatch = { items ->
                if (items.isNotEmpty()) {
                    incomingNotifications = incomingNotifications + items
                    unreadCount += items.size
                    if (activeNotification == null) activeNotification = items.first()
                }
            }
        )
        notifPoller?.start()
    }

    fun stopNotifications() {
        notifPoller?.stop()
        notifPoller = null
    }

    fun dismissNotification() {
        val cur = activeNotification ?: return
        val id = cur.id
        incomingNotifications = incomingNotifications.filter { it.id != id }
        activeNotification = incomingNotifications.firstOrNull()
        unreadCount = (unreadCount - 1).coerceAtLeast(0)
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                try { api.notificationsMarkRead(listOf(id)) } catch (_: Exception) {}
            }
        }
    }

    private fun startTaskWatch() {
        taskWatchJob?.cancel()
        val tid = currentMeta.taskId
        if (tid <= 0) return
        taskWatchJob = viewModelScope.launch {
            while (isActive) {
                delay(8000L)
                if (screen !is Screen.TaskExec) break
                val st = withContext(Dispatchers.IO) {
                    try { api.taskStatus(tid) }
                    catch (_: Exception) {
                        com.wms.client.api.TaskStatus(exists = true, status = "")
                    }
                }
                if (!st.exists) {
                    notify("Task was deleted")
                    backToModes()
                    break
                }
                if (st.status == "done") {
                    notify("Task completed")
                    backToModes()
                    break
                }
                if (st.assigneeLogin.isNotEmpty() && myLogin.isNotEmpty() &&
                    st.assigneeLogin != myLogin) {
                    notify("Task transferred to another employee")
                    backToModes()
                    break
                }
            }
        }
    }

    private fun stopTaskWatch() {
        taskWatchJob?.cancel()
        taskWatchJob = null
    }

    fun refreshCurrentView(taskIdOverride: Int = 0) {
        val taskId = if (taskIdOverride > 0) taskIdOverride
                     else currentMeta.taskId.takeIf { it > 0 } ?: return
        viewModelScope.launch {
            try {
                val env = withContext(Dispatchers.IO) { api.taskView(taskId) }
                applyTaskView(env.nodes, env.meta)
                if (env.notFoundResult != null) lastNotFoundResult = env.notFoundResult
                if (env.meta.finished) transitionToDone()
            } catch (e: ApiException) {
                if (e.isNetwork) {
                    heartbeat?.forceOffline()
                    notify(Lang.humanize(e.message ?: "", locale))
                } else if (online) {
                    notify(e.message ?: "Load error")
                }
            } catch (e: Exception) {
                if (online) notify(e.message ?: "Load error")
            }
        }
    }

    fun refreshSessionView() {
        val key = currentSessionKey
        if (key.isEmpty()) return
        viewModelScope.launch {
            try {
                val env = withContext(Dispatchers.IO) { api.sessionsStart(key) }
                sessionNodes = env.nodes
            } catch (_: Exception) {}
        }
    }

    fun handleTaskAction(action: String, id: String?, value: String?) {
        if (!online) {
            notify(Lang.t("no_connection", locale))
            return
        }
        val taskId = currentMeta.taskId
        if (taskId <= 0) return
        viewModelScope.launch {
            try {
                val env = withContext(Dispatchers.IO) {
                    api.taskAction(
                        taskId = taskId, action = action, actionId = id,
                        value = value, stepNo = currentMeta.stepNo
                    )
                }
                applyTaskView(env.nodes, env.meta)
                if (env.message.isNotEmpty()) notify(env.message)
                if (env.notFoundResult != null) lastNotFoundResult = env.notFoundResult
                if (env.meta.finished) transitionToDone()
            } catch (e: ApiException) {
                if (e.isNetwork) {
                    heartbeat?.forceOffline()
                    notify(Lang.humanize(e.message ?: "", locale))
                } else if (online) {
                    notify(e.message ?: "Action error")
                }
            } catch (e: Exception) {
                if (online) notify(e.message ?: "Action error")
            }
        }
    }

    fun handleTaskScan(code: String) {
        if (code.isBlank()) return
        handleTaskAction("scan", null, code)
    }

    fun consumeNotFoundResult() {
        lastNotFoundResult = null
    }

    private fun applyTaskView(nodes: List<ViewNode>, meta: ViewMeta) {
        currentNodes = nodes
        currentMeta = meta
        if (meta.taskNumber.isNotEmpty()) lastTaskNumber = meta.taskNumber
        if (meta.taskType.isNotEmpty()) lastTaskType = meta.taskType
    }

    private fun transitionToDone() {
        stopTaskWatch()
        currentNodes = emptyList()
        currentMeta = ViewMeta()
        screen = Screen.Done
        viewModelScope.launch {
            // settings уже актуальны; при переходе к Done повторно
            // не запрашиваем — сессия считается завершённой.
            loadModes()
        }
    }

    fun notify(msg: String) {
        if (msg.isNotEmpty()) {
            snackbarText = msg
            snackbarId += 1
        }
    }

    fun lastContactSeconds(): Long {
        if (lastContactMs <= 0L) return 0L
        return ((System.currentTimeMillis() - lastContactMs) / 1000L)
            .coerceAtLeast(0L)
    }

    fun logout() {
        stopTaskWatch()
        stopHeartbeat()
        stopNotifications()
        api.token = null
        api.settings.clear()
        userRoles = emptyList()
        userFio = "—"
        myLogin = ""
        incomingNotifications = emptyList()
        activeNotification = null
        currentNodes = emptyList()
        currentMeta = ViewMeta()
        availableSessions = emptyList()
        currentSessionKey = ""
        currentSessionTitle = ""
        sessionNodes = emptyList()
        menuPageId = ""
        menuPageTitle = ""
        menuPageNodes = emptyList()
        menuPageLoading = false
        screen = Screen.LoginServer
    }

    override fun onCleared() {
        stopTaskWatch()
        stopHeartbeat()
        stopNotifications()
        super.onCleared()
    }
}