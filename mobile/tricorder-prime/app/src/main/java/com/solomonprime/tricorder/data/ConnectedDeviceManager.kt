package com.solomonprime.tricorder.data

import android.bluetooth.BluetoothA2dp
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothClass
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothHeadset
import android.bluetooth.BluetoothProfile
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.media.AudioManager
import android.os.Build
import android.view.KeyEvent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Connected device data class representing a Bluetooth or wired device.
 */
data class ConnectedDevice(
    val name: String,
    val address: String,
    val type: String, // "HEADSET", "A2DP", "OBD2", "FITNESS", "WIRED_HEADSET", "UNKNOWN"
    val capabilities: Set<DeviceCapability>
)

/**
 * Device capabilities that can enhance Tricorder functionality.
 */
enum class DeviceCapability {
    AUDIO_OUTPUT,
    MICROPHONE,
    BONE_CONDUCTION,
    OBD2_READER,
    HEART_RATE,
    AVRCP_CONTROLS,
    HIGH_QUALITY_MIC
}

/**
 * Monitors connected Bluetooth and wired audio devices and maps their
 * capabilities to Tricorder enhancements.
 */
class ConnectedDeviceManager(private val context: Context) : SensorEventListener {

    private val _connectedDevices = MutableStateFlow<List<ConnectedDevice>>(emptyList())
    val connectedDevices: StateFlow<List<ConnectedDevice>> = _connectedDevices.asStateFlow()

    private val _activeEnhancements = MutableStateFlow<List<String>>(emptyList())
    val activeEnhancements: StateFlow<List<String>> = _activeEnhancements.asStateFlow()

    private val _preferHfpMic = MutableStateFlow(false)
    val preferHfpMic: StateFlow<Boolean> = _preferHfpMic.asStateFlow()

    private val _avrcpButtonEvents = MutableStateFlow<String?>(null)
    val avrcpButtonEvents: StateFlow<String?> = _avrcpButtonEvents.asStateFlow()

    private val bluetoothAdapter: BluetoothAdapter? = BluetoothAdapter.getDefaultAdapter()
    private var bluetoothHeadset: BluetoothHeadset? = null
    private var bluetoothA2dp: BluetoothA2dp? = null
    private var isStarted = false

    private val deviceReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            when (intent.action) {
                AudioManager.ACTION_HEADSET_PLUG -> {
                    val state = intent.getIntExtra("state", 0)
                    val hasMic = intent.getIntExtra("microphone", 0) == 1
                    handleWiredHeadset(state == 1, hasMic)
                }
                BluetoothHeadset.ACTION_CONNECTION_STATE_CHANGED -> {
                    val state = intent.getIntExtra(BluetoothProfile.EXTRA_STATE, BluetoothProfile.STATE_DISCONNECTED)
                    val device = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    }
                    device?.let { handleBluetoothHeadsetStateChange(it, state) }
                }
                BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED -> {
                    val state = intent.getIntExtra(BluetoothProfile.EXTRA_STATE, BluetoothProfile.STATE_DISCONNECTED)
                    val device = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    }
                    device?.let { handleBluetoothA2dpStateChange(it, state) }
                }
                BluetoothDevice.ACTION_ACL_CONNECTED -> {
                    val device = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    }
                    device?.let { handleDeviceConnected(it) }
                }
                BluetoothDevice.ACTION_ACL_DISCONNECTED -> {
                    val device = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE, BluetoothDevice::class.java)
                    } else {
                        @Suppress("DEPRECATION")
                        intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE)
                    }
                    device?.let { handleDeviceDisconnected(it) }
                }
            }
        }
    }

    private val avrcpReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (Intent.ACTION_MEDIA_BUTTON == intent.action) {
                val keyEvent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT, KeyEvent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(Intent.EXTRA_KEY_EVENT)
                }
                keyEvent?.let { handleAvrcpKeyEvent(it) }
            }
        }
    }

    private val profileListener = object : BluetoothProfile.ServiceListener {
        override fun onServiceConnected(profile: Int, proxy: BluetoothProfile) {
            when (profile) {
                BluetoothProfile.HEADSET -> {
                    bluetoothHeadset = proxy as BluetoothHeadset
                    refreshConnectedDevices()
                }
                BluetoothProfile.A2DP -> {
                    bluetoothA2dp = proxy as BluetoothA2dp
                    refreshConnectedDevices()
                }
            }
        }

        override fun onServiceDisconnected(profile: Int) {
            when (profile) {
                BluetoothProfile.HEADSET -> bluetoothHeadset = null
                BluetoothProfile.A2DP -> bluetoothA2dp = null
            }
        }
    }

    /**
     * Start monitoring connected devices.
     */
    fun start() {
        if (isStarted) return
        isStarted = true

        // Register broadcast receiver for device events
        val filter = IntentFilter().apply {
            addAction(AudioManager.ACTION_HEADSET_PLUG)
            addAction(BluetoothHeadset.ACTION_CONNECTION_STATE_CHANGED)
            addAction(BluetoothA2dp.ACTION_CONNECTION_STATE_CHANGED)
            addAction(BluetoothDevice.ACTION_ACL_CONNECTED)
            addAction(BluetoothDevice.ACTION_ACL_DISCONNECTED)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(deviceReceiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            context.registerReceiver(deviceReceiver, filter)
        }

        // Get Bluetooth profile proxies
        bluetoothAdapter?.getProfileProxy(context, profileListener, BluetoothProfile.HEADSET)
        bluetoothAdapter?.getProfileProxy(context, profileListener, BluetoothProfile.A2DP)

        // Initial scan
        refreshConnectedDevices()
    }

    /**
     * Stop monitoring connected devices.
     */
    fun stop() {
        if (!isStarted) return
        isStarted = false

        try {
            context.unregisterReceiver(deviceReceiver)
        } catch (e: IllegalArgumentException) {
            // Receiver not registered
        }

        try {
            context.unregisterReceiver(avrcpReceiver)
        } catch (e: IllegalArgumentException) {
            // Receiver not registered
        }
    }

    /**
     * Release all resources.
     */
    fun release() {
        stop()
        bluetoothHeadset?.let { bluetoothAdapter?.closeProfileProxy(BluetoothProfile.HEADSET, it) }
        bluetoothA2dp?.let { bluetoothAdapter?.closeProfileProxy(BluetoothProfile.A2DP, it) }
        bluetoothHeadset = null
        bluetoothA2dp = null
    }

    /**
     * Register AVRCP media button listener.
     */
    fun registerAvrcp() {
        val filter = IntentFilter(Intent.ACTION_MEDIA_BUTTON)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.registerReceiver(avrcpReceiver, filter, Context.RECEIVER_EXPORTED)
        } else {
            context.registerReceiver(avrcpReceiver, filter)
        }
    }

    /**
     * Classify device capabilities based on name and Bluetooth class.
     */
    fun classifyDevice(name: String, bluetoothClass: Int): Set<DeviceCapability> {
        val capabilities = mutableSetOf<DeviceCapability>()
        val lowerName = name.lowercase()

        // Bone conduction headsets
        if (lowerName.contains("shokz") || 
            lowerName.contains("openfit") || 
            lowerName.contains("aftershokz")) {
            capabilities.addAll(listOf(
                DeviceCapability.AUDIO_OUTPUT,
                DeviceCapability.MICROPHONE,
                DeviceCapability.BONE_CONDUCTION,
                DeviceCapability.AVRCP_CONTROLS
            ))
            return capabilities
        }

        // Fitness/HR monitors
        if (lowerName.contains("polar") || 
            lowerName.contains("garmin") || 
            lowerName.contains("fitbit") || 
            lowerName.contains("band")) {
            capabilities.add(DeviceCapability.HEART_RATE)
            return capabilities
        }

        // OBD2 adapters
        if (lowerName.contains("obd") || 
            lowerName.contains("elm") || 
            lowerName.contains("obdii") || 
            lowerName.contains("vlink")) {
            capabilities.add(DeviceCapability.OBD2_READER)
            return capabilities
        }

        // Bluetooth class-based detection
        val majorDeviceClass = bluetoothClass and 0x1F00
        val deviceClass = bluetoothClass and 0xFFFC

        when (deviceClass) {
            BluetoothClass.Device.AUDIO_VIDEO_HANDSFREE,
            BluetoothClass.Device.AUDIO_VIDEO_CAR_AUDIO -> {
                capabilities.add(DeviceCapability.MICROPHONE)
                capabilities.add(DeviceCapability.HIGH_QUALITY_MIC)
                capabilities.add(DeviceCapability.AUDIO_OUTPUT)
            }
            BluetoothClass.Device.AUDIO_VIDEO_HEADPHONES -> {
                capabilities.add(DeviceCapability.AUDIO_OUTPUT)
            }
            BluetoothClass.Device.AUDIO_VIDEO_WEARABLE_HEADSET -> {
                capabilities.add(DeviceCapability.AUDIO_OUTPUT)
                capabilities.add(DeviceCapability.MICROPHONE)
                capabilities.add(DeviceCapability.AVRCP_CONTROLS)
            }
        }

        // Major class fallback
        if (capabilities.isEmpty() && majorDeviceClass == BluetoothClass.Device.Major.AUDIO_VIDEO) {
            capabilities.add(DeviceCapability.AUDIO_OUTPUT)
        }

        return capabilities
    }

    private fun handleWiredHeadset(connected: Boolean, hasMic: Boolean) {
        val currentDevices = _connectedDevices.value.toMutableList()
        
        if (connected) {
            val capabilities = mutableSetOf(DeviceCapability.AUDIO_OUTPUT)
            if (hasMic) {
                capabilities.add(DeviceCapability.MICROPHONE)
            }
            val device = ConnectedDevice(
                name = "Wired Headset",
                address = "wired:headset",
                type = "WIRED_HEADSET",
                capabilities = capabilities
            )
            if (currentDevices.none { it.address == device.address }) {
                currentDevices.add(device)
            }
        } else {
            currentDevices.removeAll { it.address == "wired:headset" }
        }
        
        _connectedDevices.value = currentDevices
        updateEnhancements()
    }

    private fun handleBluetoothHeadsetStateChange(device: BluetoothDevice, state: Int) {
        val currentDevices = _connectedDevices.value.toMutableList()
        val address = device.address ?: return

        if (state == BluetoothProfile.STATE_CONNECTED) {
            val existingIndex = currentDevices.indexOfFirst { it.address == address }
            val name = device.name ?: "Unknown Device"
            val btClass = device.bluetoothClass?.deviceClass ?: 0
            val capabilities = classifyDevice(name, btClass).toMutableSet()
            capabilities.add(DeviceCapability.MICROPHONE)
            capabilities.add(DeviceCapability.HIGH_QUALITY_MIC)
            
            val connectedDevice = ConnectedDevice(
                name = name,
                address = address,
                type = "HEADSET",
                capabilities = capabilities
            )
            
            if (existingIndex >= 0) {
                currentDevices[existingIndex] = connectedDevice
            } else {
                currentDevices.add(connectedDevice)
            }
        } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
            currentDevices.removeAll { it.address == address && it.type == "HEADSET" }
        }

        _connectedDevices.value = currentDevices
        updateEnhancements()
    }

    private fun handleBluetoothA2dpStateChange(device: BluetoothDevice, state: Int) {
        val currentDevices = _connectedDevices.value.toMutableList()
        val address = device.address ?: return

        if (state == BluetoothProfile.STATE_CONNECTED) {
            val existingIndex = currentDevices.indexOfFirst { it.address == address }
            val name = device.name ?: "Unknown Device"
            val btClass = device.bluetoothClass?.deviceClass ?: 0
            val capabilities = classifyDevice(name, btClass).toMutableSet()
            capabilities.add(DeviceCapability.AUDIO_OUTPUT)
            
            val connectedDevice = ConnectedDevice(
                name = name,
                address = address,
                type = "A2DP",
                capabilities = capabilities
            )
            
            if (existingIndex >= 0) {
                // Merge capabilities
                val merged = currentDevices[existingIndex].capabilities + capabilities
                currentDevices[existingIndex] = connectedDevice.copy(capabilities = merged)
            } else {
                currentDevices.add(connectedDevice)
            }
        } else if (state == BluetoothProfile.STATE_DISCONNECTED) {
            currentDevices.removeAll { it.address == address && it.type == "A2DP" }
        }

        _connectedDevices.value = currentDevices
        updateEnhancements()
    }

    private fun handleDeviceConnected(device: BluetoothDevice) {
        val currentDevices = _connectedDevices.value.toMutableList()
        val address = device.address ?: return
        
        // Skip if already tracked by specific profile
        if (currentDevices.any { it.address == address }) return

        val name = device.name ?: "Unknown Device"
        val btClass = device.bluetoothClass?.deviceClass ?: 0
        val capabilities = classifyDevice(name, btClass)
        
        val type = when {
            capabilities.contains(DeviceCapability.OBD2_READER) -> "OBD2"
            capabilities.contains(DeviceCapability.HEART_RATE) -> "FITNESS"
            else -> "UNKNOWN"
        }

        val connectedDevice = ConnectedDevice(
            name = name,
            address = address,
            type = type,
            capabilities = capabilities
        )
        
        currentDevices.add(connectedDevice)
        _connectedDevices.value = currentDevices
        updateEnhancements()
    }

    private fun handleDeviceDisconnected(device: BluetoothDevice) {
        val address = device.address ?: return
        val currentDevices = _connectedDevices.value.toMutableList()
        currentDevices.removeAll { it.address == address }
        _connectedDevices.value = currentDevices
        updateEnhancements()
    }

    private fun handleAvrcpKeyEvent(keyEvent: KeyEvent) {
        if (keyEvent.action != KeyEvent.ACTION_DOWN) return
        
        val eventName = when (keyEvent.keyCode) {
            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE -> "PLAY_PAUSE"
            KeyEvent.KEYCODE_MEDIA_PLAY -> "PLAY"
            KeyEvent.KEYCODE_MEDIA_PAUSE -> "PAUSE"
            KeyEvent.KEYCODE_MEDIA_NEXT -> "NEXT"
            KeyEvent.KEYCODE_MEDIA_PREVIOUS -> "PREVIOUS"
            KeyEvent.KEYCODE_MEDIA_STOP -> "STOP"
            else -> null
        }
        
        eventName?.let { _avrcpButtonEvents.value = it }
    }

    private fun refreshConnectedDevices() {
        // Check for BLUETOOTH_CONNECT permission on Android 12+
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            if (context.checkSelfPermission(android.Manifest.permission.BLUETOOTH_CONNECT)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                // Permission not granted yet, skip refresh
                return
            }
        }

        val devices = mutableListOf<ConnectedDevice>()

        // Get connected headset devices
        bluetoothHeadset?.connectedDevices?.forEach { device ->
            val name = device.name ?: "Unknown Device"
            val address = device.address ?: return@forEach
            val btClass = device.bluetoothClass?.deviceClass ?: 0
            val capabilities = classifyDevice(name, btClass).toMutableSet()
            capabilities.add(DeviceCapability.MICROPHONE)
            capabilities.add(DeviceCapability.HIGH_QUALITY_MIC)
            
            devices.add(ConnectedDevice(
                name = name,
                address = address,
                type = "HEADSET",
                capabilities = capabilities
            ))
        }

        // Get connected A2DP devices
        bluetoothA2dp?.connectedDevices?.forEach { device ->
            val name = device.name ?: "Unknown Device"
            val address = device.address ?: return@forEach
            val btClass = device.bluetoothClass?.deviceClass ?: 0
            val capabilities = classifyDevice(name, btClass).toMutableSet()
            capabilities.add(DeviceCapability.AUDIO_OUTPUT)
            
            val existingIndex = devices.indexOfFirst { it.address == address }
            if (existingIndex >= 0) {
                // Merge capabilities
                val merged = devices[existingIndex].capabilities + capabilities
                devices[existingIndex] = devices[existingIndex].copy(capabilities = merged)
            } else {
                devices.add(ConnectedDevice(
                    name = name,
                    address = address,
                    type = "A2DP",
                    capabilities = capabilities
                ))
            }
        }

        _connectedDevices.value = devices
        updateEnhancements()
    }

    private fun updateEnhancements() {
        val enhancements = mutableListOf<String>()
        val devices = _connectedDevices.value
        var hasHfpMic = false

        for (device in devices) {
            val caps = device.capabilities
            
            if (caps.contains(DeviceCapability.BONE_CONDUCTION)) {
                enhancements.add("Bone-conduction mic active for PIPE detection")
                enhancements.add("Voice alerts routing to headset")
                hasHfpMic = true
            } else if (caps.contains(DeviceCapability.HIGH_QUALITY_MIC)) {
                enhancements.add("HFP mic available for acoustic analysis")
                hasHfpMic = true
            }
            
            if (caps.contains(DeviceCapability.OBD2_READER)) {
                enhancements.add("OBD2 adapter ready — open OBD tab")
            }
            
            if (caps.contains(DeviceCapability.HEART_RATE)) {
                enhancements.add("Heart rate monitor active — BIO tab using live data")
            }
            
            if (caps.contains(DeviceCapability.AVRCP_CONTROLS)) {
                enhancements.add("Headset buttons: PLAY/PAUSE to tag location")
            }
        }

        _activeEnhancements.value = enhancements.distinct()
        _preferHfpMic.value = hasHfpMic
    }

    // SensorEventListener implementation (for future sensor fusion)
    override fun onSensorChanged(event: SensorEvent?) {
        // Reserved for future sensor integration
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Reserved for future sensor integration
    }
}
