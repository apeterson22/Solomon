package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.PipeLeakViewModel
import kotlin.math.sin
import kotlin.random.Random

/**
 * PIPE LEAK DETECTOR screen — multi-modal with simulated thermal display
 */
@Composable
fun PipeLeakScreen(viewModel: PipeLeakViewModel = viewModel()) {
    val leakAlert by viewModel.leakAlert.collectAsState()
    val leakProb by viewModel.leakProbability.collectAsState()
    val acousticEnergy by viewModel.acousticEnergy.collectAsState()
    val magVariance by viewModel.magneticVariance.collectAsState()
    val pressureVar by viewModel.pressureVariance.collectAsState()
    val accelRMS by viewModel.accelerometerRMS.collectAsState()
    val irReading by viewModel.irReading.collectAsState()
    val calibrated by viewModel.baselineCalibrated.collectAsState()
    val scanHistory by viewModel.scanHistory.collectAsState()
    val taggedLocations by viewModel.taggedLocations.collectAsState()
    val pressureDrop by viewModel.pressureDropDetected.collectAsState()

    // Start/stop scanning with screen lifecycle
    DisposableEffect(Unit) {
        viewModel.startScan()
        onDispose { viewModel.stopScan() }
    }

    // Pulse animation for alerts
    val shouldPulse = leakAlert == "MEDIUM" || leakAlert == "HIGH"
    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = if (shouldPulse) 0.4f else 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulseAlpha"
    )

    // Animation time for thermal flicker
    val flickerTime by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(
            animation = tween(10000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "flicker"
    )

    val alertColor = when (leakAlert) {
        "HIGH" -> LcarsRed
        "MEDIUM" -> LcarsOrange
        else -> LcarsBlue
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(LcarsBlack)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        LcarsSectionHeader(title = "PIPE LEAK DETECTOR", color = LcarsBlue)

        Spacer(modifier = Modifier.height(12.dp))

        // Calibration status
        LcarsScanningIndicator(isActive = !calibrated, color = LcarsBlue)

        Spacer(modifier = Modifier.height(8.dp))

        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(4.dp))
                .background(if (calibrated) LcarsBlue.copy(alpha = 0.3f) else LcarsOrange.copy(alpha = 0.3f))
                .padding(horizontal = 16.dp, vertical = 6.dp)
        ) {
            Text(
                text = if (calibrated) "CALIBRATED" else "CALIBRATING (5s)...",
                color = if (calibrated) LcarsBlue else LcarsOrange,
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        // ---- SIMULATED THERMAL VISUALIZATION ----
        Text(
            text = "THERMAL ANALYSIS (SIMULATED — contact mic recommended)",
            color = LcarsWhite.copy(alpha = 0.5f),
            fontSize = 10.sp,
            fontWeight = FontWeight.Bold
        )

        Spacer(modifier = Modifier.height(6.dp))

        ThermalGrid(
            leakScore = leakProb,
            irReading = irReading,
            acousticEnergy = acousticEnergy,
            flickerTime = flickerTime
        )

        Spacer(modifier = Modifier.height(16.dp))

        // ---- ALERT DISPLAY ----
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(100.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(alertColor.copy(alpha = 0.2f))
                .alpha(pulseAlpha),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text = leakAlert,
                    color = alertColor,
                    fontSize = 44.sp,
                    fontWeight = FontWeight.ExtraBold
                )
                Text(
                    text = "LEAK STATUS",
                    color = alertColor.copy(alpha = 0.7f),
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        // Pressure drop warning
        if (pressureDrop) {
            Spacer(modifier = Modifier.height(8.dp))
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(6.dp))
                    .background(LcarsRed.copy(alpha = 0.3f))
                    .padding(8.dp),
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = "⚠ PRESSURE DROP >0.5 hPa IN 30s DETECTED",
                    color = LcarsRed,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // ---- LEAK PROBABILITY GAUGE ----
        LcarsGauge(
            value = leakProb,
            minValue = 0f,
            maxValue = 1f,
            label = "LEAK PROBABILITY",
            unit = " ",
            accentColor = alertColor
        )

        Spacer(modifier = Modifier.height(16.dp))

        // ---- TREND LINE ----
        if (scanHistory.isNotEmpty()) {
            Text(
                text = "SCAN HISTORY (LAST ${scanHistory.size} READINGS)",
                color = LcarsWhite.copy(alpha = 0.6f),
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(4.dp))
            TrendLineGraph(
                data = scanHistory,
                accentColor = alertColor
            )
            Spacer(modifier = Modifier.height(16.dp))
        }

        // ---- SENSOR DATA CARDS ----
        LcarsDataCard(
            title = "ACOUSTIC\n50-500Hz",
            value = "%.1f".format(acousticEnergy),
            unit = " ",
            accentColor = LcarsBlue
        )
        LcarsDataCard(
            title = "MAGNETIC\nANOMALY",
            value = "%.3f".format(magVariance),
            unit = "µT",
            accentColor = LcarsPink
        )
        LcarsDataCard(
            title = "PRESSURE\nVARIANCE",
            value = "%.4f".format(pressureVar),
            unit = "hPa",
            accentColor = LcarsTan
        )
        LcarsDataCard(
            title = "VIBRATION\nRMS",
            value = "%.4f".format(accelRMS),
            unit = "m/s²",
            accentColor = LcarsOrange
        )
        LcarsDataCard(
            title = "IR LIGHT",
            value = "%.1f".format(irReading),
            unit = " ",
            accentColor = LcarsRed
        )

        Spacer(modifier = Modifier.height(16.dp))

        // ---- LOCATION TAGGING ----
        LcarsButton(
            text = "TAG LOCATION",
            onClick = {
                val label = "Point ${(taggedLocations.size + 1)}"
                viewModel.tagLocation(label)
            },
            color = LcarsTan
        )

        if (taggedLocations.isNotEmpty()) {
            Spacer(modifier = Modifier.height(8.dp))
            taggedLocations.forEach { (label, score, _) ->
                val tagColor = when {
                    score > 0.6f -> LcarsRed
                    score > 0.3f -> LcarsOrange
                    else -> LcarsBlue
                }
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(vertical = 2.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(tagColor.copy(alpha = 0.15f))
                        .padding(horizontal = 12.dp, vertical = 6.dp)
                ) {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween
                    ) {
                        Text(text = label, color = tagColor, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                        Text(
                            text = "%.0f".format(score * 100) + " " ,
                            color = tagColor,
                            fontSize = 13.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
        }

        Spacer(modifier = Modifier.height(16.dp))

        // ---- BUTTONS ----
        LcarsButton(
            text = "RECALIBRATE",
            onClick = { viewModel.recalibrate() },
            color = LcarsOrange
        )

        Spacer(modifier = Modifier.height(16.dp))

        // ---- INSTRUCTIONS ----
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(8.dp))
                .background(LcarsBlue.copy(alpha = 0.1f))
                .padding(12.dp)
        ) {
            Column {
                Text(
                    text = "Place phone flat against floor/wall/pipe. Hold still during 5s calibration. " +
                        "For best results, use an external USB-C contact microphone.",
                    color = LcarsWhite.copy(alpha = 0.8f),
                    fontSize = 13.sp,
                    lineHeight = 18.sp
                )
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = "Hot water leaks detectable via IR variance. Magnetic anomaly detects " +
                        "water flow in copper pipes. Pressure drop monitors enclosed-space micro-pressure changes.",
                    color = LcarsWhite.copy(alpha = 0.5f),
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Light,
                    lineHeight = 16.sp
                )
            }
        }

        Spacer(modifier = Modifier.height(16.dp))
    }
}

// ---- SIMULATED THERMAL GRID ----

@Composable
private fun ThermalGrid(
    leakScore: Float,
    irReading: Float,
    acousticEnergy: Float,
    flickerTime: Float
) {
    // Seed a deterministic "heat map" that shifts based on sensor input
    val gridSize = 10

    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(200.dp)
            .clip(RoundedCornerShape(8.dp))
    ) {
        val cellW = size.width / gridSize
        val cellH = size.height / gridSize

        // Normalize IR to 0-1 range (typical values 0-1000+)
        val irNorm = (irReading / 500f).coerceIn(0f, 1f)
        // Base heat level from combined inputs
        val baseHeat = (leakScore * 0.5f + irNorm * 0.3f + (acousticEnergy / 5000f).coerceIn(0f, 0.2f))
            .coerceIn(0f, 1f)

        for (row in 0 until gridSize) {
            for (col in 0 until gridSize) {
                // Spatial gradient: center is hotter (simulates point source)
                val cx = (col - gridSize / 2f) / (gridSize / 2f)
                val cy = (row - gridSize / 2f) / (gridSize / 2f)
                val dist = sqrt(cx * cx + cy * cy).coerceIn(0f, 1.4f) / 1.4f

                // Flicker based on acoustic energy and time
                val flicker = sin(
                    flickerTime * 0.1f + col * 1.7f + row * 2.3f
                ).toFloat() * 0.05f * (acousticEnergy / 1000f).coerceIn(0f, 1f)

                val cellHeat = (baseHeat * (1f - dist * 0.6f) + flicker)
                    .coerceIn(0f, 1f)

                // Interpolate: Blue → Tan → Orange → Red
                val cellColor = when {
                    cellHeat < 0.33f -> lerp(LcarsBlue, LcarsTan, cellHeat / 0.33f)
                    cellHeat < 0.66f -> lerp(LcarsTan, LcarsOrange, (cellHeat - 0.33f) / 0.33f)
                    else -> lerp(LcarsOrange, LcarsRed, (cellHeat - 0.66f) / 0.34f)
                }

                drawRect(
                    color = cellColor,
                    topLeft = Offset(col * cellW, row * cellH),
                    size = Size(cellW - 1.dp.toPx(), cellH - 1.dp.toPx())
                )
            }
        }
    }
}

private fun sqrt(x: Float): Float = kotlin.math.sqrt(x)
private fun sin(x: Float): Float = kotlin.math.sin(x.toDouble()).toFloat()

// ---- TREND LINE GRAPH ----

@Composable
private fun TrendLineGraph(
    data: List<Float>,
    accentColor: Color
) {
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(80.dp)
            .clip(RoundedCornerShape(6.dp))
            .background(LcarsBlack)
    ) {
        if (data.size < 2) return@Canvas

        val w = size.width
        val h = size.height
        val stepX = w / (data.size - 1).coerceAtLeast(1)

        // Draw threshold lines
        drawLine(
            color = LcarsOrange.copy(alpha = 0.3f),
            start = Offset(0f, h * 0.7f), // 0.3 threshold
            end = Offset(w, h * 0.7f),
            strokeWidth = 1.dp.toPx()
        )
        drawLine(
            color = LcarsRed.copy(alpha = 0.3f),
            start = Offset(0f, h * 0.4f), // 0.6 threshold
            end = Offset(w, h * 0.4f),
            strokeWidth = 1.dp.toPx()
        )

        // Draw data path
        val path = Path()
        data.forEachIndexed { i, v ->
            val x = i * stepX
            val y = h * (1f - v.coerceIn(0f, 1f))
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }

        drawPath(
            path = path,
            color = accentColor,
            style = Stroke(width = 2.dp.toPx())
        )
    }
}
