package com.wms.client

/**
 * Единая точка, через которую Compose-рендерер сообщает о действиях.
 * Делегирует в WmsViewModel.
 */
object ActionDispatcher {

    private var handler: ((String, String?, String?) -> Unit)? = null

    fun bind(fn: (String, String?, String?) -> Unit) {
        handler = fn
    }

    fun unbind() {
        handler = null
    }

    fun dispatch(action: String, id: String?, value: String?) {
        handler?.invoke(action, id, value)
    }
}