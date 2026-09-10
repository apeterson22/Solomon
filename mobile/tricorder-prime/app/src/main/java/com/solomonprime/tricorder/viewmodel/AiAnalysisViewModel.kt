package com.solomonprime.tricorder.viewmodel

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * AI Analysis ViewModel — Rule-based sensor analyst engine.
 *
 * Monitors all sensor ViewModels every 10 seconds and generates
 * natural-language insights with severity classification.
 */
class AiAnalysisViewModel(application: Application) : AndroidViewModel(application) {

    data class AiInsight(
        val title: String,
        val body: String,
        val severity: String, // "info", "warning", "alert"
        val timestamp: Long,
        val sensorSource: String
    )

    private val _insights = MutableStateFlow<List<AiInsight>>(emptyList())
    val insights: StateFlow<List<AiInsight>> = _insights.asStateFlow()

    private val _currentSummary = MutableStateFlow("MONITORING... All readings nominal.")
    val currentSummary: StateFlow<String> = _currentSummary.asStateFlow()

    // --- Sensor references (set externally after VM creation) ---
    var radCpm: (() -> Float)? = null
    var acoDecibels: (() -> Float)? = null
    var acoFreqBand: (() -> String)? = null
    var envPressure: (() -> Float?)? = null
    var geoHeading: (() -> Float?)? = null
    var bioHeartRate: (() -> Int)? = null
    var pipeLeakScore: (() -> Float)? = null

    // Pressure history for drop detection
    private val pressureHistory = mutableListOf<Pair<Long, Float>>() // (timestamp, hPa)

    // Heading history for variance detection
    private val headingHistory = mutableListOf<Pair<Long, Float>>() // (timestamp, degrees)

    private var analysisRunning = false

    fun startAnalysis() {
        if (analysisRunning) return
        analysisRunning = true
        viewModelScope.launch {
            while (analysisRunning) {
                analyzeAllSensors()
                delay(10_000L)
            }
        }
    }

    fun stopAnalysis() {
        analysisRunning = false
    }

    fun clearInsights() {
        _insights.value = emptyList()
        _currentSummary.value = "MONITORING... All readings nominal."
    }

    private fun analyzeAllSensors() {
        val now = System.currentTimeMillis()
        val newInsights = mutableListOf<AiInsight>()

        // --- RAD: CPM > 30 ---
        radCpm?.invoke()?.let { cpm ->
            if (cpm > 30f) {
                newInsights += AiInsight(
                    title = "Elevated Radiation",
                    body = "CPM at ${cpm.toInt()}. Elevated background radiation detected. Possible source: medical equipment, granite, or cosmic ray burst. Stay alert.",
                    severity = if (cpm > 100f) "alert" else "warning",
                    timestamp = now,
                    sensorSource = "RAD"
                )
            }
        }

        // --- ACO: dB > 80 ---
        acoDecibels?.invoke()?.let { db ->
            if (db > 80f) {
                val band = acoFreqBand?.invoke() ?: "unknown"
                newInsights += AiInsight(
                    title = "High Acoustic Energy",
                    body = "Sound level at ${db.toInt()} dB in $band range. Possible source: machinery, HVAC, or structural vibration.",
                    severity = if (db > 100f) "alert" else "warning",
                    timestamp = now,
                    sensorSource = "ACO"
                )
            }
        }

        // --- ENV: Pressure drop > 5 hPa in 10 min ---
        envPressure?.invoke()?.let { pressure ->
            pressureHistory.add(now to pressure)
            // Trim entries older than 10 minutes
            pressureHistory.removeAll { (ts, _) -> now - ts > 600_000L }
            if (pressureHistory.size >= 2) {
                val oldest = pressureHistory.first().second
                val drop = oldest - pressure
                if (drop > 5f) {
                    newInsights += AiInsight(
                        title = "Rapid Pressure Drop",
                        body = "Barometric pressure dropped ${String.format("%.1f", drop)} hPa in ${((now - pressureHistory.first().first) / 60_000)}min. Possible approaching storm system.",
                        severity = "warning",
                        timestamp = now,
                        sensorSource = "ENV"
                    )
                }
            }
        }

        // --- GEO: Magnetic heading variance > 15° in 5s ---
        geoHeading?.invoke()?.let { heading ->
            headingHistory.add(now to heading)
            headingHistory.removeAll { (ts, _) -> now - ts > 5_000L }
            if (headingHistory.size >= 2) {
                val min = headingHistory.minOf { it.second }
                val max = headingHistory.maxOf { it.second }
                val variance = max - min
                if (variance > 15f) {
                    newInsights += AiInsight(
                        title = "Magnetic Interference",
                        body = "Heading variance of ${String.format("%.1f", variance)}° in 5s. Nearby motors, electrical panels, or buried cables possible.",
                        severity = "warning",
                        timestamp = now,
                        sensorSource = "GEO"
                    )
                }
            }
        }

        // --- BIO: Heart rate > 100 ---
        bioHeartRate?.invoke()?.let { hr ->
            if (hr > 100) {
                newInsights += AiInsight(
                    title = "Elevated Heart Rate",
                    body = "Heart rate at $hr BPM. Elevated heart rate detected. Consider reducing physical activity.",
                    severity = if (hr > 150) "alert" else "warning",
                    timestamp = now,
                    sensorSource = "BIO"
                )
            }
        }

        // --- PIPE: leakScore > 0.5 ---
        pipeLeakScore?.invoke()?.let { score ->
            if (score > 0.5f) {
                newInsights += AiInsight(
                    title = "Possible Leak Detected",
                    body = "Leak probability at ${(score * 100).toInt()}%. Acoustic/magnetic signature consistent with water flow or leak detected.",
                    severity = if (score > 0.8f) "alert" else "warning",
                    timestamp = now,
                    sensorSource = "PIPE"
                )
            }
        }

        // Merge new insights, cap at 10
        if (newInsights.isNotEmpty()) {
            _insights.value = (newInsights + _insights.value).take(10)
        }

        // Update summary
        updateSummary()
    }

    private fun updateSummary() {
        val current = _insights.value
        if (current.isEmpty()) {
            _currentSummary.value = "MONITORING... All readings nominal."
            return
        }

        val alertCount = current.count { it.severity == "alert" }
        val warningCount = current.count { it.severity == "warning" }
        val sources = current.map { it.sensorSource }.distinct().joinToString(", ")

        _currentSummary.value = when {
            alertCount > 0 -> "⚠ $alertCount ALERT${if (alertCount > 1) "S" else ""}, $warningCount warning${if (warningCount != 1) "s" else ""} — Active sensors: $sources"
            warningCount > 0 -> "$warningCount warning${if (warningCount != 1) "s" else ""} detected — Sensors: $sources"
            else -> "MONITORING... All readings nominal."
        }
    }

    
    /**
     * Process user natural language query about sensor data.
     * Uses rule-based responses for now; can be extended with LLM integration.
     */
    fun processUserQuery(query: String) {
        val now = System.currentTimeMillis()
        val lowerQuery = query.lowercase()
        
        val response = when {
            lowerQuery.contains("radiation") || lowerQuery.contains("rad") -> {
                val cpm = radCpm?.invoke() ?: 0f
                AiInsight(
                    title = "Radiation Query Response",
                    body = "Current radiation level: ${cpm.toInt()} CPM. " +
                        if (cpm < 20) "This is normal background radiation." 
                        else if (cpm < 50) "Slightly elevated. Monitor the situation."
                        else "Elevated levels detected. Consider moving to a different area.",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            lowerQuery.contains("heart") || lowerQuery.contains("bio") || lowerQuery.contains("health") -> {
                val hr = bioHeartRate?.invoke() ?: 0
                AiInsight(
                    title = "Biometric Query Response",
                    body = "Current heart rate: $hr BPM. " +
                        if (hr < 60) "Below normal resting rate."
                        else if (hr < 100) "Normal resting heart rate."
                        else "Elevated heart rate. Consider resting.",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            lowerQuery.contains("sound") || lowerQuery.contains("noise") || lowerQuery.contains("aco") -> {
                val db = acoDecibels?.invoke() ?: 0f
                val band = acoFreqBand?.invoke() ?: "unknown"
                AiInsight(
                    title = "Acoustic Query Response",
                    body = "Current sound level: ${db.toInt()} dB in $band frequency range. " +
                        if (db < 50) "Quiet environment."
                        else if (db < 70) "Normal conversation level."
                        else if (db < 85) "Loud environment."
                        else "Potentially harmful noise levels. Consider ear protection.",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            lowerQuery.contains("weather") || lowerQuery.contains("pressure") || lowerQuery.contains("env") -> {
                val pressure = envPressure?.invoke()
                AiInsight(
                    title = "Environmental Query Response",
                    body = if (pressure != null) 
                        "Current barometric pressure: ${String.format("%.1f", pressure)} hPa. " +
                        if (pressure > 1020) "High pressure - expect clear weather."
                        else if (pressure > 1000) "Normal pressure."
                        else "Low pressure - possible storm approaching."
                    else "Pressure sensor not available.",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            lowerQuery.contains("location") || lowerQuery.contains("gps") || lowerQuery.contains("heading") -> {
                val heading = geoHeading?.invoke()
                val direction = when {
                    heading == null -> "unknown"
                    heading < 22.5 || heading >= 337.5 -> "North"
                    heading < 67.5 -> "Northeast"
                    heading < 112.5 -> "East"
                    heading < 157.5 -> "Southeast"
                    heading < 202.5 -> "South"
                    heading < 247.5 -> "Southwest"
                    heading < 292.5 -> "West"
                    else -> "Northwest"
                }
                AiInsight(
                    title = "Geophysical Query Response",
                    body = "Current heading: ${heading?.toInt() ?: 0}° ($direction). " +
                        "Compass is calibrated and functioning.",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            lowerQuery.contains("leak") || lowerQuery.contains("pipe") || lowerQuery.contains("water") -> {
                val score = pipeLeakScore?.invoke() ?: 0f
                AiInsight(
                    title = "Pipe Leak Query Response",
                    body = "Leak probability: ${(score * 100).toInt()}%. " +
                        if (score < 0.2) "No leak indicators detected."
                        else if (score < 0.5) "Minor acoustic anomaly. Monitor area."
                        else "Possible leak detected. Investigate further.",
                    severity = if (score > 0.5) "warning" else "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            lowerQuery.contains("status") || lowerQuery.contains("summary") || lowerQuery.contains("all") -> {
                AiInsight(
                    title = "System Status Summary",
                    body = "RAD: ${radCpm?.invoke()?.toInt() ?: 0} CPM | " +
                        "ACO: ${acoDecibels?.invoke()?.toInt() ?: 0} dB | " +
                        "BIO: ${bioHeartRate?.invoke() ?: 0} BPM | " +
                        "LEAK: ${((pipeLeakScore?.invoke() ?: 0f) * 100).toInt()}%",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
            else -> {
                AiInsight(
                    title = "Query Received",
                    body = "I can answer questions about: radiation, heart rate/biometrics, " +
                        "sound levels, weather/pressure, GPS/heading, pipe leaks, or system status. " +
                        "Try asking about one of these topics.",
                    severity = "info",
                    timestamp = now,
                    sensorSource = "AI"
                )
            }
        }
        
        _insights.value = listOf(response) + _insights.value.take(9)
        updateSummary()
    }
}
