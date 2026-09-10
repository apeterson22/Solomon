package com.solomonprime.tricorder.viewmodel

import android.annotation.SuppressLint
import android.app.Application
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.BatteryManager
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.io.File
import kotlin.math.sqrt
import kotlin.random.Random

class BioScannerViewModel(application: Application) : AndroidViewModel(application) {

    val isRooted: Boolean

    private val _heartRate = MutableStateFlow(0)
    val heartRate = _heartRate.asStateFlow()

    private val _bloodOxygen = MutableStateFlow(97.5f)
    val bloodOxygen = _bloodOxygen.asStateFlow()

    private val _skinTemp = MutableStateFlow(0f)
    val skinTemp = _skinTemp.asStateFlow()

    private val _stressIndex = MutableStateFlow(0.3f)
    val stressIndex = _stressIndex.asStateFlow()

    private val _movementLevel = MutableStateFlow(0f)
    val movementLevel = _movementLevel.asStateFlow()

    private val _dataSource = MutableStateFlow("SIMULATED")
    val dataSource = _dataSource.asStateFlow()

    // Camera pulse detection state
    private val _isCameraPulseActive = MutableStateFlow(false)
    val isCameraPulseActive = _isCameraPulseActive.asStateFlow()

    private val _cameraPulseReady = MutableStateFlow(false)
    val cameraPulseReady = _cameraPulseReady.asStateFlow()

    private val redChannelBuffer = mutableListOf<Float>()
    private val redTimestamps = mutableListOf<Long>()

    private val _connectedDeviceName = MutableStateFlow<String?>(null)
    val connectedDeviceName = _connectedDeviceName.asStateFlow()

    private val _pairedDevices = MutableStateFlow<List<String>>(emptyList())
    val pairedDevices = _pairedDevices.asStateFlow()

    // New fields for enhanced BIO screen
    private val _bloodPressureSystolic = MutableStateFlow(120)
    val bloodPressureSystolic = _bloodPressureSystolic.asStateFlow()

    private val _bloodPressureDiastolic = MutableStateFlow(80)
    val bloodPressureDiastolic = _bloodPressureDiastolic.asStateFlow()

    private val _steps = MutableStateFlow(0)
    val steps = _steps.asStateFlow()

    private val _caloriesBurned = MutableStateFlow(0f)
    val caloriesBurned = _caloriesBurned.asStateFlow()

    private val _sleepHours = MutableStateFlow(0f)
    val sleepHours = _sleepHours.asStateFlow()

    private val sensorManager: SensorManager =
        application.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    private var hasHardwareHeartRate = false
    private var hasBtDevice = false
    private var scanJob: Job? = null
    private var stepSensorRegistered = false

    private val sensorListener = object : SensorEventListener {
        override fun onSensorChanged(event: SensorEvent) {
            when (event.sensor.type) {
                Sensor.TYPE_HEART_RATE -> {
                    val hr = event.values[0].toInt()
                    if (hr > 0) {
                        _heartRate.value = hr
                        _dataSource.value = "PHONE_SENSORS"
                    }
                }
                Sensor.TYPE_ACCELEROMETER -> {
                    val x = event.values[0]
                    val y = event.values[1]
                    val z = event.values[2]
                    val mag = sqrt(x * x + y * y + z * z)
                    val deviation = kotlin.math.abs(mag - 9.81f) / 9.81f
                    _movementLevel.value = deviation.coerceIn(0f, 1f)
                }
                Sensor.TYPE_STEP_COUNTER -> {
                    _steps.value = event.values[0].toInt()
                    _caloriesBurned.value = _steps.value * 0.04f
                }
                Sensor.TYPE_LIGHT -> {
                    // Light sensor can indicate proximity-based SpO2 proxy
                    // Very bright = finger not covering sensor; dim = finger on sensor
                    val lux = event.values[0]
                    if (lux < 10f && _isCameraPulseActive.value) {
                        // Finger is covering the light sensor — use for pulse proxy
                        onCameraFrame(lux * 10f + 80f)
                    }
                }
                Sensor.TYPE_PROXIMITY -> {
                    // Proximity = 0 means something is close (finger)
                    val prox = event.values[0]
                    if (prox < 1f) {
                        // Could be used for gesture detection
                    }
                }
            }
        }
        override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}
    }

    init {
        isRooted = detectRoot()
        detectBluetoothDevices()
        hasHardwareHeartRate = sensorManager.getDefaultSensor(Sensor.TYPE_HEART_RATE) != null
        
        _dataSource.value = when {
            hasBtDevice -> "WEARABLE"
            hasHardwareHeartRate -> "PHONE_SENSORS"
            else -> "SIMULATED"
        }
        
        readBatteryTemperature()
        
        // Try to detect Samsung Health or Google Fit
        checkHealthPlatforms()
    }

    private fun checkHealthPlatforms() {
        val ctx = getApplication<Application>()
        val pm = ctx.packageManager
        
        // Check for Samsung Health
        try {
            pm.getPackageInfo("com.sec.android.app.shealth", 0)
            if (_dataSource.value == "SIMULATED") {
                _dataSource.value = "SAMSUNG_HEALTH"
            }
        } catch (_: Exception) {}
        
        // Check for Google Fit
        try {
            pm.getPackageInfo("com.google.android.apps.fitness", 0)
            if (_dataSource.value == "SIMULATED") {
                _dataSource.value = "GOOGLE_FIT"
            }
        } catch (_: Exception) {}
    }

    private fun detectRoot(): Boolean {
        try {
            if (File("/system/xbin/su").exists() || File("/system/bin/su").exists()) return true
        } catch (_: Exception) {}
        try {
            if (Build.TAGS?.contains("test-keys") == true) return true
        } catch (_: Exception) {}
        return false
    }

    @SuppressLint("MissingPermission")
    private fun detectBluetoothDevices() {
        try {
            val btManager = getApplication<Application>().getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
            val adapter = btManager?.adapter ?: BluetoothAdapter.getDefaultAdapter() ?: return
            
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                // Need BLUETOOTH_CONNECT permission
                return
            }
            
            @Suppress("DEPRECATION")
            val bonded = adapter.bondedDevices ?: return
            val fitnessKeywords = listOf("polar", "garmin", "fitbit", "mi band", "band", "watch", "galaxy", "sony", "smartwatch", "sw3", "huawei")
            val allPaired = bonded.mapNotNull { it.name }
            _pairedDevices.value = allPaired

            val matched = allPaired.firstOrNull { name ->
                fitnessKeywords.any { name.lowercase().contains(it) }
            }
            if (matched != null) {
                hasBtDevice = true
                _connectedDeviceName.value = matched
            }
        } catch (_: SecurityException) {
        } catch (_: Exception) {}
    }

    fun scanForDevices() {
        viewModelScope.launch {
            detectBluetoothDevices()
            checkHealthPlatforms()
            
            // Update data source based on new findings
            _dataSource.value = when {
                hasBtDevice -> "WEARABLE"
                hasHardwareHeartRate -> "PHONE_SENSORS"
                _dataSource.value == "SAMSUNG_HEALTH" -> "SAMSUNG_HEALTH"
                _dataSource.value == "GOOGLE_FIT" -> "GOOGLE_FIT"
                else -> "SIMULATED"
            }
        }
    }

    private fun readBatteryTemperature() {
        try {
            val ctx = getApplication<Application>()
            val intent = ctx.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            val tempTenths = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) ?: 0
            if (tempTenths > 0) {
                _skinTemp.value = tempTenths / 10f
            }
        } catch (_: Exception) {}
    }

    fun startScan() {
        if (scanJob?.isActive == true) return

        // Register step counter
        sensorManager.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
            stepSensorRegistered = true
        }

        when (_dataSource.value) {
            "PHONE_SENSORS" -> startLiveSensors()
            "WEARABLE", "SAMSUNG_HEALTH", "GOOGLE_FIT" -> startWearableSimulation()
            else -> startSimulation()
        }
    }

    fun startLiveSensors() {
        // Register ALL available phone sensors for maximum data
        sensorManager.getDefaultSensor(Sensor.TYPE_HEART_RATE)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_GAME)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_LIGHT)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_FASTEST)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_PROXIMITY)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_STEP_COUNTER)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
            stepSensorRegistered = true
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        sensorManager.getDefaultSensor(Sensor.TYPE_PRESSURE)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
        }

        scanJob = viewModelScope.launch {
            if (_heartRate.value == 0) _heartRate.value = 72
            while (true) {
                readBatteryTemperature()
                val hrFactor = ((_heartRate.value - 60f) / 40f).coerceIn(0f, 1f)
                val mvFactor = _movementLevel.value
                _stressIndex.value = ((hrFactor * 0.7f + mvFactor * 0.3f)).coerceIn(0f, 1f)
                _bloodOxygen.value = (_bloodOxygen.value + Random.nextFloat() * 0.4f - 0.2f).coerceIn(95f, 99.9f)
                
                // Simulate activity data
                _caloriesBurned.value = (_steps.value * 0.04f)
                _sleepHours.value = 7.5f + Random.nextFloat() - 0.5f
                
                // Blood pressure varies slightly
                _bloodPressureSystolic.value = (120 + Random.nextInt(-5, 6)).coerceIn(100, 140)
                _bloodPressureDiastolic.value = (80 + Random.nextInt(-3, 4)).coerceIn(60, 90)
                
                delay(2000L)
            }
        }
    }

    private fun startWearableSimulation() {
        sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)?.let {
            sensorManager.registerListener(sensorListener, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        
        scanJob = viewModelScope.launch {
            _heartRate.value = 72
            _steps.value = Random.nextInt(2000, 8000) // Simulate daily steps
            _sleepHours.value = 6.5f + Random.nextFloat() * 2f
            _caloriesBurned.value = _steps.value * 0.04f
            
            while (true) {
                _heartRate.value = (_heartRate.value + Random.nextInt(-2, 3)).coerceIn(55, 110)
                _bloodOxygen.value = (_bloodOxygen.value + Random.nextFloat() * 0.4f - 0.2f).coerceIn(95f, 99.9f)
                readBatteryTemperature()
                _stressIndex.value = (_stressIndex.value + Random.nextFloat() * 0.08f - 0.04f).coerceIn(0f, 1f)
                _movementLevel.value = (_movementLevel.value + Random.nextFloat() * 0.1f - 0.05f).coerceIn(0f, 1f)
                
                _bloodPressureSystolic.value = (118 + Random.nextInt(-8, 9)).coerceIn(100, 140)
                _bloodPressureDiastolic.value = (78 + Random.nextInt(-5, 6)).coerceIn(60, 90)
                
                // Steps increment slowly
                _steps.value = _steps.value + Random.nextInt(0, 5)
                _caloriesBurned.value = _steps.value * 0.04f
                
                delay(2000L)
            }
        }
    }

    private fun startSimulation() {
        scanJob = viewModelScope.launch {
            _heartRate.value = 72
            if (_skinTemp.value == 0f) _skinTemp.value = 36.6f
            _steps.value = Random.nextInt(1000, 5000)
            _sleepHours.value = 7f + Random.nextFloat()
            _caloriesBurned.value = _steps.value * 0.04f
            
            while (true) {
                _heartRate.value = (_heartRate.value + Random.nextInt(-3, 4)).coerceIn(60, 100)
                _bloodOxygen.value = (_bloodOxygen.value + Random.nextFloat() * 0.6f - 0.3f).coerceIn(95f, 99.9f)
                _skinTemp.value = (_skinTemp.value + Random.nextFloat() * 0.2f - 0.1f).coerceIn(36f, 37.5f)
                _stressIndex.value = (_stressIndex.value + Random.nextFloat() * 0.1f - 0.05f).coerceIn(0f, 1f)
                _movementLevel.value = (_movementLevel.value + Random.nextFloat() * 0.1f - 0.05f).coerceIn(0f, 1f)
                
                _bloodPressureSystolic.value = (120 + Random.nextInt(-10, 11)).coerceIn(100, 140)
                _bloodPressureDiastolic.value = (80 + Random.nextInt(-6, 7)).coerceIn(60, 90)
                
                _steps.value = _steps.value + Random.nextInt(0, 3)
                _caloriesBurned.value = _steps.value * 0.04f
                
                delay(2000L)
            }
        }
    }

    /** Called from CameraX ImageAnalysis to feed red channel average */
    fun onCameraFrame(redAvg: Float) {
        if (!_isCameraPulseActive.value) return
        val now = System.currentTimeMillis()
        redChannelBuffer.add(redAvg)
        redTimestamps.add(now)

        // Keep last 10 seconds of data
        while (redTimestamps.size > 300) { redTimestamps.removeAt(0); redChannelBuffer.removeAt(0) }

        // Need at least 3 seconds of data to estimate
        if (redTimestamps.size < 90) {
            _cameraPulseReady.value = false
            return
        }
        _cameraPulseReady.value = true

        // Simple peak detection: count zero-crossings of the detrended signal
        val mean = redChannelBuffer.average().toFloat()
        val detrended = redChannelBuffer.map { it - mean }
        var crossings = 0
        for (i in 1 until detrended.size) {
            if (detrended[i - 1] < 0 && detrended[i] >= 0) crossings++
        }
        val durationSec = (redTimestamps.last() - redTimestamps.first()) / 1000.0f
        if (durationSec > 2f && crossings > 0) {
            val bpm = (crossings / durationSec * 60f).toInt().coerceIn(40, 200)
            _heartRate.value = bpm
            _dataSource.value = "CAMERA_PULSE"
        }
    }

    fun startCameraPulse() {
        _isCameraPulseActive.value = true
        _cameraPulseReady.value = false
        redChannelBuffer.clear()
        redTimestamps.clear()
        _dataSource.value = "CAMERA_PULSE"
    }

    fun stopCameraPulse() {
        _isCameraPulseActive.value = false
        _cameraPulseReady.value = false
    }

    /** Force switch to live phone sensors mode */
    fun switchToLiveMode() {
        scanJob?.cancel()
        scanJob = null
        _dataSource.value = "PHONE_SENSORS"
        startLiveSensors()
        // Start scan job for continuous updates
        scanJob = viewModelScope.launch {
            if (_heartRate.value == 0) _heartRate.value = 72
            while (true) {
                readBatteryTemperature()
                val hrFactor = ((_heartRate.value - 60f) / 40f).coerceIn(0f, 1f)
                val mvFactor = _movementLevel.value
                _stressIndex.value = ((hrFactor * 0.7f + mvFactor * 0.3f)).coerceIn(0f, 1f)
                _bloodOxygen.value = (_bloodOxygen.value + Random.nextFloat() * 0.4f - 0.2f).coerceIn(95f, 99.9f)
                _caloriesBurned.value = (_steps.value * 0.04f)
                _bloodPressureSystolic.value = (120 + Random.nextInt(-5, 6)).coerceIn(100, 140)
                _bloodPressureDiastolic.value = (80 + Random.nextInt(-3, 4)).coerceIn(60, 90)
                delay(2000L)
            }
        }
    }

    fun stopScan() {
        scanJob?.cancel()
        scanJob = null
        try {
            sensorManager.unregisterListener(sensorListener)
        } catch (_: Exception) {}
    }

    override fun onCleared() {
        super.onCleared()
        stopScan()
    }
}
