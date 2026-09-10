package com.solomonprime.tricorder.model

/**
 * Represents a single logged scan snapshot from all Tricorder sensors.
 */
data class ScanSession(
    val timestamp: Long,
    // Environmental
    val envPressure: Float,
    val envLight: Float,
    // Geolocation
    val geoLatitude: Double,
    val geoLongitude: Double,
    // Electromagnetic
    val emMagneticX: Float,
    val emMagneticY: Float,
    val emMagneticZ: Float,
    // Biometric
    val bioHeartRate: Int,
    val bioBloodOxygen: Float,
    val bioSkinTemp: Float,
    val bioStressIndex: Float,
    // Radiation
    val radCpm: Int,
    val radMicroSievert: Float,
    val radAlertLevel: String,
    // Acoustic
    val acousticDecibels: Float
) {
    /**
     * Converts this session to a CSV row string.
     */
    fun toCsvRow(): String = listOf(
        timestamp,
        envPressure,
        envLight,
        geoLatitude,
        geoLongitude,
        emMagneticX,
        emMagneticY,
        emMagneticZ,
        bioHeartRate,
        bioBloodOxygen,
        bioSkinTemp,
        bioStressIndex,
        radCpm,
        radMicroSievert,
        "\"${radAlertLevel.replace("\"", "\"\"")}\"",
        acousticDecibels
    ).joinToString(",")

    companion object {
        /**
         * Returns the CSV header row.
         */
        fun csvHeader(): String = listOf(
            "timestamp",
            "envPressure",
            "envLight",
            "geoLatitude",
            "geoLongitude",
            "emMagneticX",
            "emMagneticY",
            "emMagneticZ",
            "bioHeartRate",
            "bioBloodOxygen",
            "bioSkinTemp",
            "bioStressIndex",
            "radCpm",
            "radMicroSievert",
            "radAlertLevel",
            "acousticDecibels"
        ).joinToString(",")

        /**
         * Parses a CSV row back into a ScanSession.
         */
        fun fromCsvRow(row: String): ScanSession? {
            return try {
                val parts = parseCsvRow(row)
                if (parts.size < 16) return null
                ScanSession(
                    timestamp = parts[0].toLong(),
                    envPressure = parts[1].toFloat(),
                    envLight = parts[2].toFloat(),
                    geoLatitude = parts[3].toDouble(),
                    geoLongitude = parts[4].toDouble(),
                    emMagneticX = parts[5].toFloat(),
                    emMagneticY = parts[6].toFloat(),
                    emMagneticZ = parts[7].toFloat(),
                    bioHeartRate = parts[8].toInt(),
                    bioBloodOxygen = parts[9].toFloat(),
                    bioSkinTemp = parts[10].toFloat(),
                    bioStressIndex = parts[11].toFloat(),
                    radCpm = parts[12].toInt(),
                    radMicroSievert = parts[13].toFloat(),
                    radAlertLevel = parts[14].trim('"'),
                    acousticDecibels = parts[15].toFloat()
                )
            } catch (e: Exception) {
                null
            }
        }

        /**
         * Simple CSV parser that handles quoted strings.
         */
        private fun parseCsvRow(row: String): List<String> {
            val result = mutableListOf<String>()
            var current = StringBuilder()
            var inQuotes = false
            var i = 0
            while (i < row.length) {
                val c = row[i]
                when {
                    c == '"' && !inQuotes -> inQuotes = true
                    c == '"' && inQuotes -> {
                        if (i + 1 < row.length && row[i + 1] == '"') {
                            current.append('"')
                            i++
                        } else {
                            inQuotes = false
                        }
                    }
                    c == ',' && !inQuotes -> {
                        result.add(current.toString())
                        current = StringBuilder()
                    }
                    else -> current.append(c)
                }
                i++
            }
            result.add(current.toString())
            return result
        }
    }
}
