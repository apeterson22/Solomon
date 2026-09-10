package com.solomonprime.tricorder

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.solomonprime.tricorder.data.AlertMonitorService
import com.solomonprime.tricorder.data.ConnectedDeviceManager
import com.solomonprime.tricorder.data.VoiceAlertManager
import com.solomonprime.tricorder.ui.*
import com.solomonprime.tricorder.ui.theme.LcarsBlack
import com.solomonprime.tricorder.ui.theme.LcarsOrange
import com.solomonprime.tricorder.ui.theme.TricorderTheme
import com.solomonprime.tricorder.viewmodel.BioScannerViewModel
import com.solomonprime.tricorder.viewmodel.RadiationViewModel

class MainActivity : ComponentActivity() {

    private var voiceAlertManager: VoiceAlertManager? = null
    private lateinit var deviceManager: ConnectedDeviceManager

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        voiceAlertManager = VoiceAlertManager(this)
        deviceManager = ConnectedDeviceManager(this)
        deviceManager.start()
        deviceManager.registerAvrcp()

        setContent {
            TricorderTheme {
                PermissionWrapper {
                    TricorderApp(
                        voiceAlertManager = voiceAlertManager!!,
                        deviceManager = deviceManager
                    )
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        voiceAlertManager?.shutdown()
        deviceManager.release()
    }
}

@Composable
fun PermissionWrapper(content: @Composable () -> Unit) {
    // Required for core functionality — location, mic, BT
    val corePermissions = mutableListOf(
        Manifest.permission.ACCESS_FINE_LOCATION,
        Manifest.permission.ACCESS_COARSE_LOCATION,
        Manifest.permission.RECORD_AUDIO
    ).apply {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            add(Manifest.permission.BLUETOOTH_SCAN)
            add(Manifest.permission.BLUETOOTH_CONNECT)
        }
    }

    // Optional — failure does NOT block app
    val optionalPermissions = mutableListOf<String>().apply {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            add(Manifest.permission.POST_NOTIFICATIONS)
        }
        add(Manifest.permission.NFC)
    }

    var coreGranted by remember { mutableStateOf(false) }

    val coreLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { results ->
        // Core granted if all required permissions are granted
        coreGranted = corePermissions.all { results[it] == true }
    }

    val optionalLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestMultiplePermissions()
    ) { /* optional — ignore result */ }

    LaunchedEffect(Unit) {
        coreLauncher.launch(corePermissions.toTypedArray())
        optionalLauncher.launch(optionalPermissions.toTypedArray())
    }

    if (coreGranted) {
        content()
    } else {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(LcarsBlack),
            contentAlignment = Alignment.Center
        ) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(text = "SENSORS OFFLINE", color = LcarsOrange)
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Location, Microphone, and Bluetooth\npermissions are required.",
                    color = LcarsOrange.copy(alpha = 0.7f)
                )
                Spacer(modifier = Modifier.height(16.dp))
                LcarsButton(
                    text = "AUTHORIZE",
                    onClick = { coreLauncher.launch(corePermissions.toTypedArray()) }
                )
            }
        }
    }
}

@Composable
fun TricorderApp(
    voiceAlertManager: VoiceAlertManager,
    deviceManager: ConnectedDeviceManager
) {
    val navController = rememberNavController()
    val navItems = listOf("HOME", "ENV", "GEO", "EM", "ACO", "BIO", "RAD", "MAP", "RF", "OBD", "AI", "SP")

    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route ?: "HOME"

    val radViewModel: RadiationViewModel = viewModel()
    val bioViewModel: BioScannerViewModel = viewModel()

    val coroutineScope = rememberCoroutineScope()
    val alertMonitor = remember {
        AlertMonitorService(radViewModel, bioViewModel, voiceAlertManager)
    }

    LaunchedEffect(alertMonitor) {
        alertMonitor.start(coroutineScope)
    }

    DisposableEffect(alertMonitor) {
        onDispose { alertMonitor.stop() }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(LcarsBlack)
            .systemBarsPadding()
    ) {
        LcarsNavigationBar(
            items = navItems,
            selectedItem = currentRoute,
            onItemSelected = { route ->
                if (route != currentRoute) {
                    navController.navigate(route) {
                        popUpTo(navController.graph.startDestinationId) { saveState = true }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
            },
            activeTabIds = setOf("HOME", "ENV", "GEO", "EM"),
            hasAlert = false
        )

        TricorderNavHost(
            navController = navController,
            deviceManager = deviceManager,
            modifier = Modifier
                .fillMaxSize()
                .weight(1f)
        )
    }
}

@Composable
fun TricorderNavHost(
    navController: NavHostController,
    deviceManager: ConnectedDeviceManager,
    modifier: Modifier = Modifier
) {
    NavHost(navController = navController, startDestination = "HOME", modifier = modifier) {
        composable("HOME") { DashboardScreen(deviceManager = deviceManager) }
        composable("ENV")  { EnvironmentalScannerScreen() }
        composable("GEO")  { GeophysicalScannerScreen() }
        composable("EM")   { EmSpectrumScannerScreen() }
        composable("ACO")  { AcousticScannerScreen() }
        composable("BIO")  { BioScannerScreen() }
        composable("RAD")  { RadiationScannerScreen() }
        composable("MAP")  { WifiMapScreen() }
        composable("RF")   { RfSecurityScreen() }
        composable("OBD")  { Obd2Screen() }
        composable("AI")   { AiScreen() }
        composable("SP")   { SolomonPrimeScreen() }
    }
}
