package com.solomonprime.tricorder.model

data class BluetoothSignal(
    val name: String,
    val address: String,
    val rssi: Int = 0,
    val type: Int = 0 // BLE vs Classic
)
