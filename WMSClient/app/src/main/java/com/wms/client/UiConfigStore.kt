package com.wms.client

import android.content.Context
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.wms.client.api.UiConfig
import com.wms.client.api.UiConfigParser

class UiConfigStore(ctx: Context) {
    private val prefs = ctx.getSharedPreferences("wms_ui", Context.MODE_PRIVATE)
    private val gson = Gson()

    fun version(): String = prefs.getString("version", "") ?: ""

    fun load(): UiConfig {
        val raw = prefs.getString("config", null)
        if (raw.isNullOrEmpty()) return UiConfig()
        return try {
            UiConfigParser.parse(gson.fromJson(raw, JsonObject::class.java))
        } catch (_: Exception) {
            UiConfig()
        }
    }

    fun save(rawJson: JsonObject, version: String) {
        prefs.edit()
            .putString("version", version)
            .putString("config", rawJson.toString())
            .apply()
    }
}