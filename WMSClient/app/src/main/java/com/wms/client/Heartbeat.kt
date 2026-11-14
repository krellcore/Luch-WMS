package com.wms.client

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch


/**
 * Пингует сервер. Когда online — с интервалом intervalMs,
 * когда offline — с интервалом offlineIntervalMs (1 сек).
 *
 * forceOffline() — немедленно перевести в офлайн (при сетевой
 * ошибке во время action).
 * forceOnline() — немедленно вернуть в онлайн (при успехе).
 */
class Heartbeat(
    private val scope: CoroutineScope,
    private val pingFn: suspend () -> Boolean,
    private val intervalMs: Long = 5000L,
    private val offlineIntervalMs: Long = 1000L,
    private val failureThreshold: Int = 3,
    private val onStateChanged: (Boolean, Long, Int) -> Unit
) {
    private var job: Job? = null
    private var failures = 0
    private var online = true
    private var lastSuccessAt: Long = 0L
    private var lastError: String = ""

    val isOnline: Boolean get() = online
    val lastContactMs: Long get() = lastSuccessAt
    val failureCount: Int get() = failures
    val lastErrorText: String get() = lastError

    fun start() {
        if (job != null) return
        job = scope.launch {
            while (isActive) {
                val ok = try {
                    pingFn()
                } catch (e: Exception) {
                    lastError = e.message ?: "network"
                    false
                }
                if (ok) {
                    lastSuccessAt = System.currentTimeMillis()
                    if (!online) {
                        online = true
                        failures = 0
                        onStateChanged(true, lastSuccessAt, 0)
                    } else {
                        failures = 0
                    }
                } else {
                    failures += 1
                    if (online && failures >= failureThreshold) {
                        online = false
                        onStateChanged(false, lastSuccessAt, failures)
                    } else if (!online) {
                        onStateChanged(false, lastSuccessAt, failures)
                    }
                }
                // П.21: 1 секунда, пока офлайн, иначе обычный интервал
                val interval = if (online) intervalMs else offlineIntervalMs
                delay(interval)
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
    }

    /** Немедленно перевести в офлайн (при сетевой ошибке). */
    fun forceOffline(reason: String = "network error") {
        lastError = reason
        failures = failureThreshold
        if (online) {
            online = false
            onStateChanged(false, lastSuccessAt, failures)
        }
    }

    /** Немедленно вернуть в онлайн (например, при успехе). */
    fun forceOnline() {
        if (!online) {
            online = true
            failures = 0
            lastSuccessAt = System.currentTimeMillis()
            onStateChanged(true, lastSuccessAt, 0)
        }
    }
}