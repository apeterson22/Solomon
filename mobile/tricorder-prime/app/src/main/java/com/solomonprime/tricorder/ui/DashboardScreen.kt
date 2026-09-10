package com.solomonprime.tricorder.ui

import android.annotation.SuppressLint
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.wifi.WifiManager
import android.os.Build
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.data.ConnectedDeviceManager
import com.solomonprime.tricorder.ui.theme.*
import androidx.compose.ui.graphics.Color
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin

// --- Data model for radar signals ---
private val LcarsGreen = Color(0xFF66CC66)
private val RadarBlue = Color(0xFF3399FF)   // Actual blue for BT dots
private val RadarOrange = Color(0xFFFF8833) // Bright orange for unknown

data class RadarSignal(
    val id: String,
    val name: String,
    val rssi: Int,
    val isWifi: Boolean,
    val timestamp: Long,
    val txPower: Int = -59
) {
    /** Estimate distance in meters using log-distance path loss model. n=2.0 free space. */
    val distanceMeters: Float
        get() = 10f.pow((txPower - rssi) / (10f * 2.0f))
}

// --- ViewModel: real BT/WiFi scanning with SIM fallback ---
class DashboardViewModel(application: android.app.Application) : AndroidViewModel(application) {
    private val wifiManager = application.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val btManager = application.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val btAdapter = btManager.adapter
    private val bleScanner: BluetoothLeScanner? = btAdapter?.bluetoothLeScanner

    private val _signals = MutableStateFlow<Map<String, RadarSignal>>(emptyMap())
    val signals = _signals.asStateFlow()

    private val _useRealSensors = MutableStateFlow(true)
    val useRealSensors = _useRealSensors.asStateFlow()

    fun setUseRealSensors(v: Boolean) { _useRealSensors.value = v }

    // WiFi scan receiver
    private val wifiReceiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            if (!_useRealSensors.value) return
            val now = System.currentTimeMillis()
            val cur = _signals.value.toMutableMap()
            for (r in wifiManager.scanResults) {
                cur[r.BSSID] = RadarSignal(
                    id = r.BSSID,
                    name = r.SSID.takeIf { it.isNotBlank() } ?: "Unknown WiFi",
                    rssi = r.level, isWifi = true, timestamp = now
                )
            }
            _signals.value = cur
        }
    }

    // BLE scan callback
    private val bleCallback = object : ScanCallback() {
        @SuppressLint("MissingPermission")
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            if (!_useRealSensors.value) return
            val now = System.currentTimeMillis()
            val addr = result.device.address
            val name = try {
                result.scanRecord?.deviceName ?: result.device.name ?: "Unknown BT"
            } catch (_: SecurityException) { "Unknown BT" }
            val cur = _signals.value.toMutableMap()
            cur[addr] = RadarSignal(
                id = addr, name = name, rssi = result.rssi, isWifi = false,
                timestamp = now,
                txPower = result.scanRecord?.txPowerLevel?.takeIf { it != Int.MIN_VALUE } ?: -59
            )
            _signals.value = cur
        }
    }

    init {
        // Prune old signals + inject simulated if needed
        viewModelScope.launch {
            while (true) {
                val now = System.currentTimeMillis()
                val cur = _signals.value.toMutableMap()
                cur.entries.removeIf { now - it.value.timestamp > 15_000 }
                if (!_useRealSensors.value) {
                    cur["sim_wifi_1"] = RadarSignal("sim_wifi_1", "SimAP-5G", -55 + (Math.random() * 10).toInt(), true, now)
                    cur["sim_wifi_2"] = RadarSignal("sim_wifi_2", "SimAP-2.4", -70 + (Math.random() * 10).toInt(), true, now)
                    cur["sim_bt_1"] = RadarSignal("sim_bt_1", "SimBeacon", -65 + (Math.random() * 15).toInt(), false, now)
                    cur["sim_bt_2"] = RadarSignal("sim_bt_2", "SimWatch", -80 + (Math.random() * 10).toInt(), false, now)
                    cur["sim_other"] = RadarSignal("sim_other", "UnkDevice", -90 + (Math.random() * 8).toInt(), false, now, txPower = -70)
                }
                _signals.value = cur
                delay(2000)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun startScanning() {
        val app = getApplication<android.app.Application>()
        try {
            app.registerReceiver(wifiReceiver, IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION))
            wifiManager.startScan()
            bleScanner?.startScan(null,
                ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(),
                bleCallback)
        } catch (_: Exception) {}
        viewModelScope.launch {
            while (true) {
                if (_useRealSensors.value) try { wifiManager.startScan() } catch (_: Exception) {}
                delay(10_000)
            }
        }
    }

    @SuppressLint("MissingPermission")
    fun stopScanning() {
        try { getApplication<android.app.Application>().unregisterReceiver(wifiReceiver) } catch (_: Exception) {}
        try { bleScanner?.stopScan(bleCallback) } catch (_: Exception) {}
    }

    override fun onCleared() { super.onCleared(); stopScanning() }
}

// --- Main Dashboard composable ---
@Composable
fun DashboardScreen(
    deviceManager: ConnectedDeviceManager? = null,
    sensorData: Map<String, Float> = emptyMap(),
    uptimeSeconds: Int = 0
) {
    val vm: DashboardViewModel = viewModel()
    val signals by vm.signals.collectAsState()
    val useReal by vm.useRealSensors.collectAsState()

    LaunchedEffect(Unit) { vm.startScanning() }
    DisposableEffect(Unit) { onDispose { vm.stopScanning() } }

    val config = LocalConfiguration.current
    val isCompact = config.screenWidthDp < 300

    LcarsScreenScaffold(title = "TRICORDER") {
        // Uptime + sensor toggle
        Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) {
            Column {
                Text("SYSTEM UPTIME", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
                LcarsFlipCounter(value = uptimeSeconds, digits = 6)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (useReal) "LIVE" else "SIM", color = if (useReal) LcarsBlue else LcarsRed,
                    fontSize = 10.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                Spacer(Modifier.width(4.dp))
                Switch(checked = useReal, onCheckedChange = { vm.setUseRealSensors(it) },
                    colors = SwitchDefaults.colors(checkedThumbColor = LcarsBlue, uncheckedThumbColor = LcarsRed))
            }
        }

        Spacer(Modifier.height(if (isCompact) 6.dp else 12.dp))

        if (!isCompact) { ConnectivityStatusRow(); Spacer(Modifier.height(12.dp)) }

        // Filter to 40ft (~12m)
        val nearby = signals.values.filter { it.distanceMeters <= 12f }

        Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxWidth()) {
            FunctionalRadar(
                signals = nearby,
                modifier = Modifier
                    .fillMaxWidth(if (isCompact) 0.95f else 0.7f)
                    .aspectRatio(1f).padding(8.dp)
            )
            if (!useReal) {
                Text("SIM", color = LcarsRed, fontWeight = FontWeight.Bold, fontSize = 10.sp,
                    modifier = Modifier.align(Alignment.TopEnd).background(LcarsBlack).padding(2.dp))
            }
        }

        Spacer(Modifier.height(if (isCompact) 8.dp else 16.dp))

        val cards = listOf(
            "ENV" to (sensorData["temperature"] ?: 22.5f),
            "GEO" to (sensorData["altitude"] ?: 125f),
            "ACO" to (sensorData["dbLevel"] ?: 42f),
            "RAD" to (sensorData["cpm"] ?: 18f),
            "BIO" to (sensorData["heartRate"] ?: 72f),
            "EM" to (sensorData["emField"] ?: 0.3f)
        )

        if (isCompact) {
            Column { cards.forEach { (l, v) -> LcarsDashCard(l, v); Spacer(Modifier.height(4.dp)) } }
        } else {
            Row(Modifier.fillMaxWidth(), Arrangement.SpaceEvenly) { cards.take(3).forEach { (l, v) -> LcarsDashCard(l, v) } }
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), Arrangement.SpaceEvenly) { cards.drop(3).forEach { (l, v) -> LcarsDashCard(l, v) } }
        }

        if (!isCompact) {
            Spacer(Modifier.height(12.dp))
            LcarsBarGraph(data = cards.map { (l, v) -> l to (v / 100f).coerceIn(0f, 1f) })
        }
    }
}

// --- Functional animated radar with real signal dots ---
@Composable
fun FunctionalRadar(signals: List<RadarSignal>, modifier: Modifier = Modifier) {
    var selected by remember { mutableStateOf<RadarSignal?>(null) }
    val transition = rememberInfiniteTransition(label = "radar")
    val sweep by transition.animateFloat(0f, 360f,
        infiniteRepeatable(tween(4000, easing = LinearEasing), RepeatMode.Restart), label = "sweep")

    Box(modifier) {
        Canvas(Modifier.fillMaxSize().pointerInput(signals) {
            detectTapGestures { tap ->
                val cx = size.width / 2; val cy = size.height / 2; val maxR = size.width / 2
                selected = signals.firstOrNull { s ->
                    val ang = (s.id.hashCode() % 360).toFloat()
                    val r = (s.distanceMeters / 12f).coerceIn(0f, 1f) * maxR
                    val rad = Math.toRadians(ang.toDouble() - 90.0)
                    val dx = cx + r * cos(rad).toFloat() - tap.x
                    val dy = cy + r * sin(rad).toFloat() - tap.y
                    Math.hypot(dx.toDouble(), dy.toDouble()) < 40.0
                }
            }
        }) {
            val cx = Offset(size.width / 2, size.height / 2)
            val maxR = size.width / 2

            // Background circles
            drawCircle(LcarsDarkPanel, maxR, cx)
            drawCircle(LcarsBlue.copy(0.3f), maxR, cx, style = Stroke(2f))
            drawCircle(LcarsBlue.copy(0.15f), maxR * 0.66f, cx, style = Stroke(1f))
            drawCircle(LcarsBlue.copy(0.15f), maxR * 0.33f, cx, style = Stroke(1f))
            // Crosshairs
            drawLine(LcarsBlue.copy(0.2f), Offset(cx.x, 0f), Offset(cx.x, size.height))
            drawLine(LcarsBlue.copy(0.2f), Offset(0f, cx.y), Offset(size.width, cx.y))

            // Sweep line
            val sRad = Math.toRadians(sweep.toDouble() - 90.0)
            drawLine(LcarsTan, cx, Offset(cx.x + maxR * cos(sRad).toFloat(), cx.y + maxR * sin(sRad).toFloat()), strokeWidth = 3f)

            // Signal dots
            for (s in signals) {
                val ang = (s.id.hashCode() % 360).toFloat()
                val r = (s.distanceMeters / 12f).coerceIn(0f, 1f) * maxR
                val rad = Math.toRadians(ang.toDouble() - 90.0)
                val dot = Offset(cx.x + r * cos(rad).toFloat(), cx.y + r * sin(rad).toFloat())
                val color = when {
                    s.isWifi -> LcarsGreen
                    s.name.contains("Unknown", true) || s.txPower < -65 -> RadarOrange
                    else -> RadarBlue
                }
                drawCircle(color, 8f, dot)
                if (s == selected) drawCircle(LcarsYellow, 13f, dot, style = Stroke(2f))
            }
        }

        // Info popup for selected signal
        selected?.let { s ->
            Box(Modifier.align(Alignment.BottomCenter).background(LcarsDarkPanel).padding(8.dp)) {
                Text("${s.name} | ${String.format("%.1f", s.distanceMeters)}m | ${s.rssi}dBm",
                    color = LcarsOrange, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
            }
        }

        // Radar legend key
        if (selected == null) {
            Row(
                Modifier.align(Alignment.BottomCenter).background(LcarsBlack.copy(0.7f)).padding(horizontal = 8.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                RadarLegendDot(RadarBlue, "BT")
                RadarLegendDot(LcarsGreen, "WiFi")
                RadarLegendDot(RadarOrange, "Other")
            }
        }
    }
}

@Composable
private fun LcarsDashCard(label: String, value: Float) {
    val color = LcarsPalette[label.hashCode().and(0x7FFFFFFF) % LcarsPalette.size]
    Box(Modifier.width(100.dp).clip(RoundedCornerShape(topStart = 16.dp, bottomEnd = 16.dp)).background(LcarsDarkPanel).padding(8.dp)) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
            LcarsAnimatedValue(value = value, color = color, decimalPlaces = 1)
        }
    }
}

@Composable
private fun ConnectivityStatusRow() {
    val ctx = LocalContext.current
    val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
    val wi = wm?.connectionInfo
    val ssid = wi?.ssid?.removeSurrounding("\"") ?: "N/A"
    val rssi = wi?.rssi ?: -100
    val strength = WifiManager.calculateSignalLevel(rssi, 5)
    val btm = ctx.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    val btOn = btm?.adapter?.isEnabled == true
    val paired = try { if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) btm?.adapter?.bondedDevices?.size ?: 0 else 0 } catch (_: SecurityException) { 0 }

    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(LcarsDarkPanel).padding(12.dp), Arrangement.SpaceBetween) {
        Column {
            Text("WIFI", color = LcarsBlue.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
            Text(if (ssid == "<unknown ssid>") "Connected" else ssid.take(15), color = LcarsBlue, fontSize = 13.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
            Row(verticalAlignment = Alignment.CenterVertically) {
                repeat(5) { i -> Box(Modifier.padding(end = 2.dp).width(4.dp).height((6 + i * 3).dp).background(if (i < strength) LcarsBlue else LcarsBlue.copy(0.2f))) }
                Spacer(Modifier.width(6.dp))
                Text("$rssi dBm", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Text("BLUETOOTH", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
            Text(if (btOn) "ENABLED" else "DISABLED", color = if (btOn) LcarsTan else LcarsRed, fontSize = 13.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
            Text("$paired paired", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
        }
    }
}

@Composable
private fun RadarLegendDot(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Canvas(Modifier.size(8.dp)) { drawCircle(color) }
        Text(label, color = color, fontSize = 9.sp, fontFamily = FontFamily.Monospace)
    }
}
