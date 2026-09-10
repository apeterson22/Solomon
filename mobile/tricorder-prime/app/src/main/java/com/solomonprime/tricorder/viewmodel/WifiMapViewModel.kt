package com.solomonprime.tricorder.viewmodel

import android.Manifest
import android.app.Application
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
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.location.*
import com.solomonprime.tricorder.model.WifiMapPoint
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

/**
 * ViewModel for WiFi signal mapping with IMU dead-reckoning.
 * Combines WiFi scan results with step detection + rotation vector
 * to build a spatial map of signal strength via dead reckoning.
 */
class WifiMapViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        private const val MAX_POINTS = 500
        private const val SCAN_INTERVAL_MS = 10_000L
        private const val STEP_SIZE_METERS = 0.75f
        private const val RSSI_BOUNDARY_THRESHOLD = 15
        private const val MIN_SCALE = 0.5f
        private const val MAX_SCALE = 4.0f
        private const val ZOOM_STEP = 0.25f
    }

    private val wifiManager: WifiManager =
        application.getSystemService(Context.WIFI_SERVICE) as WifiManager

    private val sensorManager: SensorManager =
        application.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    private val fusedLocationClient: FusedLocationProviderClient =
        LocationServices.getFusedLocationProviderClient(application)

    // --- Public state ---

    private val _points = MutableStateFlow<List<WifiMapPoint>>(emptyList())
    val points = _points.asStateFlow()

    private val _isMapping = MutableStateFlow(false)
    val isMapping = _isMapping.asStateFlow()

    private val _pointCount = MutableStateFlow(0)
    val pointCount = _pointCount.asStateFlow()

    private val _currentPosition = MutableStateFlow(0f to 0f)
    val currentPosition = _currentPosition.asStateFlow()

    private val _roomBoundaryPoints = MutableStateFlow<List<Pair<Float, Float>>>(emptyList())
    val roomBoundaryPoints = _roomBoundaryPoints.asStateFlow()

    private val _mapScale = MutableStateFlow(1.0f)
    val mapScale = _mapScale.asStateFlow()

    private val _headingDegrees = MutableStateFlow(0f)
    val headingDegrees = _headingDegrees.asStateFlow()

    // --- Internal state ---

    private var currentLatitude: Double? = null
    private var currentLongitude: Double? = null
    private var posX = 0f
    private var posY = 0f
    private var headingRad = 0f
    private val ringBuffer = ArrayDeque<WifiMapPoint>(MAX_POINTS)
    private val boundaryPoints = mutableListOf<Pair<Float, Float>>()

    // Rotation vector output
    private val rotationMatrix = FloatArray(9)
    private val orientationAngles = FloatArray(3)

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(locationResult: LocationResult) {
            locationResult.lastLocation?.let { loc ->
                currentLatitude = loc.latitude
                currentLongitude = loc.longitude
            }
        }
    }

    // --- Sensor listener: step detector + rotation vector + accelerometer ---

    private val sensorListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            when (event.sensor.type) {
                Sensor.TYPE_STEP_DETECTOR -> {
                    if (_isMapping.value) {
                        // Advance position by one step in current heading direction
                        posX += cos(headingRad) * STEP_SIZE_METERS
                        posY += sin(headingRad) * STEP_SIZE_METERS
                        _currentPosition.value = posX to posY
                    }
                }
                Sensor.TYPE_ROTATION_VECTOR -> {
                    SensorManager.getRotationMatrixFromVector(rotationMatrix, event.values)
                    SensorManager.getOrientation(rotationMatrix, orientationAngles)
                    // azimuth in radians
                    headingRad = orientationAngles[0]
                    _headingDegrees.value = Math.toDegrees(headingRad.toDouble()).toFloat()
                }
                Sensor.TYPE_ACCELEROMETER -> {
                    // Available for future motion detection enhancements
                }
            }
        }

        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    @Suppress("DEPRECATION")
    private val wifiScanReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == WifiManager.SCAN_RESULTS_AVAILABLE_ACTION && _isMapping.value) {
                recordScanResults()
            }
        }
    }

    private var receiverRegistered = false
    private var sensorsRegistered = false

    // --- Public API ---

    fun startMapping() {
        if (_isMapping.value) return
        // Reset dead-reckoning origin
        posX = 0f
        posY = 0f
        _currentPosition.value = 0f to 0f

        _isMapping.value = true
        startLocationUpdates()
        registerWifiReceiver()
        registerSensors()
        triggerScanLoop()
    }

    fun stopMapping() {
        _isMapping.value = false
        fusedLocationClient.removeLocationUpdates(locationCallback)
        unregisterWifiReceiver()
        unregisterSensors()
    }

    fun clearMap() {
        ringBuffer.clear()
        boundaryPoints.clear()
        _points.value = emptyList()
        _pointCount.value = 0
        _roomBoundaryPoints.value = emptyList()
        posX = 0f
        posY = 0f
        _currentPosition.value = 0f to 0f
    }

    fun zoomIn() {
        _mapScale.value = (_mapScale.value + ZOOM_STEP).coerceAtMost(MAX_SCALE)
    }

    fun zoomOut() {
        _mapScale.value = (_mapScale.value - ZOOM_STEP).coerceAtLeast(MIN_SCALE)
    }

    fun resetView() {
        _mapScale.value = 1.0f
    }

    // --- Internals ---

    private fun startLocationUpdates() {
        val context = getApplication<Application>().applicationContext
        if (ContextCompat.checkSelfPermission(
                context, Manifest.permission.ACCESS_FINE_LOCATION
            ) != PackageManager.PERMISSION_GRANTED
        ) return

        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 2000)
            .setMinUpdateIntervalMillis(1000)
            .build()
        fusedLocationClient.requestLocationUpdates(request, locationCallback, Looper.getMainLooper())
    }

    private fun registerSensors() {
        if (sensorsRegistered) return
        sensorManager.getDefaultSensor(Sensor.TYPE_STEP_DETECTOR)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_FASTEST)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_GAME)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        sensorsRegistered = true
    }

    private fun unregisterSensors() {
        if (!sensorsRegistered) return
        sensorManager.unregisterListener(sensorListener)
        sensorsRegistered = false
    }

    private fun registerWifiReceiver() {
        if (receiverRegistered) return
        val context = getApplication<Application>().applicationContext
        context.registerReceiver(
            wifiScanReceiver,
            IntentFilter(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)
        )
        receiverRegistered = true
    }

    private fun unregisterWifiReceiver() {
        if (!receiverRegistered) return
        try {
            getApplication<Application>().applicationContext.unregisterReceiver(wifiScanReceiver)
        } catch (_: IllegalArgumentException) {}
        receiverRegistered = false
    }

    @Suppress("DEPRECATION")
    private fun triggerScanLoop() {
        viewModelScope.launch {
            while (_isMapping.value) {
                try {
                    wifiManager.startScan()
                } catch (_: Exception) {}
                delay(SCAN_INTERVAL_MS)
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun recordScanResults() {
        val lat = currentLatitude ?: 0.0
        val lon = currentLongitude ?: 0.0
        val now = System.currentTimeMillis()

        try {
            val results = wifiManager.scanResults
            for (scanResult in results) {
                val point = WifiMapPoint(
                    ssid = scanResult.SSID ?: "",
                    bssid = scanResult.BSSID ?: "",
                    rssi = scanResult.level,
                    latitude = lat,
                    longitude = lon,
                    timestamp = now,
                    relativeX = posX,
                    relativeY = posY
                )
                if (ringBuffer.size >= MAX_POINTS) {
                    ringBuffer.removeFirst()
                }
                ringBuffer.addLast(point)
            }
            _points.value = ringBuffer.toList()
            _pointCount.value = ringBuffer.size

            // Detect RSSI boundaries (wall indicators)
            detectBoundaries()
        } catch (_: SecurityException) {}
    }

    /**
     * Compare RSSI readings at adjacent positions — a sharp drop (>15 dBm)
     * between nearby scan points suggests a wall or room boundary.
     */
    private fun detectBoundaries() {
        val pts = ringBuffer.toList()
        if (pts.size < 2) return

        // Group by BSSID for per-AP analysis
        val byBssid = pts.groupBy { it.bssid }
        val newBoundaries = mutableListOf<Pair<Float, Float>>()

        for ((_, bssidPoints) in byBssid) {
            if (bssidPoints.size < 2) continue
            val sorted = bssidPoints.sortedBy { it.timestamp }
            for (i in 1 until sorted.size) {
                val prev = sorted[i - 1]
                val curr = sorted[i]
                val rssiDrop = abs(curr.rssi - prev.rssi)
                if (rssiDrop > RSSI_BOUNDARY_THRESHOLD) {
                    // Midpoint between the two readings
                    val midX = (prev.relativeX + curr.relativeX) / 2f
                    val midY = (prev.relativeY + curr.relativeY) / 2f
                    newBoundaries.add(midX to midY)
                }
            }
        }

        if (newBoundaries.isNotEmpty()) {
            boundaryPoints.addAll(newBoundaries)
            _roomBoundaryPoints.value = boundaryPoints.toList()
        }
    }

    override fun onCleared() {
        super.onCleared()
        stopMapping()
    }
}
