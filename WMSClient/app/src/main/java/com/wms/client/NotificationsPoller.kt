package com.wms.client

import com.wms.client.view.NotificationItem
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch


/**
 * Раз в intervalMs опрашивает сервер на новые уведомления.
 * Возвращённые уведомления передаются в onBatch().
 */
class NotificationsPoller(
    private val scope: CoroutineScope,
    private val fetchFn: suspend () -> List<NotificationItem>,
    private val intervalMs: Long = 5000L,
    private val onBatch: (List<NotificationItem>) -> Unit
) {
    private var job: Job? = null
    private var enabled = false

    fun start() {
        if (job != null) return
        enabled = true
        job = scope.launch {
            while (isActive && enabled) {
                try {
                    val items = fetchFn()
                    if (items.isNotEmpty()) onBatch(items)
                } catch (_: Exception) {
                    // Тихо: heartbeat занимается состоянием связи
                }
                delay(intervalMs)
            }
        }
    }

    fun stop() {
        enabled = false
        job?.cancel()
        job = null
    }
}