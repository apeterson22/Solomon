package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.GeophysicalViewModel
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun GeophysicalScannerScreen(
    viewModel: GeophysicalViewModel = viewModel()
) {
    // Collect real-time state from ViewModel
    val latitude by viewModel.latitude.collectAsState()
    val longitude by viewModel.longitude.collectAsState()
    val altitude by viewModel.altitude.collectAsState()
    val heading by viewModel.heading.collectAsState()
    val speed by viewModel.speed.collectAsState()

    LcarsScreenScaffold(title = "GEO SCANNER", headerColor = LcarsTan) {

        Row(modifier = Modifier.fillMaxWidth().height(200.dp)) {
            // Compass rose
            CompassRose(
                heading = heading ?: 0f,
                modifier = Modifier.size(180.dp)
            )

            Spacer(Modifier.width(12.dp))

            // Altitude vertical scale
            Column(
                modifier = Modifier.fillMaxHeight().width(60.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("ALT", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
                AltitudeScale(
                    altitude = altitude?.toFloat() ?: 0f,
                    modifier = Modifier.fillMaxHeight().width(40.dp)
                )
            }
        }

        Spacer(Modifier.height(12.dp))

        // GPS accuracy - expanding/contracting circle
        Row(verticalAlignment = Alignment.CenterVertically) {
            GpsAccuracyCircle(
                accuracy = 10f,
                modifier = Modifier.size(60.dp)
            )
            Spacer(Modifier.width(12.dp))
            Column {
                Text("GPS ACCURACY", color = LcarsBlue.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
                LcarsAnimatedValue(value = 10f, unit = "m", color = LcarsBlue, decimalPlaces = 1)
            }
        }

        Spacer(Modifier.height(12.dp))

        // Coordinates
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column {
                Text("LAT", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
                Text("%.6f°".format(latitude ?: 0.0), color = LcarsOrange, fontSize = 16.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            }
            Column(horizontalAlignment = Alignment.End) {
                Text("LON", color = LcarsTan.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace)
                Text("%.6f°".format(longitude ?: 0.0), color = LcarsOrange, fontSize = 16.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
            }
        }

        Spacer(Modifier.height(8.dp))

        LcarsBarGraph(
            data = listOf(
                "SPD" to ((speed ?: 0f) / 50f).coerceIn(0f, 1f),
                "ALT" to ((altitude?.toFloat() ?: 0f) / 5000f).coerceIn(0f, 1f),
                "ACC" to 0.9f,
                "HDG" to ((heading ?: 0f) / 360f)
            )
        )
    }
}

@Composable
private fun CompassRose(heading: Float, modifier: Modifier) {
    val animatedHeading by animateFloatAsState(
        targetValue = heading,
        animationSpec = spring(dampingRatio = 0.6f, stiffness = 100f),
        label = "heading"
    )

    Canvas(modifier = modifier) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val r = minOf(cx, cy) * 0.85f

        // Outer ring
        drawCircle(LcarsTan.copy(alpha = 0.3f), r, Offset(cx, cy), style = Stroke(2f))
        drawCircle(LcarsDarkPanel, r - 4f, Offset(cx, cy))

        // Degree marks
        for (i in 0 until 360 step 10) {
            val rad = Math.toRadians(i.toDouble())
            val inner = if (i % 90 == 0) r * 0.7f else if (i % 30 == 0) r * 0.8f else r * 0.88f
            val outerR = r * 0.95f
            drawLine(
                color = if (i % 90 == 0) LcarsOrange else LcarsTan.copy(0.3f),
                start = Offset(cx + inner * sin(rad).toFloat(), cy - inner * cos(rad).toFloat()),
                end = Offset(cx + outerR * sin(rad).toFloat(), cy - outerR * cos(rad).toFloat()),
                strokeWidth = if (i % 90 == 0) 2f else 1f
            )
        }

        // Cardinal labels
        val labelR = r * 0.6f
        val cardinals = listOf(0f to "N", 90f to "E", 180f to "S", 270f to "W")
        val paint = android.graphics.Paint().apply {
            color = android.graphics.Color.rgb(0xFF, 0x99, 0x00)
            textSize = 16f * density
            textAlign = android.graphics.Paint.Align.CENTER
            typeface = android.graphics.Typeface.MONOSPACE
            isFakeBoldText = true
        }
        cardinals.forEach { (deg, lbl) ->
            val rad = Math.toRadians(deg.toDouble())
            val lx = cx + labelR * sin(rad).toFloat()
            val ly = cy - labelR * cos(rad).toFloat() + 6f * density
            if (lbl == "N") paint.color = android.graphics.Color.rgb(0xFF, 0x66, 0x66)
            else paint.color = android.graphics.Color.rgb(0xFF, 0x99, 0x00)
            drawContext.canvas.nativeCanvas.drawText(lbl, lx, ly, paint)
        }

        // Rotating needle pointing to heading
        rotate(-animatedHeading, Offset(cx, cy)) {
            // North arrow (red)
            val arrowLen = r * 0.45f
            drawLine(LcarsRed, Offset(cx, cy), Offset(cx, cy - arrowLen), 3f, StrokeCap.Round)
            // Arrow head
            drawLine(LcarsRed, Offset(cx, cy - arrowLen), Offset(cx - 8f, cy - arrowLen + 16f), 2f)
            drawLine(LcarsRed, Offset(cx, cy - arrowLen), Offset(cx + 8f, cy - arrowLen + 16f), 2f)
            // South tail
            drawLine(LcarsTan.copy(0.5f), Offset(cx, cy), Offset(cx, cy + arrowLen * 0.6f), 2f)
        }

        // Center dot
        drawCircle(LcarsOrange, 5f, Offset(cx, cy))
    }
}

@Composable
private fun AltitudeScale(altitude: Float, modifier: Modifier) {
    val maxAlt = 5000f
    val fraction by animateFloatAsState(
        targetValue = (altitude / maxAlt).coerceIn(0f, 1f),
        animationSpec = spring(dampingRatio = 0.7f),
        label = "alt"
    )

    Canvas(modifier = modifier) {
        val barW = size.width * 0.5f
        val barX = (size.width - barW) / 2f

        // Scale background
        drawRoundRect(
            color = LcarsDarkPanel,
            topLeft = Offset(barX, 0f),
            size = Size(barW, size.height),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(4f)
        )

        // Fill from bottom
        val fillH = size.height * fraction
        drawRoundRect(
            color = LcarsTan,
            topLeft = Offset(barX + 2f, size.height - fillH),
            size = Size(barW - 4f, fillH),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(2f)
        )

        // Tick marks
        for (i in 0..10) {
            val y = size.height * (1f - i / 10f)
            drawLine(LcarsTan.copy(0.3f), Offset(barX + barW + 2f, y), Offset(size.width, y), 1f)
        }
    }
}

@Composable
private fun GpsAccuracyCircle(accuracy: Float, modifier: Modifier) {
    val infiniteTransition = rememberInfiniteTransition(label = "gps")
    val pulse by infiniteTransition.animateFloat(
        initialValue = 0.8f,
        targetValue = 1.2f,
        animationSpec = infiniteRepeatable(
            tween((accuracy * 50).toInt().coerceIn(300, 2000), easing = FastOutSlowInEasing),
            RepeatMode.Reverse
        ),
        label = "gpsPulse"
    )

    Canvas(modifier = modifier) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val baseR = minOf(cx, cy) * 0.6f
        val r = baseR * pulse

        drawCircle(LcarsBlue.copy(alpha = 0.1f), r, Offset(cx, cy))
        drawCircle(LcarsBlue.copy(alpha = 0.4f), r, Offset(cx, cy), style = Stroke(2f))
        drawCircle(LcarsBlue, 4f, Offset(cx, cy))
    }
}
