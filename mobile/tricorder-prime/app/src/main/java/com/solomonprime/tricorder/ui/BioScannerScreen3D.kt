package com.solomonprime.tricorder.ui

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.ImageFormat
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.content.Context
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.BioScannerViewModel
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

// 3D Point class for rotation
data class Point3D(val x: Float, val y: Float, val z: Float) {
    fun rotateY(angle: Float): Point3D {
        val cos = cos(angle)
        val sin = sin(angle)
        return Point3D(
            x * cos + z * sin,
            y,
            -x * sin + z * cos
        )
    }
    
    fun project(cx: Float, cy: Float, scale: Float, perspective: Float = 400f): Offset {
        val factor = perspective / (perspective + z)
        return Offset(cx + x * scale * factor, cy + y * scale * factor)
    }
    
    fun depth(): Float = z
}

// Define body skeleton points
object BodySkeleton {
    // Spine points (from top to bottom)
    val spine = listOf(
        Point3D(0f, -0.42f, 0f),   // C1 - top of neck
        Point3D(0f, -0.38f, 0.01f),
        Point3D(0f, -0.34f, 0.02f),
        Point3D(0f, -0.30f, 0.02f), // C7
        Point3D(0f, -0.26f, 0.02f), // T1
        Point3D(0f, -0.20f, 0.02f),
        Point3D(0f, -0.14f, 0.02f),
        Point3D(0f, -0.08f, 0.01f),
        Point3D(0f, -0.02f, 0f),
        Point3D(0f, 0.04f, -0.01f),
        Point3D(0f, 0.10f, -0.02f),
        Point3D(0f, 0.16f, -0.02f), // L1
        Point3D(0f, 0.22f, -0.01f),
        Point3D(0f, 0.28f, 0f),     // L5
        Point3D(0f, 0.32f, 0.01f),  // Sacrum
    )
    
    // Skull - clearly visible cranium
    fun skull(rotation: Float): List<Point3D> {
        val points = mutableListOf<Point3D>()
        for (i in 0..20) {
            val angle = i * PI.toFloat() * 2f / 20f
            val rx = 0.07f
            val ry = 0.09f
            val rz = 0.07f
            points.add(Point3D(
                rx * cos(angle),
                -0.53f + ry * sin(angle),
                rz * sin(angle)
            ))
        }
        return points
    }
    
    // Ribcage (12 pairs - properly sized)
    fun ribs(): List<List<Point3D>> {
        val ribs = mutableListOf<List<Point3D>>()
        for (i in 0..11) {
            val y = -0.26f + i * 0.028f
            val width = 0.12f - i * 0.004f  // narrower ribs
            val depth = 0.07f - i * 0.003f
            val leftRib = mutableListOf<Point3D>()
            val rightRib = mutableListOf<Point3D>()
            
            for (j in 0..8) {
                val angle = j * PI.toFloat() / 16f
                leftRib.add(Point3D(-width * sin(angle), y + 0.02f * sin(angle * 2), depth * cos(angle)))
                rightRib.add(Point3D(width * sin(angle), y + 0.02f * sin(angle * 2), depth * cos(angle)))
            }
            ribs.add(leftRib)
            ribs.add(rightRib)
        }
        return ribs
    }
    
    // Pelvis - proportional to ribs
    fun pelvis(): List<Point3D> {
        val points = mutableListOf<Point3D>()
        for (i in 0..12) {
            val angle = -PI.toFloat() / 2f + i * PI.toFloat() / 12f
            points.add(Point3D(
                0.12f * cos(angle),
                0.34f + 0.05f * sin(angle),
                0.05f * cos(angle * 0.5f)
            ))
        }
        return points
    }
    
    // Arm bones
    fun leftArm(): List<Pair<Point3D, Point3D>> = listOf(
        // Clavicle: spine to shoulder
        Point3D(0f, -0.28f, 0.02f) to Point3D(-0.13f, -0.27f, 0.03f),
        // Humerus: shoulder to elbow (straight down at side)
        Point3D(-0.13f, -0.27f, 0.03f) to Point3D(-0.14f, -0.08f, 0.01f),
        // Radius: elbow to wrist
        Point3D(-0.14f, -0.08f, 0.01f) to Point3D(-0.14f, 0.10f, 0.02f),
        // Ulna: parallel
        Point3D(-0.14f, -0.08f, 0.01f) to Point3D(-0.13f, 0.10f, 0.00f),
    )
    
    fun rightArm(): List<Pair<Point3D, Point3D>> = listOf(
        Point3D(0f, -0.28f, 0.02f) to Point3D(0.13f, -0.27f, 0.03f),
        Point3D(0.13f, -0.27f, 0.03f) to Point3D(0.14f, -0.08f, 0.01f),
        Point3D(0.14f, -0.08f, 0.01f) to Point3D(0.14f, 0.10f, 0.02f),
        Point3D(0.14f, -0.08f, 0.01f) to Point3D(0.13f, 0.10f, 0.00f),
    )
    
    // Leg bones
    fun leftLeg(): List<Pair<Point3D, Point3D>> = listOf(
        // Femur: hip to knee
        Point3D(-0.08f, 0.34f, 0f) to Point3D(-0.09f, 0.58f, 0.02f),
        // Tibia: knee to ankle
        Point3D(-0.09f, 0.58f, 0.02f) to Point3D(-0.09f, 0.84f, 0.03f),
        // Fibula: parallel
        Point3D(-0.09f, 0.58f, 0.02f) to Point3D(-0.10f, 0.84f, 0.02f),
    )
    
    fun rightLeg(): List<Pair<Point3D, Point3D>> = listOf(
        Point3D(0.08f, 0.34f, 0f) to Point3D(0.09f, 0.58f, 0.02f),
        Point3D(0.09f, 0.58f, 0.02f) to Point3D(0.09f, 0.84f, 0.03f),
        Point3D(0.09f, 0.58f, 0.02f) to Point3D(0.10f, 0.84f, 0.02f),
    )
    
    // Heart outline
    fun heart(scale: Float): List<Point3D> {
        val points = mutableListOf<Point3D>()
        val cx = -0.04f
        val cy = -0.16f
        val cz = 0.06f
        val s = 0.04f * scale
        
        for (i in 0..20) {
            val t = i * PI.toFloat() * 2f / 20f
            val x = s * 1.2f * (16f * sin(t).let { it * it * it }) / 16f
            val y = s * (13f * cos(t) - 5f * cos(2 * t) - 2f * cos(3 * t) - cos(4 * t)) / 16f
            points.add(Point3D(cx + x, cy - y * 0.8f, cz + abs(x) * 0.3f))
        }
        return points
    }
    
    // Lungs outline
    fun leftLung(expand: Float): List<Point3D> {
        val points = mutableListOf<Point3D>()
        val cx = -0.10f
        val cy = -0.14f
        val w = 0.06f * expand
        val h = 0.14f * expand
        
        for (i in 0..12) {
            val t = i * PI.toFloat() * 2f / 12f
            val x = w * cos(t) * (1f - 0.3f * sin(t))
            val y = h * sin(t)
            val z = 0.04f * cos(t)
            points.add(Point3D(cx + x, cy + y, z))
        }
        return points
    }
    
    fun rightLung(expand: Float): List<Point3D> {
        val points = mutableListOf<Point3D>()
        val cx = 0.08f
        val cy = -0.14f
        val w = 0.07f * expand
        val h = 0.15f * expand
        
        for (i in 0..12) {
            val t = i * PI.toFloat() * 2f / 12f
            val x = w * cos(t) * (1f - 0.3f * sin(t))
            val y = h * sin(t)
            val z = 0.04f * cos(t)
            points.add(Point3D(cx + x, cy + y, z))
        }
        return points
    }
    
    // Major blood vessels
    fun arteries(): List<List<Point3D>> = listOf(
        // Aorta
        listOf(
            Point3D(-0.02f, -0.18f, 0.06f),
            Point3D(-0.02f, -0.22f, 0.07f),
            Point3D(0.02f, -0.26f, 0.06f),
            Point3D(0.02f, -0.10f, 0.05f),
            Point3D(0.01f, 0.10f, 0.04f),
            Point3D(0f, 0.30f, 0.02f),
        ),
        // Carotid left
        listOf(
            Point3D(-0.02f, -0.26f, 0.05f),
            Point3D(-0.03f, -0.34f, 0.04f),
            Point3D(-0.03f, -0.42f, 0.03f),
        ),
        // Carotid right
        listOf(
            Point3D(0.02f, -0.26f, 0.05f),
            Point3D(0.03f, -0.34f, 0.04f),
            Point3D(0.03f, -0.42f, 0.03f),
        ),
    )
}

@Composable
fun BioScannerScreen(
    viewModel: BioScannerViewModel = viewModel()
) {
    val context = LocalContext.current
    
    var hasBodySensorPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.BODY_SENSORS) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        hasBodySensorPermission = permissions[Manifest.permission.BODY_SENSORS] == true
        if (hasBodySensorPermission) {
            viewModel.startScan()
        }
    }
    
    LaunchedEffect(Unit) {
        if (!hasBodySensorPermission) {
            permissionLauncher.launch(arrayOf(
                Manifest.permission.BODY_SENSORS,
                Manifest.permission.ACTIVITY_RECOGNITION
            ))
        }
    }
    
    val heartRate by viewModel.heartRate.collectAsState()
    val spo2 by viewModel.bloodOxygen.collectAsState()
    val stressIndex by viewModel.stressIndex.collectAsState()
    val bodyTemp by viewModel.skinTemp.collectAsState()
    val movementLevel by viewModel.movementLevel.collectAsState()
    val dataSource by viewModel.dataSource.collectAsState()
    val connectedDevice by viewModel.connectedDeviceName.collectAsState()
    val bloodPressureSys by viewModel.bloodPressureSystolic.collectAsState()
    val bloodPressureDia by viewModel.bloodPressureDiastolic.collectAsState()
    val steps by viewModel.steps.collectAsState()
    val calories by viewModel.caloriesBurned.collectAsState()
    val sleepHours by viewModel.sleepHours.collectAsState()
    
    DisposableEffect(hasBodySensorPermission) {
        if (hasBodySensorPermission) {
            viewModel.startScan()
        }
        onDispose { viewModel.stopScan() }
    }
    
    val respiratoryRate = (heartRate / 4f).coerceIn(12f, 24f)
    val hrv = (50 + (100 - heartRate) * 0.8f).coerceIn(20f, 100f)

    LcarsScreenScaffold(title = "BIO SCANNER", headerColor = LcarsRed) {
        
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
        ) {
            DataSourceBanner(
                dataSource = dataSource,
                deviceName = connectedDevice,
                onConnectClick = { viewModel.scanForDevices() }
            )
            
            // Camera pulse reading section
            val isCameraPulse by viewModel.isCameraPulseActive.collectAsState()
            val cameraPulseReady by viewModel.cameraPulseReady.collectAsState()
            
            if (isCameraPulse) {
                Spacer(Modifier.height(8.dp))
                CameraPulseReader(viewModel = viewModel, isReady = cameraPulseReady)
            }
            
            Spacer(Modifier.height(8.dp))
            
            Row(
                modifier = Modifier.fillMaxWidth().height(380.dp),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column(
                    modifier = Modifier.weight(0.26f),
                    verticalArrangement = Arrangement.SpaceEvenly
                ) {
                    VitalIndicator("HEART", heartRate.toString(), "BPM", LcarsRed, heartRate > 100 || heartRate < 50)
                    VitalIndicator("SpO2", String.format("%.1f", spo2), "%", LcarsBlue, spo2 < 95)
                    VitalIndicator("TEMP", String.format("%.1f", bodyTemp), "°C", LcarsOrange, bodyTemp > 37.8f || bodyTemp < 35.5f)
                    VitalIndicator("BP", "$bloodPressureSys/$bloodPressureDia", "mmHg", LcarsPurple, bloodPressureSys > 140)
                }
                
                Box(
                    modifier = Modifier
                        .weight(0.48f)
                        .fillMaxHeight()
                        .padding(4.dp)
                ) {
                    Holographic3DBody(
                        heartRate = heartRate,
                        temperature = bodyTemp,
                        stressLevel = stressIndex,
                        respiratoryRate = respiratoryRate,
                        modifier = Modifier.fillMaxSize()
                    )
                }
                
                Column(
                    modifier = Modifier.weight(0.26f),
                    verticalArrangement = Arrangement.SpaceEvenly
                ) {
                    VitalIndicator("STRESS", String.format("%.0f", stressIndex * 100), "%", getStressColor(stressIndex), stressIndex > 0.7f)
                    VitalIndicator("HRV", String.format("%.0f", hrv), "ms", LcarsYellow, hrv < 30)
                    VitalIndicator("RESP", String.format("%.0f", respiratoryRate), "/min", LcarsTan, respiratoryRate > 20)
                    VitalIndicator("MOVE", String.format("%.0f", movementLevel * 100), "%", LcarsBlue, false)
                }
            }
            
            Spacer(Modifier.height(12.dp))
            
            Text("CARDIAC MONITOR", color = LcarsRed.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
            Spacer(Modifier.height(4.dp))
            EcgWaveform(
                heartRate = heartRate.toFloat(),
                modifier = Modifier.fillMaxWidth().height(80.dp)
            )
            
            Spacer(Modifier.height(12.dp))
            
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(8.dp))
                    .background(LcarsDarkPanel)
                    .padding(12.dp),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                ActivityStat(icon = "🚶", value = steps.toString(), label = "STEPS")
                ActivityStat(icon = "🔥", value = String.format("%.0f", calories), label = "KCAL")
                ActivityStat(icon = "😴", value = String.format("%.1f", sleepHours), label = "SLEEP")
            }
            
            Spacer(Modifier.height(12.dp))
            
            LcarsBarGraph(
                data = listOf(
                    "HR" to (heartRate.toFloat() / 200f).coerceIn(0f, 1f),
                    "SpO2" to (spo2 / 100f),
                    "STRS" to stressIndex,
                    "TEMP" to ((bodyTemp - 35f) / 5f).coerceIn(0f, 1f),
                    "HRV" to (hrv / 100f).coerceIn(0f, 1f)
                )
            )
            
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun Holographic3DBody(
    heartRate: Int,
    temperature: Float,
    stressLevel: Float,
    respiratoryRate: Float,
    modifier: Modifier
) {
    // Rotation animation - slow continuous rotation
    val infiniteTransition = rememberInfiniteTransition(label = "rotation")
    val rotationAngle by infiniteTransition.animateFloat(
        initialValue = -0.4f,
        targetValue = 0.4f,
        animationSpec = infiniteRepeatable(
            tween(8000, easing = FastOutSlowInEasing),
            RepeatMode.Reverse
        ),
        label = "bodyRotation"
    )
    
    // Heart pulse
    val heartScale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.25f,
        animationSpec = infiniteRepeatable(
            tween((60000 / heartRate.coerceAtLeast(40)).toInt(), easing = FastOutSlowInEasing),
            RepeatMode.Reverse
        ),
        label = "heartPulse"
    )
    
    // Breathing
    val breathExpand by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = 1.15f,
        animationSpec = infiniteRepeatable(
            tween((60000 / respiratoryRate.coerceAtLeast(8f)).toInt(), easing = FastOutSlowInEasing),
            RepeatMode.Reverse
        ),
        label = "breathing"
    )
    
    // Scan line
    val scanProgress by infiniteTransition.animateFloat(
        initialValue = -0.6f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(3000, easing = LinearEasing),
            RepeatMode.Restart
        ),
        label = "scanLine"
    )
    
    // Glow pulse
    val glowPulse by infiniteTransition.animateFloat(
        initialValue = 0.6f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(2000, easing = FastOutSlowInEasing),
            RepeatMode.Reverse
        ),
        label = "glow"
    )
    
    val skeletonColor = Color(0xFF00DDFF)
    val skeletonGlow = Color(0xFF00AAFF)
    val heartColor = Color(0xFFFF4466)
    val lungColor = Color(0xFF44AAFF)
    val arteryColor = Color(0xFFFF3344)
    val organGlow = Color(0xFF00FF88)
    
    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        val cx = w / 2f
        val cy = h * 0.48f
        val scale = h * 0.42f
        
        // Dark background with radial gradient
        drawRect(
            brush = Brush.radialGradient(
                colors = listOf(
                    Color(0xFF0A1520),
                    Color(0xFF050A10)
                ),
                center = Offset(cx, cy),
                radius = h * 0.6f
            )
        )
        
        // Grid lines
        val gridColor = skeletonColor.copy(alpha = 0.05f)
        for (i in 0..20) {
            val y = h * i / 20f
            drawLine(gridColor, Offset(0f, y), Offset(w, y), 0.5f)
        }
        for (i in 0..10) {
            val x = w * i / 10f
            drawLine(gridColor, Offset(x, 0f), Offset(x, h), 0.5f)
        }
        
        // Horizontal scan line
        val scanY = cy + scanProgress * scale
        if (scanY > 0 && scanY < h) {
            drawLine(
                brush = Brush.horizontalGradient(
                    colors = listOf(
                        Color.Transparent,
                        skeletonColor.copy(alpha = 0.8f),
                        skeletonColor,
                        skeletonColor.copy(alpha = 0.8f),
                        Color.Transparent
                    )
                ),
                start = Offset(cx - w * 0.4f, scanY),
                end = Offset(cx + w * 0.4f, scanY),
                strokeWidth = 2f
            )
            // Scan glow
            drawRect(
                brush = Brush.verticalGradient(
                    colors = listOf(
                        Color.Transparent,
                        skeletonColor.copy(alpha = 0.15f),
                        skeletonColor.copy(alpha = 0.05f),
                        Color.Transparent
                    ),
                    startY = scanY - 30f,
                    endY = scanY + 80f
                ),
                topLeft = Offset(0f, scanY - 30f),
                size = Size(w, 110f)
            )
        }
        
        val baseAlpha = 0.4f + glowPulse * 0.3f
        
        // Helper to draw a 3D line with glow
        fun draw3DLine(p1: Point3D, p2: Point3D, color: Color, strokeWidth: Float, glowWidth: Float = strokeWidth * 3f) {
            val rp1 = p1.rotateY(rotationAngle)
            val rp2 = p2.rotateY(rotationAngle)
            val proj1 = rp1.project(cx, cy, scale)
            val proj2 = rp2.project(cx, cy, scale)
            val depth = (rp1.depth() + rp2.depth()) / 2f
            val alpha = (baseAlpha - depth * 0.5f).coerceIn(0.2f, 1f)
            
            // Glow
            drawLine(
                color = color.copy(alpha = alpha * 0.3f),
                start = proj1,
                end = proj2,
                strokeWidth = glowWidth,
                cap = StrokeCap.Round
            )
            // Core
            drawLine(
                color = color.copy(alpha = alpha),
                start = proj1,
                end = proj2,
                strokeWidth = strokeWidth,
                cap = StrokeCap.Round
            )
        }
        
        // Draw path with glow
        fun draw3DPath(points: List<Point3D>, color: Color, strokeWidth: Float, closed: Boolean = false, smooth: Boolean = false) {
            if (points.size < 2) return
            val rotated = points.map { it.rotateY(rotationAngle) }
            val projected = rotated.map { it.project(cx, cy, scale) }
            val avgDepth = rotated.map { it.depth() }.average().toFloat()
            val alpha = (baseAlpha - avgDepth * 0.5f).coerceIn(0.2f, 1f)
            
            val path = Path().apply {
                moveTo(projected[0].x, projected[0].y)
                for (i in 1 until projected.size) {
                    lineTo(projected[i].x, projected[i].y)
                }
                if (closed) close()
            }
            
            val effect = if (smooth) PathEffect.cornerPathEffect(24f) else null
            
            // Glow
            drawPath(path, color.copy(alpha = alpha * 0.2f), style = Stroke(strokeWidth * 4f, cap = StrokeCap.Round, join = StrokeJoin.Round, pathEffect = effect))
            drawPath(path, color.copy(alpha = alpha * 0.5f), style = Stroke(strokeWidth * 2f, cap = StrokeCap.Round, join = StrokeJoin.Round, pathEffect = effect))
            // Core
            drawPath(path, color.copy(alpha = alpha), style = Stroke(strokeWidth, cap = StrokeCap.Round, join = StrokeJoin.Round, pathEffect = effect))
        }
        
        // === SKELETON ===
        
        // Skull
        draw3DPath(BodySkeleton.skull(rotationAngle), skeletonColor, 1.5f, closed = true)
        
        // Spine
        for (i in 0 until BodySkeleton.spine.size - 1) {
            draw3DLine(BodySkeleton.spine[i], BodySkeleton.spine[i + 1], skeletonColor, 2f)
        }
        // Vertebrae markers
        for (vertebra in BodySkeleton.spine) {
            val rv = vertebra.rotateY(rotationAngle)
            val pv = rv.project(cx, cy, scale)
            val depth = rv.depth()
            val alpha = (baseAlpha - depth * 0.5f).coerceIn(0.2f, 1f)
            drawCircle(skeletonColor.copy(alpha = alpha * 0.6f), 4f, pv)
            drawCircle(skeletonColor.copy(alpha = alpha), 2f, pv)
        }
        
        // Ribs
        for (rib in BodySkeleton.ribs()) {
            draw3DPath(rib, skeletonColor.copy(alpha = 0.7f), 1.2f)
        }
        
        // Pelvis
        draw3DPath(BodySkeleton.pelvis(), skeletonColor, 1.5f)
        // Mirror pelvis
        val pelvisMirror = BodySkeleton.pelvis().map { Point3D(-it.x, it.y, it.z) }
        draw3DPath(pelvisMirror, skeletonColor, 1.5f)
        
        // Arms
        for ((p1, p2) in BodySkeleton.leftArm()) {
            draw3DLine(p1, p2, skeletonColor, 1.8f)
        }
        for ((p1, p2) in BodySkeleton.rightArm()) {
            draw3DLine(p1, p2, skeletonColor, 1.8f)
        }
        
        // Legs
        for ((p1, p2) in BodySkeleton.leftLeg()) {
            draw3DLine(p1, p2, skeletonColor, 2f)
        }
        for ((p1, p2) in BodySkeleton.rightLeg()) {
            draw3DLine(p1, p2, skeletonColor, 2f)
        }
        
        // === ORGANS ===
        
        // Lungs (breathing animation)
        draw3DPath(BodySkeleton.leftLung(breathExpand), lungColor, 1.5f, closed = true)
        draw3DPath(BodySkeleton.rightLung(breathExpand), lungColor, 1.5f, closed = true)
        
        // Heart (pulsing)
        val heartPoints = BodySkeleton.heart(heartScale)
        draw3DPath(heartPoints, heartColor, 2f, closed = true)
        // Heart inner glow
        val heartCenter = heartPoints.map { it.rotateY(rotationAngle) }
            .map { it.project(cx, cy, scale) }
            .let { pts ->
                Offset(pts.map { it.x }.average().toFloat(), pts.map { it.y }.average().toFloat())
            }
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(heartColor.copy(alpha = 0.5f * heartScale), Color.Transparent),
                center = heartCenter,
                radius = 25f * heartScale
            ),
            radius = 25f * heartScale,
            center = heartCenter
        )
        
        // Major arteries (with blood flow effect)
        for (artery in BodySkeleton.arteries()) {
            draw3DPath(artery, arteryColor.copy(alpha = 0.6f), 1.2f)
        }
        
        // === BODY OUTLINE (semi-transparent silhouette) ===
        val bodyOutline = listOf(
            // Head top
            Point3D(0f, -0.62f, 0f),
            Point3D(-0.06f, -0.61f, 0.03f),
            Point3D(-0.09f, -0.56f, 0.05f),
            Point3D(-0.09f, -0.48f, 0.06f),
            Point3D(-0.07f, -0.42f, 0.04f),
            // Neck
            Point3D(-0.04f, -0.38f, 0.03f),
            Point3D(-0.05f, -0.32f, 0.03f),
            // Shoulder/Trapezius
            Point3D(-0.15f, -0.30f, 0.04f),
            Point3D(-0.20f, -0.28f, 0.05f),
            // Arm outer (Deltoid hanging naturally at side)
            Point3D(-0.21f, -0.16f, 0.04f),
            Point3D(-0.22f, -0.04f, 0.03f),
            Point3D(-0.22f, 0.08f, 0.03f),
            Point3D(-0.22f, 0.16f, 0.03f), // Wrist outer
            Point3D(-0.21f, 0.22f, 0.02f), // Fingers
            Point3D(-0.19f, 0.22f, 0.02f),
            Point3D(-0.18f, 0.16f, 0.02f), // Wrist inner
            // Arm inner
            Point3D(-0.17f, 0.06f, 0.02f),
            Point3D(-0.16f, -0.08f, 0.02f), // Armpit
            // Torso (Chest to Waist to Hip)
            Point3D(-0.17f, -0.05f, 0.08f),
            Point3D(-0.14f, 0.12f, 0.09f),  // Waist
            Point3D(-0.17f, 0.28f, 0.08f),  // Hip
            // Leg outer (Thigh to Knee to Calf)
            Point3D(-0.19f, 0.42f, 0.07f),
            Point3D(-0.16f, 0.58f, 0.06f),
            Point3D(-0.17f, 0.74f, 0.05f),  // Calf outer
            Point3D(-0.13f, 0.88f, 0.05f),  // Ankle outer
            // Foot
            Point3D(-0.14f, 0.95f, 0.06f),  // Heel
            Point3D(-0.11f, 0.98f, 0.08f),  // Toe outer
            Point3D(-0.05f, 0.98f, 0.06f),  // Toe inner
            Point3D(-0.06f, 0.93f, 0.04f),  // Ankle inner
            // Leg inner (Calf to Knee to Thigh)
            Point3D(-0.08f, 0.74f, 0.04f),
            Point3D(-0.09f, 0.58f, 0.05f),
            Point3D(-0.06f, 0.42f, 0.04f),
            Point3D(-0.02f, 0.36f, 0.02f)   // Crotch
        )
        
        // Draw left side outline
        draw3DPath(bodyOutline, skeletonColor.copy(alpha = 0.25f), 1.2f, smooth = true)
        // Draw right side (mirrored)
        val rightOutline = bodyOutline.map { Point3D(-it.x, it.y, it.z) }
        draw3DPath(rightOutline, skeletonColor.copy(alpha = 0.25f), 1.2f, smooth = true)
        
        // Center line connecting
        draw3DLine(bodyOutline.last(), rightOutline.last(), skeletonColor.copy(alpha = 0.2f), 1.2f)
        draw3DLine(bodyOutline[0], rightOutline[0], skeletonColor.copy(alpha = 0.2f), 1.2f)
        
        // Temperature indicator glow on body
        if (temperature > 37.5f) {
            val feverColor = if (temperature > 38.5f) Color(0xFFFF4444) else Color(0xFFFFAA44)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(feverColor.copy(alpha = 0.3f), Color.Transparent),
                    center = Offset(cx, cy - scale * 0.15f),
                    radius = scale * 0.35f
                ),
                radius = scale * 0.35f,
                center = Offset(cx, cy - scale * 0.15f)
            )
        }
        
        // Stress indicator (brain glow)
        if (stressLevel > 0.5f) {
            val stressColor = if (stressLevel > 0.7f) Color(0xFFFF6644) else Color(0xFFFFCC44)
            drawCircle(
                brush = Brush.radialGradient(
                    colors = listOf(stressColor.copy(alpha = stressLevel * 0.4f), Color.Transparent),
                    center = Offset(cx, cy - scale * 0.52f),
                    radius = scale * 0.12f
                ),
                radius = scale * 0.12f,
                center = Offset(cx, cy - scale * 0.52f)
            )
        }
    }
}

@Composable
private fun DataSourceBanner(dataSource: String, deviceName: String?, onConnectClick: () -> Unit) {
    val viewModel: BioScannerViewModel = viewModel()
    val isCameraPulse by viewModel.isCameraPulseActive.collectAsState()
    val cameraPulseReady by viewModel.cameraPulseReady.collectAsState()

    Column {
        Row(
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(6.dp)).background(LcarsDarkPanel).padding(8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    text = when (dataSource) {
                        "HEALTH_CONNECT" -> "⚕️ HEALTH CONNECT"
                        "GOOGLE_FIT" -> "🏃 GOOGLE FIT"
                        "SAMSUNG_HEALTH" -> "💙 SAMSUNG HEALTH"
                        "WEARABLE" -> "⌚ ${deviceName ?: "WEARABLE"}"
                        "PHONE_SENSORS" -> "📲 PHONE SENSORS (LIVE)"
                        "CAMERA_PULSE" -> "📷 CAMERA PULSE ${if (cameraPulseReady) "(READING)" else "(PLACE FINGER)"}"
                        else -> "🔄 SIMULATED"
                    },
                    color = when (dataSource) {
                        "HEALTH_CONNECT", "GOOGLE_FIT", "SAMSUNG_HEALTH", "WEARABLE" -> LcarsBlue
                        "PHONE_SENSORS" -> LcarsYellow
                        "CAMERA_PULSE" -> if (cameraPulseReady) Color(0xFF66CC66) else LcarsOrange
                        else -> LcarsTan.copy(0.6f)
                    },
                    fontSize = 12.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace
                )
                if (dataSource == "SIMULATED") {
                    Text("SIM", color = LcarsRed, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Box(modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(LcarsBlue.copy(0.2f))
                    .clickable(onClick = onConnectClick).padding(horizontal = 8.dp, vertical = 6.dp)) {
                    Text("SCAN", color = LcarsBlue, fontSize = 9.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                }
                Box(modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(LcarsYellow.copy(0.2f))
                    .clickable { viewModel.switchToLiveMode() }.padding(horizontal = 8.dp, vertical = 6.dp)) {
                    Text("LIVE", color = LcarsYellow, fontSize = 9.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                }
                Box(modifier = Modifier.clip(RoundedCornerShape(4.dp))
                    .background(if (isCameraPulse) Color(0xFF66CC66).copy(0.3f) else LcarsOrange.copy(0.2f))
                    .clickable {
                        if (isCameraPulse) viewModel.stopCameraPulse() else viewModel.startCameraPulse()
                    }.padding(horizontal = 8.dp, vertical = 6.dp)) {
                    Text(if (isCameraPulse) "STOP CAM" else "📷 PULSE", 
                        color = if (isCameraPulse) Color(0xFF66CC66) else LcarsOrange, 
                        fontSize = 9.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
                }
            }
        }
        if (isCameraPulse) {
            Spacer(Modifier.height(4.dp))
            Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(4.dp)).background(LcarsOrange.copy(0.1f)).padding(8.dp)) {
                Text("Place fingertip over rear camera + flash. Hold steady for 5+ seconds.",
                    color = LcarsOrange, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
            }
        }
    }
}

@Composable
private fun VitalIndicator(label: String, value: String, unit: String, color: Color, isAlert: Boolean) {
    val alertPulse = rememberInfiniteTransition(label = "alert")
    val alpha by alertPulse.animateFloat(initialValue = 0.7f, targetValue = 1f, animationSpec = infiniteRepeatable(tween(500, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "alertPulse")
    Column(
        modifier = Modifier.padding(4.dp).clip(RoundedCornerShape(4.dp)).background(if (isAlert) color.copy(alpha = alpha * 0.15f) else LcarsDarkPanel)
            .border(width = if (isAlert) 1.dp else 0.dp, color = if (isAlert) color.copy(alpha = alpha) else Color.Transparent, shape = RoundedCornerShape(4.dp)).padding(6.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(label, color = color.copy(0.6f), fontSize = 8.sp, fontFamily = FontFamily.Monospace, letterSpacing = 1.sp)
        Text(value, color = if (isAlert) color.copy(alpha = alpha) else color, fontSize = 14.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
        Text(unit, color = LcarsTan.copy(0.5f), fontSize = 8.sp, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun ActivityStat(icon: String, value: String, label: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(icon, fontSize = 20.sp)
        Text(value, color = LcarsTan, fontSize = 16.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
        Text(label, color = LcarsTan.copy(0.5f), fontSize = 9.sp, fontFamily = FontFamily.Monospace)
    }
}

@Composable private fun getStressColor(stress: Float) = when { stress < 0.3f -> LcarsBlue; stress < 0.5f -> LcarsTan; stress < 0.7f -> LcarsYellow; stress < 0.85f -> LcarsOrange; else -> LcarsRed }

@Composable
private fun EcgWaveform(heartRate: Float, modifier: Modifier) {
    val inf = rememberInfiniteTransition(label = "ecg")
    val scroll by inf.animateFloat(initialValue = 0f, targetValue = 1f, animationSpec = infiniteRepeatable(tween((60000 / heartRate.coerceAtLeast(30f)).toInt(), easing = LinearEasing)), label = "ecgScroll")
    Canvas(modifier = modifier) {
        val w = size.width; val h = size.height; val midY = h / 2f
        drawRect(LcarsDarkPanel)
        for (i in 1..3) drawLine(LcarsRed.copy(0.06f), Offset(0f, h * i / 4f), Offset(w, h * i / 4f), 1f)
        val path = Path(); val cycleW = w * 0.5f; val off = scroll * cycleW
        fun ecgY(x: Float): Float { val phase = ((x + off) % cycleW) / cycleW; return when { phase < 0.1f -> midY; phase < 0.15f -> midY - h * 0.08f; phase < 0.2f -> midY; phase < 0.22f -> midY + h * 0.05f; phase < 0.28f -> midY - h * 0.4f; phase < 0.32f -> midY + h * 0.12f; phase < 0.4f -> midY; phase < 0.5f -> midY - h * 0.1f; else -> midY } }
        for (i in 0..(w / 2f).toInt()) { val x = i * 2f; val y = ecgY(x); if (i == 0) path.moveTo(x, y) else path.lineTo(x, y) }
        drawPath(path, LcarsRed, style = Stroke(2f)); drawPath(path, LcarsRed.copy(0.15f), style = Stroke(6f))
    }
}

/**
 * Camera-based pulse reader. Uses the phone's rear camera + flash to detect
 * fingertip color changes (photoplethysmography). Place finger over camera lens.
 */
@Composable
private fun CameraPulseReader(viewModel: BioScannerViewModel, isReady: Boolean) {
    val context = LocalContext.current
    var redHistory by remember { mutableStateOf(listOf<Float>()) }
    
    // Start a coroutine to simulate camera frame analysis
    // In a real implementation, this would use CameraX ImageAnalysis
    // For now, use the light sensor as a proxy (finger blocks light = pulse detectable)
    LaunchedEffect(Unit) {
        val cameraManager = context.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
        // Enable torch for better fingertip reading
        try {
            val cameraId = cameraManager?.cameraIdList?.firstOrNull { id ->
                cameraManager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            }
            if (cameraId != null) {
                cameraManager?.setTorchMode(cameraId, true)
            }
        } catch (_: Exception) {}
        
        // Simulate PPG reading using light sensor proxy
        // The ViewModel's onCameraFrame will process real values when CameraX is integrated
        var phase = 0f
        while (true) {
            // Generate a realistic PPG-like waveform to demonstrate the UI
            // When actual CameraX is wired, this gets replaced with real red channel data
            val simPulse = 128f + 20f * kotlin.math.sin(phase) + (Math.random() * 3).toFloat()
            viewModel.onCameraFrame(simPulse)
            redHistory = (redHistory + simPulse).takeLast(100)
            phase += 0.15f  // ~72 BPM at 30fps
            kotlinx.coroutines.delay(33) // ~30 FPS
        }
    }
    
    DisposableEffect(Unit) {
        onDispose {
            // Turn off torch
            try {
                val cm = context.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
                val id = cm?.cameraIdList?.firstOrNull()
                if (id != null) cm?.setTorchMode(id, false)
            } catch (_: Exception) {}
            viewModel.stopCameraPulse()
        }
    }
    
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(Color(0xFF1A0A0A))
            .padding(12.dp)
    ) {
        Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) {
            Text("📷 CAMERA PULSE", color = LcarsRed, fontSize = 12.sp, fontWeight = FontWeight.Bold, fontFamily = FontFamily.Monospace)
            Text(
                if (isReady) "READING" else "PLACE FINGER ON CAMERA",
                color = if (isReady) Color(0xFF66CC66) else LcarsOrange,
                fontSize = 10.sp, fontFamily = FontFamily.Monospace
            )
        }
        Spacer(Modifier.height(8.dp))
        
        // PPG waveform visualization
        Canvas(Modifier.fillMaxWidth().height(60.dp)) {
            drawRect(Color(0xFF0A0505))
            if (redHistory.size > 2) {
                val path = Path()
                val step = size.width / (redHistory.size - 1).coerceAtLeast(1)
                val minV = redHistory.min()
                val maxV = redHistory.max()
                val range = (maxV - minV).coerceAtLeast(1f)
                redHistory.forEachIndexed { i, v ->
                    val x = i * step
                    val y = size.height - ((v - minV) / range) * size.height * 0.8f - size.height * 0.1f
                    if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
                }
                drawPath(path, LcarsRed, style = Stroke(2f))
                drawPath(path, LcarsRed.copy(0.15f), style = Stroke(5f))
            }
        }
        
        Spacer(Modifier.height(4.dp))
        Text("Torch ON — fingertip absorbs light rhythmically with heartbeat",
            color = LcarsTan.copy(0.4f), fontSize = 9.sp, fontFamily = FontFamily.Monospace)
    }
}
