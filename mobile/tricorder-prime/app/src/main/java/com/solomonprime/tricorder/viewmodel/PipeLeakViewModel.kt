package com.solomonprime.tricorder.viewmodel

import android.annotation.SuppressLint
import android.app.Application
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlin.math.sqrt

/**
 * Pipe Leak Detector ViewModel — Multi-modal (4 sensors + IR)
 *
 * Combines acoustic energy (50-500 Hz), magnetic field anomaly,
 * barometric pressure variance, accelerometer vibration, and IR light
 * to estimate pipe leak probability.
 *
 * Scoring formula (normalized 0-1):
 *   leakScore = acoustic*0.35 + magnetic*0.30 + pressure*0.20 + vibration*0.15
 */
class PipeLeakViewModel(application: Application) : AndroidViewModel(application), SensorEventListener {

    // ---- Audio config ----
    private val sampleRate = 44100
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    private val bufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)

    private var audioRecord: AudioRecord? = null
    private var recordingJob: Job? = null

    // ---- Sensor handles ----
    private var sensorManager: SensorManager? = null
    private var magSensor: Sensor? = null
    private var pressureSensor: Sensor? = null
    private var accelSensor: Sensor? = null
    private var irSensor: Sensor? = null

    // ---- Exposed state ----

    private val _acousticEnergy = MutableStateFlow(0f)
    val acousticEnergy: StateFlow<Float> = _acousticEnergy.asStateFlow()

    private val _magneticVariance = MutableStateFlow(0f)
    val magneticVariance: StateFlow<Float> = _magneticVariance.asStateFlow()

    private val _pressureVariance = MutableStateFlow(0f)
    val pressureVariance: StateFlow<Float> = _pressureVariance.asStateFlow()

    private val _accelerometerRMS = MutableStateFlow(0f)
    val accelerometerRMS: StateFlow<Float> = _accelerometerRMS.asStateFlow()

    private val _irReading = MutableStateFlow(0f)
    val irReading: StateFlow<Float> = _irReading.asStateFlow()

    private val _leakProbability = MutableStateFlow(0f)
    val leakProbability: StateFlow<Float> = _leakProbability.asStateFlow()

    private val _leakAlert = MutableStateFlow("SCANNING")
    val leakAlert: StateFlow<String> = _leakAlert.asStateFlow()

    private val _baselineCalibrated = MutableStateFlow(false)
    val baselineCalibrated: StateFlow<Boolean> = _baselineCalibrated.asStateFlow()

    private val _scanHistory = MutableStateFlow<List<Float>>(emptyList())
    val scanHistory: StateFlow<List<Float>> = _scanHistory.asStateFlow()

    private val _taggedLocations = MutableStateFlow<List<Triple<String, Float, Long>>>(emptyList())
    val taggedLocations: StateFlow<List<Triple<String, Float, Long>>> = _taggedLocations.asStateFlow()

    private val _pressureDropDetected = MutableStateFlow(false)
    val pressureDropDetected: StateFlow<Boolean> = _pressureDropDetected.asStateFlow()

    // ---- Internal calibration & history ----

    private var baselineAcoustic = 1f
    private var baselineMagnetic = 1f
    private var baselinePressure = 1f
    private var baselineAccel = 1f
    private var calibrationStartMs = 0L
    private val calibrationDurationMs = 5000L

    // Rolling histories
    private val magHistory = mutableListOf<Float>()
    private val pressureHistory = mutableListOf<Float>()
    private val accelHistory = mutableListOf<Float>()
    private val maxHistorySize = 150 // ~3s at 50Hz

    // Pressure drop detection: timestamped readings over 30s window
    private val pressureTimeSeries = mutableListOf<Pair<Long, Float>>()

    // Calibration accumulators
    private val calAcousticSamples = mutableListOf<Float>()

    // Audio filter state
    private var prevSample = 0f

    // Scan history (last 60 scores)
    private val historyBuffer = mutableListOf<Float>()
    private val maxScanHistory = 60

    // ---- Lifecycle ----

    @SuppressLint("MissingPermission")
    fun startScan() {
        if (recordingJob?.isActive == true) return

        _baselineCalibrated.value = false
        _leakAlert.value = "CALIBRATING"
        _pressureDropDetected.value = false
        calibrationStartMs = System.currentTimeMillis()
        baselineAcoustic = 1f
        baselineMagnetic = 1f
        baselinePressure = 1f
        baselineAccel = 1f
        magHistory.clear()
        pressureHistory.clear()
        accelHistory.clear()
        pressureTimeSeries.clear()
        calAcousticSamples.clear()
        historyBuffer.clear()

        sensorManager = getApplication<Application>()
            .getSystemService(android.content.Context.SENSOR_SERVICE) as SensorManager

        // Magnetometer
        magSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
        magSensor?.let { sensorManager?.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }

        // Barometric pressure
        pressureSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_PRESSURE)
        pressureSensor?.let { sensorManager?.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }

        // Accelerometer
        accelSensor = sensorManager?.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        accelSensor?.let { sensorManager?.registerListener(this, it, SensorManager.SENSOR_DELAY_GAME) }

        // Samsung IR light sensor (best-effort)
        try {
            val sensorList = sensorManager?.getSensorList(Sensor.TYPE_ALL) ?: emptyList()
            irSensor = sensorList.firstOrNull { it.stringType == "com.samsung.sensor.light_ir" }
            irSensor?.let { sensorManager?.registerListener(this, it, SensorManager.SENSOR_DELAY_NORMAL) }
        } catch (_: Exception) { /* IR sensor not available */ }

        // Start audio capture
        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                sampleRate, channelConfig, audioFormat, bufferSize
            )
            if (audioRecord?.state == AudioRecord.STATE_INITIALIZED) {
                audioRecord?.startRecording()
                recordingJob = viewModelScope.launch(Dispatchers.IO) {
                    val buffer = ShortArray(bufferSize)
                    while (isActive) {
                        val readSize = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                        if (readSize > 0) {
                            val energy = computeBandEnergy(buffer, readSize)
                            _acousticEnergy.value = energy

                            val elapsed = System.currentTimeMillis() - calibrationStartMs
                            if (!_baselineCalibrated.value && elapsed < calibrationDurationMs) {
                                calAcousticSamples.add(energy)
                            } else if (!_baselineCalibrated.value) {
                                finalizeCalibration()
                            }

                            if (_baselineCalibrated.value) {
                                updateLeakScore()
                            }
                        }
                        delay(50)
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    fun stopScan() {
        recordingJob?.cancel()
        recordingJob = null
        sensorManager?.unregisterListener(this)
        try {
            audioRecord?.stop()
            audioRecord?.release()
        } catch (_: Exception) {}
        audioRecord = null
        _leakAlert.value = "STOPPED"
    }

    fun recalibrate() {
        stopScan()
        startScan()
    }

    fun tagLocation(label: String) {
        val current = _taggedLocations.value.toMutableList()
        current.add(Triple(label, _leakProbability.value, System.currentTimeMillis()))
        _taggedLocations.value = current
    }

    // ---- Calibration ----

    private fun finalizeCalibration() {
        baselineAcoustic = if (calAcousticSamples.isNotEmpty())
            calAcousticSamples.average().toFloat().coerceAtLeast(1e-6f) else 1f

        synchronized(magHistory) {
            baselineMagnetic = stdDev(magHistory).coerceAtLeast(1e-6f)
        }
        synchronized(pressureHistory) {
            baselinePressure = stdDev(pressureHistory).coerceAtLeast(1e-6f)
        }
        synchronized(accelHistory) {
            baselineAccel = stdDev(accelHistory).coerceAtLeast(1e-6f)
        }
        _baselineCalibrated.value = true
        _leakAlert.value = "LOW"
    }

    // ---- Audio processing ----

    /**
     * Bandpass RMS energy (50-500 Hz approximation):
     * first-order high-pass (removes DC/sub-50Hz) + low-pass averaging (attenuates >500Hz)
     */
    private fun computeBandEnergy(buffer: ShortArray, size: Int): Float {
        var sum = 0.0
        var prev = prevSample
        var prevHp = 0f
        for (i in 0 until size) {
            val sample = buffer[i].toFloat()
            val hp = sample - prev * 0.98f
            prev = sample
            val bp = (hp + prevHp) * 0.5f
            prevHp = hp
            sum += bp * bp
        }
        prevSample = prev
        return sqrt(sum / size).toFloat()
    }

    // ---- Sensor callbacks ----

    override fun onSensorChanged(event: SensorEvent?) {
        event ?: return
        when (event.sensor.type) {
            Sensor.TYPE_MAGNETIC_FIELD -> handleMag(event)
            Sensor.TYPE_PRESSURE -> handlePressure(event)
            Sensor.TYPE_ACCELEROMETER -> handleAccel(event)
            else -> {
                // IR sensor (vendor-specific type)
                if (event.sensor.stringType == "com.samsung.sensor.light_ir") {
                    _irReading.value = event.values[0]
                }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    private fun handleMag(event: SensorEvent) {
        val mag = sqrt(
            event.values[0] * event.values[0] +
            event.values[1] * event.values[1] +
            event.values[2] * event.values[2]
        )
        synchronized(magHistory) {
            magHistory.add(mag)
            if (magHistory.size > maxHistorySize) magHistory.removeAt(0)
            _magneticVariance.value = stdDev(magHistory)
        }
    }

    private fun handlePressure(event: SensorEvent) {
        val p = event.values[0]
        synchronized(pressureHistory) {
            pressureHistory.add(p)
            if (pressureHistory.size > maxHistorySize) pressureHistory.removeAt(0)
            _pressureVariance.value = stdDev(pressureHistory)
        }

        // Pressure drop detection (>0.5 hPa in 30s)
        val now = System.currentTimeMillis()
        pressureTimeSeries.add(Pair(now, p))
        // Prune older than 30s
        val cutoff = now - 30_000L
        pressureTimeSeries.removeAll { it.first < cutoff }
        if (pressureTimeSeries.size >= 2) {
            val oldest = pressureTimeSeries.first().second
            val newest = pressureTimeSeries.last().second
            _pressureDropDetected.value = (oldest - newest) > 0.5f
        }
    }

    private fun handleAccel(event: SensorEvent) {
        // Remove gravity (~9.81) by using deviation from magnitude
        val mag = sqrt(
            event.values[0] * event.values[0] +
            event.values[1] * event.values[1] +
            event.values[2] * event.values[2]
        )
        val vibration = kotlin.math.abs(mag - 9.81f)
        synchronized(accelHistory) {
            accelHistory.add(vibration)
            if (accelHistory.size > maxHistorySize) accelHistory.removeAt(0)
            _accelerometerRMS.value = sqrt(
                accelHistory.sumOf { (it * it).toDouble() } / accelHistory.size
            ).toFloat()
        }
    }

    // ---- Leak scoring ----

    private fun updateLeakScore() {
        val normAcoustic = (_acousticEnergy.value / baselineAcoustic).coerceIn(0f, 10f) / 10f
        val normMagnetic = (_magneticVariance.value / baselineMagnetic).coerceIn(0f, 10f) / 10f
        val normPressure = (_pressureVariance.value / baselinePressure).coerceIn(0f, 10f) / 10f
        val normVibration = (_accelerometerRMS.value / baselineAccel).coerceIn(0f, 10f) / 10f

        val score = (
            normAcoustic * 0.35f +
            normMagnetic * 0.30f +
            normPressure * 0.20f +
            normVibration * 0.15f
        ).coerceIn(0f, 1f)

        _leakProbability.value = score

        // Update scan history
        historyBuffer.add(score)
        if (historyBuffer.size > maxScanHistory) historyBuffer.removeAt(0)
        _scanHistory.value = historyBuffer.toList()

        _leakAlert.value = when {
            score > 0.6f -> "HIGH"
            score > 0.3f -> "MEDIUM"
            else -> "LOW"
        }
    }

    // ---- Utility ----

    private fun stdDev(data: List<Float>): Float {
        if (data.size < 2) return 0f
        val mean = data.average().toFloat()
        val variance = data.sumOf { ((it - mean) * (it - mean)).toDouble() } / data.size
        return sqrt(variance).toFloat()
    }

    override fun onCleared() {
        super.onCleared()
        stopScan()
    }
}
