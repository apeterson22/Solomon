package com.solomonprime.tricorder.model

data class AlertThreshold(
    val id: String,
    val label: String,
    val field: String,
    val minValue: Float?,
    val maxValue: Float?,
    val enabled: Boolean = true
) {
    companion object {
        fun defaults(): List<AlertThreshold> = listOf(
            AlertThreshold(
                id = "rad_cpm_high",
                label = "Radiation CPM High",
                field = "radCpm",
                minValue = null,
                maxValue = 60f
            ),
            AlertThreshold(
                id = "bio_hr_high",
                label = "Heart Rate High",
                field = "bioHeartRate",
                minValue = null,
                maxValue = 100f
            ),
            AlertThreshold(
                id = "bio_hr_low",
                label = "Heart Rate Low",
                field = "bioHeartRate",
                minValue = 50f,
                maxValue = null
            ),
            AlertThreshold(
                id = "bio_spo2_low",
                label = "Blood Oxygen Low",
                field = "bioBloodOxygen",
                minValue = 95f,
                maxValue = null
            ),
            AlertThreshold(
                id = "acoustic_db_high",
                label = "Decibels High",
                field = "acousticDecibels",
                minValue = null,
                maxValue = 85f
            )
        )
    }
}
