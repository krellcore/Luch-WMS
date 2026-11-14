package com.wms.client

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.media.AudioManager
import android.media.ToneGenerator
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.view.KeyEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.ExitToApp
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Language
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.google.zxing.BarcodeFormat
import com.google.zxing.ResultPoint
import com.journeyapps.barcodescanner.BarcodeCallback
import com.journeyapps.barcodescanner.BarcodeResult
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.wms.client.api.MenuItem
import com.wms.client.api.UiConfig
import com.wms.client.view.NotificationItem
import com.wms.client.view.RenderDocument
import kotlinx.coroutines.launch
import java.util.regex.Pattern


class MainActivity : ComponentActivity() {
    private val vm: WmsViewModel by viewModels()

    private val scanBuffer = StringBuilder()
    private val scanHandler = Handler(Looper.getMainLooper())
    private val scanFlushRunnable = Runnable {
        val code = scanBuffer.toString().trim()
        scanBuffer.setLength(0)
        if (code.isNotEmpty()) {
            try { onScanCallback(code) }
            catch (e: Exception) {
                android.util.Log.e("wms", "onScan error", e)
            }
        }
    }

    var acceptScans: Boolean = false
    var onScanCallback: (String) -> Unit = {}

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (!acceptScans) return super.dispatchKeyEvent(event)
        if (event.action != KeyEvent.ACTION_DOWN) return true

        if (event.keyCode == KeyEvent.KEYCODE_ENTER ||
            event.keyCode == KeyEvent.KEYCODE_NUMPAD_ENTER) {
            scanHandler.removeCallbacks(scanFlushRunnable)
            scanFlushRunnable.run()
            return true
        }

        val ch = event.unicodeChar
        if (ch != 0) {
            scanBuffer.append(ch.toChar())
            scanHandler.removeCallbacks(scanFlushRunnable)
            scanHandler.postDelayed(scanFlushRunnable, 250L)
            return true
        }

        return super.dispatchKeyEvent(event)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            Lang.init(this)
            val prefs = getSharedPreferences("wms", MODE_PRIVATE)
            val saved = prefs.getString("server", "") ?: ""
            val savedLoc = prefs.getString("locale", "ru") ?: "ru"
            vm.changeLocale(savedLoc)
            if (saved.isNotEmpty()) {
                vm.api.base = saved
                vm.serverUrl = saved
            }
            vm.loadUiConfig(this)
        } catch (e: Exception) {
            android.util.Log.e("wms", "onCreate init error", e)
        }

        ActionDispatcher.bind { action, id, value ->
            when (vm.screen) {
                is Screen.SessionView -> vm.sessionAction(id ?: "", value)
                is Screen.TaskExec -> vm.handleTaskAction(action, id, value)
                else -> {}
            }
        }

        setContent {
            AppTheme(vm.uiConfig) {
                Surface(Modifier.fillMaxSize()) {
                    MainRoot(vm)
                }
            }
        }
    }

    override fun onDestroy() {
        scanHandler.removeCallbacks(scanFlushRunnable)
        ActionDispatcher.unbind()
        super.onDestroy()
    }
}


@Composable
fun AppTheme(cfg: UiConfig, content: @Composable () -> Unit) {
    val colors = lightColorScheme(
        primary = parseHex(cfg.theme.primary),
        onPrimary = parseHex(cfg.theme.onPrimary),
        secondary = parseHex(cfg.theme.secondary),
        onSecondary = parseHex(cfg.theme.onSecondary),
        background = parseHex(cfg.theme.background),
        onBackground = parseHex(cfg.theme.onBackground),
        surface = parseHex(cfg.theme.surface),
        onSurface = parseHex(cfg.theme.onSurface),
        error = parseHex(cfg.theme.error),
        onError = parseHex(cfg.theme.onError)
    )
    MaterialTheme(colorScheme = colors) { content() }
}


fun parseHex(hex: String): Color {
    return try {
        Color(android.graphics.Color.parseColor(hex))
    } catch (_: Exception) {
        Color.Gray
    }
}


fun deviceShortLabel(mode: String, locale: String): String {
    return when (mode) {
        "pda" -> Lang.t("device_pda_short", locale)
        "phone" -> Lang.t("device_phone_short", locale)
        else -> "—"
    }
}


@Composable
fun LightDrawerItem(
    icon: ImageVector?,
    title: String,
    selected: Boolean,
    onClick: () -> Unit
) {
    val interactionSource = remember { MutableInteractionSource() }
    val bg = if (selected)
        MaterialTheme.colorScheme.secondaryContainer
    else
        Color.Transparent

    Row(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 2.dp)
            .heightIn(min = 44.dp)
            .clip(RoundedCornerShape(24.dp))
            .background(bg)
            .clickable(
                interactionSource = interactionSource,
                indication = null,
                onClick = onClick
            )
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        if (icon != null) {
            Icon(
                icon,
                contentDescription = null,
                modifier = Modifier.size(22.dp)
            )
            Spacer(Modifier.width(12.dp))
        }
        Text(
            title,
            fontSize = 14.sp,
            fontWeight = if (selected) FontWeight.Bold
                         else FontWeight.Normal
        )
    }
}


@Composable
fun WmsLogo(
    modifier: Modifier,
    contentScale: ContentScale = ContentScale.Fit
) {
    val ctx = LocalContext.current
    val bmp = remember(ctx) {
        try {
            val raw = BitmapFactory.decodeResource(
                ctx.resources, R.drawable.logo_horizontal
            )
            if (raw != null) {
                val scaled = Bitmap.createScaledBitmap(
                    raw, 400, 200, true
                )
                if (scaled !== raw) raw.recycle()
                scaled.asImageBitmap()
            } else null
        } catch (_: Exception) { null }
    }
    val b = bmp
    if (b != null) {
        Image(
            bitmap = b,
            contentDescription = "Luch",
            modifier = modifier,
            contentScale = contentScale
        )
    } else {
        Box(modifier, contentAlignment = Alignment.Center) {
            Text("ЛУЧ", fontSize = 22.sp, fontWeight = FontWeight.Bold)
        }
    }
}


@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainRoot(vm: WmsViewModel) {
    val ctx = LocalContext.current
    val snackbarHostState = remember { SnackbarHostState() }
    val drawerState = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    var showLangDialog by remember { mutableStateOf(false) }

    val visibleItems by remember {
        derivedStateOf {
            val roles = vm.userRoles.toSet()
            vm.menuItems.filter { item ->
                item.roles.isEmpty() ||
                    "any" in item.roles ||
                    item.roles.any { it in roles }
            }
        }
    }

    val drawerSpec = tween<Float>(
        durationMillis = 120,
        easing = LinearEasing
    )

    @Suppress("DEPRECATION")
    fun closeDrawer() {
        if (drawerState.isClosed) return
        scope.launch {
            drawerState.animateTo(DrawerValue.Closed, drawerSpec)
        }
    }

    @Suppress("DEPRECATION")
    fun toggleDrawer() {
        scope.launch {
            drawerState.animateTo(
                if (drawerState.isClosed) DrawerValue.Open
                else DrawerValue.Closed,
                drawerSpec
            )
        }
    }

    fun handleMenuItem(item: MenuItem) {
        closeDrawer()
        when (item.kind) {
            "url" -> {
                if (item.url.isNotBlank()) {
                    try {
                        ctx.startActivity(Intent(
                            Intent.ACTION_VIEW,
                            Uri.parse(item.url)
                        ))
                    } catch (_: Exception) {}
                }
            }
            else -> vm.openMenuItem(item)
        }
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        gesturesEnabled = !vm.forcedChoice,
        drawerContent = {
            ModalDrawerSheet(
                modifier = Modifier.width(240.dp),
                drawerTonalElevation = 0.dp
            ) {
                Column(
                    Modifier
                        .fillMaxWidth()
                        .padding(16.dp)
                ) {
                    Text(
                        Lang.t("sidebar_brand", vm.locale),
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        color = MaterialTheme.colorScheme.primary
                    )
                    Spacer(Modifier.height(2.dp))
                    Text(
                        vm.userFio,
                        fontSize = 12.sp,
                        color = Color(0xFF7F8C8D)
                    )
                    if (vm.userRoles.isNotEmpty()) {
                        Text(
                            vm.userRoles.joinToString(", ") {
                                vm.roleLabel(it)
                            },
                            fontSize = 11.sp,
                            color = Color(0xFF95A5A6)
                        )
                    }
                }
                HorizontalDivider()
                Spacer(Modifier.height(2.dp))

                LightDrawerItem(
                    icon = Icons.Default.Settings,
                    title = Lang.t("menu_scanner_settings", vm.locale),
                    selected = vm.screen is Screen.ScannerSettings,
                    onClick = {
                        closeDrawer()
                        vm.openScannerSettings()
                    }
                )

                LightDrawerItem(
                    icon = Icons.Default.Language,
                    title = Lang.t("menu_language", vm.locale),
                    selected = false,
                    onClick = {
                        closeDrawer()
                        showLangDialog = true
                    }
                )

                if (visibleItems.isNotEmpty()) {
                    HorizontalDivider(
                        Modifier.padding(horizontal = 12.dp,
                                         vertical = 2.dp)
                    )
                }
                for (item in visibleItems) {
                    LightDrawerItem(
                        icon = Icons.Default.Info,
                        title = item.title,
                        selected = vm.screen is Screen.MenuPage &&
                                vm.menuPageId == item.id,
                        onClick = { handleMenuItem(item) }
                    )
                }

                if (vm.myLogin.isNotEmpty()) {
                    LightDrawerItem(
                        icon = Icons.AutoMirrored.Filled.ExitToApp,
                        title = Lang.t("menu_logout", vm.locale),
                        selected = false,
                        onClick = {
                            closeDrawer()
                            vm.logout()
                        }
                    )
                }

                Spacer(Modifier.weight(1f))
            }
        }
    ) {
        Box(Modifier.fillMaxSize()) {
            if (!vm.forcedChoice) {
                Box(
                    Modifier
                        .align(Alignment.TopStart)
                        .padding(8.dp)
                        .size(44.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .clickable { toggleDrawer() },
                    contentAlignment = Alignment.Center
                ) {
                    Icon(
                        Icons.Default.Menu,
                        contentDescription = Lang.t("menu_open", vm.locale),
                        tint = Color(0xFF2C3E50)
                    )
                }
            }

            when (vm.screen) {
                is Screen.LoginServer -> LoginServerScreen(vm)
                is Screen.LoginEmployee -> LoginEmployeeScreen(vm)
                is Screen.Modes -> ModesScreen(vm)
                is Screen.SessionView -> SessionViewScreen(vm)
                is Screen.TaskExec -> TaskExecScreen(vm)
                is Screen.Done -> DoneScreen(vm)
                is Screen.ScannerSettings -> ScannerSettingsScreen(vm)
                is Screen.MenuPage -> MenuPageScreen(vm)
            }

            SnackbarHost(
                hostState = snackbarHostState,
                modifier = Modifier.align(Alignment.BottomCenter)
            )

            if (!vm.online) OfflineOverlay(vm)

            vm.activeNotification?.let { notif ->
                NotificationDialog(notif, vm.locale) { vm.dismissNotification() }
            }

            vm.lastNotFoundResult?.let { res ->
                NotFoundResultDialog(res, vm.locale) { vm.consumeNotFoundResult() }
            }

            if (showLangDialog) {
                LanguageDialog(vm) { showLangDialog = false }
            }
        }
    }

    LaunchedEffect(vm.snackbarId) {
        if (vm.snackbarId > 0) {
            snackbarHostState.showSnackbar(
                message = vm.snackbarText,
                duration = SnackbarDuration.Short
            )
        }
    }
}


@Composable
fun MenuPageScreen(vm: WmsViewModel) {
    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Spacer(Modifier.height(44.dp))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            TextButton(onClick = { vm.closeMenuPage() }) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = null
                )
                Spacer(Modifier.width(4.dp))
                Text(Lang.t("menu_back", vm.locale))
            }
            Spacer(Modifier.weight(1f))
        }
        Spacer(Modifier.height(8.dp))
        if (vm.menuPageTitle.isNotEmpty()) {
            Text(
                vm.menuPageTitle,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(16.dp))
        }
        Column(
            Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
        ) {
            if (vm.menuPageLoading) {
                Box(
                    Modifier.fillMaxWidth().padding(24.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator()
                }
            } else {
                RenderDocument(vm.menuPageNodes) { _, _, _ -> }
            }
        }
    }
}


@Composable
fun ScannerSettingsScreen(vm: WmsViewModel) {
    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(20.dp)
    ) {
        if (vm.forcedChoice) {
            Spacer(Modifier.height(40.dp))
        } else {
            Spacer(Modifier.height(44.dp))
            TextButton(onClick = { vm.closeScannerSettings() }) {
                Icon(
                    Icons.AutoMirrored.Filled.ArrowBack,
                    contentDescription = null
                )
                Spacer(Modifier.width(4.dp))
                Text(Lang.t("menu_back", vm.locale))
            }
            Spacer(Modifier.height(8.dp))
        }

        Text(
            Lang.t("scanner_settings_title", vm.locale),
            fontSize = 22.sp,
            fontWeight = FontWeight.Bold
        )
        if (vm.forcedChoice) {
            Spacer(Modifier.height(8.dp))
            Text(
                Lang.t("scanner_settings_intro", vm.locale),
                fontSize = 14.sp,
                color = Color.Gray,
                lineHeight = 19.sp
            )
        }
        Spacer(Modifier.height(24.dp))

        DeviceOptionCard(
            selected = vm.deviceType == "pda",
            title = Lang.t("device_pda_title", vm.locale),
            description = Lang.t("device_pda_desc", vm.locale),
            onClick = { vm.changeDeviceType("pda") }
        )
        Spacer(Modifier.height(12.dp))
        DeviceOptionCard(
            selected = vm.deviceType == "phone",
            title = Lang.t("device_phone_title", vm.locale),
            description = Lang.t("device_phone_desc", vm.locale),
            onClick = { vm.changeDeviceType("phone") }
        )
        Spacer(Modifier.height(16.dp))
    }
}


@Composable
private fun DeviceOptionCard(
    selected: Boolean,
    title: String,
    description: String,
    onClick: () -> Unit
) {
    Card(
        Modifier
            .fillMaxWidth()
            .clickable { onClick() }
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalAlignment = Alignment.Top
        ) {
            RadioButton(
                selected = selected,
                onClick = onClick,
                modifier = Modifier.padding(top = 2.dp)
            )
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    fontWeight = FontWeight.Bold,
                    fontSize = 16.sp,
                    lineHeight = 20.sp
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    description,
                    fontSize = 13.sp,
                    color = Color.Gray,
                    lineHeight = 18.sp
                )
            }
        }
    }
}


@Composable
fun LanguageDialog(vm: WmsViewModel, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(Lang.t("menu_language", vm.locale)) },
        text = {
            Column(
                Modifier
                    .fillMaxWidth()
                    .verticalScroll(rememberScrollState())
            ) {
                for (code in vm.availableLocales) {
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable {
                                vm.changeLocale(code)
                                onDismiss()
                            }
                            .padding(vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        RadioButton(
                            selected = code == vm.locale,
                            onClick = {
                                vm.changeLocale(code)
                                onDismiss()
                            }
                        )
                        Spacer(Modifier.width(4.dp))
                        Text(
                            "${Lang.displayName(code)} (${code})",
                            fontSize = 15.sp
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onDismiss) {
                Text(Lang.t("ok", vm.locale))
            }
        }
    )
}


@Composable
fun OfflineOverlay(vm: WmsViewModel) {
    Box(
        Modifier.fillMaxSize().background(Color(0xCC000000)),
        contentAlignment = Alignment.Center
    ) {
        Card(
            Modifier.fillMaxWidth().padding(24.dp),
            colors = CardDefaults.cardColors(
                containerColor = Color(0xFFB71C1C),
                contentColor = Color.White
            )
        ) {
            Column(
                Modifier.padding(20.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(Lang.t("no_connection", vm.locale),
                    fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Spacer(Modifier.height(12.dp))
                Text(
                    Lang.t("attempt", vm.locale,
                        "n" to vm.failures),
                    fontSize = 14.sp
                )
                if (vm.lastContactMs > 0) {
                    Spacer(Modifier.height(4.dp))
                    Text(
                        Lang.t("last_contact", vm.locale,
                            "sec" to vm.lastContactSeconds()),
                        fontSize = 13.sp
                    )
                }
                Spacer(Modifier.height(20.dp))
                Text(Lang.t("work_blocked", vm.locale),
                    fontSize = 13.sp, textAlign = TextAlign.Center)
                Spacer(Modifier.height(12.dp))
                Text(Lang.t("reconnecting", vm.locale),
                    fontSize = 12.sp, color = Color(0xFFFFD54F))
            }
        }
    }
}


@Composable
fun NotificationDialog(
    item: NotificationItem,
    locale: String,
    onDismiss: () -> Unit
) {
    val context = LocalContext.current

    LaunchedEffect(item.id) {
        if (item.type == "urgent") {
            try {
                @Suppress("DEPRECATION")
                val vib = context.getSystemService(
                    android.content.Context.VIBRATOR_SERVICE
                ) as? Vibrator
                if (vib != null && vib.hasVibrator()) {
                    if (android.os.Build.VERSION.SDK_INT >=
                        android.os.Build.VERSION_CODES.O) {
                        vib.vibrate(VibrationEffect.createOneShot(
                            600L, VibrationEffect.DEFAULT_AMPLITUDE))
                    } else {
                        @Suppress("DEPRECATION")
                        vib.vibrate(600L)
                    }
                }
            } catch (_: Exception) {}
            try {
                val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 100)
                tone.startTone(ToneGenerator.TONE_PROP_BEEP2, 600)
                Handler(Looper.getMainLooper()).postDelayed({
                    try { tone.release() } catch (_: Exception) {}
                }, 1200L)
            } catch (_: Exception) {}
        }
    }

    AlertDialog(
        onDismissRequest = { },
        title = {
            Text(
                if (item.type == "urgent") Lang.t("notif_urgent", locale)
                else Lang.t("notif_title", locale),
                color = if (item.type == "urgent")
                    MaterialTheme.colorScheme.error
                else MaterialTheme.colorScheme.primary,
                fontWeight = FontWeight.Bold
            )
        },
        text = {
            Column {
                if (item.senderLogin.isNotEmpty()) {
                    Text("${Lang.t("from", locale)} ${item.senderLogin}",
                        fontSize = 12.sp, color = Color(0xFF7F8C8D))
                    Spacer(Modifier.height(4.dp))
                }
                if (item.createdAt.isNotEmpty()) {
                    Text(item.createdAt.take(19),
                        fontSize = 11.sp, color = Color(0xFF95A5A6))
                    Spacer(Modifier.height(8.dp))
                }
                Text(item.message, fontSize = 16.sp)
            }
        },
        confirmButton = {
            Button(onClick = onDismiss) {
                Text(Lang.t("notif_read", locale))
            }
        }
    )
}


@Composable
fun NotFoundResultDialog(
    res: com.wms.client.view.NotFoundResult,
    locale: String,
    onDismiss: () -> Unit
) {
    val title = when (res.result) {
        "relocated" -> Lang.t("not_found_relocated", locale)
        "split" -> Lang.t("not_found_split", locale)
        "lost" -> Lang.t("not_found_lost", locale)
        else -> Lang.t("not_found_result", locale)
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title, fontWeight = FontWeight.Bold) },
        text = {
            Column {
                Text(res.message, fontSize = 15.sp)
                if (res.newCell.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        Lang.t("not_found_cell", locale,
                            "cell" to res.newCell),
                        fontSize = 14.sp
                    )
                }
                if (res.newTaskNumber.isNotEmpty()) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        Lang.t("not_found_task", locale,
                            "task" to res.newTaskNumber),
                        fontSize = 14.sp
                    )
                }
            }
        },
        confirmButton = {
            Button(onClick = onDismiss) { Text(Lang.t("ok", locale)) }
        }
    )
}


@Composable
fun EmbeddedCameraScanner(
    modifier: Modifier = Modifier,
    cooldownMs: Long = 1000L,
    hintText: String = "",
    onScanned: (String) -> Unit
) {
    val ctx = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val barcodeViewRef = remember { mutableStateOf<DecoratedBarcodeView?>(null) }
    val lastScanAtRef = remember { longArrayOf(0L) }
    val onScannedState = rememberUpdatedState(onScanned)

    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(
                ctx, Manifest.permission.CAMERA
            ) == PackageManager.PERMISSION_GRANTED
        )
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> hasPermission = granted }

    LaunchedEffect(Unit) {
        if (!hasPermission) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
        }
    }

    val callback = remember {
        object : BarcodeCallback {
            override fun barcodeResult(result: BarcodeResult?) {
                val code = result?.text?.trim() ?: return
                if (code.isEmpty()) return
                val now = SystemClock.elapsedRealtime()
                if (now - lastScanAtRef[0] < cooldownMs) return
                lastScanAtRef[0] = now
                onScannedState.value(code)
            }
            override fun possibleResultPoints(
                resultPoints: MutableList<ResultPoint>?
            ) {}
        }
    }

    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME ->
                    barcodeViewRef.value?.resume()
                Lifecycle.Event.ON_PAUSE ->
                    barcodeViewRef.value?.pause()
                else -> {}
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
            barcodeViewRef.value?.pause()
            barcodeViewRef.value = null
        }
    }

    Box(modifier = modifier) {
        if (hasPermission) {
            AndroidView(
                factory = { ctx2 ->
                    DecoratedBarcodeView(ctx2).apply {
                        setDecoderFactory(DefaultDecoderFactory(
                            listOf(
                                BarcodeFormat.CODE_128,
                                BarcodeFormat.CODE_39,
                                BarcodeFormat.QR_CODE,
                                BarcodeFormat.EAN_13
                            )
                        ))
                        if (hintText.isNotEmpty()) {
                            setStatusText(hintText)
                        }
                        decodeContinuous(callback)
                        barcodeViewRef.value = this
                    }
                },
                modifier = Modifier.fillMaxSize()
            )
        } else {
            Box(
                Modifier.fillMaxSize(),
                contentAlignment = Alignment.Center
            ) {
                Column(
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text(
                        "Нет доступа к камере",
                        color = Color(0xFF7F8C8D),
                        fontSize = 14.sp
                    )
                    Spacer(Modifier.height(8.dp))
                    Button(onClick = {
                        permissionLauncher.launch(
                            Manifest.permission.CAMERA
                        )
                    }) {
                        Text("Разрешить")
                    }
                }
            }
        }
    }
}


@Composable
fun UnifiedScanner(
    enabled: Boolean,
    deviceType: String,
    locale: String,
    modifier: Modifier = Modifier,
    onScanned: (String) -> Unit
) {
    if (!enabled) return
    if (deviceType != "phone") return

    Box(modifier = modifier, contentAlignment = Alignment.BottomCenter) {
        CameraScanButton(
            locale = locale,
            onScanned = onScanned,
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp)
        )
    }
}


@Composable
fun CameraScanButton(
    locale: String,
    onScanned: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    val launcher = rememberLauncherForActivityResult(
        ScanContract()
    ) { result ->
        result.contents?.let { code ->
            if (code.isNotBlank()) onScanned(code)
        }
    }

    Button(
        onClick = {
            val opts = ScanOptions().apply {
                setDesiredBarcodeFormats(ScanOptions.ALL_CODE_TYPES)
                setPrompt(Lang.t("scan_with_camera", locale))
                setBeepEnabled(true)
                setOrientationLocked(false)
            }
            try { launcher.launch(opts) } catch (_: Exception) {}
        },
        modifier = modifier
    ) {
        Text(
            Lang.t("scan_with_camera", locale),
            fontSize = 16.sp
        )
    }
}


// ================================================================
// Экраны
// ================================================================

@Composable
private fun PdaScanHook(
    deviceType: String,
    onScan: (String) -> Unit
) {
    val ctx = LocalContext.current
    val activity = remember(ctx) {
        var c: android.content.Context? = ctx
        var found: MainActivity? = null
        while (c != null) {
            if (c is MainActivity) { found = c; break }
            c = if (c is android.content.ContextWrapper)
                c.baseContext else null
        }
        found
    }
    DisposableEffect(deviceType, activity) {
        if (activity == null) {
            onDispose {}
        } else {
            if (deviceType == "pda") {
                activity.acceptScans = true
                activity.onScanCallback = onScan
            } else {
                activity.acceptScans = false
            }
            onDispose {
                activity.acceptScans = false
                activity.onScanCallback = {}
            }
        }
    }
}


@Composable
fun LoginServerScreen(vm: WmsViewModel) {
    val ctx = LocalContext.current
    var error by remember { mutableStateOf<String?>(null) }

    fun process(url: String) {
        val p = Pattern.compile(
            "^WMS://([^/:]+)(?::(\\d+))?/?$",
            Pattern.CASE_INSENSITIVE
        )
        val m = p.matcher(url.trim())
        if (!m.matches()) {
            error = "Not a server QR"
            return
        }
        val host = m.group(1)
        val port = m.group(2) ?: "8765"
        val full = "http://$host:$port"
        vm.setServer(full)
        ctx.getSharedPreferences("wms", 0).edit()
            .putString("server", full).apply()
        vm.loadUiConfig(ctx)
    }

    PdaScanHook(vm.deviceType) { url -> process(url) }

    Box(Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            WmsLogo(
                modifier = Modifier
                    .fillMaxWidth(0.85f)
                    .height(100.dp)
            )
            Spacer(Modifier.height(24.dp))
            Text(
                if (vm.serverUrl.isEmpty())
                    Lang.t("login_server_prompt", vm.locale)
                else "${Lang.t("server", vm.locale)} ${vm.serverUrl}",
                fontSize = 18.sp,
                color = MaterialTheme.colorScheme.primary,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(8.dp))
            Text(Lang.t("login_server_hint", vm.locale),
                fontSize = 13.sp, color = Color.Gray,
                textAlign = TextAlign.Center)
            error?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = MaterialTheme.colorScheme.error,
                    textAlign = TextAlign.Center)
            }
        }
        UnifiedScanner(
            enabled = true,
            deviceType = vm.deviceType,
            locale = vm.locale,
            modifier = Modifier.fillMaxSize()
        ) { process(it) }
    }
}


@Composable
fun LoginEmployeeScreen(vm: WmsViewModel) {
    var status by remember { mutableStateOf("") }

    PdaScanHook(vm.deviceType) { qr ->
        vm.doLogin(qr) { ok, err ->
            status = if (!ok) (err ?: "Error") else ""
        }
    }

    Box(Modifier.fillMaxSize()) {
        Column(
            Modifier.fillMaxSize().padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            WmsLogo(
                modifier = Modifier
                    .fillMaxWidth(0.85f)
                    .height(100.dp)
            )
            Spacer(Modifier.height(32.dp))
            Text(Lang.t("login_emp_prompt", vm.locale),
                fontSize = 22.sp, fontWeight = FontWeight.Bold,
                textAlign = TextAlign.Center)
            Spacer(Modifier.height(16.dp))
            if (status.isNotEmpty()) {
                Text(status, color = MaterialTheme.colorScheme.error)
            }
            Spacer(Modifier.height(24.dp))
            TextButton(onClick = { vm.goToLoginServer() }) {
                Text(Lang.t("change_server", vm.locale))
            }
        }
        UnifiedScanner(
            enabled = true,
            deviceType = vm.deviceType,
            locale = vm.locale,
            modifier = Modifier.fillMaxSize()
        ) { qr ->
            vm.doLogin(qr) { ok, err ->
                status = if (!ok) (err ?: "Error") else ""
            }
        }
    }
}


@Composable
fun ModesScreen(vm: WmsViewModel) {
    Column(Modifier.fillMaxSize().padding(20.dp)) {
        Spacer(Modifier.height(44.dp))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(Modifier.weight(1f)) {
                Text(Lang.t("user", vm.locale, "fio" to vm.userFio),
                    fontWeight = FontWeight.Bold, fontSize = 16.sp)
                if (vm.userRoles.isNotEmpty()) {
                    Text(
                        vm.userRoles.joinToString(", ") {
                            vm.roleLabel(it)
                        },
                        fontSize = 12.sp, color = Color.Gray
                    )
                } else {
                    Text(Lang.t("no_roles", vm.locale),
                        fontSize = 12.sp, color = Color(0xFFC0392B))
                }
            }
            TextButton(onClick = { vm.logout() }) {
                Text(Lang.t("logout", vm.locale))
            }
        }

        Spacer(Modifier.height(20.dp))

        if (vm.availableSessions.isNotEmpty()) {
            Text(Lang.t("sessions", vm.locale), fontSize = 14.sp,
                fontWeight = FontWeight.Bold, color = Color.Gray)
            Spacer(Modifier.height(8.dp))
            for (s in vm.availableSessions) {
                SessionCard(
                    title = s.title,
                    onClick = { vm.startSession(s.key, s.title) },
                    enabled = vm.online && !vm.busy,
                )
                Spacer(Modifier.height(8.dp))
            }
            Spacer(Modifier.height(16.dp))
        }

        Button(
            onClick = { vm.getTask() },
            enabled = vm.online && !vm.busy && vm.userRoles.isNotEmpty(),
            modifier = Modifier.fillMaxWidth().height(56.dp)
        ) {
            Text(Lang.t("get_task", vm.locale), fontSize = 16.sp)
        }

        if (vm.busy) {
            Spacer(Modifier.height(16.dp))
            CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally))
        }

        Spacer(Modifier.weight(1f))
    }
}


@Composable
private fun SessionCard(
    title: String,
    onClick: () -> Unit,
    enabled: Boolean
) {
    Card(
        Modifier.fillMaxWidth().clickable(enabled = enabled) { onClick() },
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Row(
            Modifier.fillMaxWidth().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("▶", fontSize = 20.sp)
            Spacer(Modifier.width(12.dp))
            Text(title, fontSize = 16.sp, fontWeight = FontWeight.Bold)
        }
    }
}


@Composable
fun SessionViewScreen(vm: WmsViewModel) {
    val isPhone = vm.deviceType == "phone"

    PdaScanHook(vm.deviceType) { code ->
        vm.sessionAction("_scan_", code)
    }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Spacer(Modifier.height(44.dp))
        Row(
            Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(vm.currentSessionTitle,
                fontSize = 18.sp, fontWeight = FontWeight.Bold,
                modifier = Modifier.weight(1f))
            TextButton(onClick = { vm.closeSession() }) {
                Text(Lang.t("close_session", vm.locale))
            }
        }
        Spacer(Modifier.height(12.dp))

        Column(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .verticalScroll(rememberScrollState())
        ) {
            RenderDocument(vm.sessionNodes) { _, id, value ->
                vm.sessionAction(id ?: "", value)
            }
            Spacer(Modifier.height(12.dp))
        }

        if (isPhone) {
            Spacer(Modifier.height(8.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(240.dp)
                    .clip(RoundedCornerShape(8.dp))
            ) {
                EmbeddedCameraScanner(
                    modifier = Modifier.fillMaxSize(),
                    cooldownMs = 1000L,
                    hintText = Lang.t("scan_with_camera", vm.locale),
                    onScanned = { code ->
                        vm.sessionAction("_scan_", code)
                    }
                )
            }
        }
    }
}


@Composable
fun TaskExecScreen(vm: WmsViewModel) {
    val meta = vm.currentMeta
    val nodes = vm.currentNodes
    val isPhone = vm.deviceType == "phone"

    PdaScanHook(vm.deviceType) { code -> vm.handleTaskScan(code) }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Spacer(Modifier.height(44.dp))
        Text("${meta.taskNumber}",
            fontSize = 16.sp, fontWeight = FontWeight.Bold,
            modifier = Modifier.fillMaxWidth())

        if (meta.blockBf.isNotEmpty() ||
            (meta.batchPosition > 0 && meta.batchTotal > 1)) {
            BatchHeader(
                blockBf = meta.blockBf,
                batchPos = meta.batchPosition,
                batchTotal = meta.batchTotal,
                locale = vm.locale
            )
            Spacer(Modifier.height(6.dp))
        }

        Column(
            Modifier
                .fillMaxWidth()
                .weight(1f)
                .verticalScroll(rememberScrollState())
        ) {
            if (nodes.isEmpty() && !meta.finished) {
                Box(
                    Modifier.fillMaxWidth().padding(24.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        CircularProgressIndicator()
                        Spacer(Modifier.height(16.dp))
                        Text(Lang.t("loading", vm.locale))
                        Spacer(Modifier.height(16.dp))
                        OutlinedButton(onClick = { vm.refreshCurrentView() }) {
                            Text(Lang.t("refresh", vm.locale))
                        }
                    }
                }
            } else {
                RenderDocument(nodes) { action, id, value ->
                    vm.handleTaskAction(action, id, value)
                }
            }
            Spacer(Modifier.height(12.dp))
        }

        if (isPhone) {
            Spacer(Modifier.height(8.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .height(240.dp)
                    .clip(RoundedCornerShape(8.dp))
            ) {
                EmbeddedCameraScanner(
                    modifier = Modifier.fillMaxSize(),
                    cooldownMs = 1000L,
                    hintText = Lang.t("scan_with_camera", vm.locale),
                    onScanned = { code -> vm.handleTaskScan(code) }
                )
            }
        }
    }
}


@Composable
fun BatchHeader(blockBf: String, batchPos: Int, batchTotal: Int, locale: String) {
    Surface(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(6.dp)),
        color = MaterialTheme.colorScheme.primary,
        contentColor = MaterialTheme.colorScheme.onPrimary
    ) {
        Row(
            Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            if (blockBf.isNotEmpty()) {
                Text(Lang.t("batch_block", locale, "bf" to blockBf),
                    fontWeight = FontWeight.Bold, fontSize = 14.sp)
            }
            if (batchPos > 0 && batchTotal > 1) {
                if (blockBf.isNotEmpty()) Text("  ·  ", fontSize = 14.sp)
                Text(
                    Lang.t("batch_part", locale,
                        "pos" to batchPos, "total" to batchTotal),
                    fontSize = 14.sp
                )
            }
            Spacer(Modifier.weight(1f))
        }
    }
}


@Composable
fun DoneScreen(vm: WmsViewModel) {
    val ttype = when (vm.lastTaskType) {
        "pick" -> Lang.t("role_picker", vm.locale)
        "receive" -> Lang.t("role_receiver", vm.locale)
        "putaway" -> Lang.t("role_putaway", vm.locale)
        "inventory" -> Lang.t("role_inventory", vm.locale)
        else -> vm.lastTaskType
    }
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            Lang.t("task_done", vm.locale),
            fontSize = 26.sp, fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            textAlign = TextAlign.Center
        )
        Spacer(Modifier.height(16.dp))
        Text("$ttype  ${vm.lastTaskNumber}",
            fontSize = 18.sp, textAlign = TextAlign.Center)
    }
}