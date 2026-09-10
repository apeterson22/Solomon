package com.solomonprime.tricorder.viewmodel

import android.Manifest
import android.app.Activity
import android.app.Application
import android.app.PendingIntent
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.nfc.NdefMessage
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.tech.Ndef
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.launch
import kotlin.math.log10
import kotlin.math.pow

// ── Data Classes ──────────────────────────────────────────────

data class WifiNetworkInfo(
    val ssid: String,
    val bssid: String,
    val rssi: Int,
    val frequency: Int,
    val capabilities: String,
    val channelWidth: Int,
    val isHidden: Boolean
)

data class BtDeviceInfo(
    val name: String,
    val address: String,
    val type: String,       // "CLASSIC", "LE", "DUAL", "UNKNOWN"
    val rssi: Int,
    val deviceClass: Int
)

data class NetworkAnalysis(
    val encryptionType: String,     // "OPEN", "WEP", "WPA", "WPA2", "WPA3"
    val signalQuality: Int,         // 0-100
    val channelInterference: Int,   // count of other networks on same channel
    val estimatedDistance: Double    // meters from RSSI using free-space path loss
)

data class NfcTagInfo(
    val uid: String,
    val type: String,
    val techList: List<String>,
    val ndefData: String?
)

// ── ViewModel ─────────────────────────────────────────────────

/**
 * Passive RF security scanner. WiFi analysis, Bluetooth recon, NFC tag reading.
 * All operations are receive-only — no frames transmitted, no active attacks.
 */
class RfSecurityViewModel(application: Application) : AndroidViewModel(application) {

    private val wifiManager =
        application.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val bluetoothManager =
        application.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
    private val bluetoothAdapter: BluetoothAdapter? = bluetoothManager?.adapter

    // ── WiFi ──────────────────────────────────────────────────

    private val _wifiNetworks = MutableStateFlow<List<WifiNetworkInfo>>(emptyList())
    val wifiNetworks: StateFlow<List<WifiNetworkInfo>> = _wifiNetworks.asStateFlow()

    /** Open/unencrypted networks — potential security concern */
    val openNetworks: StateFlow<List<WifiNetworkInfo>> = _wifiNetworks
        .combine(MutableStateFlow(Unit)) { nets, _ ->
            nets.filter { parseEncryption(it.capabilities) == "OPEN" }
        }
        .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    private val wifiScanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == WifiManager.SCAN_RESULTS_AVAILABLE_ACTION) {
                processWifiResults()
            }
        }
    }

    // ── Bluetooth ─────────────────────────────────────────────

    private val _btDevices = MutableStateFlow<List<BtDeviceInfo>>(emptyList())
    val btDevices: StateFlow<List<BtDeviceInfo>> = _btDevices.asStateFlow()

    private val discoveredBt = mutableMapOf<String, BtDeviceInfo>()

    /** Heuristic: devices with default names that may indicate weak pairing */
    private val defaultNamePatterns = listOf(
        Regex("^iPhone$", RegexOption.IGNORE_CASE),
        Regex("^Galaxy.*$", RegexOption.IGNORE_CASE),
        Regex("^\\d{4,}$"),                       // numeric-only names
        Regex("^BT-\\d+$", RegexOption.IGNORE_CASE),
        Regex("^HC-\\d+$"),                        // common HC-05/06 modules
        Regex("^JBL.*$", RegexOption.IGNORE_CASE), // default speaker names
        Regex("^Bluetooth\\s*$", RegexOption.IGNORE_CASE)
    )

    val vulnerableDevices: StateFlow<List<BtDeviceInfo>> = _btDevices
        .combine(MutableStateFlow(Unit)) { devs, _ ->
            devs.filter { d ->
                d.name.isNotBlank() && defaultNamePatterns.any { it.matches(d.name) }
            }
        }
        .stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())

    private val btDiscoveryReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                BluetoothDevice.ACTION_FOUND -> {
                    try {
                        val device = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                        } else {
                            @Suppress("DEPRECATION")
                            intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                        }
                        val rssi = intent.getShortExtra(BluetoothDevice.EXTRA_RSSI, Short.MIN_VALUE).toInt()
                        device?.let { addBtDevice(it, rssi) }
                    } catch (_: SecurityException) { }
                }
            }
        }
    }

    // ── NFC ───────────────────────────────────────────────────

    private val _nfcTagInfo = MutableStateFlow<NfcTagInfo?>(null)
    val nfcTagInfo: StateFlow<NfcTagInfo?> = _nfcTagInfo.asStateFlow()

    // ── Init / Lifecycle ──────────────────────────────────────

    init {
        startWifiScan()
    }

    // ── WiFi Methods ──────────────────────────────────────────

    private fun startWifiScan() {
        val ctx = getApplication<Application>().applicationContext
        val hasPermission = ContextCompat.checkSelfPermission(
            ctx, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED

        if (hasPermission) {
            ctx.registerReceiver(
                wifiScanReceiver,
                IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
            )
            @Suppress("DEPRECATION")
            wifiManager.startScan()

            // Periodic re-scan (Android throttles to ~4/2min)
            viewModelScope.launch {
                while (true) {
                    delay(30_000L)
                    try {
                        @Suppress("DEPRECATION")
                        wifiManager.startScan()
                    } catch (_: Exception) { }
                }
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun processWifiResults() {
        try {
            val results = wifiManager.scanResults
            _wifiNetworks.value = results
                .sortedByDescending { it.level }
                .map { sr ->
                    WifiNetworkInfo(
                        ssid = sr.SSID.orEmpty(),
                        bssid = sr.BSSID.orEmpty(),
                        rssi = sr.level,
                        frequency = sr.frequency,
                        capabilities = sr.capabilities.orEmpty(),
                        channelWidth = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                            sr.channelWidth
                        } else 0,
                        isHidden = sr.SSID.isNullOrEmpty()
                    )
                }
        } catch (_: SecurityException) { }
    }

    /** Analyze a specific network by BSSID */
    fun analyzeNetwork(bssid: String): NetworkAnalysis {
        val allNets = _wifiNetworks.value
        val target = allNets.firstOrNull { it.bssid == bssid }
            ?: return NetworkAnalysis("UNKNOWN", 0, 0, -1.0)

        val channel = frequencyToChannel(target.frequency)
        val sameChannel = allNets.count {
            it.bssid != bssid && frequencyToChannel(it.frequency) == channel
        }

        return NetworkAnalysis(
            encryptionType = parseEncryption(target.capabilities),
            signalQuality = rssiToQuality(target.rssi),
            channelInterference = sameChannel,
            estimatedDistance = estimateDistance(target.rssi, target.frequency)
        )
    }

    // ── Bluetooth Methods ─────────────────────────────────────

    fun startBtDiscovery() {
        val ctx = getApplication<Application>().applicationContext
        val hasPermission = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.BLUETOOTH_SCAN) ==
                PackageManager.PERMISSION_GRANTED
        } else {
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) ==
                PackageManager.PERMISSION_GRANTED
        }

        if (!hasPermission) return

        try {
            val filter = IntentFilter(BluetoothDevice.ACTION_FOUND)
            ctx.registerReceiver(btDiscoveryReceiver, filter)
            bluetoothAdapter?.startDiscovery()
        } catch (_: SecurityException) { }
    }

    fun stopBtDiscovery() {
        try {
            bluetoothAdapter?.cancelDiscovery()
            getApplication<Application>().applicationContext
                .unregisterReceiver(btDiscoveryReceiver)
        } catch (_: Exception) { }
    }

    private fun addBtDevice(device: BluetoothDevice, rssi: Int) {
        try {
            val info = BtDeviceInfo(
                name = device.name.orEmpty(),
                address = device.address,
                type = when (device.type) {
                    BluetoothDevice.DEVICE_TYPE_CLASSIC -> "CLASSIC"
                    BluetoothDevice.DEVICE_TYPE_LE -> "LE"
                    BluetoothDevice.DEVICE_TYPE_DUAL -> "DUAL"
                    else -> "UNKNOWN"
                },
                rssi = rssi,
                deviceClass = device.bluetoothClass?.majorDeviceClass ?: 0
            )
            discoveredBt[device.address] = info
            _btDevices.value = discoveredBt.values.sortedByDescending { it.rssi }
        } catch (_: SecurityException) { }
    }

    // ── NFC Methods ───────────────────────────────────────────

    fun enableNfcScan(activity: Activity) {
        val nfcAdapter = NfcAdapter.getDefaultAdapter(activity) ?: return
        val intent = Intent(activity, activity.javaClass).apply {
            addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        val pendingIntent = PendingIntent.getActivity(
            activity, 0, intent,
            PendingIntent.FLAG_MUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        nfcAdapter.enableForegroundDispatch(activity, pendingIntent, null, null)
    }

    fun disableNfcScan(activity: Activity) {
        NfcAdapter.getDefaultAdapter(activity)?.disableForegroundDispatch(activity)
    }

    /** Call from Activity.onNewIntent when NFC tag is tapped */
    fun handleNfcIntent(intent: Intent) {
        val tag = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            intent.getParcelableExtra(NfcAdapter.EXTRA_TAG, Tag::class.java)
        } else {
            @Suppress("DEPRECATION")
            intent.getParcelableExtra(NfcAdapter.EXTRA_TAG)
        } ?: return

        val uid = tag.id.joinToString(":") { "%02X".format(it) }
        val techList = tag.techList.map { it.substringAfterLast('.') }

        // Try reading NDEF data
        val ndefData = try {
            val ndef = Ndef.get(tag)
            ndef?.connect()
            val msg = ndef?.ndefMessage
            ndef?.close()
            msg?.records?.joinToString("\n") { record ->
                String(record.payload).drop(if (record.payload.isNotEmpty()) 1 else 0)
            }
        } catch (_: Exception) { null }

        val typeName = when {
            techList.contains("MifareClassic") -> "MIFARE Classic"
            techList.contains("MifareUltralight") -> "MIFARE Ultralight"
            techList.contains("IsoDep") -> "ISO-DEP (ISO 14443-4)"
            techList.contains("NfcA") -> "NFC-A (ISO 14443-3A)"
            techList.contains("NfcB") -> "NFC-B (ISO 14443-3B)"
            techList.contains("NfcF") -> "NFC-F (JIS 6319-4)"
            techList.contains("NfcV") -> "NFC-V (ISO 15693)"
            else -> "Unknown"
        }

        _nfcTagInfo.value = NfcTagInfo(
            uid = uid,
            type = typeName,
            techList = techList,
            ndefData = ndefData
        )
    }

    
    // ── GATT Enumeration ──────────────────────────────────────
    private var currentGatt: BluetoothGatt? = null
    private val _gattResults = MutableStateFlow<String?>(null)
    val gattResults: StateFlow<String?> = _gattResults.asStateFlow()

    fun enumerateDevice(address: String) {
        val device = bluetoothAdapter?.getRemoteDevice(address) ?: return
        _gattResults.value = "Connecting to ${device.name ?: address}..."
        
        try {
            currentGatt?.close()
            currentGatt = device.connectGatt(getApplication(), false, object : BluetoothGattCallback() {
                override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
                    if (newState == BluetoothProfile.STATE_CONNECTED) {
                        _gattResults.value = "Connected. Discovering services..."
                        try { gatt.discoverServices() } catch (e: SecurityException) { }
                    } else if (newState == BluetoothProfile.STATE_DISCONNECTED) {
                        val current = _gattResults.value ?: ""
                        if (!current.contains("SERVICES DISCOVERED")) {
                            _gattResults.value = current + "\nDisconnected."
                        }
                    }
                }

                override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
                    if (status == BluetoothGatt.GATT_SUCCESS) {
                        val sb = java.lang.StringBuilder()
                        sb.append("SERVICES DISCOVERED:\n")
                        gatt.services.forEach { service ->
                            val shortUuid = service.uuid.toString().substring(4, 8)
                            sb.append("■ Service: 0x$shortUuid\n")
                            service.characteristics.forEach { char ->
                                val shortCharUuid = char.uuid.toString().substring(4, 8)
                                sb.append("  └─ Char: 0x$shortCharUuid\n")
                            }
                        }
                        _gattResults.value = sb.toString()
                        try { gatt.disconnect() } catch (e: SecurityException) { }
                    }
                }
            })
        } catch(e: SecurityException) {
            _gattResults.value = "Permission denied."
        }
    }
    
    fun clearGattResults() {
        _gattResults.value = null
        try {
            currentGatt?.close()
            currentGatt = null
        } catch (e: SecurityException) {}
    }

    // ── Helpers ───────────────────────────────────────────────

    private fun parseEncryption(capabilities: String): String = when {
        capabilities.contains("WPA3") -> "WPA3"
        capabilities.contains("WPA2") -> "WPA2"
        capabilities.contains("WPA") && !capabilities.contains("WPA2") -> "WPA"
        capabilities.contains("WEP") -> "WEP"
        else -> "OPEN"
    }

    private fun rssiToQuality(rssi: Int): Int = when {
        rssi >= -30 -> 100
        rssi <= -90 -> 0
        else -> ((rssi + 90) * 100) / 60
    }.coerceIn(0, 100)

    /** Free-space path loss estimate — rough, indoor accuracy ±5m */
    private fun estimateDistance(rssi: Int, frequencyMhz: Int): Double {
        // FSPL: d = 10^((27.55 - (20*log10(f)) + |RSSI|) / 20)
        val exp = (27.55 - (20 * log10(frequencyMhz.toDouble())) + kotlin.math.abs(rssi)) / 20.0
        return 10.0.pow(exp).coerceIn(0.1, 200.0)
    }

    private fun frequencyToChannel(freq: Int): Int = when {
        freq in 2412..2484 -> (freq - 2407) / 5     // 2.4 GHz channels 1-14
        freq in 5170..5825 -> (freq - 5000) / 5     // 5 GHz
        freq in 5955..7115 -> (freq - 5950) / 5     // 6 GHz (Wi-Fi 6E)
        else -> 0
    }

    // ── Cleanup ───────────────────────────────────────────────

    override fun onCleared() {
        super.onCleared()
        try {
            getApplication<Application>().applicationContext
                .unregisterReceiver(wifiScanReceiver)
        } catch (_: Exception) { }
        stopBtDiscovery()
    }
}
