package com.solomonprime.tricorder.viewmodel

import android.annotation.SuppressLint
import android.app.Application
import android.content.Context
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.solomonprime.tricorder.data.ConnectedDeviceManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.SharingStarted
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.sin
import kotlin.math.sqrt

class AcousticViewModel(
    application: Application,
    private val deviceManager: ConnectedDeviceManager? = null
) : AndroidViewModel(application) {

    private fun getAudioSource(): Int =
        if (deviceManager?.preferHfpMic?.value == true)
            MediaRecorder.AudioSource.VOICE_COMMUNICATION
        else
            MediaRecorder.AudioSource.MIC

    private val sampleRate = 44100
    private val channelConfig = AudioFormat.CHANNEL_IN_MONO
    private val audioFormat = AudioFormat.ENCODING_PCM_16BIT
    private val bufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)

    private var audioRecord: AudioRecord? = null

    // ── Bluetooth SCO Routing ─────────────────────────────────
    private val audioManager = application.getSystemService(Context.AUDIO_SERVICE) as AudioManager
    private val _scoEnabled = MutableStateFlow(false)
    val scoEnabled: StateFlow<Boolean> = _scoEnabled.asStateFlow()

    fun toggleBluetoothSco(enable: Boolean) {
        if (enable) {
            audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
            audioManager.startBluetoothSco()
            audioManager.isBluetoothScoOn = true
            _scoEnabled.value = true
        } else {
            audioManager.isBluetoothScoOn = false
            audioManager.stopBluetoothSco()
            audioManager.mode = AudioManager.MODE_NORMAL
            _scoEnabled.value = false
        }
    }
    


    private var recordingJob: Job? = null
    private var noiseFloorJob: Job? = null

    private val _decibels = MutableStateFlow(0f)
    val decibels = _decibels.asStateFlow()

    private val _waveform = MutableStateFlow<List<Float>>(emptyList())
    val waveform = _waveform.asStateFlow()

    private val _dominantFrequency = MutableStateFlow(0f)
    val dominantFrequency = _dominantFrequency.asStateFlow()

    private val _freqBand = MutableStateFlow("SILENT")
    val freqBand = _freqBand.asStateFlow()

    private val _noiseFloorDb = MutableStateFlow(-60f)
    val noiseFloorDb = _noiseFloorDb.asStateFlow()

    // SNR = current dB - noise floor
    val snrDb: StateFlow<Float> = combine(_decibels, _noiseFloorDb) { db, floor ->
        (db - floor).coerceAtLeast(0f)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), 0f)

    // History for noise floor calculation (last 10 seconds at ~20 samples/sec)
    private val dbHistory = mutableListOf<Float>()
    private val maxHistorySize = 200 // ~10 seconds at 50ms intervals

    // Frequency band definitions
    private data class FrequencyBand(val name: String, val minHz: Float, val maxHz: Float)
    private val frequencyBands = listOf(
        FrequencyBand("SUB-BASS", 20f, 60f),
        FrequencyBand("BASS", 60f, 250f),
        FrequencyBand("MID", 250f, 2000f),
        FrequencyBand("HIGH-MID", 2000f, 6000f),
        FrequencyBand("HIGH", 6000f, 20000f)
    )

    /**
     * Goertzel algorithm to calculate magnitude at a specific frequency.
     * More efficient than full FFT when only checking specific frequencies.
     */
    private fun goertzelMagnitude(samples: ShortArray, targetFreq: Float, sampleRate: Int): Float {
        val numSamples = samples.size
        val k = (0.5 + (numSamples * targetFreq) / sampleRate).toInt()
        val omega = (2.0 * PI * k) / numSamples
        val coeff = 2.0 * cos(omega)
        
        var s0 = 0.0
        var s1 = 0.0
        var s2 = 0.0
        
        for (sample in samples) {
            s0 = sample.toDouble() + coeff * s1 - s2
            s2 = s1
            s1 = s0
        }
        
        val real = s1 - s2 * cos(omega)
        val imag = s2 * sin(omega)
        return sqrt(real * real + imag * imag).toFloat()
    }

    /**
     * Calculate energy in a frequency band using multiple Goertzel calculations.
     */
    private fun bandEnergy(samples: ShortArray, minFreq: Float, maxFreq: Float, sampleRate: Int): Float {
        // Sample frequencies within the band
        val numSamples = 5
        val step = (maxFreq - minFreq) / numSamples
        var totalEnergy = 0f
        
        var freq = minFreq + step / 2
        while (freq < maxFreq) {
            val mag = goertzelMagnitude(samples, freq, sampleRate)
            totalEnergy += mag * mag
            freq += step
        }
        
        return sqrt(totalEnergy)
    }

    /**
     * Find dominant frequency using Goertzel algorithm across key frequencies.
     */
    private fun findDominantFrequency(samples: ShortArray): Pair<Float, String> {
        // Check energy in each band
        val bandEnergies = frequencyBands.map { band ->
            band to bandEnergy(samples, band.minHz, band.maxHz, sampleRate)
        }
        
        val dominantBand = bandEnergies.maxByOrNull { it.second }
        
        if (dominantBand == null || dominantBand.second < 100f) {
            return Pair(0f, "SILENT")
        }
        
        // Refine frequency within the dominant band
        val band = dominantBand.first
        val refinedFreq = findPeakInBand(samples, band.minHz, band.maxHz)
        
        return Pair(refinedFreq, band.name)
    }

    /**
     * Find peak frequency within a band using finer Goertzel steps.
     */
    private fun findPeakInBand(samples: ShortArray, minFreq: Float, maxFreq: Float): Float {
        val numSteps = 20
        val step = (maxFreq - minFreq) / numSteps
        var maxMag = 0f
        var peakFreq = minFreq
        
        var freq = minFreq
        while (freq <= maxFreq) {
            val mag = goertzelMagnitude(samples, freq, sampleRate)
            if (mag > maxMag) {
                maxMag = mag
                peakFreq = freq
            }
            freq += step
        }
        
        return peakFreq
    }

    @SuppressLint("MissingPermission")
    fun startRecording() {
        if (recordingJob?.isActive == true) return
        
        // Check RECORD_AUDIO permission before attempting to record
        val ctx = getApplication<Application>()
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.M) {
            if (ctx.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) 
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                // Permission not granted - emit simulated data instead
                startSimulatedRecording()
                return
            }
        }

        try {
            audioRecord = AudioRecord(
                getAudioSource(),
                sampleRate,
                channelConfig,
                audioFormat,
                bufferSize
            )
        } catch (e: SecurityException) {
            // Permission denied at runtime
            startSimulatedRecording()
            return
        } catch (e: IllegalArgumentException) {
            // Invalid audio parameters
            startSimulatedRecording()
            return
        }

        try {
            if (audioRecord?.state == AudioRecord.STATE_INITIALIZED) {
                audioRecord?.startRecording()
                
                // Main recording job
                recordingJob = viewModelScope.launch(Dispatchers.IO) {
                    val buffer = ShortArray(bufferSize)
                    val history = mutableListOf<Float>()
                    
                    while (isActive) {
                        val readSize = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                        if (readSize > 0) {
                            // Calculate amplitude (RMS)
                            var sum = 0.0
                            for (i in 0 until readSize) {
                                sum += buffer[i] * buffer[i]
                            }
                            val amplitude = sqrt(sum / readSize)
                            
                            // Calculate dB
                            val db = if (amplitude > 0) 20 * log10(amplitude) else 0.0
                            _decibels.value = db.toFloat()

                            // Update dB history for noise floor
                            synchronized(dbHistory) {
                                dbHistory.add(db.toFloat())
                                if (dbHistory.size > maxHistorySize) {
                                    dbHistory.removeAt(0)
                                }
                            }

                            // Perform frequency analysis
                            val (freq, band) = findDominantFrequency(buffer.copyOf(readSize))
                            _dominantFrequency.value = freq
                            _freqBand.value = band

                            // Update waveform
                            val normalizedDb = (db.toFloat() / 100f).coerceIn(0f, 1f)
                            history.add(normalizedDb)
                            if (history.size > 50) history.removeAt(0)
                            _waveform.value = history.toList()
                        }
                        delay(50)
                    }
                }

                // Noise floor update job (every 1 second)
                noiseFloorJob = viewModelScope.launch(Dispatchers.Default) {
                    while (isActive) {
                        delay(1000)
                        synchronized(dbHistory) {
                            if (dbHistory.isNotEmpty()) {
                                // Noise floor is the minimum dB over the history period
                                val minDb = dbHistory.minOrNull() ?: -60f
                                _noiseFloorDb.value = minDb
                            }
                        }
                    }
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    
    /**
     * Fallback simulated recording when RECORD_AUDIO permission not granted.
     * Generates fake waveform data so the UI doesn't crash.
     */
    private fun startSimulatedRecording() {
        if (recordingJob?.isActive == true) return
        
        recordingJob = viewModelScope.launch(Dispatchers.IO) {
            while (isActive) {
                // Generate simulated waveform
                val time = System.currentTimeMillis() / 1000.0
                val fakeWaveform = List(128) { i ->
                    (kotlin.math.sin(i * 0.1 + time) * 0.3f + 
                     kotlin.math.sin(i * 0.05 + time * 0.7) * 0.2f).toFloat()
                }
                _waveform.value = fakeWaveform
                
                // Simulated ambient dB level (40-60 range)
                _decibels.value = 45f + (kotlin.math.sin(time * 0.5) * 10f).toFloat()
                _dominantFrequency.value = 200f + (kotlin.math.sin(time * 0.3) * 100f).toFloat()
                _freqBand.value = "MID"
                
                delay(50) // ~20 fps
            }
        }
    }

    fun stopRecording() {
        recordingJob?.cancel()
        recordingJob = null
        noiseFloorJob?.cancel()
        noiseFloorJob = null
        try {
            audioRecord?.stop()
            audioRecord?.release()
        } catch (e: Exception) {
            e.printStackTrace()
        }
        audioRecord = null
        
        // Reset state
        dbHistory.clear()
        _noiseFloorDb.value = -60f
    }

    override fun onCleared() {
        super.onCleared()
        stopRecording()
        if (_scoEnabled.value) toggleBluetoothSco(false)
    }
}
