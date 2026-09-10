package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solomonprime.tricorder.ui.theme.*
import kotlin.random.Random

@Composable
fun RadiationScannerScreen(
    cpm: Float = 18f,
    doseMicroSv: Float = 0.12f,
    alertLevel: Int = 0 // 0=normal, 1=elevated, 2=high, 3=danger
) {
    LcarsScreenScaffold(title = "RAD SCANNER", headerColor = LcarsRed) {

        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            LcarsAnimatedValue(value = cpm, label = "COUNTS/MIN", unit = "CPM", color = LcarsYellow, decimalPlaces = 0)
            LcarsAnimatedValue(value = doseMicroSv, label = "DOSE RATE", unit = "μSv/h", color = LcarsRed, decimalPlaces = 3)
        }

        Spacer(Modifier.height(12.dp))

        // Alert ring
        AlertRing(
            level = alertLevel,
            modifier = Modifier.size(80.dp).align(Alignment.CenterHorizontally)
        )

        Spacer(Modifier.height(12.dp))

        // Geiger counter particle field
        Text("PARTICLE DETECTION GRID", color = LcarsRed.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
        Spacer(Modifier.height(4.dp))
        GeigerField(
            cpm = cpm,
            modifier = Modifier.fillMaxWidth().height(160.dp)
        )

        Spacer(Modifier.height(12.dp))

        
        // Accumulated dose estimation
        Spacer(Modifier.height(8.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text("ACCUMULATED (EST)", color = LcarsRed.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
                Text("0.02 µSv", color = LcarsOrange, fontSize = 14.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("TIME EXPOSED", color = LcarsRed.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
                Text("05:32", color = LcarsYellow, fontSize = 14.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.height(8.dp))
        
        LcarsBarGraph(
            data = listOf(
                "CPM" to (cpm / 200f).coerceIn(0f, 1f),
                "DOSE" to (doseMicroSv / 5f).coerceIn(0f, 1f),
                "ALERT" to (alertLevel / 3f)
            )
        )
    }
}

@Composable
private fun AlertRing(level: Int, modifier: Modifier) {
    val color = when (level) {
        0 -> LcarsBlue
        1 -> LcarsYellow
        2 -> LcarsOrange
        else -> LcarsRed
    }
    val label = when (level) {
        0 -> "NOMINAL"
        1 -> "ELEVATED"
        2 -> "HIGH"
        else -> "DANGER"
    }

    val infiniteTransition = rememberInfiniteTransition(label = "alert")
    val pulseAlpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(if (level >= 2) 300 else 1000, easing = LinearEasing),
            RepeatMode.Reverse
        ),
        label = "alertPulse"
    )

    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val cx = size.width / 2f
            val cy = size.height / 2f
            val r = minOf(cx, cy) * 0.85f
            drawCircle(color.copy(alpha = pulseAlpha * 0.2f), r, Offset(cx, cy))
            drawCircle(color.copy(alpha = pulseAlpha), r, Offset(cx, cy), style = Stroke(4f))
        }
        Text(label, color = color, fontSize = 10.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun GeigerField(cpm: Float, modifier: Modifier) {
    // Particles appear and fade based on CPM
    data class Particle(val x: Float, val y: Float, val born: Long, val lifetime: Long)

    val particles = remember { mutableStateListOf<Particle>() }
    val infiniteTransition = rememberInfiniteTransition(label = "geiger")
    val tick by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1000f,
        animationSpec = infiniteRepeatable(tween(1000, easing = LinearEasing)),
        label = "tick"
    )

    // Spawn particles proportional to CPM
    LaunchedEffect(tick.toInt() / 50) { // ~20 spawns per second at most
        val spawnChance = (cpm / 60f) * 0.05f // probability per tick
        if (Random.nextFloat() < spawnChance) {
            particles.add(
                Particle(
                    x = Random.nextFloat(),
                    y = Random.nextFloat(),
                    born = System.currentTimeMillis(),
                    lifetime = Random.nextLong(400, 1200)
                )
            )
        }
        // Remove dead particles
        val now = System.currentTimeMillis()
        particles.removeAll { now - it.born > it.lifetime }
    }

    Canvas(modifier = modifier) {
        drawRect(LcarsDarkPanel)

        // Grid
        val gridStep = 20f
        var gx = 0f
        while (gx < size.width) {
            drawLine(LcarsRed.copy(0.05f), Offset(gx, 0f), Offset(gx, size.height), 1f)
            gx += gridStep
        }
        var gy = 0f
        while (gy < size.height) {
            drawLine(LcarsRed.copy(0.05f), Offset(0f, gy), Offset(size.width, gy), 1f)
            gy += gridStep
        }

        // Particles
        val now = System.currentTimeMillis()
        particles.forEach { p ->
            val age = (now - p.born).toFloat() / p.lifetime
            val alpha = (1f - age).coerceIn(0f, 1f)
            val px = p.x * size.width
            val py = p.y * size.height
            drawCircle(LcarsYellow.copy(alpha = alpha), 4f, Offset(px, py))
            drawCircle(LcarsYellow.copy(alpha = alpha * 0.3f), 10f, Offset(px, py))
        }
    }
}
