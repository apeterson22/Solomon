package com.solomonprime.tricorder.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.viewmodel.Obd2ViewModel
import com.solomonprime.tricorder.ui.theme.*

/**
 * OBD2 Vehicle Diagnostics Screen
 * 
 * Displays real-time vehicle sensor data from ELM327-compatible Bluetooth OBD2 adapters.
 * Shows RPM, speed, temperatures, engine load, fuel level, throttle position, and DTCs.
 * 
 * NOTE: Add "OBD" tab to MainActivity navigation.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Obd2Screen(
    viewModel: Obd2ViewModel = viewModel()
) {
    // Collect state from ViewModel
    val connectionState by viewModel.connectionState.collectAsState()
    val pairedDevices by viewModel.pairedObdDevices.collectAsState()
    val rpm by viewModel.rpm.collectAsState()
    val speed by viewModel.speed.collectAsState()
    val coolantTemp by viewModel.coolantTemp.collectAsState()
    val engineLoad by viewModel.engineLoad.collectAsState()
    val fuelLevel by viewModel.fuelLevel.collectAsState()
    val intakeTemp by viewModel.intakeTemp.collectAsState()
    val throttlePos by viewModel.throttlePos.collectAsState()
    val dtcCount by viewModel.dtcCount.collectAsState()
    val dtcCodes by viewModel.dtcCodes.collectAsState()

    // Selected device state
    var selectedDevice by remember { mutableStateOf("") }
    var dropdownExpanded by remember { mutableStateOf(false) }

    // Refresh devices on first composition
    LaunchedEffect(Unit) {
        viewModel.refreshPairedDevices()
    }

    // Auto-select first device if none selected
    LaunchedEffect(pairedDevices) {
        if (selectedDevice.isEmpty() && pairedDevices.isNotEmpty()) {
            selectedDevice = pairedDevices.first()
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .padding(16.dp)
            .verticalScroll(rememberScrollState())
    ) {
        // LCARS Header
        LcarsSectionHeader(title = "VEHICLE DIAGNOSTICS")

        Spacer(modifier = Modifier.height(16.dp))

        // Connection Panel
        ConnectionPanel(
            connectionState = connectionState,
            pairedDevices = pairedDevices,
            selectedDevice = selectedDevice,
            dropdownExpanded = dropdownExpanded,
            onDeviceSelected = { device ->
                selectedDevice = device
                dropdownExpanded = false
            },
            onDropdownToggle = { dropdownExpanded = !dropdownExpanded },
            onDropdownDismiss = { dropdownExpanded = false },
            onConnect = { viewModel.connectToDevice(selectedDevice) },
            onDisconnect = { viewModel.disconnect() },
            onRefresh = { viewModel.refreshPairedDevices() }
        )

        Spacer(modifier = Modifier.height(24.dp))

        // Main content based on connection state
        when (connectionState) {
            "CONNECTED" -> {
                ConnectedContent(
                    rpm = rpm,
                    speed = speed,
                    coolantTemp = coolantTemp,
                    engineLoad = engineLoad,
                    fuelLevel = fuelLevel,
                    intakeTemp = intakeTemp,
                    throttlePos = throttlePos,
                    dtcCount = dtcCount,
                    dtcCodes = dtcCodes,
                    onClearDtc = { viewModel.clearDtc() }
                )
            }
            "CONNECTING" -> {
                ConnectingContent()
            }
            "ERROR" -> {
                ErrorContent(
                    onRetry = { 
                        if (selectedDevice.isNotEmpty()) {
                            viewModel.connectToDevice(selectedDevice)
                        }
                    }
                )
            }
            else -> {
                DisconnectedContent()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ConnectionPanel(
    connectionState: String,
    pairedDevices: List<String>,
    selectedDevice: String,
    dropdownExpanded: Boolean,
    onDeviceSelected: (String) -> Unit,
    onDropdownToggle: () -> Unit,
    onDropdownDismiss: () -> Unit,
    onConnect: () -> Unit,
    onDisconnect: () -> Unit,
    onRefresh: () -> Unit
) {
    // Status badge color
    val statusColor = when (connectionState) {
        "CONNECTED" -> Color.Green
        "CONNECTING" -> LcarsOrange
        "ERROR" -> LcarsRed
        else -> Color.Gray
    }

    Column(
        modifier = Modifier.fillMaxWidth()
    ) {
        // Status badge row
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = "CONNECTION STATUS",
                color = LcarsTan,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold
            )
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Box(
                    modifier = Modifier
                        .size(12.dp)
                        .background(statusColor, shape = androidx.compose.foundation.shape.CircleShape)
                )
                Text(
                    text = connectionState,
                    color = statusColor,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Device selection dropdown
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            ExposedDropdownMenuBox(
                expanded = dropdownExpanded,
                onExpandedChange = { onDropdownToggle() },
                modifier = Modifier.weight(1f)
            ) {
                OutlinedTextField(
                    value = selectedDevice.ifEmpty { "Select OBD2 Adapter" },
                    onValueChange = {},
                    readOnly = true,
                    trailingIcon = {
                        ExposedDropdownMenuDefaults.TrailingIcon(expanded = dropdownExpanded)
                    },
                    modifier = Modifier
                        .menuAnchor()
                        .fillMaxWidth(),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = LcarsTan,
                        unfocusedTextColor = LcarsTan,
                        focusedBorderColor = LcarsOrange,
                        unfocusedBorderColor = LcarsPurple
                    ),
                    enabled = connectionState != "CONNECTING" && connectionState != "CONNECTED"
                )

                ExposedDropdownMenu(
                    expanded = dropdownExpanded,
                    onDismissRequest = onDropdownDismiss
                ) {
                    if (pairedDevices.isEmpty()) {
                        DropdownMenuItem(
                            text = { Text("No OBD2 devices paired") },
                            onClick = { onDropdownDismiss() }
                        )
                    } else {
                        pairedDevices.forEach { device ->
                            DropdownMenuItem(
                                text = { Text(device) },
                                onClick = { onDeviceSelected(device) }
                            )
                        }
                    }
                }
            }

            // Refresh button
            LcarsButton(
                text = "↻",
                onClick = onRefresh,
                color = LcarsPurple,
                enabled = connectionState != "CONNECTING"
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        // Connect/Disconnect buttons
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            if (connectionState == "CONNECTED") {
                LcarsButton(
                    text = "DISCONNECT",
                    onClick = onDisconnect,
                    color = LcarsRed,
                    modifier = Modifier.weight(1f)
                )
            } else {
                LcarsButton(
                    text = "CONNECT",
                    onClick = onConnect,
                    color = LcarsBlue,
                    modifier = Modifier.weight(1f),
                    enabled = selectedDevice.isNotEmpty() && connectionState != "CONNECTING"
                )
            }
        }
    }
}

@Composable
private fun ConnectedContent(
    rpm: Int,
    speed: Int,
    coolantTemp: Int,
    engineLoad: Float,
    fuelLevel: Float,
    intakeTemp: Int,
    throttlePos: Float,
    dtcCount: Int,
    dtcCodes: List<String>,
    onClearDtc: () -> Unit
) {
    // DTC Warning Section (show first if there are codes)
    if (dtcCount > 0) {
        DtcWarningSection(
            dtcCount = dtcCount,
            dtcCodes = dtcCodes,
            onClearDtc = onClearDtc
        )
        Spacer(modifier = Modifier.height(16.dp))
    }

    // Primary RPM Gauge (large)
    LcarsGauge(
        value = rpm.toFloat(),
        minValue = 0f,
        maxValue = 8000f,
        label = "ENGINE RPM",
        unit = "RPM",
        accentColor = if (rpm > 6000) LcarsRed else LcarsOrange,
        modifier = Modifier
            .fillMaxWidth()
            .height(120.dp)
    )

    Spacer(modifier = Modifier.height(16.dp))

    // Speed card
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        LcarsDataCard(
            title = "SPEED",
            value = "$speed",
            unit = "km/h",
            accentColor = LcarsBlue,
            modifier = Modifier.weight(1f)
        )
        
        // Coolant temp with color coding
        val coolantColor = when {
            coolantTemp > 100 -> LcarsRed
            coolantTemp >= 80 -> LcarsOrange
            else -> LcarsBlue
        }
        LcarsDataCard(
            title = "COOLANT",
            value = "$coolantTemp",
            unit = "°C",
            accentColor = coolantColor,
            modifier = Modifier.weight(1f)
        )
    }

    Spacer(modifier = Modifier.height(16.dp))

    // Engine Load Gauge
    LcarsGauge(
        value = engineLoad,
        minValue = 0f,
        maxValue = 100f,
        label = "ENGINE LOAD",
        unit = "%",
        accentColor = if (engineLoad > 80) LcarsRed else LcarsPurple,
        modifier = Modifier
            .fillMaxWidth()
            .height(80.dp)
    )

    Spacer(modifier = Modifier.height(12.dp))

    // Throttle Position Gauge
    LcarsGauge(
        value = throttlePos,
        minValue = 0f,
        maxValue = 100f,
        label = "THROTTLE",
        unit = "%",
        accentColor = LcarsOrange,
        modifier = Modifier
            .fillMaxWidth()
            .height(80.dp)
    )

    Spacer(modifier = Modifier.height(12.dp))

    // Fuel Level Gauge
    LcarsGauge(
        value = fuelLevel,
        minValue = 0f,
        maxValue = 100f,
        label = "FUEL LEVEL",
        unit = "%",
        accentColor = if (fuelLevel < 15) LcarsRed else LcarsBlue,
        modifier = Modifier
            .fillMaxWidth()
            .height(80.dp)
    )

    Spacer(modifier = Modifier.height(16.dp))

    // Intake temp card
    LcarsDataCard(
        title = "INTAKE AIR TEMP",
        value = "$intakeTemp",
        unit = "°C",
        accentColor = LcarsTan,
        modifier = Modifier.fillMaxWidth()
    )
}

@Composable
private fun DtcWarningSection(
    dtcCount: Int,
    dtcCodes: List<String>,
    onClearDtc: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(LcarsRed.copy(alpha = 0.2f), shape = MaterialTheme.shapes.medium)
            .padding(16.dp)
    ) {
        Text(
            text = "⚠ CHECK ENGINE: $dtcCount codes",
            color = LcarsRed,
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold
        )

        if (dtcCodes.isNotEmpty()) {
            Spacer(modifier = Modifier.height(8.dp))
            dtcCodes.forEach { code ->
                Text(
                    text = "• $code",
                    color = LcarsRed,
                    fontSize = 14.sp,
                    modifier = Modifier.padding(start = 8.dp)
                )
            }
        }

        Spacer(modifier = Modifier.height(12.dp))

        LcarsButton(
            text = "CLEAR DTC",
            onClick = onClearDtc,
            color = LcarsOrange,
            modifier = Modifier.fillMaxWidth()
        )
    }
}

@Composable
private fun ConnectingContent() {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            CircularProgressIndicator(
                color = LcarsOrange,
                modifier = Modifier.size(48.dp)
            )
            Spacer(modifier = Modifier.height(16.dp))
            Text(
                text = "ESTABLISHING LINK...",
                color = LcarsOrange,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

@Composable
private fun ErrorContent(
    onRetry: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = "CONNECTION FAILED",
            color = LcarsRed,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold
        )
        Spacer(modifier = Modifier.height(12.dp))
        Text(
            text = "Unable to establish connection to OBD2 adapter. Verify the adapter is powered and in range.",
            color = LcarsTan,
            fontSize = 14.sp
        )
        Spacer(modifier = Modifier.height(16.dp))
        LcarsButton(
            text = "RETRY CONNECTION",
            onClick = onRetry,
            color = LcarsOrange
        )
    }
}

@Composable
private fun DisconnectedContent() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(24.dp)
    ) {
        Text(
            text = "CONNECT OBD2 ADAPTER",
            color = LcarsOrange,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold
        )

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = "Pair a Bluetooth ELM327 OBD2 adapter to your phone, then select it above. Available at most auto parts stores (\$10-30).",
            color = LcarsTan,
            fontSize = 14.sp
        )

        Spacer(modifier = Modifier.height(24.dp))

        // Setup guide
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(LcarsPurple.copy(alpha = 0.2f), shape = MaterialTheme.shapes.medium)
                .padding(16.dp)
        ) {
            Text(
                text = "SETUP GUIDE",
                color = LcarsPurple,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "1. Plug adapter into vehicle OBD2 port (under dash, driver side)",
                color = LcarsTan,
                fontSize = 13.sp
            )
            Text(
                text = "2. Turn ignition ON (engine can be off or running)",
                color = LcarsTan,
                fontSize = 13.sp
            )
            Text(
                text = "3. Pair via phone Bluetooth settings",
                color = LcarsTan,
                fontSize = 13.sp
            )
            Text(
                text = "4. Return here and select the adapter",
                color = LcarsTan,
                fontSize = 13.sp
            )
        }

        Spacer(modifier = Modifier.height(24.dp))

        // Supported data
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(LcarsBlue.copy(alpha = 0.2f), shape = MaterialTheme.shapes.medium)
                .padding(16.dp)
        ) {
            Text(
                text = "AVAILABLE DIAGNOSTICS",
                color = LcarsBlue,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "• Engine RPM & Speed\n• Coolant & Intake Temperature\n• Engine Load & Throttle Position\n• Fuel Level\n• Check Engine Light / DTC Codes\n• Clear Trouble Codes",
                color = LcarsTan,
                fontSize = 13.sp
            )
        }
    }
}
