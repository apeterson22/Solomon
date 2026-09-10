package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.animateFloatAsState
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
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.*
import androidx.compose.ui.text.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.solomonprime.tricorder.ui.theme.*
import kotlin.math.*
import kotlin.random.Random

// ═══════════════════════════════════════════════════════════════════════
// 1. LcarsAnimatedValue
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsAnimatedValue(
    value: Float,
    label: String = "",
    unit: String = "",
    modifier: Modifier = Modifier,
    color: Color = LcarsOrange,
    decimalPlaces: Int = 1
) {
    val animatedVal by animateFloatAsState(
        targetValue = value,
        animationSpec = spring(dampingRatio = 0.7f, stiffness = 80f),
        label = "value"
    )
    val infiniteTransition = rememberInfiniteTransition(label = "shimmer")
    val shimmerOffset by infiniteTransition.animateFloat(
        initialValue = -1f,
        targetValue = 2f,
        animationSpec = infiniteRepeatable(tween(2000, easing = LinearEasing)),
        label = "shimmer"
    )

    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        if (label.isNotEmpty()) {
            Text(
                text = label.uppercase(),
                color = color.copy(alpha = 0.6f),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 2.sp
            )
        }
        Box {
            val formattedValue = "%.${decimalPlaces}f".format(animatedVal)
            Text(
                text = "$formattedValue $unit",
                color = color,
                fontSize = 28.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )
            // Shimmer overlay
            Canvas(modifier = Modifier.matchParentSize()) {
                val shimmerX = shimmerOffset * size.width
                val brush = Brush.linearGradient(
                    colors = listOf(Color.Transparent, color.copy(alpha = 0.15f), Color.Transparent),
                    start = Offset(shimmerX - 60f, 0f),
                    end = Offset(shimmerX + 60f, 0f)
                )
                drawRect(brush = brush)
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// 2. LcarsBarGraph
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsBarGraph(
    data: List<Pair<String, Float>>,
    modifier: Modifier = Modifier,
    barHeight: Dp = 20.dp,
    blockWidth: Dp = 8.dp,
    blockGap: Dp = 4.dp
) {
    var appeared by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { appeared = true }

    Column(modifier = modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        data.forEachIndexed { idx, (label, value) ->
            val animatedFraction by animateFloatAsState(
                targetValue = if (appeared) value.coerceIn(0f, 1f) else 0f,
                animationSpec = tween(800, delayMillis = idx * 100, easing = FastOutSlowInEasing),
                label = "bar$idx"
            )
            val barColor = LcarsPalette[idx % LcarsPalette.size]

            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = label.uppercase(),
                    color = barColor.copy(alpha = 0.7f),
                    fontSize = 10.sp,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.width(48.dp)
                )
                Canvas(modifier = Modifier.weight(1f).height(barHeight)) {
                    val bw = blockWidth.toPx()
                    val bg = blockGap.toPx()
                    val totalBlocks = ((size.width + bg) / (bw + bg)).toInt()
                    val filledBlocks = (totalBlocks * animatedFraction).toInt()
                    for (i in 0 until filledBlocks) {
                        val x = i * (bw + bg)
                        drawRoundRect(
                            color = barColor,
                            topLeft = Offset(x, 2f),
                            size = Size(bw, size.height - 4f),
                            cornerRadius = androidx.compose.ui.geometry.CornerRadius(2f, 2f)
                        )
                    }
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// 3. LcarsRadarSweep
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsRadarSweep(
    dataPoints: List<Pair<Float, Float>> = emptyList(), // angle (deg), radius (0-1)
    modifier: Modifier = Modifier,
    sweepColor: Color = LcarsOrange,
    dotColor: Color = LcarsBlue
) {
    val infiniteTransition = rememberInfiniteTransition(label = "radar")
    val sweepAngle by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(3000, easing = LinearEasing)),
        label = "sweep"
    )

    Canvas(modifier = modifier.aspectRatio(1f)) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val maxR = minOf(cx, cy) * 0.9f

        // Background
        drawCircle(color = LcarsDarkPanel, radius = maxR, center = Offset(cx, cy))

        // Concentric rings
        for (i in 1..4) {
            drawCircle(
                color = LcarsTan.copy(alpha = 0.12f),
                radius = maxR * i / 4f,
                center = Offset(cx, cy),
                style = Stroke(1f)
            )
        }

        // Cross hairs
        val dimLine = LcarsTan.copy(alpha = 0.08f)
        drawLine(dimLine, Offset(cx - maxR, cy), Offset(cx + maxR, cy), 1f)
        drawLine(dimLine, Offset(cx, cy - maxR), Offset(cx, cy + maxR), 1f)

        // Sweep arc gradient
        val sweepRad = Math.toRadians(sweepAngle.toDouble())
        val arcDeg = 60f
        for (i in 0..30) {
            val angle = sweepRad - Math.toRadians((arcDeg * i / 30.0))
            val alpha = (1f - i / 30f) * 0.4f
            val ex = cx + maxR * cos(angle).toFloat()
            val ey = cy + maxR * sin(angle).toFloat()
            drawLine(
                color = sweepColor.copy(alpha = alpha),
                start = Offset(cx, cy),
                end = Offset(ex, ey),
                strokeWidth = 2f
            )
        }

        // Data points
        dataPoints.forEach { (angleDeg, radius) ->
            val r = radius.coerceIn(0f, 1f) * maxR
            val a = Math.toRadians(angleDeg.toDouble())
            val px = cx + r * cos(a).toFloat()
            val py = cy + r * sin(a).toFloat()
            drawCircle(color = dotColor, radius = 4f, center = Offset(px, py))
            drawCircle(color = dotColor.copy(alpha = 0.3f), radius = 8f, center = Offset(px, py))
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// 4. LcarsFlipCounter
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsFlipCounter(
    value: Int,
    digits: Int = 5,
    modifier: Modifier = Modifier,
    color: Color = LcarsOrange
) {
    val padded = value.toString().padStart(digits, '0')
    Row(modifier = modifier, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        padded.forEach { ch ->
            val target = ch.digitToIntOrNull()?.toFloat() ?: 0f
            val animatedDigit by animateFloatAsState(
                targetValue = target,
                animationSpec = tween(400, easing = FastOutSlowInEasing),
                label = "flip"
            )
            Box(
                modifier = Modifier
                    .size(28.dp, 40.dp)
                    .clip(RoundedCornerShape(4.dp))
                    .background(LcarsDarkPanel),
                contentAlignment = Alignment.Center
            ) {
                // Top half clipped
                Box(modifier = Modifier.fillMaxSize().clipToBounds()) {
                    val displayDigit = animatedDigit.toInt() % 10
                    Text(
                        text = "$displayDigit",
                        color = color,
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        fontFamily = FontFamily.Monospace,
                        modifier = Modifier.align(Alignment.Center)
                    )
                }
                // Divider line
                Canvas(modifier = Modifier.fillMaxWidth().height(1.dp).align(Alignment.Center)) {
                    drawLine(Color.Black, Offset(0f, 0f), Offset(size.width, 0f), 2f)
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// 5. LcarsStatusGrid
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsStatusGrid(
    rows: Int = 3,
    cols: Int = 3,
    modifier: Modifier = Modifier
) {
    val infiniteTransition = rememberInfiniteTransition(label = "statusGrid")
    val cells = remember { List(rows * cols) { Random.nextInt(500, 3000) } }

    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(3.dp)) {
        for (r in 0 until rows) {
            Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
                for (c in 0 until cols) {
                    val idx = r * cols + c
                    val blinkAlpha by infiniteTransition.animateFloat(
                        initialValue = 0.3f,
                        targetValue = 1f,
                        animationSpec = infiniteRepeatable(
                            tween(cells[idx], easing = LinearEasing),
                            RepeatMode.Reverse
                        ),
                        label = "cell$idx"
                    )
                    val cellColor = LcarsPalette[idx % LcarsPalette.size]
                    Box(
                        modifier = Modifier
                            .size(12.dp, 8.dp)
                            .clip(RoundedCornerShape(2.dp))
                            .background(cellColor.copy(alpha = blinkAlpha))
                    )
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// 6. LcarsElbowHeader
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsElbowHeader(
    title: String,
    modifier: Modifier = Modifier,
    color: Color = LcarsOrange,
    elbowWidth: Dp = 48.dp,
    elbowHeight: Dp = 64.dp
) {
    val infiniteTransition = rememberInfiniteTransition(label = "scanLine")
    val scanLineY by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(1500, easing = LinearEasing)),
        label = "scanY"
    )

    Box(modifier = modifier.fillMaxWidth().height(elbowHeight)) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            val ew = elbowWidth.toPx()
            val eh = size.height
            val barW = ew * 0.6f
            val horizH = eh * 0.3f
            val cornerR = barW / 2f

            // Vertical bar (left)
            drawRoundRect(
                color = color,
                topLeft = Offset(0f, 0f),
                size = Size(barW, eh),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(cornerR, cornerR)
            )

            // Horizontal bar (top right)
            drawRoundRect(
                color = color,
                topLeft = Offset(barW + 4f, 0f),
                size = Size(size.width - barW - 4f, horizH),
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(0f, horizH / 2f)
            )

            // Elbow connector
            drawRect(
                color = color,
                topLeft = Offset(barW * 0.5f, 0f),
                size = Size(barW * 0.6f, horizH)
            )

            // Scan line on vertical bar
            val scanY = scanLineY * eh
            drawRect(
                color = LcarsBlue.copy(alpha = 0.7f),
                topLeft = Offset(2f, scanY),
                size = Size(barW - 4f, 4f)
            )
        }

        // Title text
        Text(
            text = title.uppercase(),
            color = LcarsDarkBg,
            fontSize = 16.sp,
            fontWeight = FontWeight.Bold,
            fontFamily = FontFamily.Monospace,
            letterSpacing = 3.sp,
            modifier = Modifier
                .align(Alignment.TopEnd)
                .padding(end = 16.dp, top = 4.dp)
        )
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Utility: LCARS Scan Line (full-width decorative)
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsScanLine(
    modifier: Modifier = Modifier,
    color: Color = LcarsBlue
) {
    val infiniteTransition = rememberInfiniteTransition(label = "hScan")
    val scanX by infiniteTransition.animateFloat(
        initialValue = -0.1f,
        targetValue = 1.1f,
        animationSpec = infiniteRepeatable(tween(2500, easing = LinearEasing)),
        label = "hScanX"
    )
    Canvas(modifier = modifier.fillMaxWidth().height(2.dp)) {
        val x = scanX * size.width
        drawLine(
            brush = Brush.horizontalGradient(
                colors = listOf(Color.Transparent, color, Color.Transparent),
                startX = x - 80f,
                endX = x + 80f
            ),
            start = Offset(0f, size.height / 2),
            end = Offset(size.width, size.height / 2),
            strokeWidth = 2f
        )
    }
}

// ═══════════════════════════════════════════════════════════════════════
// Utility: LCARS Screen Wrapper (standard layout for all screens)
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsScreenScaffold(
    title: String,
    headerColor: Color = LcarsOrange,
    content: @Composable ColumnScope.() -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(LcarsDarkBg)
            .padding(8.dp)
    ) {
        LcarsElbowHeader(title = title, color = headerColor)
        LcarsScanLine()
        Spacer(modifier = Modifier.height(8.dp))

        Box(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.fillMaxWidth().padding(end = 50.dp),
                content = content
            )
            LcarsStatusGrid(
                modifier = Modifier.align(Alignment.TopEnd).padding(top = 4.dp)
            )
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// LcarsScanningIndicator — pulsing scan indicator
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsScanningIndicator(
    isActive: Boolean,
    color: Color = LcarsOrange,
    modifier: Modifier = Modifier
) {
    if (!isActive) return
    val infiniteTransition = rememberInfiniteTransition(label = "scanning")
    val alpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(800, easing = LinearEasing),
            RepeatMode.Reverse
        ),
        label = "scanAlpha"
    )
    Text(
        text = "● SCANNING",
        color = color.copy(alpha = alpha),
        fontSize = 12.sp,
        fontWeight = FontWeight.Bold,
        fontFamily = FontFamily.Monospace,
        modifier = modifier
    )
}

// ═══════════════════════════════════════════════════════════════════════
// LcarsGauge — horizontal bar gauge with label
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsGauge(
    value: Float,
    minValue: Float,
    maxValue: Float,
    label: String,
    unit: String,
    accentColor: Color,
    modifier: Modifier = Modifier
) {
    val fraction by animateFloatAsState(
        targetValue = ((value - minValue) / (maxValue - minValue)).coerceIn(0f, 1f),
        animationSpec = spring(dampingRatio = 0.7f, stiffness = 80f),
        label = "gauge"
    )

    Column(modifier = modifier) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(
                text = label.uppercase(),
                color = accentColor.copy(alpha = 0.7f),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 2.sp
            )
            Text(
                text = "${"%.1f".format(value)} $unit",
                color = accentColor,
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace
            )
        }
        Spacer(modifier = Modifier.height(4.dp))
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(16.dp)
                .clip(RoundedCornerShape(4.dp))
                .background(LcarsDarkPanel)
        ) {
            Box(
                modifier = Modifier
                    .fillMaxHeight()
                    .fillMaxWidth(fraction)
                    .clip(RoundedCornerShape(4.dp))
                    .background(accentColor)
            )
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// LcarsDataCard — compact value display card
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsDataCard(
    title: String,
    value: String,
    unit: String,
    accentColor: Color,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(topStart = 16.dp, bottomEnd = 16.dp))
            .background(LcarsDarkPanel)
            .padding(12.dp)
    ) {
        Column {
            Text(
                text = title.uppercase(),
                color = accentColor.copy(alpha = 0.7f),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 2.sp
            )
            Spacer(modifier = Modifier.height(4.dp))
            Row(
                verticalAlignment = Alignment.Bottom
            ) {
                Text(
                    text = value,
                    color = accentColor,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    fontFamily = FontFamily.Monospace
                )
                Spacer(modifier = Modifier.width(4.dp))
                Text(
                    text = unit,
                    color = accentColor.copy(alpha = 0.6f),
                    fontSize = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    modifier = Modifier.padding(bottom = 2.dp)
                )
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════
// LcarsSectionHeader — simple LCARS-style section header
// ═══════════════════════════════════════════════════════════════════════
@Composable
fun LcarsSectionHeader(
    title: String,
    modifier: Modifier = Modifier,
    color: Color = LcarsOrange
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .width(60.dp)
                .height(28.dp)
                .clip(RoundedCornerShape(topStart = 14.dp, bottomStart = 14.dp))
                .background(color)
        )
        Box(
            modifier = Modifier
                .weight(1f)
                .height(28.dp)
                .background(color),
            contentAlignment = Alignment.CenterEnd
        ) {
            Text(
                text = title.uppercase(),
                color = LcarsDarkBg,
                fontSize = 16.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                letterSpacing = 2.sp,
                modifier = Modifier.padding(end = 12.dp)
            )
        }
        Box(
            modifier = Modifier
                .width(20.dp)
                .height(28.dp)
                .clip(RoundedCornerShape(topEnd = 14.dp, bottomEnd = 14.dp))
                .background(color)
        )
    }
}
