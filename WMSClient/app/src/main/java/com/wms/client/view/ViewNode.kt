package com.wms.client.view

import com.google.gson.JsonObject


// ------------------------------------------------------------------
// Безопасные хелперы над JsonObject
// ------------------------------------------------------------------

internal fun JsonObject.safeString(key: String): String? {
    val el = get(key) ?: return null
    if (el.isJsonNull) return null
    return try {
        if (el.isJsonPrimitive) el.asString else null
    } catch (_: Exception) { null }
}

internal fun JsonObject.safeInt(key: String, def: Int = 0): Int {
    val el = get(key) ?: return def
    if (el.isJsonNull) return def
    return try {
        if (el.isJsonPrimitive && el.asJsonPrimitive.isNumber)
            el.asInt
        else def
    } catch (_: Exception) { def }
}

internal fun JsonObject.safeBool(key: String, def: Boolean = false): Boolean {
    val el = get(key) ?: return def
    if (el.isJsonNull) return def
    return try {
        if (el.isJsonPrimitive && el.asJsonPrimitive.isBoolean)
            el.asBoolean
        else def
    } catch (_: Exception) { def }
}


// ------------------------------------------------------------------


data class TileItem(
    val barcode: String = "",
    val label: String = "",
    val status: String = "pending",
    val accent: String = "default"
)

data class TableColumn(
    val key: String = "",
    val label: String = "",
    val type: String = "text",   // text | number | image
    val width: Float = 0f
)

data class ViewNode(
    val type: String,
    val value: String? = null,
    val label: String? = null,
    val id: String? = null,
    val action: String? = null,
    val enabled: Boolean = true,
    val style: String? = null,
    val level: Int = 1,
    val size: Int = 8,
    val orientation: String = "vertical",
    val spacing: Int = 8,
    val progressValue: Int = 0,
    val progressMax: Int = 0,
    val progressLabel: String? = null,
    val inputType: String = "text",
    val options: List<String> = emptyList(),
    val title: String? = null,
    val accent: String? = null,
    val items: List<TileItem> = emptyList(),
    val url: String? = null,
    val html: String? = null,
    val textBold: Boolean = false,
    val textColor: String? = null,
    val textSize: Int = 0,
    // table
    val tableColumns: List<TableColumn> = emptyList(),
    val tableRows: List<Map<String, String>> = emptyList(),
    val children: List<ViewNode> = emptyList()
) {
    companion object {
        fun parse(o: JsonObject): ViewNode {
            val type = o.safeString("type") ?: "text"

            val children = mutableListOf<ViewNode>()
            val arr = o.getAsJsonArray("children")
            if (arr != null) {
                for (el in arr) {
                    if (el.isJsonObject) {
                        children.add(parse(el.asJsonObject))
                    }
                }
            }

            val items = mutableListOf<TileItem>()
            val tiles = o.getAsJsonArray("items")
            if (tiles != null) {
                for (el in tiles) {
                    if (!el.isJsonObject) continue
                    val t = el.asJsonObject
                    items.add(TileItem(
                        barcode = t.safeString("barcode") ?: "",
                        label = t.safeString("label")
                            ?: t.safeString("barcode") ?: "",
                        status = t.safeString("status") ?: "pending",
                        accent = t.safeString("accent") ?: "default"
                    ))
                }
            }

            // table
            val tableColumns = mutableListOf<TableColumn>()
            val colsArr = o.getAsJsonArray("columns")
            if (colsArr != null) {
                for (el in colsArr) {
                    if (!el.isJsonObject) continue
                    val c = el.asJsonObject
                    val colKey = c.safeString("key") ?: ""
                    if (colKey.isEmpty()) continue
                    val widthEl = c.get("width")
                    val w = if (widthEl != null && !widthEl.isJsonNull
                        && widthEl.isJsonPrimitive) {
                        try { widthEl.asFloat } catch (_: Exception) { 0f }
                    } else 0f
                    tableColumns.add(TableColumn(
                        key = colKey,
                        label = c.safeString("label") ?: colKey,
                        type = c.safeString("type") ?: "text",
                        width = w
                    ))
                }
            }
            val tableRows = mutableListOf<Map<String, String>>()
            val rowsArr = o.getAsJsonArray("rows")
            if (rowsArr != null) {
                for (el in rowsArr) {
                    if (!el.isJsonObject) continue
                    val rowObj = el.asJsonObject
                    val rowMap = mutableMapOf<String, String>()
                    for ((k, v) in rowObj.entrySet()) {
                        if (v != null && !v.isJsonNull) {
                            try { rowMap[k] = v.asString }
                            catch (_: Exception) { rowMap[k] = "" }
                        } else {
                            rowMap[k] = ""
                        }
                    }
                    tableRows.add(rowMap)
                }
            }

            val options = mutableListOf<String>()
            val optsArr = o.getAsJsonArray("options")
            if (optsArr != null) {
                for (el in optsArr) {
                    if (el.isJsonPrimitive) options.add(el.asString)
                }
            }

            // style: объект для text, строка для button
            var bold = false
            var color: String? = null
            var tsize = 0
            var buttonStyle: String? = null
            val styleEl = o.get("style")
            if (styleEl != null && !styleEl.isJsonNull) {
                if (styleEl.isJsonObject) {
                    val styleObj = styleEl.asJsonObject
                    bold = styleObj.safeBool("bold")
                    color = styleObj.safeString("color")
                    tsize = styleObj.safeInt("size")
                } else if (styleEl.isJsonPrimitive
                    && styleEl.asJsonPrimitive.isString) {
                    buttonStyle = styleEl.asString
                }
            }

            return ViewNode(
                type = type,
                value = o.safeString("value"),
                label = o.safeString("label"),
                id = o.safeString("id"),
                action = o.safeString("action"),
                enabled = o.safeBool("enabled", true),
                style = buttonStyle,
                level = o.safeInt("level", 1),
                size = o.safeInt("size", 8),
                orientation = o.safeString("orientation")
                    ?: "vertical",
                spacing = o.safeInt("spacing", 8),
                progressValue = o.safeInt("value", 0),
                progressMax = o.safeInt("max", 0),
                progressLabel = o.safeString("label"),
                inputType = o.safeString("input_type") ?: "text",
                options = options,
                title = o.safeString("title"),
                accent = o.safeString("accent"),
                items = items,
                url = o.safeString("url"),
                html = o.safeString("html"),
                textBold = bold,
                textColor = color,
                textSize = tsize,
                tableColumns = tableColumns,
                tableRows = tableRows,
                children = children
            )
        }

        fun parseDocument(o: JsonObject): List<ViewNode> {
            val out = mutableListOf<ViewNode>()
            val arr = o.getAsJsonArray("children")
            if (arr != null) {
                for (el in arr) {
                    if (el.isJsonObject) out.add(parse(el.asJsonObject))
                }
            }
            return out
        }
    }
}


data class ViewMeta(
    val taskId: Int = 0,
    val taskType: String = "",
    val taskNumber: String = "",
    val status: String = "in_progress",
    val stepNo: Int = 0,
    val totalSteps: Int = 0,
    val finished: Boolean = false,
    val pendingAction: String = "",
    val pendingCell: String = "",
    val batchId: String = "",
    val blockBf: String = "",
    val batchPosition: Int = 0,
    val batchTotal: Int = 0,
    val progressA: Int = 0,
    val progressAMax: Int = 0,
    val progressB: Int = 0,
    val progressBMax: Int = 0
)


data class ViewEnvelope(
    val nodes: List<ViewNode>,
    val meta: ViewMeta,
    val message: String = "",
    val notFoundResult: NotFoundResult? = null
)


data class NotFoundResult(
    val result: String = "",
    val message: String = "",
    val newCell: String = "",
    val newTaskNumber: String = ""
)


data class NotificationItem(
    val id: Int = 0,
    val message: String = "",
    val type: String = "info",
    val createdAt: String = "",
    val senderLogin: String = "",
    val taskId: Int = 0
)