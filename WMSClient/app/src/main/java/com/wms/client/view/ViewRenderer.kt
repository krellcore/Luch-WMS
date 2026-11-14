package com.wms.client.view

import android.graphics.BitmapFactory
import android.util.Base64
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.net.URL


typealias OnViewAction = (String, String?, String?) -> Unit


@Composable
fun RenderDocument(
    nodes: List<ViewNode>,
    onAction: OnViewAction
) {
    Column(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        for (n in nodes) {
            RenderNode(n, onAction)
        }
    }
}


@Composable
fun RenderNode(node: ViewNode, onAction: OnViewAction) {
    when (node.type) {
        "text" -> RenderText(node)
        "heading" -> RenderHeading(node)
        "caption" -> RenderCaption(node)
        "card" -> RenderCard(node, onAction)
        "group" -> RenderGroup(node, onAction)
        "divider" -> Divider(Modifier.padding(vertical = 4.dp))
        "spacer" -> Spacer(Modifier.height(node.size.dp))
        "progress" -> RenderProgress(node)
        "button" -> RenderButton(node, onAction)
        "input" -> RenderInput(node, onAction)
        "list" -> RenderList(node, onAction)
        "tiles" -> RenderTiles(node)
        "table" -> RenderTable(node)
        "image" -> RenderImage(node)
        "barcode" -> RenderBarcode(node)
        "slot" -> RenderGroup(
            node.copy(type = "group"), onAction)
        "webview" -> RenderFallbackText(
            "(webview недоступен)")
        else -> RenderFallbackText("[${node.type}]")
    }
}


@Composable
private fun RenderText(node: ViewNode) {
    val color = parseColor(node.textColor)
    Text(
        node.value ?: "",
        modifier = Modifier.fillMaxWidth(),
        fontSize = (if (node.textSize > 0) node.textSize
                    else 16).sp,
        fontWeight = if (node.textBold) FontWeight.Bold
                     else FontWeight.Normal,
        color = color ?: LocalContentColor.current
    )
}


@Composable
private fun RenderHeading(node: ViewNode) {
    val size = when (node.level) {
        1 -> 22.sp
        2 -> 19.sp
        else -> 17.sp
    }
    Text(
        node.value ?: "",
        fontSize = size,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.fillMaxWidth()
    )
}


@Composable
private fun RenderCaption(node: ViewNode) {
    Text(
        node.value ?: "",
        fontSize = 12.sp,
        color = Color(0xFF7F8C8D),
        modifier = Modifier.fillMaxWidth()
    )
}


@Composable
private fun RenderCard(node: ViewNode, onAction: OnViewAction) {
    val bg = when (node.accent) {
        "success" -> Color(0xFFE8F5E9)
        "warning" -> Color(0xFFFFF8E1)
        "error" -> Color(0xFFFFEBEE)
        "primary" -> Color(0xFFE3F2FD)
        else -> MaterialTheme.colorScheme.surface
    }
    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(8.dp),
        color = bg,
        tonalElevation = 1.dp
    ) {
        Column(Modifier.padding(12.dp)) {
            node.title?.let {
                Text(
                    it,
                    fontWeight = FontWeight.Bold,
                    fontSize = 14.sp,
                    modifier = Modifier.padding(bottom = 6.dp)
                )
            }
            Column(
                verticalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                for (c in node.children) {
                    RenderNode(c, onAction)
                }
            }
        }
    }
}


@Composable
private fun RenderGroup(node: ViewNode, onAction: OnViewAction) {
    if (node.orientation == "horizontal") {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(
                node.spacing.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            for (c in node.children) {
                Box(Modifier.weight(1f)) {
                    RenderNode(c, onAction)
                }
            }
        }
    } else {
        Column(
            Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(
                node.spacing.dp)
        ) {
            for (c in node.children) {
                RenderNode(c, onAction)
            }
        }
    }
}


@Composable
private fun RenderProgress(node: ViewNode) {
    val max = node.progressMax.coerceAtLeast(1)
    val value = node.progressValue.coerceIn(0, max)
    val fraction = value.toFloat() / max.toFloat()
    Column(Modifier.fillMaxWidth()) {
        node.progressLabel?.let {
            Text(
                it,
                fontSize = 12.sp,
                color = Color(0xFF7F8C8D),
                modifier = Modifier.padding(bottom = 2.dp)
            )
        }
        LinearProgressIndicator(
            progress = { fraction },
            modifier = Modifier.fillMaxWidth()
        )
    }
}


@Composable
private fun RenderButton(node: ViewNode, onAction: OnViewAction) {
    val style = node.style ?: "default"
    val enabled = node.enabled
    val label = node.label ?: "OK"
    val action = node.action ?: "tap"
    val actionId = node.id
    val value = node.value

    // value="ask" — показать диалог перед отправкой
    var showConfirm by remember { mutableStateOf(false) }

    val click: () -> Unit = {
        if (value == "ask") {
            showConfirm = true
        } else {
            onAction(action, actionId, value)
        }
    }

    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text("Подтверждение") },
            text = { Text("Вы уверены?") },
            confirmButton = {
                Button(onClick = {
                    showConfirm = false
                    onAction(action, actionId, null)
                }) { Text("Да") }
            },
            dismissButton = {
                OutlinedButton(onClick = { showConfirm = false }) {
                    Text("Нет")
                }
            }
        )
    }

    when (style) {
        "primary" -> Button(
            onClick = click,
            enabled = enabled,
            modifier = Modifier.fillMaxWidth()
        ) { Text(label) }

        "danger" -> Button(
            onClick = click,
            enabled = enabled,
            colors = ButtonDefaults.buttonColors(
                containerColor = MaterialTheme.colorScheme.error,
                contentColor = MaterialTheme.colorScheme.onError
            ),
            modifier = Modifier.fillMaxWidth()
        ) { Text(label) }

        else -> OutlinedButton(
            onClick = click,
            enabled = enabled,
            modifier = Modifier.fillMaxWidth()
        ) { Text(label) }
    }
}


@Composable
private fun RenderInput(node: ViewNode, onAction: OnViewAction) {
    var text by remember(node.id, node.value) {
        mutableStateOf(node.value ?: "")
    }
    Column(Modifier.fillMaxWidth()) {
        node.label?.let { Text(it, fontSize = 13.sp) }
        when (node.inputType) {
            "select" -> {
                var expanded by remember { mutableStateOf(false) }
                Box {
                    OutlinedButton(
                        onClick = { expanded = true },
                        modifier = Modifier.fillMaxWidth()
                    ) { Text(text.ifEmpty { "—" }) }
                    DropdownMenu(
                        expanded = expanded,
                        onDismissRequest = { expanded = false }
                    ) {
                        for (opt in node.options) {
                            DropdownMenuItem(
                                text = { Text(opt) },
                                onClick = {
                                    text = opt
                                    expanded = false
                                    onAction("input_submit",
                                             node.id, opt)
                                }
                            )
                        }
                    }
                }
            }
            else -> OutlinedTextField(
                value = text,
                onValueChange = { text = it },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true
            )
        }
        Spacer(Modifier.height(4.dp))
        Button(
            onClick = {
                onAction("input_submit", node.id, text)
            },
            modifier = Modifier.fillMaxWidth()
        ) { Text("Отправить") }
    }
}


@Composable
private fun RenderList(node: ViewNode, onAction: OnViewAction) {
    Column(
        Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        for (c in node.children) {
            RenderNode(c, onAction)
        }
    }
}


@Composable
private fun RenderTiles(node: ViewNode) {
    if (node.items.isEmpty()) return
    Column(Modifier.fillMaxWidth()) {
        node.items.chunked(2).forEach { row ->
            Row(
                Modifier
                    .fillMaxWidth()
                    .padding(vertical = 2.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                row.forEach { item ->
                    Box(Modifier.weight(1f)) {
                        TileView(item)
                    }
                }
                if (row.size == 1) {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}


@Composable
private fun TileView(item: TileItem) {
    val bg = when (item.accent) {
        "success" -> Color(0xFF4CAF50)
        "warning" -> Color(0xFFFFA726)
        "primary" -> Color(0xFF2196F3)
        "error" -> Color(0xFFE53935)
        else -> Color(0xFFE0E0E0)
    }
    val fg = if (item.accent == "default" || item.accent.isEmpty())
        Color(0xFF333333) else Color.White
    Box(
        Modifier
            .height(60.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(bg)
            .padding(6.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            item.label.ifEmpty { item.barcode },
            color = fg,
            fontWeight = FontWeight.Bold,
            fontSize = 12.sp,
            textAlign = TextAlign.Center,
            maxLines = 2
        )
    }
}


@Composable
private fun RenderTable(node: ViewNode) {
    val cols = node.tableColumns
    if (cols.isEmpty()) return

    Surface(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(6.dp),
        color = Color.White
    ) {
        Column(Modifier.padding(6.dp)) {
            node.title?.let {
                Text(it, fontWeight = FontWeight.Bold,
                    fontSize = 14.sp,
                    modifier = Modifier.padding(bottom = 4.dp))
            }

            // Заголовок
            Row(
                Modifier
                    .fillMaxWidth()
                    .background(Color(0xFFF5F5F5))
                    .padding(vertical = 6.dp, horizontal = 4.dp)
            ) {
                for (c in cols) {
                    val weight = if (c.width > 0f) c.width else 1f
                    Text(
                        c.label,
                        modifier = Modifier.weight(weight),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        color = Color(0xFF2C3E50)
                    )
                }
            }

            // Строки
            for ((idx, row) in node.tableRows.withIndex()) {
                if (idx % 2 == 1) {
                    Row(Modifier
                        .fillMaxWidth()
                        .background(Color(0xFFFAFAFA))) {}
                }
                Row(
                    Modifier
                        .fillMaxWidth()
                        .background(if (idx % 2 == 1) Color(0xFFFAFAFA)
                                    else Color.White)
                        .padding(vertical = 4.dp, horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    for (c in cols) {
                        val weight = if (c.width > 0f) c.width else 1f
                        Box(Modifier.weight(weight)) {
                            val cellVal = row[c.key] ?: ""
                            when (c.type) {
                                "image" -> {
                                    if (cellVal.isNotEmpty()) {
                                        ImageCell(cellVal)
                                    } else {
                                        Text("—",
                                            fontSize = 10.sp,
                                            color = Color.Gray)
                                    }
                                }
                                "number" -> Text(
                                    cellVal,
                                    fontSize = 12.sp,
                                    textAlign = TextAlign.End,
                                    modifier = Modifier.fillMaxWidth()
                                )
                                else -> Text(cellVal, fontSize = 12.sp)
                            }
                        }
                    }
                }
            }

            if (node.tableRows.isEmpty()) {
                Text(
                    "(пусто)",
                    fontSize = 12.sp,
                    color = Color.Gray,
                    modifier = Modifier.padding(8.dp)
                )
            }
        }
    }
}


@Composable
private fun ImageCell(url: String) {
    val bmp = remember(url) { loadBitmap(url) }
    if (bmp != null) {
        Image(
            bitmap = bmp.asImageBitmap(),
            contentDescription = null,
            modifier = Modifier
                .size(40.dp)
                .clip(RoundedCornerShape(4.dp)),
            contentScale = ContentScale.Crop
        )
    } else {
        Text("—", fontSize = 10.sp, color = Color.Gray)
    }
}


@Composable
private fun RenderImage(node: ViewNode) {
    val src = node.url ?: node.value ?: ""
    val bmp = remember(src) { loadBitmap(src) }
    if (bmp != null) {
        Image(
            bitmap = bmp.asImageBitmap(),
            contentDescription = null,
            modifier = Modifier
                .fillMaxWidth()
                .height(180.dp)
                .clip(RoundedCornerShape(6.dp)),
            contentScale = ContentScale.Fit
        )
    } else {
        Surface(
            Modifier
                .fillMaxWidth()
                .height(120.dp),
            color = Color(0xFFECF0F1),
            shape = RoundedCornerShape(6.dp)
        ) {
            Box(contentAlignment = Alignment.Center) {
                Text("[изображение]", color = Color(0xFF7F8C8D))
            }
        }
    }
}


private fun loadBitmap(url: String): android.graphics.Bitmap? {
    if (url.isBlank()) return null
    try {
        if (url.startsWith("data:")) {
            val idx = url.indexOf(',')
            if (idx < 0) return null
            val b64 = url.substring(idx + 1)
            val bytes = Base64.decode(b64, Base64.DEFAULT)
            return BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
        }
        // http(s)
        val stream = URL(url).openStream()
        return BitmapFactory.decodeStream(stream)
    } catch (_: Exception) {
        return null
    }
}


@Composable
private fun RenderBarcode(node: ViewNode) {
    Surface(
        Modifier.fillMaxWidth(),
        color = Color.White,
        shape = RoundedCornerShape(6.dp)
    ) {
        Column(Modifier.padding(10.dp)) {
            node.label?.let {
                Text(it, fontSize = 12.sp,
                    color = Color(0xFF7F8C8D))
            }
            Text(
                node.value ?: "",
                fontSize = 18.sp,
                fontWeight = FontWeight.Bold,
                color = Color(0xFF2C3E50)
            )
        }
    }
}


@Composable
private fun RenderFallbackText(text: String) {
    Text(text, color = Color(0xFF7F8C8D))
}


private fun parseColor(hex: String?): Color? {
    if (hex.isNullOrEmpty()) return null
    return try {
        Color(android.graphics.Color.parseColor(hex))
    } catch (_: Exception) {
        null
    }
}