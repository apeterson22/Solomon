package com.solomonprime.tricorder.model

data class WifiMapPoint(
    val ssid: String,
    val bssid: String,
    val rssi: Int,
    val latitude: Double,
    val longitude: Double,
    val timestamp: Long,
    val relativeX: Float = 0f,
    val relativeY: Float = 0f
)
