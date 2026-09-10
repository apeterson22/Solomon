package com.solomonprime.tricorder.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.model.BluetoothSignal
import com.solomonprime.tricorder.model.WifiSignal
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.EmSpectrumViewModel
import kotlin.math.abs

@Composable
fun EmSpectrumScannerScreen(
    modifier: Modifier = Modifier,
    viewModel: EmSpectrumViewModel = viewModel()
) {
    val wifiSignals by viewModel.wifiSignals.collectAsState()
    val bluetoothSignals by viewModel.bluetoothSignals.collectAsState()

    Column(
        modifier = modifier
            .fillMaxSize()
            .background(LcarsBlack)
            .padding(12.dp)
    ) {
        LcarsSectionHeader(title = "EM Spectrum Analysis", color = LcarsPink)
        
        LcarsScanningIndicator(isActive = true, color = LcarsPink)
        
        Spacer(modifier = Modifier.height(8.dp))
        
        // Summary cards
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceEvenly
        ) {
            EmSummaryCard(
                label = "Wi-Fi",
                count = wifiSignals.size,
                color = LcarsBlue
            )
            EmSummaryCard(
                label = "Bluetooth",
                count = bluetoothSignals.size,
                color = LcarsPurple
            )
        }
        
        Spacer(modifier = Modifier.height(16.dp))
        
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f)
        ) {
            // Wi-Fi column
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(end = 4.dp)
            ) {
                LcarsSectionHeader(title = "Wi-Fi Networks", color = LcarsBlue)
                
                LazyColumn(
                    modifier = Modifier.fillMaxSize()
                ) {
                    items(wifiSignals) { signal ->
                        WifiSignalCard(signal)
                        Spacer(modifier = Modifier.height(4.dp))
                    }
                    
                    if (wifiSignals.isEmpty()) {
                        item {
                            Text(
                                text = "Scanning...",
                                color = LcarsWhite.copy(alpha = 0.5f),
                                fontSize = 14.sp
                            )
                        }
                    }
                }
            }
            
            // Bluetooth column
            Column(
                modifier = Modifier
                    .weight(1f)
                    .padding(start = 4.dp)
            ) {
                LcarsSectionHeader(title = "BT Devices", color = LcarsPurple)
                
                LazyColumn(
                    modifier = Modifier.fillMaxSize()
                ) {
                    items(bluetoothSignals) { signal ->
                        BluetoothSignalCard(signal)
                        Spacer(modifier = Modifier.height(4.dp))
                    }
                    
                    if (bluetoothSignals.isEmpty()) {
                        item {
                            Text(
                                text = "Scanning...",
                                color = LcarsWhite.copy(alpha = 0.5f),
                                fontSize = 14.sp
                            )
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun EmSummaryCard(
    label: String,
    count: Int,
    color: androidx.compose.ui.graphics.Color
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.2f))
            .padding(horizontal = 24.dp, vertical = 12.dp)
    ) {
        Text(
            text = count.toString(),
            color = LcarsWhite,
            fontSize = 32.sp,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = label.uppercase(),
            color = color,
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
private fun WifiSignalCard(signal: WifiSignal) {
    val signalStrength = getSignalStrength(signal.rssi)
    val signalColor = when {
        signal.rssi >= -50 -> LcarsOrange
        signal.rssi >= -70 -> LcarsTan
        else -> LcarsRed
    }
    
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(4.dp))
            .background(LcarsBlue.copy(alpha = 0.15f))
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        // Signal strength indicator
        Box(
            modifier = Modifier
                .width(4.dp)
                .height(24.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(signalColor)
        )
        
        Spacer(modifier = Modifier.width(8.dp))
        
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = signal.ssid.ifEmpty { "<Hidden>" },
                color = LcarsWhite,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1
            )
            Text(
                text = "${signal.rssi} dBm",
                color = signalColor,
                fontSize = 10.sp
            )
        }
        
        // Signal bars
        SignalBars(strength = signalStrength, color = signalColor)
    }
}

@Composable
private fun BluetoothSignalCard(signal: BluetoothSignal) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(4.dp))
            .background(LcarsPurple.copy(alpha = 0.15f))
            .padding(8.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .width(4.dp)
                .height(24.dp)
                .clip(RoundedCornerShape(2.dp))
                .background(LcarsPurple)
        )
        
        Spacer(modifier = Modifier.width(8.dp))
        
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = signal.name.ifEmpty { "Unknown" },
                color = LcarsWhite,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                maxLines = 1
            )
            Text(
                text = signal.address,
                color = LcarsPurple.copy(alpha = 0.7f),
                fontSize = 9.sp
            )
        }
    }
}

@Composable
private fun SignalBars(strength: Int, color: androidx.compose.ui.graphics.Color) {
    Row(
        verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {
        repeat(4) { index ->
            Box(
                modifier = Modifier
                    .width(4.dp)
                    .height((8 + index * 4).dp)
                    .clip(RoundedCornerShape(1.dp))
                    .background(
                        if (index < strength) color
                        else color.copy(alpha = 0.2f)
                    )
            )
        }
    }
}

private fun getSignalStrength(rssi: Int): Int {
    return when {
        rssi >= -50 -> 4
        rssi >= -60 -> 3
        rssi >= -70 -> 2
        rssi >= -80 -> 1
        else -> 0
    }
}
