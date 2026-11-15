package com.wms.client.api

import android.util.Base64
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.reflect.TypeToken
import com.wms.client.view.NotFoundResult
import com.wms.client.view.NotificationItem
import com.wms.client.view.ViewEnvelope
import com.wms.client.view.ViewMeta
import com.wms.client.view.ViewNode
import com.wms.client.view.safeBool
import com.wms.client.view.safeInt
import com.wms.client.view.safeString
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLException
import javax.net.ssl.SSLSocket
import javax.net.ssl.TrustManager
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager


class ApiException(
    message: String,
    val isNetwork: Boolean = false,
    val isTls: Boolean = false,
    val tlsFp: String = ""
) : Exception(message)


data class TaskFull(
    val id: Int,
    val task_number: String,
    val task_type: String,
    val status: String,
    val assignee_login: String?,
    val target_a: Int,
    val target_b: Int,
    val processed_a: Int,
    val processed_b: Int,
    val created_at: String?,
    val container_barcode: String? = null,
    val batch_id: String? = null,
    val block_bf: String? = null
)

data class TaskItem(
    val id: Int,
    val task_id: Int,
    val item_code: String? = null,
    val item_name: String? = null,
    val item_barcode: String? = null,
    val cell_barcode: String? = null,
    val container_barcode: String? = null,
    val quantity: Int = 0,
    val processed: Int = 0,
    val step_no: Int = 0,
    val status: String = "pending"
)

data class TaskDetails(val task: TaskFull, val items: List<TaskItem>)

data class MeInfo(
    val fio: String = "—",
    val roles: List<String> = emptyList()
)

data class TaskStatus(
    val exists: Boolean = false,
    val status: String = "",
    val assigneeLogin: String = ""
)

data class SessionInfo(
    val key: String,
    val title: String
)


class Api {
    var base: String = ""
    var token: String? = null
    var locale: String = "ru"
    val settings = mutableMapOf<String, String>()

    var serverPem: String = ""
        private set

    private val gson = Gson()
    private val jsonType = "application/json; charset=utf-8".toMediaType()

    private var client: OkHttpClient = defaultClient()

    private fun defaultClient(): OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .build()

    private fun pinnedClient(pem: String): OkHttpClient {
        val trust = makeTrustManager(pem)
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf<TrustManager>(trust), null)
        return OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .sslSocketFactory(ctx.socketFactory, trust)
            .build()
    }

    /**
     * Устанавливает базовый URL.
     *
     * Для HTTPS обязателен [pem] — сертификат сервера,
     * сохранённый ранее или полученный через [doTofu].
     * Клиент будет доверять ТОЛЬКО этому сертификату
     * (системные CA игнорируются — это pinning).
     */
    fun setBase(url: String, pem: String?) {
        base = url.trimEnd('/')
        token = null
        settings.clear()
        if (base.startsWith("https://")) {
            if (pem.isNullOrBlank()) {
                throw ApiException(
                    "TLS: сертификат сервера не передан",
                    isNetwork = false, isTls = true)
            }
            serverPem = pem
            client = pinnedClient(pem)
        } else {
            serverPem = ""
            client = defaultClient()
        }
    }

    /**
     * Нужен ли TOFU для данного URL?
     *
     * - http → false (TLS нет).
     * - https + сохранённого PEM нет → true.
     * - https + сохранённый PEM есть + fp в QR отсутствует
     *   → false (используем сохранённый).
     * - https + сохранённый PEM есть + fp в QR есть
     *   и совпадает → false.
     * - https + сохранённый PEM есть + fp в QR есть
     *   и НЕ совпадает → true (сервер перевыпустил серт).
     */
    fun needsTofu(url: String, fpInQr: String?, savedPem: String?): Boolean {
        if (!url.startsWith("https://")) return false
        if (savedPem.isNullOrBlank()) return true
        if (fpInQr.isNullOrBlank()) return false
        return fingerprintOfPem(savedPem) != fpInQr
    }

    /**
     * Выполняет TOFU: забирает сертификат с сервера
     * без валидации, сверяет fingerprint с [fpInQr].
     * Возвращает PEM для сохранения.
     * Блокирующий — вызывать из Dispatchers.IO.
     */
    fun doTofu(url: String, fpInQr: String): String {
        val (host, port) = splitHostPort(url)
        val pem = fetchPeerPem(host, port)
            ?: throw ApiException(
                "Сервер не вернул сертификат",
                isNetwork = true, isTls = true)
        val actual = fingerprintOfPem(pem)
        if (actual != fpInQr) {
            throw ApiException(
                "Сертификат сервера не совпадает с QR. " +
                "Возможна MITM-атака.",
                isNetwork = false, isTls = true,
                tlsFp = actual)
        }
        return pem
    }

    private fun post(path: String, body: Map<String, Any?>): JsonObject {
        val mutableBody = body.toMutableMap()
        mutableBody["locale"] = locale
        val payload = gson.toJson(mutableBody)
        val req = Request.Builder()
            .url(base + path)
            .post(payload.toRequestBody(jsonType))
            .build()
        try {
            client.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                return gson.fromJson(text, JsonObject::class.java)
            }
        } catch (e: SSLException) {
            throw ApiException(
                e.message ?: "TLS handshake failed",
                isNetwork = true, isTls = true)
        } catch (e: java.net.ConnectException) {
            throw ApiException(e.message ?: "connection refused",
                isNetwork = true)
        } catch (e: java.net.SocketTimeoutException) {
            throw ApiException(e.message ?: "timeout", isNetwork = true)
        } catch (e: java.net.UnknownHostException) {
            throw ApiException(e.message ?: "unknown host",
                isNetwork = true)
        } catch (e: IOException) {
            throw ApiException(e.message ?: "io error", isNetwork = true)
        } catch (e: Exception) {
            throw ApiException(e.message ?: "network error",
                isNetwork = true)
        }
    }

    private fun withToken(vararg extra: Pair<String, Any?>):
            Map<String, Any?> {
        val m = mutableMapOf<String, Any?>("token" to token)
        extra.forEach { m[it.first] = it.second }
        return m
    }

    fun ping(): Boolean {
        return try {
            val r = post("/ping", emptyMap())
            r.get("ok")?.asBoolean == true
        } catch (_: Exception) { false }
    }

    fun login(login: String, secret: String): Pair<Boolean, String?> {
        val r = post("/login", mapOf(
            "login" to login, "secret" to secret))
        return if (r.get("ok")?.asBoolean == true) {
            token = r.get("token")?.asString
            true to null
        } else {
            false to (r.get("error")?.asString ?: "invalid")
        }
    }

    fun logout(): Boolean {
        return try {
            val old = token
            token = old
            val r = post("/logout", withToken())
            token = null
            r.get("ok")?.asBoolean == true
        } catch (_: Exception) {
            token = null
            false
        }
    }

    fun me(): MeInfo {
        val r = post("/employees/me", withToken())
        if (r.get("ok")?.asBoolean != true) return MeInfo()
        val fio = r.safeString("fio") ?: "—"
        val roles = mutableListOf<String>()
        r.getAsJsonArray("roles")?.forEach {
            if (it.isJsonPrimitive) roles.add(it.asString)
        }
        return MeInfo(fio, roles)
    }

    fun loadSettings(): Boolean {
        val r = post("/settings", withToken())
        if (r.get("ok")?.asBoolean == true) {
            settings.clear()
            r.getAsJsonObject("settings")?.entrySet()
                ?.forEach { (k, v) ->
                    if (v != null && !v.isJsonNull) {
                        try { settings[k] = v.asString }
                        catch (_: Exception) {}
                    }
                }
            return true
        }
        return false
    }

    fun capabilitiesHello(
        protocol: String,
        widgets: List<String>,
        actions: List<String>,
        features: List<String>,
        device: String
    ): Boolean {
        val r = post("/capabilities/hello", mapOf(
            "protocol" to protocol,
            "widgets" to widgets,
            "actions" to actions,
            "features" to features,
            "device" to device
        ))
        return r.get("ok")?.asBoolean == true
    }

    fun loadLocales(): Map<String, ServerLocale>? {
        val r = post("/ui_config", emptyMap())
        if (r.get("ok")?.asBoolean != true) return null
        val cfg = r.getAsJsonObject("config") ?: return null
        val loc = cfg.getAsJsonObject("locales") ?: return null
        val available = loc.getAsJsonArray("available") ?: return null
        val data = loc.getAsJsonObject("data")
        val out = mutableMapOf<String, ServerLocale>()
        for (it in available) {
            if (!it.isJsonObject) continue
            val o = it.asJsonObject
            val code = o.safeString("code") ?: continue
            val dict = mutableMapOf<String, String>()
            val d = data?.getAsJsonObject(code)
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
                name = o.safeString("name") ?: code.uppercase(),
                rtl = o.safeBool("rtl"),
                fallback = o.safeString("fallback"),
                data = dict
            )
        }
        return out
    }

    fun sessionsList(): List<SessionInfo> {
        val r = post("/sessions/list",
                     withToken("device" to "android"))
        if (r.get("ok")?.asBoolean != true) return emptyList()
        val arr = r.getAsJsonArray("sessions") ?: return emptyList()
        val out = mutableListOf<SessionInfo>()
        for (el in arr) {
            if (!el.isJsonObject) continue
            val o = el.asJsonObject
            val key = o.safeString("key") ?: ""
            val title = o.safeString("title") ?: key
            if (key.isNotEmpty()) out.add(SessionInfo(key, title))
        }
        return out
    }

    fun sessionsStart(key: String): ViewEnvelope {
        val r = post("/sessions/$key/start",
                     withToken("device" to "android"))
        return parseEnvelope(r)
    }

    fun sessionsAction(
        key: String,
        actionId: String,
        value: String?
    ): ViewEnvelope {
        val body = mutableMapOf<String, Any?>(
            "token" to token,
            "id" to actionId,
            "device" to "android"
        )
        if (value != null) body["value"] = value
        val r = post("/sessions/$key/action", body)
        return parseEnvelope(r)
    }

    fun sessionsClose(key: String): Boolean {
        val r = post("/sessions/$key/close",
                     withToken("device" to "android"))
        return r.get("ok")?.asBoolean == true
    }

    fun menuView(itemId: String): ViewEnvelope {
        val r = post("/menu/$itemId/view",
                     withToken("device" to "android"))
        return parseEnvelope(r)
    }

    fun nextTask(platform: String = "android"):
            Pair<TaskDetails?, String?> {
        val r = post("/tasks/next",
                     withToken("platform" to platform))
        if (r.get("ok")?.asBoolean != true) {
            val err = r.safeString("error")
            return null to when (err) {
                "no tasks" -> "no_tasks"
                "no roles" -> "no_roles"
                "race" -> "race"
                null, "" -> "error_start"
                else -> err
            }
        }
        val task = gson.fromJson(r.getAsJsonObject("task"),
                                 TaskFull::class.java)
        val t = object : TypeToken<List<TaskItem>>() {}.type
        val items: List<TaskItem> = gson.fromJson(
            r.getAsJsonArray("items"), t)
        return TaskDetails(task, items) to null
    }

    fun taskStatus(taskId: Int): TaskStatus {
        val r = post("/tasks/$taskId/status", withToken())
        if (r.get("ok")?.asBoolean != true) {
            return TaskStatus(exists = true, status = "")
        }
        return TaskStatus(
            exists = r.safeBool("exists"),
            status = r.safeString("status") ?: "",
            assigneeLogin = r.safeString("assignee_login") ?: ""
        )
    }

    fun taskView(taskId: Int): ViewEnvelope {
        val r = post("/tasks/$taskId/view", withToken())
        return parseEnvelope(r)
    }

    fun taskAction(
        taskId: Int,
        action: String,
        actionId: String?,
        value: String?,
        stepNo: Int?
    ): ViewEnvelope {
        val body = mutableMapOf<String, Any?>(
            "token" to token,
            "action" to action,
        )
        if (actionId != null) body["id"] = actionId
        if (value != null) body["value"] = value
        if (stepNo != null) body["step_no"] = stepNo
        val r = post("/tasks/$taskId/action", body)
        return parseEnvelope(r)
    }

    fun notificationsInbox(): List<NotificationItem> {
        val r = post("/notifications/inbox", withToken())
        if (r.get("ok")?.asBoolean != true) return emptyList()
        val arr = r.getAsJsonArray("notifications")
            ?: return emptyList()
        val out = mutableListOf<NotificationItem>()
        for (el in arr) {
            if (!el.isJsonObject) continue
            val o = el.asJsonObject
            out.add(NotificationItem(
                id = o.safeInt("id"),
                message = o.safeString("message") ?: "",
                type = o.safeString("type") ?: "info",
                createdAt = o.safeString("created_at") ?: "",
                senderLogin = o.safeString("sender_login") ?: "",
                taskId = o.safeInt("task_id")
            ))
        }
        return out
    }

    fun notificationsMarkRead(ids: List<Int>): Boolean {
        if (ids.isEmpty()) return true
        val r = post("/notifications/mark_read",
                     withToken("ids" to ids))
        return r.get("ok")?.asBoolean == true
    }

    fun uiConfigVersion(localVersion: String): Pair<String?, Boolean> {
        val r = post("/ui_config/version",
                     mapOf("version" to localVersion))
        if (r.get("ok")?.asBoolean != true) return null to false
        return r.safeString("version") to
                r.safeBool("changed")
    }

    fun uiConfig(): Pair<String, JsonObject>? {
        val r = post("/ui_config", emptyMap())
        if (r.get("ok")?.asBoolean != true) return null
        val v = r.safeString("version") ?: ""
        val cfgEl = r.get("config")
        if (cfgEl == null || !cfgEl.isJsonObject) return null
        return v to cfgEl.asJsonObject
    }

    private fun parseEnvelope(r: JsonObject): ViewEnvelope {
        if (r.get("ok")?.asBoolean != true) {
            val err = r.safeString("error") ?: "Ошибка"
            throw ApiException(err)
        }

        val nodes = mutableListOf<ViewNode>()
        val viewEl = r.get("view")
        if (viewEl != null && viewEl.isJsonObject) {
            nodes.addAll(ViewNode.parseDocument(viewEl.asJsonObject))
        }

        val mEl = r.get("meta")
        val m = if (mEl != null && mEl.isJsonObject)
            mEl.asJsonObject else JsonObject()

        val progEl = m.get("progress")
        val prog = if (progEl != null && progEl.isJsonObject)
            progEl.asJsonObject else null

        val meta = ViewMeta(
            taskId = m.safeInt("task_id"),
            taskType = m.safeString("task_type") ?: "",
            taskNumber = m.safeString("task_number") ?: "",
            status = m.safeString("status") ?: "in_progress",
            stepNo = m.safeInt("step_no"),
            totalSteps = m.safeInt("total_steps"),
            finished = m.safeBool("finished"),
            pendingAction = m.safeString("pending_action") ?: "",
            pendingCell = m.safeString("pending_cell") ?: "",
            batchId = m.safeString("batch_id") ?: "",
            blockBf = m.safeString("block_bf") ?: "",
            batchPosition = m.safeInt("batch_position"),
            batchTotal = m.safeInt("batch_total"),
            progressA = prog?.safeInt("a") ?: 0,
            progressAMax = prog?.safeInt("a_max") ?: 0,
            progressB = prog?.safeInt("b") ?: 0,
            progressBMax = prog?.safeInt("b_max") ?: 0
        )

        val msg = r.safeString("message") ?: ""

        var nf: NotFoundResult? = null
        val nfEl = r.get("not_found_result")
        if (nfEl != null && nfEl.isJsonObject) {
            val nfObj = nfEl.asJsonObject
            nf = NotFoundResult(
                result = nfObj.safeString("result") ?: "",
                message = nfObj.safeString("message") ?: "",
                newCell = nfObj.safeString("new_cell") ?: "",
                newTaskNumber = nfObj.safeString("new_task_number") ?: ""
            )
        }

        return ViewEnvelope(nodes, meta, msg, nf)
    }
}


// ================================================================
// TLS: pinning через собственный TrustManager.
// ================================================================

private fun makeTrustManager(pem: String): X509TrustManager {
    val cf = CertificateFactory.getInstance("X.509")
    val cert = cf.generateCertificate(
        ByteArrayInputStream(pem.toByteArray(Charsets.US_ASCII))
    ) as X509Certificate
    val ks = KeyStore.getInstance(KeyStore.getDefaultType())
    ks.load(null, null)
    ks.setCertificateEntry("server", cert)
    val tmf = TrustManagerFactory.getInstance(
        TrustManagerFactory.getDefaultAlgorithm())
    tmf.init(ks)
    for (tm in tmf.trustManagers) {
        if (tm is X509TrustManager) return tm
    }
    throw IllegalStateException("no X509TrustManager")
}


fun fingerprintOfDer(der: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(der)
    return Base64.encodeToString(
        digest,
        Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
}


fun fingerprintOfPem(pem: String): String {
    val cf = CertificateFactory.getInstance("X.509")
    val cert = cf.generateCertificate(
        ByteArrayInputStream(pem.toByteArray(Charsets.US_ASCII))
    ) as X509Certificate
    return fingerprintOfDer(cert.encoded)
}


private fun fetchPeerPem(host: String, port: Int,
                         timeoutMs: Int = 5000): String? {
    val trustAll = arrayOf<TrustManager>(object : X509TrustManager {
        override fun checkClientTrusted(
            chain: Array<X509Certificate>, authType: String) {}
        override fun checkServerTrusted(
            chain: Array<X509Certificate>, authType: String) {}
        override fun getAcceptedIssuers(): Array<X509Certificate> =
            emptyArray()
    })
    val ctx = SSLContext.getInstance("TLS")
    ctx.init(null, trustAll, null)
    val socket = ctx.socketFactory.createSocket() as SSLSocket
    try {
        socket.soTimeout = timeoutMs
        socket.connect(InetSocketAddress(host, port), timeoutMs)
        socket.startHandshake()
        val cert = socket.session.peerCertificates
            .firstOrNull() as? X509Certificate ?: return null
        val b64 = Base64.encodeToString(cert.encoded, Base64.NO_WRAP)
        val sb = StringBuilder()
        sb.append("-----BEGIN CERTIFICATE-----\n")
        for (chunk in b64.chunked(64)) {
            sb.append(chunk).append("\n")
        }
        sb.append("-----END CERTIFICATE-----\n")
        return sb.toString()
    } finally {
        try { socket.close() } catch (_: Exception) {}
    }
}


fun splitHostPort(url: String): Pair<String, Int> {
    var s = url.trim()
    if (s.startsWith("https://")) s = s.removePrefix("https://")
    else if (s.startsWith("http://")) s = s.removePrefix("http://")
    s = s.substringBefore("/")
    return if (":" in s) {
        val idx = s.lastIndexOf(':')
        val h = s.substring(0, idx)
        val port = s.substring(idx + 1).toIntOrNull() ?: 8765
        h to port
    } else {
        s to 8765
    }
}