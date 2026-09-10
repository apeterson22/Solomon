package com.solomonprime.tricorder.viewmodel

import android.annotation.SuppressLint
import android.app.Application
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothSocket
import android.content.Context
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.util.UUID

/**
 * OBD2 Vehicle Diagnostics ViewModel
 * Connects to ELM327-compatible Bluetooth OBD2 adapters for real-time vehicle data.
 */
class Obd2ViewModel(application: Application) : AndroidViewModel(application) {

    companion object {
        // Standard SPP UUID for Bluetooth serial communication
        private val SPP_UUID: UUID = UUID.fromString("00001101-0000-1000-8000-00805F9B34FB")
        
        // OBD device name patterns (case-insensitive)
        private val OBD_NAME_PATTERNS = listOf("OBD", "ELM", "OBDII", "OBD2", "VLINK", "SCAN")
        
        // ELM327 initialization commands
        private val ELM_INIT_COMMANDS = listOf(
            "ATZ\r",    // Reset
            "ATE0\r",   // Echo off
            "ATL0\r",   // Linefeeds off
            "ATH0\r",   // Headers off
            "ATSP0\r"   // Auto protocol
        )
        
        // Polling interval for live sensor data (ms)
        private const val POLL_INTERVAL_MS = 1500L
        
        // Command timeout (ms)
        private const val COMMAND_TIMEOUT_MS = 3000L
    }

    // Connection state
    private val _connectionState = MutableStateFlow("DISCONNECTED")
    val connectionState: StateFlow<String> = _connectionState.asStateFlow()

    // Paired OBD devices
    private val _pairedObdDevices = MutableStateFlow<List<String>>(emptyList())
    val pairedObdDevices: StateFlow<List<String>> = _pairedObdDevices.asStateFlow()

    // Live sensor data
    private val _rpm = MutableStateFlow(0)
    val rpm: StateFlow<Int> = _rpm.asStateFlow()

    private val _speed = MutableStateFlow(0)
    val speed: StateFlow<Int> = _speed.asStateFlow()

    private val _coolantTemp = MutableStateFlow(0)
    val coolantTemp: StateFlow<Int> = _coolantTemp.asStateFlow()

    private val _engineLoad = MutableStateFlow(0f)
    val engineLoad: StateFlow<Float> = _engineLoad.asStateFlow()

    private val _fuelLevel = MutableStateFlow(0f)
    val fuelLevel: StateFlow<Float> = _fuelLevel.asStateFlow()

    private val _intakeTemp = MutableStateFlow(0)
    val intakeTemp: StateFlow<Int> = _intakeTemp.asStateFlow()

    private val _throttlePos = MutableStateFlow(0f)
    val throttlePos: StateFlow<Float> = _throttlePos.asStateFlow()

    private val _dtcCount = MutableStateFlow(0)
    val dtcCount: StateFlow<Int> = _dtcCount.asStateFlow()

    private val _dtcCodes = MutableStateFlow<List<String>>(emptyList())
    val dtcCodes: StateFlow<List<String>> = _dtcCodes.asStateFlow()

    // Bluetooth resources
    private var bluetoothAdapter: BluetoothAdapter? = null
    private var bluetoothSocket: BluetoothSocket? = null
    private var inputStream: InputStream? = null
    private var outputStream: OutputStream? = null
    private var pollingJob: Job? = null

    init {
        val bluetoothManager = application.getSystemService(Context.BLUETOOTH_SERVICE) as? BluetoothManager
        bluetoothAdapter = bluetoothManager?.adapter
        refreshPairedDevices()
    }

    /**
     * Refresh the list of paired Bluetooth devices that match OBD adapter patterns.
     */
    @SuppressLint("MissingPermission")
    fun refreshPairedDevices() {
        val adapter = bluetoothAdapter ?: return
        
        try {
            val pairedDevices = adapter.bondedDevices ?: emptySet()
            val obdDevices = pairedDevices
                .filter { device ->
                    val name = device.name?.uppercase() ?: ""
                    OBD_NAME_PATTERNS.any { pattern -> name.contains(pattern) }
                }
                .mapNotNull { it.name }
            
            _pairedObdDevices.value = obdDevices
        } catch (e: SecurityException) {
            _pairedObdDevices.value = emptyList()
        }
    }

    /**
     * Connect to a Bluetooth OBD2 device by name.
     */
    @SuppressLint("MissingPermission")
    fun connectToDevice(deviceName: String) {
        if (_connectionState.value == "CONNECTING" || _connectionState.value == "CONNECTED") {
            return
        }

        viewModelScope.launch(Dispatchers.IO) {
            _connectionState.value = "CONNECTING"

            try {
                val adapter = bluetoothAdapter
                    ?: throw IOException("Bluetooth not available")

                // Find the device by name
                val device: BluetoothDevice = adapter.bondedDevices
                    ?.find { it.name == deviceName }
                    ?: throw IOException("Device not found: $deviceName")

                // Create and connect socket
                val socket = device.createRfcommSocketToServiceRecord(SPP_UUID)
                socket.connect()

                bluetoothSocket = socket
                inputStream = socket.inputStream
                outputStream = socket.outputStream

                // Initialize ELM327
                for (cmd in ELM_INIT_COMMANDS) {
                    sendCommand(cmd)
                    delay(200)
                }

                _connectionState.value = "CONNECTED"

                // Start polling sensor data
                startPolling()

            } catch (e: Exception) {
                _connectionState.value = "ERROR"
                cleanupConnection()
            }
        }
    }

    /**
     * Disconnect from the OBD2 device.
     */
    fun disconnect() {
        pollingJob?.cancel()
        pollingJob = null
        cleanupConnection()
        _connectionState.value = "DISCONNECTED"
        resetSensorData()
    }

    /**
     * Clear diagnostic trouble codes (DTCs).
     */
    fun clearDtc() {
        viewModelScope.launch(Dispatchers.IO) {
            if (_connectionState.value != "CONNECTED") return@launch
            
            try {
                sendCommand("04\r") // Mode 04: Clear DTCs
                delay(500)
                _dtcCount.value = 0
                _dtcCodes.value = emptyList()
            } catch (e: Exception) {
                // Ignore errors during clear
            }
        }
    }

    /**
     * Send a command to the ELM327 and read the response.
     */
    private suspend fun sendCommand(cmd: String): String = withContext(Dispatchers.IO) {
        val output = outputStream ?: return@withContext ""
        val input = inputStream ?: return@withContext ""

        try {
            // Clear any pending data
            while (input.available() > 0) {
                input.read()
            }

            // Send command
            output.write(cmd.toByteArray())
            output.flush()

            // Read response with timeout
            val response = withTimeoutOrNull(COMMAND_TIMEOUT_MS) {
                val buffer = StringBuilder()
                var lastReadTime = System.currentTimeMillis()
                
                while (isActive) {
                    if (input.available() > 0) {
                        val byte = input.read()
                        if (byte == -1) break
                        
                        val char = byte.toChar()
                        if (char == '>') {
                            // Prompt received, response complete
                            break
                        }
                        buffer.append(char)
                        lastReadTime = System.currentTimeMillis()
                    } else {
                        // No data available, check for timeout
                        if (System.currentTimeMillis() - lastReadTime > 500) {
                            break
                        }
                        delay(10)
                    }
                }
                buffer.toString()
            } ?: ""

            // Clean up response
            response
                .replace("\r", "")
                .replace("\n", "")
                .replace(" ", "")
                .trim()

        } catch (e: Exception) {
            ""
        }
    }

    /**
     * Start polling live sensor data.
     */
    private fun startPolling() {
        pollingJob?.cancel()
        pollingJob = viewModelScope.launch(Dispatchers.IO) {
            while (isActive && _connectionState.value == "CONNECTED") {
                try {
                    // Query RPM (PID 010C)
                    parseRpm(sendCommand("010C\r"))

                    // Query Speed (PID 010D)
                    parseSpeed(sendCommand("010D\r"))

                    // Query Coolant Temp (PID 0105)
                    parseCoolantTemp(sendCommand("0105\r"))

                    // Query Engine Load (PID 0104)
                    parseEngineLoad(sendCommand("0104\r"))

                    // Query Fuel Level (PID 012F)
                    parseFuelLevel(sendCommand("012F\r"))

                    // Query Intake Temp (PID 010F)
                    parseIntakeTemp(sendCommand("010F\r"))

                    // Query Throttle Position (PID 0111)
                    parseThrottlePos(sendCommand("0111\r"))

                    // Query DTC count and MIL status (PID 0101) - less frequently
                    parseDtcStatus(sendCommand("0101\r"))

                } catch (e: Exception) {
                    // Connection lost
                    if (_connectionState.value == "CONNECTED") {
                        _connectionState.value = "ERROR"
                        cleanupConnection()
                    }
                    break
                }

                delay(POLL_INTERVAL_MS)
            }
        }
    }

    /**
     * Read DTCs using Mode 03.
     */
    fun readDtcCodes() {
        viewModelScope.launch(Dispatchers.IO) {
            if (_connectionState.value != "CONNECTED") return@launch
            
            try {
                val response = sendCommand("03\r")
                parseDtcCodes(response)
            } catch (e: Exception) {
                // Ignore errors
            }
        }
    }

    // ========== PID PARSING FUNCTIONS ==========

    /**
     * Parse RPM response (PID 010C).
     * Formula: ((A * 256) + B) / 4
     */
    private fun parseRpm(response: String) {
        val data = extractPidData(response, "410C", 4) ?: return
        try {
            val a = data.substring(0, 2).toInt(16)
            val b = data.substring(2, 4).toInt(16)
            _rpm.value = ((a * 256) + b) / 4
        } catch (e: Exception) {
            // Keep previous value on parse error
        }
    }

    /**
     * Parse Speed response (PID 010D).
     * Formula: A (direct value in km/h)
     */
    private fun parseSpeed(response: String) {
        val data = extractPidData(response, "410D", 2) ?: return
        try {
            _speed.value = data.toInt(16)
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse Coolant Temperature response (PID 0105).
     * Formula: A - 40 (degrees Celsius)
     */
    private fun parseCoolantTemp(response: String) {
        val data = extractPidData(response, "4105", 2) ?: return
        try {
            _coolantTemp.value = data.toInt(16) - 40
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse Engine Load response (PID 0104).
     * Formula: A * 100 / 255 (percentage)
     */
    private fun parseEngineLoad(response: String) {
        val data = extractPidData(response, "4104", 2) ?: return
        try {
            _engineLoad.value = data.toInt(16) * 100f / 255f
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse Fuel Level response (PID 012F).
     * Formula: A * 100 / 255 (percentage)
     */
    private fun parseFuelLevel(response: String) {
        val data = extractPidData(response, "412F", 2) ?: return
        try {
            _fuelLevel.value = data.toInt(16) * 100f / 255f
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse Intake Air Temperature response (PID 010F).
     * Formula: A - 40 (degrees Celsius)
     */
    private fun parseIntakeTemp(response: String) {
        val data = extractPidData(response, "410F", 2) ?: return
        try {
            _intakeTemp.value = data.toInt(16) - 40
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse Throttle Position response (PID 0111).
     * Formula: A * 100 / 255 (percentage)
     */
    private fun parseThrottlePos(response: String) {
        val data = extractPidData(response, "4111", 2) ?: return
        try {
            _throttlePos.value = data.toInt(16) * 100f / 255f
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse DTC status response (PID 0101).
     * Byte A bit 7: MIL on/off
     * Byte A bits 0-6: DTC count
     */
    private fun parseDtcStatus(response: String) {
        val data = extractPidData(response, "4101", 8) ?: return
        try {
            val a = data.substring(0, 2).toInt(16)
            val milOn = (a and 0x80) != 0
            val count = a and 0x7F
            _dtcCount.value = if (milOn) count else 0
            
            // Auto-read DTCs if MIL is on
            if (milOn && count > 0 && _dtcCodes.value.isEmpty()) {
                readDtcCodes()
            }
        } catch (e: Exception) {
            // Keep previous value
        }
    }

    /**
     * Parse Mode 03 DTC response.
     * Format: 43 XX YY ZZ AA BB CC ... (each pair of bytes = 1 DTC)
     */
    private fun parseDtcCodes(response: String) {
        if (response.contains("NODATA") || response.contains("ERROR")) {
            _dtcCodes.value = emptyList()
            return
        }

        try {
            // Remove "43" header
            val cleaned = response.replace("43", "").trim()
            if (cleaned.isEmpty()) {
                _dtcCodes.value = emptyList()
                return
            }

            val codes = mutableListOf<String>()
            var i = 0
            while (i + 4 <= cleaned.length) {
                val highByte = cleaned.substring(i, i + 2).toInt(16)
                val lowByte = cleaned.substring(i + 2, i + 4).toInt(16)
                
                if (highByte == 0 && lowByte == 0) {
                    i += 4
                    continue
                }

                // Decode DTC prefix
                val prefix = when ((highByte shr 6) and 0x03) {
                    0 -> "P" // Powertrain
                    1 -> "C" // Chassis
                    2 -> "B" // Body
                    3 -> "U" // Network
                    else -> "P"
                }

                // Build DTC code
                val firstDigit = (highByte shr 4) and 0x03
                val secondDigit = highByte and 0x0F
                val thirdDigit = (lowByte shr 4) and 0x0F
                val fourthDigit = lowByte and 0x0F

                val dtc = "$prefix$firstDigit${secondDigit.toString(16).uppercase()}${thirdDigit.toString(16).uppercase()}${fourthDigit.toString(16).uppercase()}"
                codes.add(dtc)

                i += 4
            }

            _dtcCodes.value = codes
        } catch (e: Exception) {
            _dtcCodes.value = emptyList()
        }
    }

    /**
     * Extract PID data bytes from response.
     * Returns null if response is invalid (NO DATA, ERROR, etc.)
     */
    private fun extractPidData(response: String, expectedHeader: String, expectedLength: Int): String? {
        if (response.contains("NODATA") || response.contains("ERROR") || response.isEmpty()) {
            return null
        }

        val headerIndex = response.indexOf(expectedHeader)
        if (headerIndex == -1) return null

        val dataStart = headerIndex + expectedHeader.length
        if (dataStart + expectedLength > response.length) return null

        return response.substring(dataStart, dataStart + expectedLength)
    }

    /**
     * Clean up Bluetooth connection resources.
     */
    private fun cleanupConnection() {
        try {
            inputStream?.close()
        } catch (e: Exception) { /* ignore */ }
        try {
            outputStream?.close()
        } catch (e: Exception) { /* ignore */ }
        try {
            bluetoothSocket?.close()
        } catch (e: Exception) { /* ignore */ }

        inputStream = null
        outputStream = null
        bluetoothSocket = null
    }

    /**
     * Reset all sensor data to default values.
     */
    private fun resetSensorData() {
        _rpm.value = 0
        _speed.value = 0
        _coolantTemp.value = 0
        _engineLoad.value = 0f
        _fuelLevel.value = 0f
        _intakeTemp.value = 0
        _throttlePos.value = 0f
        _dtcCount.value = 0
        _dtcCodes.value = emptyList()
    }

    override fun onCleared() {
        super.onCleared()
        disconnect()
    }
}
