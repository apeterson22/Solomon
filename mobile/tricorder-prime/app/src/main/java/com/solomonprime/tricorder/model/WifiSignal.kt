package com.solomonprime.tricorder.model

data class WifiSignal(
    val ssid: String,
    val bssid: String,
    val rssi: Int,
    val frequency: Int,
    val channelWidth: Int? = null
)
