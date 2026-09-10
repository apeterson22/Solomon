package com.solomonprime.tricorder.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import android.content.Intent
import android.net.wifi.WifiNetworkSpecifier
import android.net.NetworkRequest
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.provider.Settings
import android.widget.Toast
import androidx.compose.ui.platform.LocalContext
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.*

// ── Helpers ───────────────────────────────────────────────────

private fun encryptionColor(enc: String): Color = when (enc) {
    "OPEN" -> LcarsRed
    "WEP" -> LcarsOrange
    "WPA" -> LcarsTan
    else -> LcarsBlue   // WPA2, WPA3
}

private fun parseEncryptionFromCaps(capabilities: String): String = when {
    capabilities.contains("WPA3") -> "WPA3"
    capabilities.contains("WPA2") -> "WPA2"
    capabilities.contains("WPA") && !capabilities.contains("WPA2") -> "WPA"
    capabilities.contains("WEP") -> "WEP"
    else -> "OPEN"
}

private fun rssiToQuality(rssi: Int): Int = when {
    rssi >= -30 -> 100
    rssi <= -90 -> 0
    else -> ((rssi + 90) * 100) / 60
}.coerceIn(0, 100)

// ── Main Screen ───────────────────────────────────────────────

@Composable
fun RfSecurityScreen(
    modifier: Modifier = Modifier,
    viewModel: RfSecurityViewModel = viewModel()
) {
    val wifiNetworks by viewModel.wifiNetworks.collectAsState()
    val openNets by viewModel.openNetworks.collectAsState()
    val btDevices by viewModel.btDevices.collectAsState()
    val vulnerable by viewModel.vulnerableDevices.collectAsState()
    val nfcTag by viewModel.nfcTagInfo.collectAsState()
    val gattResults by viewModel.gattResults.collectAsState()

    var wifiExpanded by remember { mutableStateOf(true) }
    var btExpanded by remember { mutableStateOf(true) }
    var nfcExpanded by remember { mutableStateOf(true) }
    var selectedBssid by remember { mutableStateOf<String?>(null) }
    var selectedBtAddress by remember { mutableStateOf<String?>(null) }
    var actionLog by remember { mutableStateOf<String?>(null) }

    // Start BT discovery on first composition
    LaunchedEffect(Unit) {
        viewModel.startBtDiscovery()
    }

    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .background(LcarsBlack)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        // ── LCARS Header ──
        item {
            LcarsSectionHeader(title = "RF SECURITY SCANNER", color = LcarsPink)
            Spacer(Modifier.height(4.dp))
        }

        // ── Disclaimer ──
        item {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(4.dp))
                    .background(LcarsBlack)
                    .padding(8.dp)
            ) {
                Text(
                    text = "⚠ FOR AUTHORIZED SECURITY TESTING ONLY. Only scan networks/devices you own or have permission to analyze.",
                    color = LcarsOrange,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                    lineHeight = 14.sp
                )
            }
        }

        // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        // SECTION 1: WIFI ANALYSIS
        // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        item {
            SectionToggle(
                title = "WIFI ANALYSIS",
                count = wifiNetworks.size,
                expanded = wifiExpanded,
                color = LcarsBlue,
                onToggle = { wifiExpanded = !wifiExpanded }
            )
        }

        item {
            AnimatedVisibility(
                visible = wifiExpanded,
                enter = expandVertically(),
                exit = shrinkVertically()
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    // Open network alert
                    if (openNets.isNotEmpty()) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(4.dp))
                                .background(LcarsRed.copy(alpha = 0.15f))
                                .padding(8.dp)
                        ) {
                            Text(
                                text = "⚠ ${openNets.size} OPEN NETWORK${if (openNets.size > 1) "S" else ""} DETECTED",
                                color = LcarsRed,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }

                    wifiNetworks.forEach { net ->
                        val enc = parseEncryptionFromCaps(net.capabilities)
                        val isSelected = net.bssid == selectedBssid
                        WifiNetworkRow(
                            net = net,
                            encryption = enc,
                            isSelected = isSelected,
                            analysis = if (isSelected) viewModel.analyzeNetwork(net.bssid) else null,
                            actionLog = if (isSelected) actionLog else null,
                            onAction = { actionLog = it },
                            onClick = {
                                selectedBssid = if (isSelected) null else net.bssid
                            }
                        )
                    }
                }
            }
        }

        // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        // SECTION 2: BLUETOOTH RECON
        // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        item {
            SectionToggle(
                title = "BLUETOOTH RECON",
                count = btDevices.size,
                expanded = btExpanded,
                color = LcarsTan,
                onToggle = { btExpanded = !btExpanded }
            )
        }

        item {
            AnimatedVisibility(
                visible = btExpanded,
                enter = expandVertically(),
                exit = shrinkVertically()
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (vulnerable.isNotEmpty()) {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(4.dp))
                                .background(LcarsOrange.copy(alpha = 0.15f))
                                .padding(8.dp)
                        ) {
                            Text(
                                text = "⚠ ${vulnerable.size} DEVICE${if (vulnerable.size > 1) "S" else ""} WITH DEFAULT NAMES",
                                color = LcarsOrange,
                                fontSize = 13.sp,
                                fontWeight = FontWeight.Bold
                            )
                        }
                    }

                    btDevices.forEach { dev ->
                        val isSelected = dev.address == selectedBtAddress
                        BtDeviceRow(
                            device = dev,
                            isVulnerable = vulnerable.any { it.address == dev.address },
                            isSelected = isSelected,
                            gattData = if (isSelected) actionLog ?: gattResults else null,
                            onClick = {
                                actionLog = null
                                if (isSelected) {
                                    selectedBtAddress = null
                                    viewModel.clearGattResults()
                                } else {
                                    selectedBtAddress = dev.address
                                    viewModel.clearGattResults()
                                }
                            },
                            onEnumerate = { actionLog = null; viewModel.enumerateDevice(dev.address) },
                            onAction = { actionLog = it }
                        )
                    }

                    if (btDevices.isEmpty()) {
                        Text(
                            text = "Scanning for Bluetooth devices…",
                            color = LcarsTan.copy(alpha = 0.6f),
                            fontSize = 13.sp,
                            modifier = Modifier.padding(8.dp)
                        )
                    }
                }
            }
        }

        // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        // SECTION 3: NFC SCANNER
        // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

        item {
            SectionToggle(
                title = "NFC SCANNER",
                count = if (nfcTag != null) 1 else 0,
                expanded = nfcExpanded,
                color = LcarsPink,
                onToggle = { nfcExpanded = !nfcExpanded }
            )
        }

        item {
            AnimatedVisibility(
                visible = nfcExpanded,
                enter = expandVertically(),
                exit = shrinkVertically()
            ) {
                Column(
                    modifier = Modifier.padding(4.dp),
                    verticalArrangement = Arrangement.spacedBy(6.dp)
                ) {
                    if (nfcTag != null) {
                        val tag = nfcTag!!
                        NfcDetailRow("UID", tag.uid)
                        NfcDetailRow("TYPE", tag.type)
                        NfcDetailRow("TECH", tag.techList.joinToString(", "))
                        if (tag.ndefData != null) {
                            NfcDetailRow("NDEF", tag.ndefData)
                        } else {
                            Text(
                                text = "No NDEF data (tag may be unformatted or locked)",
                                color = LcarsTan.copy(alpha = 0.6f),
                                fontSize = 12.sp
                            )
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            val context = LocalContext.current
                            NetworkActionButton(
                                text = "CLONE TAG",
                                color = LcarsRed,
                                onClick = {
                                    actionLog = "Cloning UID ${tag.uid} to blank tag...\nWriting to Sector 0, Block 0."
                                }
                            )
                            NetworkActionButton(
                                text = "BRUTEFORCE",
                                color = LcarsOrange,
                                onClick = {
                                    actionLog = "Running dictionary attack on sector keys...\nTrying known default keys (FF FF FF FF FF FF)..."
                                }
                            )
                            NetworkActionButton(
                                text = "EMULATE",
                                color = LcarsPurple,
                                onClick = {
                                    actionLog = "Starting Host Card Emulation for ${tag.uid}...\nBroadcasting emulated NDEF records."
                                }
                            )
                        }
                        if (actionLog != null) {
                            Spacer(Modifier.height(8.dp))
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .clip(RoundedCornerShape(4.dp))
                                    .background(Color(0xFF0A0A18))
                                    .padding(8.dp)
                            ) {
                                Text(
                                    text = actionLog!!,
                                    color = LcarsTan,
                                    fontSize = 10.sp,
                                    fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                                    lineHeight = 14.sp
                                )
                            }
                        }
                    } else {
                        Box(
                            modifier = Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(4.dp))
                                .background(Color(0xFF1A1A2E))
                                .padding(16.dp),
                            contentAlignment = Alignment.Center
                        ) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text(
                                    text = "📡",
                                    fontSize = 32.sp
                                )
                                Spacer(Modifier.height(8.dp))
                                Text(
                                    text = "SCAN NFC TAG",
                                    color = LcarsPink,
                                    fontSize = 16.sp,
                                    fontWeight = FontWeight.Bold
                                )
                                Text(
                                    text = "Hold device near an NFC tag to read",
                                    color = LcarsTan.copy(alpha = 0.6f),
                                    fontSize = 12.sp
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ── Section Toggle ────────────────────────────────────────────

@Composable
private fun SectionToggle(
    title: String,
    count: Int,
    expanded: Boolean,
    color: Color,
    onToggle: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = 12.dp, bottomStart = 12.dp, topEnd = 4.dp, bottomEnd = 4.dp))
            .background(color)
            .clickable(onClick = onToggle)
            .padding(horizontal = 14.dp, vertical = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(
            text = title,
            color = LcarsBlack,
            fontWeight = FontWeight.Bold,
            fontSize = 15.sp
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                text = "$count",
                color = LcarsBlack,
                fontWeight = FontWeight.Bold,
                fontSize = 14.sp
            )
            Text(
                text = if (expanded) "▼" else "▶",
                color = LcarsBlack,
                fontSize = 14.sp
            )
        }
    }
}

// ── WiFi Network Row ──────────────────────────────────────────

@Composable
private fun WifiNetworkRow(
    net: WifiNetworkInfo,
    encryption: String,
    isSelected: Boolean,
    analysis: NetworkAnalysis?,
    actionLog: String?,
    onAction: (String) -> Unit,
    onClick: () -> Unit
) {
    val secColor = encryptionColor(encryption)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(4.dp))
            .background(if (isSelected) Color(0xFF1A1A2E) else Color(0xFF0D0D1A))
            .clickable(onClick = onClick)
            .padding(10.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = if (net.isHidden) "[HIDDEN NETWORK]" else net.ssid.ifBlank { "[No SSID]" },
                    color = if (encryption == "OPEN") LcarsRed else LcarsTan,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = net.bssid,
                    color = LcarsTan.copy(alpha = 0.5f),
                    fontSize = 11.sp
                )
            }

            // Security badge
            Box(
                modifier = Modifier
                    .clip(RoundedCornerShape(4.dp))
                    .background(secColor.copy(alpha = 0.2f))
                    .padding(horizontal = 8.dp, vertical = 3.dp)
            ) {
                Text(
                    text = encryption,
                    color = secColor,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        // Signal bar
        Spacer(Modifier.height(4.dp))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            val quality = rssiToQuality(net.rssi)
            LinearProgressIndicator(
                progress = { quality / 100f },
                modifier = Modifier
                    .weight(1f)
                    .height(4.dp)
                    .clip(RoundedCornerShape(2.dp)),
                color = when {
                    quality > 70 -> LcarsBlue
                    quality > 40 -> LcarsOrange
                    else -> LcarsRed
                },
                trackColor = Color(0xFF2A2A3E),
            )
            Text(
                text = "${net.rssi} dBm · ${net.frequency} MHz",
                color = LcarsTan.copy(alpha = 0.6f),
                fontSize = 10.sp
            )
        }

        // Action buttons when selected
        if (isSelected) {
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                val context = LocalContext.current
                NetworkActionButton(
                    text = "DEAUTH",
                    color = LcarsRed,
                    onClick = {
                        onAction("Initiating DEAUTH sequence on ${net.bssid}...\nInjecting forged management frames.\nWaiting for client disconnect...")
                    }
                )
                NetworkActionButton(
                    text = "CAPTURE HANDSHAKE",
                    color = LcarsOrange,
                    onClick = {
                        onAction("Listening for WPA handshakes...\nChannel ${((net.frequency - 2412) / 5 + 1)} tuned.\nAwaiting EAPOL exchange...")
                    }
                )
                NetworkActionButton(
                    text = "PIXIE DUST",
                    color = LcarsPurple,
                    onClick = {
                        onAction("Running WPS Pixie Dust attack...\nTarget: ${net.bssid}\nExploiting entropy flaw...")
                    }
                )
            }
            
            if (actionLog != null) {
                Spacer(Modifier.height(8.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(4.dp))
                        .background(Color(0xFF0A0A18))
                        .padding(8.dp)
                ) {
                    Text(
                        text = actionLog,
                        color = LcarsTan,
                        fontSize = 10.sp,
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                        lineHeight = 14.sp
                    )
                }
            }
        }
        
        // Expanded analysis
        if (isSelected && analysis != null) {
            Spacer(Modifier.height(6.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(4.dp))
                    .background(Color(0xFF0A0A18))
                    .padding(8.dp)
            ) {
                Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    AnalysisRow("ENCRYPTION", analysis.encryptionType, encryptionColor(analysis.encryptionType))
                    AnalysisRow("SIGNAL", "${analysis.signalQuality}%", LcarsTan)
                    AnalysisRow(
                        "CH INTERFERENCE",
                        "${analysis.channelInterference} network${if (analysis.channelInterference != 1) "s" else ""}",
                        if (analysis.channelInterference > 3) LcarsOrange else LcarsTan
                    )
                    AnalysisRow(
                        "EST. DISTANCE",
                        "%.1f m".format(analysis.estimatedDistance),
                        LcarsTan
                    )
                }
            }
        }
    }
}

@Composable
private fun AnalysisRow(label: String, value: String, valueColor: Color) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text = label, color = LcarsTan.copy(alpha = 0.5f), fontSize = 11.sp)
        Text(text = value, color = valueColor, fontSize = 11.sp, fontWeight = FontWeight.Bold)
    }
}

// ── Bluetooth Device Row ──────────────────────────────────────

@Composable
private fun BtDeviceRow(
    device: BtDeviceInfo, 
    isVulnerable: Boolean,
    isSelected: Boolean,
    gattData: String?,
    onClick: () -> Unit,
    onEnumerate: () -> Unit,
    onAction: (String) -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(4.dp))
            .background(if (isSelected) Color(0xFF1A1A2E) else if (isVulnerable) LcarsOrange.copy(alpha = 0.08f) else Color(0xFF0D0D1A))
            .clickable(onClick = onClick)
            .padding(10.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = device.name.ifBlank { "[Unknown Device]" },
                    color = if (isVulnerable) LcarsOrange else LcarsTan,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Text(
                    text = "${device.address} · ${device.type}",
                    color = LcarsTan.copy(alpha = 0.5f),
                    fontSize = 11.sp
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "${device.rssi} dBm",
                    color = LcarsTan.copy(alpha = 0.7f),
                    fontSize = 12.sp
                )
                if (isVulnerable) {
                    Text(
                        text = "DEFAULT NAME",
                        color = LcarsOrange,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
        
        if (isSelected) {
            Spacer(Modifier.height(6.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                val context = LocalContext.current
                NetworkActionButton(
                    text = "L2CAP PING",
                    color = LcarsBlue,
                    onClick = { onAction("Pinging L2CAP port on ${device.address}...\nSending Echo Request...\nResponse time: 14ms (Simulated)") }
                )
                NetworkActionButton(
                    text = "ENUMERATE",
                    color = LcarsTan,
                    onClick = onEnumerate
                )
                NetworkActionButton(
                    text = "BLUESNARF",
                    color = LcarsRed,
                    onClick = { onAction("Attempting BlueSnarf attack...\nConnecting to OBEX Push profile...\nAccess denied: Service requires pairing.") }
                )
            }
            
            if (gattData != null) {
                Spacer(Modifier.height(8.dp))
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(4.dp))
                        .background(Color(0xFF0A0A18))
                        .padding(8.dp)
                ) {
                    Text(
                        text = gattData,
                        color = LcarsTan,
                        fontSize = 10.sp,
                        fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace,
                        lineHeight = 14.sp
                    )
                }
            }
        }
    }
}

// ── NFC Detail Row ────────────────────────────────────────────

@Composable
private fun NfcDetailRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(4.dp))
            .background(Color(0xFF0D0D1A))
            .padding(horizontal = 10.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(
            text = label,
            color = LcarsPink.copy(alpha = 0.7f),
            fontSize = 12.sp,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = value,
            color = LcarsTan,
            fontSize = 12.sp,
            modifier = Modifier.weight(1f, fill = false).padding(start = 12.dp),
            maxLines = 3,
            overflow = TextOverflow.Ellipsis
        )
    }
}


@Composable
private fun NetworkActionButton(
    text: String,
    color: Color,
    onClick: () -> Unit
) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(4.dp))
            .background(color.copy(alpha = 0.2f))
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 6.dp)
    ) {
        Text(
            text = text,
            color = color,
            fontSize = 11.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = androidx.compose.ui.text.font.FontFamily.Monospace
        )
    }
}