package com.solomonprime.tricorder.viewmodel

import android.Manifest
import android.app.Application
import android.bluetooth.BluetoothManager
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanResult
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.net.wifi.WifiManager
import android.os.Build
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.delay
import com.solomonprime.tricorder.model.BluetoothSignal
import com.solomonprime.tricorder.model.WifiSignal
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * ViewModel for the EM Spectrum Scanner screen.
 * Provides Wi-Fi network scan results, BLE device discoveries,
 * and raw magnetic field sensor data via StateFlows.
 */
class EmSpectrumViewModel(application: Application) : AndroidViewModel(application), SensorEventListener {

    private val sensorManager: SensorManager =
        application.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private val wifiManager: WifiManager =
        application.getSystemService(Context.WIFI_SERVICE) as WifiManager
    private val bluetoothManager: BluetoothManager? =
        application.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager

    // Sensors
    private val magnetometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)

    // --- StateFlows ---

    /** Magnetic field vector [x, y, z] in µT */
    private val _magneticField = MutableStateFlow(floatArrayOf(0f, 0f, 0f))
    val magneticField = _magneticField.asStateFlow()

    /** Detected Wi-Fi networks from the latest scan */
    private val _wifiSignals = MutableStateFlow<List<WifiSignal>>(emptyList())
    val wifiSignals = _wifiSignals.asStateFlow()

    /** Discovered Bluetooth LE devices */
    private val _bluetoothSignals = MutableStateFlow<List<BluetoothSignal>>(emptyList())
    val bluetoothSignals = _bluetoothSignals.asStateFlow()

    // --- Internal state ---

    private val discoveredBleDevices = mutableMapOf<String, BluetoothSignal>()
    private var bleScanner: BluetoothLeScanner? = null

    // Wi-Fi scan results receiver
    private val wifiScanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == WifiManager.SCAN_RESULTS_AVAILABLE_ACTION) {
                processWifiResults()
            }
        }
    }

    // BLE scan callback
    private val bleScanCallback = object : ScanCallback() {
        override fun onScanResult(callbackType: Int, result: ScanResult) {
            val address = result.device.address
            val name = try {
                result.device.name ?: ""
            } catch (_: SecurityException) {
                ""
            }
            val signal = BluetoothSignal(
                name = name,
                address = address,
                rssi = result.rssi,
                type = result.device.type
            )
            discoveredBleDevices[address] = signal
            _bluetoothSignals.value = discoveredBleDevices.values.toList()
        }
    }

    init {
        // Register magnetic field sensor
        magnetometer?.also { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }

        // Start Wi-Fi scanning
        startWifiScan()

        // Start BLE scanning
        startBleScan()
    }

    // --- Wi-Fi ---

    private fun startWifiScan() {
        val context = getApplication<Application>().applicationContext
        val hasWifiPermission = ContextCompat.checkSelfPermission(
            context, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED

        if (hasWifiPermission) {
            context.registerReceiver(
                wifiScanReceiver,
                IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
            )
            @Suppress("DEPRECATION")
            wifiManager.startScan()
        }
    }

    @Suppress("DEPRECATION")
    private fun processWifiResults() {
        try {
            val results = wifiManager.scanResults
            _wifiSignals.value = results
                .sortedByDescending { it.level }
                .map { scanResult ->
                    WifiSignal(
                        ssid = scanResult.SSID ?: "",
                        bssid = scanResult.BSSID ?: "",
                        rssi = scanResult.level,
                        frequency = scanResult.frequency
                    )
                }
            // Trigger next scan after throttle delay (Android throttles to ~4 scans/2min)
            viewModelScope.launch {
                kotlinx.coroutines.delay(30_000L)
                try {
                    @Suppress("DEPRECATION")
                    wifiManager.startScan()
                } catch (_: Exception) {}
            }
        } catch (_: SecurityException) {
            // Permission revoked at runtime
        }
    }

    // --- BLE ---

    private fun startBleScan() {
        val context = getApplication<Application>().applicationContext
        val hasBtPermission = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.BLUETOOTH_SCAN
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            ContextCompat.checkSelfPermission(
                context, Manifest.permission.ACCESS_FINE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED
        }

        if (hasBtPermission) {
            try {
                bleScanner = bluetoothManager?.adapter?.bluetoothLeScanner
                bleScanner?.startScan(bleScanCallback)
            } catch (_: SecurityException) {
                // Permission revoked
            }
        }
    }

    // --- Sensor callbacks ---

    override fun onSensorChanged(event: SensorEvent?) {
        when (event?.sensor?.type) {
            Sensor.TYPE_MAGNETIC_FIELD -> _magneticField.value = event.values.clone()
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Not needed for this implementation
    }

    // --- Cleanup ---

    override fun onCleared() {
        super.onCleared()
        sensorManager.unregisterListener(this)

        try {
            getApplication<Application>().applicationContext.unregisterReceiver(wifiScanReceiver)
        } catch (_: IllegalArgumentException) {
            // Receiver not registered
        }

        try {
            bleScanner?.stopScan(bleScanCallback)
        } catch (_: SecurityException) {
            // Permission revoked
        }
    }
}
