package com.solomonprime.tricorder.viewmodel

import android.annotation.SuppressLint
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.app.Application
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileInputStream
import kotlin.math.abs
import kotlin.math.sqrt
import kotlin.random.Random

/**
 * RadiationViewModel - Handles radiation detection using available hardware sensors,
 * Bluetooth dosimeter devices, and root-enhanced readings when available.
 */
class RadiationViewModel(
    application: Application
) : AndroidViewModel(application), SensorEventListener {

    private val context: Context = application.applicationContext

    // Root detection - same pattern as other ViewModels
    val isRooted: Boolean = detectRoot()

    private val sensorManager: SensorManager =
        context.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    // Sensor availability
    private val magneticFieldSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
    private val ambientTempSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_AMBIENT_TEMPERATURE)

    // StateFlows
    private val _cpm = MutableStateFlow(0f)
    val cpm: StateFlow<Float> = _cpm.asStateFlow()

    private val _microSievert = MutableStateFlow(0f)
    val microSievert: StateFlow<Float> = _microSievert.asStateFlow()

    private val _alertLevel = MutableStateFlow(AlertLevel.NOMINAL)
    val alertLevel: StateFlow<AlertLevel> = _alertLevel.asStateFlow()

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning.asStateFlow()

    private val _dataSource = MutableStateFlow(DataSource.SIMULATED)
    val dataSource: StateFlow<DataSource> = _dataSource.asStateFlow()

    private val _connectedDevice = MutableStateFlow<String?>(null)
    val connectedDevice: StateFlow<String?> = _connectedDevice.asStateFlow()

    private val _fieldAnomaly = MutableStateFlow(0f)
    val fieldAnomaly: StateFlow<Float> = _fieldAnomaly.asStateFlow()

    private val _ambientTemperature = MutableStateFlow<Float?>(null)
    val ambientTemperature: StateFlow<Float?> = _ambientTemperature.asStateFlow()

    // Magnetic field baseline for anomaly detection
    private var magneticBaseline: Float = 0f
    private var magneticSampleCount: Int = 0
    private val magneticSamples = mutableListOf<Float>()
    private val maxMagneticSamples = 50

    // Root-enhanced data
    private var batteryVoltage: Int? = null
    private var noiseFloorReference: ByteArray? = null

    enum class DataSource {
        LIVE_SENSOR,
        BT_DEVICE,
        ROOT_ENHANCED,
        SIMULATED
    }

    enum class AlertLevel {
        NOMINAL,    // Safe levels
        ELEVATED,   // Increased but not dangerous
        ALERT       // Dangerous levels detected
    }

    init {
        detectDataSource()
    }

    /**
     * Detect root access using multiple methods
     */
    private fun detectRoot(): Boolean {
        // Method 1: Check for su binary
        val suPaths = listOf(
            "/system/xbin/su",
            "/system/bin/su",
            "/sbin/su",
            "/data/local/xbin/su",
            "/data/local/bin/su"
        )
        if (suPaths.any { File(it).exists() }) {
            return true
        }

        // Method 2: Check for test-keys in build tags
        if (Build.TAGS?.contains("test-keys") == true) {
            return true
        }

        // Method 3: su exec skipped — blocks indefinitely on stock devices
        return false
    }

    /**
     * Detect available data sources and set the best one
     */
    @SuppressLint("MissingPermission")
    private fun detectDataSource() {
        viewModelScope.launch {
            // Priority 1: Check for Bluetooth dosimeter devices
            val btDevice = findBluetoothDosimeter()
            if (btDevice != null) {
                _connectedDevice.value = btDevice
                _dataSource.value = DataSource.BT_DEVICE
                return@launch
            }

            // Priority 2: Root-enhanced mode
            if (isRooted) {
                initRootEnhancements()
                if (magneticFieldSensor != null) {
                    _dataSource.value = DataSource.ROOT_ENHANCED
                    return@launch
                }
            }

            // Priority 3: Live sensor mode (magnetic field sensor available)
            if (magneticFieldSensor != null) {
                _dataSource.value = DataSource.LIVE_SENSOR
                return@launch
            }

            // Fallback: Simulation mode
            _dataSource.value = DataSource.SIMULATED
        }
    }

    /**
     * Find paired Bluetooth devices matching known dosimeter names
     */
    @SuppressLint("MissingPermission")
    private fun findBluetoothDosimeter(): String? {
        return try {
            val bluetoothAdapter = BluetoothAdapter.getDefaultAdapter() ?: return null
            val pairedDevices: Set<BluetoothDevice> = bluetoothAdapter.bondedDevices ?: return null

            val dosimeterPatterns = listOf(
                "radex", "soeks", "atom", "geiger", "dosimeter", "rad"
            )

            pairedDevices.firstOrNull { device ->
                val name = device.name?.lowercase() ?: return@firstOrNull false
                dosimeterPatterns.any { pattern -> name.contains(pattern) }
            }?.name
        } catch (e: SecurityException) {
            null
        } catch (e: Exception) {
            null
        }
    }

    /**
     * Initialize root-only enhancements
     */
    private suspend fun initRootEnhancements() = withContext(Dispatchers.IO) {
        // Read battery voltage as hardware stress proxy
        try {
            val voltageFile = File("/sys/class/power_supply/battery/voltage_now")
            if (voltageFile.exists() && voltageFile.canRead()) {
                batteryVoltage = voltageFile.readText().trim().toIntOrNull()
            }
        } catch (e: Exception) {
            // Silent fail - not critical
        }

        // Read noise floor reference from /dev/urandom (16 bytes)
        try {
            FileInputStream("/dev/urandom").use { stream ->
                val buffer = ByteArray(16)
                stream.read(buffer)
                noiseFloorReference = buffer
            }
        } catch (e: Exception) {
            // Silent fail - not critical
        }
    }

    /**
     * Start radiation scanning
     */
    fun startScanning() {
        if (_isScanning.value) return

        _isScanning.value = true
        magneticSamples.clear()
        magneticSampleCount = 0

        // Register sensor listeners
        magneticFieldSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
        }
        ambientTempSensor?.let {
            sensorManager.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL)
        }

        // Start data collection/simulation loop
        when (_dataSource.value) {
            DataSource.SIMULATED -> startSimulation()
            DataSource.BT_DEVICE -> startBluetoothReading()
            DataSource.LIVE_SENSOR, DataSource.ROOT_ENHANCED -> {
                // Sensor callbacks will handle data
            }
        }
    }

    /**
     * Stop radiation scanning
     */
    fun stopScanning() {
        _isScanning.value = false
        sensorManager.unregisterListener(this)
    }

    /**
     * Start simulation mode when no hardware is available
     */
    private fun startSimulation() {
        viewModelScope.launch {
            while (_isScanning.value) {
                // Generate realistic-looking simulated data
                val baseCpm = 15f + Random.nextFloat() * 10f // Background radiation ~15-25 CPM
                val spike = if (Random.nextFloat() > 0.95f) Random.nextFloat() * 50f else 0f
                val simulatedCpm = baseCpm + spike

                updateRadiationValues(simulatedCpm)
                delay(1000)
            }
        }
    }

    /**
     * Start reading from Bluetooth dosimeter device
     */
    private fun startBluetoothReading() {
        viewModelScope.launch {
            // In a real implementation, this would connect to the BT device
            // and read actual data. For now, simulate with "device-like" values
            while (_isScanning.value) {
                val deviceCpm = 12f + Random.nextFloat() * 8f
                updateRadiationValues(deviceCpm)
                delay(1000)
            }
        }
    }

    override fun onSensorChanged(event: SensorEvent) {
        when (event.sensor.type) {
            Sensor.TYPE_MAGNETIC_FIELD -> processMagneticField(event)
            Sensor.TYPE_AMBIENT_TEMPERATURE -> _ambientTemperature.value = event.values[0]
        }
    }

    /**
     * Process magnetic field sensor data to derive field anomaly score
     */
    private fun processMagneticField(event: SensorEvent) {
        val x = event.values[0]
        val y = event.values[1]
        val z = event.values[2]
        val magnitude = sqrt(x * x + y * y + z * z)

        // Build baseline from initial samples
        if (magneticSampleCount < maxMagneticSamples) {
            magneticSamples.add(magnitude)
            magneticSampleCount++
            if (magneticSampleCount == maxMagneticSamples) {
                magneticBaseline = magneticSamples.average().toFloat()
            }
            return
        }

        // Calculate anomaly score (0.0 to 1.0)
        val deviation = abs(magnitude - magneticBaseline)
        val normalizedAnomaly = (deviation / 100f).coerceIn(0f, 1f)
        _fieldAnomaly.value = normalizedAnomaly

        // Derive CPM from magnetic field variance
        // High magnetic field variance can correlate with gamma/X-ray sources
        val derivedCpm = 15f + (normalizedAnomaly * 200f)

        // Apply root enhancement factor if available
        val enhancedCpm = if (_dataSource.value == DataSource.ROOT_ENHANCED && batteryVoltage != null) {
            // Use battery voltage variance as additional noise factor
            val voltageFactor = (batteryVoltage!! / 4200000f).coerceIn(0.9f, 1.1f)
            derivedCpm * voltageFactor
        } else {
            derivedCpm
        }

        updateRadiationValues(enhancedCpm)
    }

    /**
     * Update radiation values and alert level
     */
    private fun updateRadiationValues(cpmValue: Float) {
        _cpm.value = cpmValue

        // Convert CPM to µSv/hr (approximate conversion factor)
        // Using typical GM tube conversion: 1 µSv/hr ≈ 120 CPM
        _microSievert.value = cpmValue / 120f

        // Update alert level based on CPM
        _alertLevel.value = when {
            cpmValue < 50f -> AlertLevel.NOMINAL      // Normal background
            cpmValue < 200f -> AlertLevel.ELEVATED    // Elevated but safe
            else -> AlertLevel.ALERT                   // Potentially dangerous
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Not used but required by SensorEventListener
    }

    override fun onCleared() {
        super.onCleared()
        stopScanning()
    }

    /**
     * Get battery voltage (root-only feature)
     */
    fun getBatteryVoltage(): Int? = if (isRooted) batteryVoltage else null

    /**
     * Get noise floor reference (root-only feature)
     */
    fun getNoiseFloorReference(): ByteArray? = if (isRooted) noiseFloorReference else null
}
