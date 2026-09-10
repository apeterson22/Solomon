package com.solomonprime.tricorder.data

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.solomonprime.tricorder.model.AlertThreshold
import com.solomonprime.tricorder.model.ScanSession
import org.json.JSONArray
import org.json.JSONObject

/**
 * Manages alert thresholds: persistence via SharedPreferences,
 * threshold evaluation against ScanSession data, and Android notifications.
 */
class AlertManager(private val context: Context) {

    private val prefs = context.getSharedPreferences("tricorder_alerts", Context.MODE_PRIVATE)
    private val notificationManager = NotificationManagerCompat.from(context)

    init {
        createNotificationChannel()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Tricorder Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Alerts when sensor readings exceed configured thresholds"
            }
            val mgr = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            mgr.createNotificationChannel(channel)
        }
    }

    // ── Persistence ──────────────────────────────────────────────

    fun saveThresholds(thresholds: List<AlertThreshold>) {
        val json = JSONArray().apply {
            thresholds.forEach { t ->
                put(JSONObject().apply {
                    put("id", t.id)
                    put("label", t.label)
                    put("field", t.field)
                    put("minValue", t.minValue?.toDouble() ?: JSONObject.NULL)
                    put("maxValue", t.maxValue?.toDouble() ?: JSONObject.NULL)
                    put("enabled", t.enabled)
                })
            }
        }
        prefs.edit().putString(KEY_THRESHOLDS, json.toString()).apply()
    }

    fun loadThresholds(): List<AlertThreshold> {
        val raw = prefs.getString(KEY_THRESHOLDS, null) ?: return AlertThreshold.defaults()
        return try {
            val arr = JSONArray(raw)
            (0 until arr.length()).map { i ->
                val obj = arr.getJSONObject(i)
                AlertThreshold(
                    id = obj.getString("id"),
                    label = obj.getString("label"),
                    field = obj.getString("field"),
                    minValue = if (obj.isNull("minValue")) null else obj.getDouble("minValue").toFloat(),
                    maxValue = if (obj.isNull("maxValue")) null else obj.getDouble("maxValue").toFloat(),
                    enabled = obj.optBoolean("enabled", true)
                )
            }
        } catch (_: Exception) {
            AlertThreshold.defaults()
        }
    }

    // ── Threshold evaluation ─────────────────────────────────────

    /**
     * Returns the list of enabled thresholds that the given [session] violates.
     * - If [maxValue] is set, the alert triggers when the reading **exceeds** it.
     * - If [minValue] is set, the alert triggers when the reading **falls below** it.
     */
    fun checkThresholds(session: ScanSession): List<AlertThreshold> {
        val thresholds = loadThresholds().filter { it.enabled }
        return thresholds.filter { t ->
            val value = fieldValue(session, t.field) ?: return@filter false
            val aboveMax = t.maxValue != null && value > t.maxValue
            val belowMin = t.minValue != null && value < t.minValue
            aboveMax || belowMin
        }
    }

    /** Maps a threshold field key to the corresponding ScanSession value. */
    private fun fieldValue(session: ScanSession, field: String): Float? = when (field) {
        "radCpm" -> session.radCpm.toFloat()
        "bioHeartRate" -> session.bioHeartRate.toFloat()
        "bioBloodOxygen" -> session.bioBloodOxygen
        "acousticDecibels" -> session.acousticDecibels
        "envPressure" -> session.envPressure
        "envLight" -> session.envLight
        "radMicroSievert" -> session.radMicroSievert
        "bioSkinTemp" -> session.bioSkinTemp
        "bioStressIndex" -> session.bioStressIndex
        else -> null
    }

    // ── Notifications ────────────────────────────────────────────

    /**
     * Posts an Android notification for each triggered threshold.
     * Requires POST_NOTIFICATIONS permission on Android 13+.
     */
    fun notifyTriggered(triggered: List<AlertThreshold>) {
        triggered.forEach { alert ->
            val notification = NotificationCompat.Builder(context, CHANNEL_ID)
                .setSmallIcon(android.R.drawable.ic_dialog_alert)
                .setContentTitle("Tricorder Alert")
                .setContentText("${alert.label} threshold exceeded")
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
                .build()

            try {
                notificationManager.notify(alert.id.hashCode(), notification)
            } catch (_: SecurityException) {
                // POST_NOTIFICATIONS not granted — silently skip
            }
        }
    }

    companion object {
        private const val CHANNEL_ID = "TRICORDER_ALERTS"
        private const val KEY_THRESHOLDS = "thresholds_json"
    }
}
