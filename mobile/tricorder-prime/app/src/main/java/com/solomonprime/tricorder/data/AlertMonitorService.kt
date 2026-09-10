package com.solomonprime.tricorder.data

import com.solomonprime.tricorder.viewmodel.BioScannerViewModel
import com.solomonprime.tricorder.viewmodel.RadiationViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * AlertMonitorService - Coroutine-based monitor that periodically checks
 * sensor values and triggers voice alerts when thresholds are exceeded.
 * 
 * This is NOT an Android Service - it's a lightweight monitoring class
 * that runs within a provided CoroutineScope.
 */
class AlertMonitorService(
    private val radViewModel: RadiationViewModel,
    private val bioViewModel: BioScannerViewModel,
    private val voiceAlert: VoiceAlertManager
) {
    private var monitorJob: Job? = null

    companion object {
        private const val CHECK_INTERVAL_MS = 2000L

        // Radiation thresholds (CPM)
        private const val RAD_ELEVATED_CPM = 50f
        private const val RAD_ALERT_CPM = 200f

        // Heart rate thresholds (BPM)
        private const val HR_HIGH_BPM = 100
        private const val HR_LOW_BPM = 50

        // Blood oxygen threshold (%)
        private const val SPO2_LOW = 95f
    }

    /**
     * Starts the monitoring loop in the provided scope.
     * Checks sensor values every 2 seconds and triggers voice alerts as needed.
     */
    fun start(scope: CoroutineScope) {
        if (monitorJob?.isActive == true) return

        monitorJob = scope.launch {
            while (isActive) {
                checkRadiation()
                checkBioSigns()
                delay(CHECK_INTERVAL_MS)
            }
        }
    }

    /**
     * Stops the monitoring loop.
     */
    fun stop() {
        monitorJob?.cancel()
        monitorJob = null
    }

    private fun checkRadiation() {
        val alertLevel = radViewModel.alertLevel.value
        val cpm = radViewModel.cpm.value

        when (alertLevel) {
            RadiationViewModel.AlertLevel.ALERT -> {
                voiceAlert.speakAlert("critical", "radiation", "${cpm.toInt()} CPM")
            }
            RadiationViewModel.AlertLevel.ELEVATED -> {
                voiceAlert.speakAlert("elevated", "radiation", "${cpm.toInt()} CPM")
            }
            RadiationViewModel.AlertLevel.NOMINAL -> {
                // No alert needed
            }
        }
    }

    private fun checkBioSigns() {
        // Heart rate checks
        val heartRate = bioViewModel.heartRate.value
        when {
            heartRate > HR_HIGH_BPM -> {
                voiceAlert.speakAlert("elevated", "heart rate", "$heartRate BPM")
            }
            heartRate in 1 until HR_LOW_BPM -> {
                voiceAlert.speakAlert("low", "heart rate", "$heartRate BPM")
            }
        }

        // Blood oxygen check
        val spo2 = bioViewModel.bloodOxygen.value
        if (spo2 > 0f && spo2 < SPO2_LOW) {
            voiceAlert.speakAlert("low", "blood oxygen", "${String.format("%.1f", spo2)}%")
        }
    }
}
