package com.solomonprime.tricorder.ui

import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.*
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.ViewModelProvider
import android.app.Application
import com.solomonprime.tricorder.ui.theme.*
import com.solomonprime.tricorder.viewmodel.AcousticViewModel
import kotlin.math.sin

@Composable
fun AcousticScannerScreen() {
    val context = LocalContext.current
    val viewModel: AcousticViewModel = viewModel(
        factory = object : ViewModelProvider.Factory {
            override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return AcousticViewModel(
                    context.applicationContext as Application
                ) as T
            }
        }
    )
    var hasPermission by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        )
    }
    
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission()
    ) { granted ->
        hasPermission = granted
        if (granted) {
            viewModel.startRecording()
        }
    }
    
    // Request permission on first composition if not granted
    LaunchedEffect(Unit) {
        if (!hasPermission) {
            permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }
    
    // Collect real-time state from ViewModel
    val waveformData by viewModel.waveform.collectAsState()
    val dbLevel by viewModel.decibels.collectAsState()
    val peakFrequency by viewModel.dominantFrequency.collectAsState()
    val freqBand by viewModel.freqBand.collectAsState()
    val scoEnabled by viewModel.scoEnabled.collectAsState()
    
    // Start/stop recording based on lifecycle
    DisposableEffect(hasPermission) {
        if (hasPermission) {
            viewModel.startRecording()
        }
        onDispose { viewModel.stopRecording() }
    }
    
    // Generate FFT-style data from waveform for visualization
    // Generate FFT-style data for visualization
    val fftData = remember(waveformData) {
        if (waveformData.isEmpty() || waveformData.size < 2) {
            List(64) { 0f }
        } else {
            val avgLevel = waveformData.map { kotlin.math.abs(it) }.average().toFloat().coerceIn(0f, 1f)
            List(64) { i ->
                val base = avgLevel * (1f - i * 0.008f)
                val waveIdx = (i * waveformData.size / 64).coerceIn(0, waveformData.lastIndex)
                val sample = kotlin.math.abs(waveformData[waveIdx])
                (base + sample * 0.3f).coerceIn(0f, 1f)
            }
        }
    }

    LcarsScreenScaffold(title = "ACO SCANNER", headerColor = LcarsPurple) {
        
        // Permission hint - show if waveform looks simulated (no real variation)
        val isSimulated = remember(waveformData) {
            waveformData.isEmpty() || waveformData.all { kotlin.math.abs(it) < 0.5f }
        }
        if (isSimulated) {
            Text(
                text = "⚠️ MICROPHONE ACCESS REQUIRED FOR LIVE DATA",
                color = LcarsOrange.copy(0.8f),
                fontSize = 10.sp,
                fontFamily = FontFamily.Monospace,
                modifier = Modifier.padding(bottom = 4.dp)
            )
        }

        // Toggles
        Row(Modifier.fillMaxWidth(), Arrangement.SpaceBetween, Alignment.CenterVertically) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("BT MIC", color = if (scoEnabled) LcarsPurple else LcarsTan.copy(0.4f),
                    fontSize = 10.sp, fontFamily = FontFamily.Monospace, fontWeight = androidx.compose.ui.text.font.FontWeight.Bold)
                Spacer(Modifier.width(4.dp))
                Switch(checked = scoEnabled, onCheckedChange = { viewModel.toggleBluetoothSco(it) },
                    colors = SwitchDefaults.colors(checkedThumbColor = LcarsPurple, uncheckedThumbColor = LcarsTan))
            }
        }
        
        Spacer(Modifier.height(8.dp))

        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            LcarsAnimatedValue(value = dbLevel, label = "LEVEL", unit = "dB", color = LcarsPurple)
            LcarsAnimatedValue(value = peakFrequency, label = "PEAK FREQ", unit = "Hz", color = LcarsYellow, decimalPlaces = 0)
        }

        Spacer(Modifier.height(12.dp))

        // Oscilloscope waveform (top)
        Text("WAVEFORM", color = LcarsPurple.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
        Spacer(Modifier.height(4.dp))
        OscilloscopeView(
            data = waveformData,
            modifier = Modifier.fillMaxWidth().height(120.dp)
        )

        Spacer(Modifier.height(12.dp))

        // Frequency spectrum (bottom)
        Text("FREQUENCY SPECTRUM", color = LcarsYellow.copy(0.6f), fontSize = 10.sp, fontFamily = FontFamily.Monospace, letterSpacing = 2.sp)
        Spacer(Modifier.height(4.dp))
        FrequencySpectrum(
            data = fftData,
            modifier = Modifier.fillMaxWidth().height(120.dp)
        )

        Spacer(Modifier.height(12.dp))

        LcarsBarGraph(
            data = listOf(
                "LOW" to (fftData.take(16).takeIf { it.isNotEmpty() }?.average()?.toFloat() ?: 0f),
                "MID" to (fftData.drop(16).take(24).takeIf { it.isNotEmpty() }?.average()?.toFloat() ?: 0f),
                "HIGH" to (fftData.drop(40).takeIf { it.isNotEmpty() }?.average()?.toFloat() ?: 0f),
                "dB" to (dbLevel / 120f).coerceIn(0f, 1f)
            )
        )
    }
}

@Composable
private fun OscilloscopeView(data: List<Float>, modifier: Modifier) {
    val safeData = if (data.isEmpty()) List(50) { 0f } else data
    val infiniteTransition = rememberInfiniteTransition(label = "oscPhase")
    val phase by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 6.28f,
        animationSpec = infiniteRepeatable(tween(2000, easing = LinearEasing)),
        label = "phase"
    )

    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height
        val midY = h / 2f

        // Background
        drawRect(LcarsDarkPanel)

        // Grid lines
        for (i in 1..3) {
            val y = h * i / 4f
            drawLine(LcarsTan.copy(0.08f), Offset(0f, y), Offset(w, y), 1f)
        }
        for (i in 1..7) {
            val x = w * i / 8f
            drawLine(LcarsTan.copy(0.08f), Offset(x, 0f), Offset(x, h), 1f)
        }
        // Center line
        drawLine(LcarsTan.copy(0.15f), Offset(0f, midY), Offset(w, midY), 1f)

        // Waveform path
        if (data.isNotEmpty()) {
            val path = Path()
            val step = w / (safeData.size - 1).coerceAtLeast(1)
            safeData.forEachIndexed { i, v ->
                val x = i * step
                val sampleVal = v * sin(phase + i * 0.1f) // subtle animation
                val y = midY - sampleVal * midY * 0.8f
                if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
            }
            drawPath(path, LcarsPurple, style = Stroke(2f))
            // Glow
            drawPath(path, LcarsPurple.copy(alpha = 0.2f), style = Stroke(6f))
        }
    }
}

@Composable
private fun FrequencySpectrum(data: List<Float>, modifier: Modifier) {
    var appeared by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { appeared = true }

    Canvas(modifier = modifier) {
        val w = size.width
        val h = size.height

        drawRect(LcarsDarkPanel)

        if (data.isEmpty()) return@Canvas

        val barCount = data.size
        val totalGap = barCount * 2f
        val barW = ((w - totalGap) / barCount).coerceAtLeast(2f)

        data.forEachIndexed { i, magnitude ->
            val x = i * (barW + 2f)
            val barH = magnitude.coerceIn(0f, 1f) * h * (if (appeared) 1f else 0f)

            // Color by frequency band
            val color = when {
                i < barCount * 0.25f -> LcarsPurple   // sub-bass / bass
                i < barCount * 0.5f -> LcarsBlue      // low-mid
                i < barCount * 0.75f -> LcarsYellow   // high-mid
                else -> LcarsRed                        // treble
            }

            drawRect(
                color = color,
                topLeft = Offset(x, h - barH),
                size = Size(barW, barH)
            )
        }
    }
}
