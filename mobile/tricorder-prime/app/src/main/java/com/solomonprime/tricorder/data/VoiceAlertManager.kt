package com.solomonprime.tricorder.data

import android.content.Context
import android.media.RingtoneManager
import android.speech.tts.TextToSpeech
import java.util.Locale

/**
 * VoiceAlertManager - Manages voice alerts using Android TextToSpeech API.
 * Provides clear, authoritative voice feedback for sensor alerts.
 */
class VoiceAlertManager(private val context: Context) {

    private var tts: TextToSpeech? = null
    private var isInitialized = false
    private var lastAlertTime = 0L
    private var lastAlertKey = ""
    private var isCurrentlyAlerting = false

    companion object {
        private const val ALERT_THROTTLE_MS = 10_000L // 10 seconds
    }

    init {
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.let { engine ->
                    engine.language = Locale.US
                    engine.setSpeechRate(0.9f)   // Slightly slower for clarity
                    engine.setPitch(0.85f)       // Authoritative tone
                    isInitialized = true
                }
            }
        }
    }

    /**
     * Speaks text immediately, interrupting any current speech.
     */
    fun speak(text: String) {
        if (!isInitialized || tts == null) return
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "speak_${System.currentTimeMillis()}")
    }

    /**
     * Speaks an alert with standard formatting.
     * Format: "Alert. [sensor] reading [level]. Value: [value]"
     * 
     * Throttled: will not repeat the same alert within 10 seconds.
     * For ALERT level, also plays a notification sound.
     * 
     * @param level The alert level (e.g., "elevated", "critical")
     * @param sensor The sensor name (e.g., "radiation", "heart rate")
     * @param value The current value with units (e.g., "45 CPM", "110 BPM")
     */
    fun speakAlert(level: String, sensor: String, value: String) {
        val now = System.currentTimeMillis()
        val alertKey = "$sensor:$level"

        // Throttle: don't repeat same alert within 10 seconds
        if (alertKey == lastAlertKey && (now - lastAlertTime) < ALERT_THROTTLE_MS) {
            return
        }

        lastAlertTime = now
        lastAlertKey = alertKey
        isCurrentlyAlerting = true

        // Play notification sound for critical alerts
        if (level.lowercase() == "alert" || level.lowercase() == "critical") {
            playAlertSound()
        }

        val message = "Alert. $sensor reading $level. Value: $value"
        tts?.speak(message, TextToSpeech.QUEUE_FLUSH, null, "alert_$now")

        // Reset alerting flag after estimated speech time
        android.os.Handler(context.mainLooper).postDelayed({
            isCurrentlyAlerting = false
        }, 3000L)
    }

    /**
     * Speaks a status message with lower priority.
     * Only speaks if not currently in the middle of an alert.
     */
    fun speakStatus(text: String) {
        if (!isInitialized || tts == null) return
        if (isCurrentlyAlerting) return

        tts?.speak(text, TextToSpeech.QUEUE_ADD, null, "status_${System.currentTimeMillis()}")
    }

    /**
     * Plays the system notification sound for alert emphasis.
     */
    private fun playAlertSound() {
        try {
            val uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)
            val ringtone = RingtoneManager.getRingtone(context, uri)
            ringtone?.play()
        } catch (_: Exception) {
            // Silent fail - TTS will still work
        }
    }

    /**
     * Shuts down the TTS engine. Call in onDestroy.
     */
    fun shutdown() {
        tts?.stop()
        tts?.shutdown()
        tts = null
        isInitialized = false
    }
}
