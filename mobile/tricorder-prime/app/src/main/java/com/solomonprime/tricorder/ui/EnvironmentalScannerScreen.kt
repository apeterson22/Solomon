package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solomonprime.tricorder.ui.theme.*
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun EnvironmentalScannerScreen(
    temperature: Float = 22.5f,
    humidity: Float = 45f,
    pressure: Float = 1013.25f,
    lightLevel: Float = 500f, // lux
    maxLight: Float = 2000f
) {
    LcarsScreenScaffold(title = "ENV SCANNER", headerColor = LcarsYellow) {

        Row(modifier = Modifier.fillMaxWidth().height(180.dp)) {
            // Thermometer vertical bar
            Box(modifier = Modifier.width(60.dp).fillMaxHeight()) {
                ThermometerBar(
                    value = temperature,
                    min = -20f,
                    max = 50f,
                    modifier = Modifier.fillMaxSize()
                )
            }

            Spacer(Modifier.width(16.dp))

            // Pressure gauge (circular arc)
            Box(modifier = Modifier.weight(1f).fillMaxHeight(), contentAlignment = Alignment.Center) {
                PressureGauge(
                    pressure = pressure,
                    min = 950f,
                    max = 1080f,
                    modifier = Modifier.size(150.dp)
                )
            }
        }

        Spacer(Modifier.height(16.dp))

        // Humidity
        LcarsAnimatedValue(value = humidity, label = "HUMIDITY", unit = "%", color = LcarsBlue)

        Spacer(Modifier.height(12.dp))

        // Light level spectrum bar (UV blue → IR red)
        Text(
            "LIGHT SPECTRUM",
            color = LcarsTan.copy(alpha = 0.6f),
            fontSize = 10.sp,
            fontFamily = FontFamily.Monospace,
            letterSpacing = 2.sp
        )
        Spacer(Modifier.height(4.dp))
        LightSpectrumBar(
            value = lightLevel / maxLight,
            modifier = Modifier.fillMaxWidth().height(24.dp)
        )
        Text(
            "${lightLevel.toInt()} lux",
            color = LcarsYellow,
            fontSize = 14.sp,
            fontFamily = FontFamily.Monospace,
            modifier = Modifier.align(Alignment.End)
        )

        Spacer(Modifier.height(12.dp))

        LcarsBarGraph(
            data = listOf(
                "TEMP" to ((temperature + 20f) / 70f),
                "HUM" to (humidity / 100f),
                "PRES" to ((pressure - 950f) / 130f),
                "LUX" to (lightLevel / maxLight)
            )
        )
    }
}

@Composable
private fun ThermometerBar(value: Float, min: Float, max: Float, modifier: Modifier) {
    val fraction by animateFloatAsState(
        targetValue = ((value - min) / (max - min)).coerceIn(0f, 1f),
        animationSpec = spring(dampingRatio = 0.6f),
        label = "therm"
    )

    Canvas(modifier = modifier) {
        val barW = size.width * 0.4f
        val barX = (size.width - barW) / 2f
        val bulbR = size.width * 0.35f

        // Tube background
        drawRoundRect(
            color = LcarsDarkPanel,
            topLeft = Offset(barX, 0f),
            size = Size(barW, size.height - bulbR),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(barW / 2f)
        )

        // Fill
        val fillH = (size.height - bulbR) * fraction
        val topOfFill = size.height - bulbR - fillH
        val fillColor = if (value > 35) LcarsRed else if (value < 5) LcarsBlue else LcarsOrange
        drawRoundRect(
            color = fillColor,
            topLeft = Offset(barX + 4f, topOfFill),
            size = Size(barW - 8f, fillH),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(barW / 4f)
        )

        // Bulb at bottom
        drawCircle(
            color = fillColor,
            radius = bulbR,
            center = Offset(size.width / 2f, size.height - bulbR)
        )
    }
}

@Composable
private fun PressureGauge(pressure: Float, min: Float, max: Float, modifier: Modifier) {
    val fraction by animateFloatAsState(
        targetValue = ((pressure - min) / (max - min)).coerceIn(0f, 1f),
        animationSpec = spring(dampingRatio = 0.7f),
        label = "pressure"
    )

    Box(modifier = modifier, contentAlignment = Alignment.Center) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val r = minOf(size.width, size.height) / 2f * 0.85f
            val cx = size.width / 2f
            val cy = size.height / 2f
            val startAngle = 135f
            val totalSweep = 270f

            // Background arc
            drawArc(
                color = LcarsDarkPanel,
                startAngle = startAngle,
                sweepAngle = totalSweep,
                useCenter = false,
                style = Stroke(width = 16f, cap = StrokeCap.Round),
                topLeft = Offset(cx - r, cy - r),
                size = Size(r * 2, r * 2)
            )

            // Value arc
            drawArc(
                color = LcarsYellow,
                startAngle = startAngle,
                sweepAngle = totalSweep * fraction,
                useCenter = false,
                style = Stroke(width = 14f, cap = StrokeCap.Round),
                topLeft = Offset(cx - r, cy - r),
                size = Size(r * 2, r * 2)
            )

            // Needle
            val needleAngle = Math.toRadians((startAngle + totalSweep * fraction).toDouble())
            val nx = cx + (r - 20f) * cos(needleAngle).toFloat()
            val ny = cy + (r - 20f) * sin(needleAngle).toFloat()
            drawLine(LcarsRed, Offset(cx, cy), Offset(nx, ny), 3f, StrokeCap.Round)
            drawCircle(LcarsRed, 6f, Offset(cx, cy))
        }

        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                "${"%.1f".format(pressure)}",
                color = LcarsYellow,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )
            Text(
                "hPa",
                color = LcarsYellow.copy(alpha = 0.6f),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace
            )
        }
    }
}

@Composable
private fun LightSpectrumBar(value: Float, modifier: Modifier) {
    val animatedVal by animateFloatAsState(
        targetValue = value.coerceIn(0f, 1f),
        animationSpec = tween(800),
        label = "light"
    )
    Canvas(modifier = modifier.clip(RoundedCornerShape(4.dp))) {
        // Full spectrum background
        drawRect(
            brush = Brush.horizontalGradient(
                colors = listOf(LcarsBlue, Color(0xFF00CCFF), Color(0xFF00FF66), LcarsYellow, LcarsOrange, LcarsRed)
            ),
            alpha = 0.2f
        )
        // Filled portion
        drawRect(
            brush = Brush.horizontalGradient(
                colors = listOf(LcarsBlue, Color(0xFF00CCFF), Color(0xFF00FF66), LcarsYellow, LcarsOrange, LcarsRed)
            ),
            size = Size(size.width * animatedVal, size.height)
        )
    }
}
