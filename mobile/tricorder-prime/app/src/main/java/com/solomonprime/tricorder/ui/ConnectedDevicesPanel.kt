package com.solomonprime.tricorder.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solomonprime.tricorder.data.ConnectedDevice
import com.solomonprime.tricorder.data.ConnectedDeviceManager
import com.solomonprime.tricorder.data.DeviceCapability
import com.solomonprime.tricorder.ui.theme.LcarsBlack
import com.solomonprime.tricorder.ui.theme.LcarsOrange
import com.solomonprime.tricorder.ui.theme.LcarsPurple
import com.solomonprime.tricorder.ui.theme.LcarsTan
import com.solomonprime.tricorder.ui.theme.LcarsBlue
import com.solomonprime.tricorder.ui.theme.LcarsWhite

private fun deviceTypeIcon(type: String): String = when (type) {
    "HEADSET" -> "♪"
    "A2DP" -> "🎧"
    "WIRED_HEADSET" -> "🎙"
    "OBD2" -> "⛽"
    "FITNESS" -> "♡"
    else -> "⊕"
}

private fun capabilityLabel(cap: DeviceCapability): String = when (cap) {
    DeviceCapability.AUDIO_OUTPUT -> "🔊"
    DeviceCapability.MICROPHONE -> "🎤"
    DeviceCapability.BONE_CONDUCTION -> "BC"
    DeviceCapability.OBD2_READER -> "OBD"
    DeviceCapability.HEART_RATE -> "HR"
    DeviceCapability.AVRCP_CONTROLS -> "CTRL"
    DeviceCapability.HIGH_QUALITY_MIC -> "HQ-MIC"
}

@Composable
fun ConnectedDevicesPanel(deviceManager: ConnectedDeviceManager) {
    val devices by deviceManager.connectedDevices.collectAsState()
    val enhancements by deviceManager.activeEnhancements.collectAsState()
    val hasDevices = devices.isNotEmpty()

    AnimatedVisibility(
        visible = hasDevices,
        enter = expandVertically(),
        exit = shrinkVertically()
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(LcarsBlack)
                .padding(horizontal = 12.dp, vertical = 6.dp)
        ) {
            Text(
                text = "CONNECTED DEVICES",
                color = LcarsOrange,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(bottom = 4.dp)
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                devices.forEach { device ->
                    DeviceChip(device)
                }
            }

            if (enhancements.isNotEmpty()) {
                Spacer(modifier = Modifier.height(4.dp))
                enhancements.take(2).forEach { enhancement ->
                    Text(
                        text = "▸ $enhancement",
                        color = LcarsOrange,
                        fontSize = 10.sp,
                        modifier = Modifier.padding(vertical = 1.dp)
                    )
                }
            }
        }
    }
}

@Composable
private fun DeviceChip(device: ConnectedDevice) {
    Row(
        modifier = Modifier
            .background(LcarsPurple.copy(alpha = 0.3f), RoundedCornerShape(12.dp))
            .padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(4.dp)
    ) {
        Text(
            text = deviceTypeIcon(device.type),
            fontSize = 12.sp,
            color = LcarsWhite
        )
        Text(
            text = device.name.take(12),
            color = LcarsWhite,
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold
        )
        if (device.capabilities.isNotEmpty()) {
            Text(
                text = device.capabilities.take(3).joinToString(" ") { capabilityLabel(it) },
                color = LcarsTan,
                fontSize = 9.sp
            )
        }
    }
}
