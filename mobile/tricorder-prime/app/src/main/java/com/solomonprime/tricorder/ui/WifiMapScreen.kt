package com.solomonprime.tricorder.ui

import android.content.res.Configuration
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.rememberTransformableState
import androidx.compose.foundation.gestures.transformable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.input.pointer.pointerInput
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.model.WifiMapPoint
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.WifiMapViewModel
import kotlin.math.cos
import kotlin.math.sin

enum class SignalType { WIFI, BT, UNKNOWN }

data class TriangulationPoint(
    val id: String,
    val name: String,
    val type: SignalType,
    val rssi: Int,
    val distance: Float,
    val angleRad: Float,
    val zOffset: Float,
    val isKnownContact: Boolean
)

data class ProjectedPoint(
    val pt: TriangulationPoint,
    val px: Float,
    val py: Float,
    val pz: Float,
    val depthScale: Float
)

@Composable
fun WifiMapScreen(viewModel: WifiMapViewModel = viewModel()) {
    val points by viewModel.points.collectAsState()
    val isMapping by viewModel.isMapping.collectAsState()

    var isSimulated by remember { mutableStateOf(false) }
    var gestureScale by remember { mutableFloatStateOf(1f) }
    var panOffset by remember { mutableStateOf(Offset.Zero) }
    var userYawDeg by remember { mutableFloatStateOf(0f) }
    var userPitchDeg by remember { mutableFloatStateOf(65f) }
    var isDragging by remember { mutableStateOf(false) }

    val transformState = rememberTransformableState { zoomChange, offsetChange, _ ->
        gestureScale = (gestureScale * zoomChange).coerceIn(0.2f, 5f)
        // If pinch-zooming, don't pan
        if (zoomChange == 1f) {
            // Single finger drag = rotate
            userYawDeg += offsetChange.x * 0.3f
            userPitchDeg = (userPitchDeg - offsetChange.y * 0.3f).coerceIn(10f, 89f)
            isDragging = true
        }
    }

    val config = LocalConfiguration.current
    val isCompact = config.screenWidthDp < 300

    val infiniteTransition = rememberInfiniteTransition(label = "pulse")
    val pulseRadius by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 20f,
        animationSpec = infiniteRepeatable(
            animation = tween(1500, easing = LinearOutSlowInEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "pulseRadius"
    )

    val timeAngle by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(60000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "timeAngle"
    )

    // Use manual rotation if user dragged, otherwise slow auto-rotate
    val effectiveYawDeg = if (isDragging) userYawDeg else userYawDeg + timeAngle * 0.5f

    val knownContactNames = listOf("phone", "iphone", "pixel", "galaxy", "watch", "mac")

    fun isKnownContact(name: String): Boolean {
        val lower = name.lowercase()
        return knownContactNames.any { lower.contains(it) }
    }

    fun determineSignalType(ssid: String): SignalType {
        val lower = ssid.lowercase()
        return when {
            lower.contains("bt") || lower.contains("le-") || lower.contains("watch") || lower.contains("mac") -> SignalType.BT
            ssid.isNotEmpty() -> SignalType.WIFI
            else -> SignalType.UNKNOWN
        }
    }

    val displayPoints = remember(points, isSimulated) {
        val rawPoints = if (isSimulated) {
            val now = System.currentTimeMillis()
            List(50) { i ->
                val isBT = i % 3 == 0
                val isUnk = i % 5 == 0
                val isTarget = i == 7
                val name = when {
                    isTarget -> "Known Phone"
                    isUnk -> ""
                    isBT -> "BT-Device-$i"
                    else -> "WiFi-Net-$i"
                }
                val rssi = -30 - (i * 2) % 65
                val bssid = "00:11:22:33:44:${i.toString(16).padStart(2, '0')}"
                val timestamp = now - (i * 1000L)
                val distance = (-rssi).coerceIn(30, 100).toFloat() * 1.5f
                val angle = Math.toRadians((bssid.hashCode() % 360).toDouble()).toFloat()
                
                // Stable Z for simulated points too
                val zIdx = Math.abs(bssid.hashCode()) % 10
                val zOffset = (zIdx * 15f) - 75f

                TriangulationPoint(
                    id = bssid,
                    name = name,
                    type = if (isUnk) SignalType.UNKNOWN else if (isBT) SignalType.BT else SignalType.WIFI,
                    rssi = rssi,
                    distance = distance,
                    angleRad = angle,
                    zOffset = zOffset,
                    isKnownContact = isKnownContact(name)
                )
            }
        } else {
            points.map { pt ->
                val type = determineSignalType(pt.ssid)
                val distance = (-pt.rssi).coerceIn(30, 100).toFloat() * 1.5f
                val angle = Math.toRadians((pt.bssid.hashCode() % 360).toDouble()).toFloat()
                
                // Stable Z based on BSSID hash so the tag doesn't jump when timestamp updates
                val zIdx = Math.abs(pt.bssid.hashCode()) % 10
                val zOffset = (zIdx * 15f) - 75f

                TriangulationPoint(
                    id = pt.bssid,
                    name = pt.ssid,
                    type = type,
                    rssi = pt.rssi,
                    distance = distance,
                    angleRad = angle,
                    zOffset = zOffset,
                    isKnownContact = isKnownContact(pt.ssid)
                )
            }
        }
        // Deduplicate: keep only latest entry per device ID (one dot per device)
        rawPoints.groupBy { it.id }.map { (_, entries) -> entries.maxByOrNull { it.rssi } ?: entries.first() }
    }

    val totalSignals = displayPoints.size
    val nearest = displayPoints.minByOrNull { it.distance }
    val nearestNameAndDist = if (nearest != null) "${nearest.name.ifEmpty { "Unknown" }} (${"%.1f".format(nearest.distance)}m)" else "—"
    val strongest = displayPoints.maxByOrNull { it.rssi }
    val strongestName = strongest?.name?.ifEmpty { "Unknown" } ?: "—"

    LcarsScreenScaffold(title = "SIGNAL TRIANGULATION", headerColor = LcarsPurple) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(12.dp)
        ) {
            // Stats panel
            if (isCompact) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFF1A1A2E), RoundedCornerShape(4.dp))
                        .padding(8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    StatRow("TOTAL", "$totalSignals")
                    StatRow("NEAREST", nearestNameAndDist)
                    StatRow("BEST", strongestName)
                }
            } else {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(Color(0xFF1A1A2E), RoundedCornerShape(4.dp))
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    StatLabel("TOTAL", "$totalSignals")
                    StatLabel("NEAREST", nearestNameAndDist)
                    StatLabel("BEST", strongestName)
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Controls
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                LcarsButton(
                    text = "SIM",
                    onClick = { isSimulated = true },
                    color = if (isSimulated) LcarsOrange else LcarsTan,
                    modifier = Modifier.weight(1f)
                )
                LcarsButton(
                    text = "LIVE",
                    onClick = { isSimulated = false },
                    color = if (!isSimulated) LcarsPurple else LcarsTan,
                    modifier = Modifier.weight(1f)
                )
                if (!isSimulated) {
                    LcarsButton(
                        text = if (isMapping) "STOP" else "SCAN",
                        onClick = { if (isMapping) viewModel.stopMapping() else viewModel.startMapping() },
                        color = if (isMapping) LcarsRed else LcarsPurple,
                        modifier = Modifier.weight(1f)
                    )
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            // Canvas
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
                    .background(Color(0xFF0A0A1A), RoundedCornerShape(8.dp))
                    .transformable(state = transformState)
                    .pointerInput(Unit) {
                        detectDragGestures { change, dragAmount ->
                            change.consume()
                            userYawDeg += dragAmount.x * 0.5f
                            userPitchDeg = (userPitchDeg - dragAmount.y * 0.3f).coerceIn(10f, 89f)
                            isDragging = true
                        }
                    }
            ) {
                Canvas(modifier = Modifier.fillMaxSize()) {
                    val cw = size.width
                    val ch = size.height
                    val cx = cw / 2f
                    val cy = ch / 2f

                    val yawRad = Math.toRadians(effectiveYawDeg.toDouble()).toFloat()
                    val pitchRad = Math.toRadians(userPitchDeg.toDouble()).toFloat()
                    val cosP = cos(pitchRad)
                    val sinP = sin(pitchRad)
                    val cosY = cos(yawRad)
                    val sinY = sin(yawRad)
                    val fov = 400f

                    // Draw 3D cube grid (3ft per cell ≈ 0.9m, scaled to 50px)
                    val gridColor = Color(0xFF222233)
                    val gridColorZ = Color(0xFF1A1A2E)
                    // Grid scales inversely with zoom so it always fills the viewport
                    val gridSize = 250f / gestureScale.coerceAtLeast(0.3f)
                    val step = 50f // ~3ft per grid cell
                    val gridSteps = (gridSize / step).toInt().coerceIn(3, 8)
                    val zLevels = listOf(-gridSize, 0f, gridSize) // bottom, middle, top planes

                    // Floor grid (z = -gridSize)
                    for (i in -gridSteps..gridSteps) {
                        val d = i * step
                        val s1 = project3D(d, -gridSize, -gridSize, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        val e1 = project3D(d, gridSize, -gridSize, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        drawLine(gridColor, s1, e1, strokeWidth = 1f)
                        val s2 = project3D(-gridSize, d, -gridSize, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        val e2 = project3D(gridSize, d, -gridSize, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        drawLine(gridColor, s2, e2, strokeWidth = 1f)
                    }

                    // Middle grid (z = 0)
                    for (i in -gridSteps..gridSteps) {
                        val d = i * step
                        val s1 = project3D(d, -gridSize, 0f, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        val e1 = project3D(d, gridSize, 0f, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        drawLine(gridColor.copy(alpha = 0.5f), s1, e1, strokeWidth = 0.5f)
                        val s2 = project3D(-gridSize, d, 0f, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        val e2 = project3D(gridSize, d, 0f, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                        drawLine(gridColor.copy(alpha = 0.5f), s2, e2, strokeWidth = 0.5f)
                    }

                    // Vertical edges of the cube
                    for (i in listOf(-gridSteps, 0, gridSteps)) {
                        for (j in listOf(-gridSteps, 0, gridSteps)) {
                            val x = i * step; val y = j * step
                            val bot = project3D(x, y, -gridSize, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                            val top = project3D(x, y, gridSize, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset)
                            drawLine(gridColorZ, bot, top, strokeWidth = 0.8f)
                        }
                    }

                    // Project points
                    val projPoints = displayPoints.map { pt ->
                        val x = pt.distance * cos(pt.angleRad)
                        val y = pt.distance * sin(pt.angleRad)
                        val z = pt.zOffset

                        val x1 = x * cosY - y * sinY
                        val y1 = x * sinY + y * cosY

                        val x2 = x1
                        val y2 = y1 * cosP - z * sinP
                        val z2 = y1 * sinP + z * cosP

                        val depth = fov / (fov + z2).coerceAtLeast(1f)
                        val px = cx + panOffset.x + x2 * gestureScale * depth
                        val py = cy + panOffset.y + y2 * gestureScale * depth

                        ProjectedPoint(pt, px, py, z2, depth)
                    }.sortedByDescending { it.pz }

                    // Draw points
                    for (p in projPoints) {
                        val color = when (p.pt.type) {
                            SignalType.BT -> Color(0xFF4488FF)
                            SignalType.WIFI -> Color(0xFF44FF44)
                            SignalType.UNKNOWN -> LcarsOrange
                        }

                        // Drop-line to z=0 plane
                        val dropProj = project3D(
                            p.pt.distance * cos(p.pt.angleRad),
                            p.pt.distance * sin(p.pt.angleRad),
                            0f,
                            gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset
                        )

                        drawLine(
                            color = color.copy(alpha = 0.3f),
                            start = dropProj,
                            end = Offset(p.px, p.py),
                            strokeWidth = 1f * p.depthScale
                        )

                        val radius = ((p.pt.rssi + 100).coerceIn(0, 60) / 60f * 8f + 2f) * gestureScale * p.depthScale
                        drawCircle(color, radius = radius, center = Offset(p.px, p.py))

                        if (p.pt.isKnownContact) {
                            drawCircle(
                                Color.Yellow,
                                radius = radius + (pulseRadius * p.depthScale),
                                center = Offset(p.px, p.py),
                                style = Stroke(width = 2f * p.depthScale)
                            )

                            drawContext.canvas.nativeCanvas.drawText(
                                p.pt.name,
                                p.px + (radius * 1.5f),
                                p.py - (radius),
                                android.graphics.Paint().apply {
                                    this.color = android.graphics.Color.YELLOW
                                    textSize = (24f * gestureScale * p.depthScale).coerceIn(10f, 36f)
                                    isAntiAlias = true
                                }
                            )
                        }
                    }

                    // Origin
                    drawCircle(LcarsRed, radius = 4f * gestureScale, center = project3D(0f, 0f, 0f, gestureScale, fov, cosY, sinY, cosP, sinP, cx, cy, panOffset))
                }

                // Zoom overlay
                Column(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(8.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    LcarsButton(text = "+", onClick = { gestureScale *= 1.2f }, color = LcarsTan, modifier = Modifier.size(40.dp))
                    LcarsButton(text = "−", onClick = { gestureScale /= 1.2f }, color = LcarsTan, modifier = Modifier.size(40.dp))
                    LcarsButton(text = "⟳", onClick = { gestureScale = 1f; panOffset = Offset.Zero; userYawDeg = 0f; userPitchDeg = 65f; isDragging = false }, color = LcarsPurple, modifier = Modifier.size(40.dp))
                }
            }

            Spacer(modifier = Modifier.height(6.dp))

            // Legend
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceEvenly,
                verticalAlignment = Alignment.CenterVertically
            ) {
                LegendDot(color = Color(0xFF44FF44), label = "WIFI")
                LegendDot(color = Color(0xFF4488FF), label = "BT")
                LegendDot(color = LcarsOrange, label = "UNK")
                LegendDot(color = Color.Yellow, label = "TARGET")
            }
        }
    }
}

private fun project3D(
    x: Float, y: Float, z: Float,
    scale: Float, fov: Float,
    cosY: Float, sinY: Float,
    cosP: Float, sinP: Float,
    cx: Float, cy: Float,
    pan: Offset
): Offset {
    val x1 = x * cosY - y * sinY
    val y1 = x * sinY + y * cosY

    val x2 = x1
    val y2 = y1 * cosP - z * sinP
    val z2 = y1 * sinP + z * cosP

    val depth = fov / (fov + z2).coerceAtLeast(1f)
    return Offset(
        cx + pan.x + x2 * scale * depth,
        cy + pan.y + y2 * scale * depth
    )
}

@Composable
private fun StatLabel(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(text = value, color = LcarsOrange, fontWeight = FontWeight.Bold, fontSize = 14.sp)
        Text(text = label, color = LcarsTan.copy(alpha = 0.7f), fontSize = 10.sp)
    }
}

@Composable
private fun StatRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(text = label, color = LcarsTan.copy(alpha = 0.7f), fontSize = 12.sp)
        Text(text = value, color = LcarsOrange, fontWeight = FontWeight.Bold, fontSize = 12.sp)
    }
}

@Composable
private fun LegendDot(color: Color, label: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Canvas(modifier = Modifier.size(10.dp)) {
            drawCircle(color = color, radius = size.minDimension / 2)
        }
        Spacer(modifier = Modifier.width(4.dp))
        Text(text = label, color = LcarsTan.copy(alpha = 0.8f), fontSize = 10.sp)
    }
}
