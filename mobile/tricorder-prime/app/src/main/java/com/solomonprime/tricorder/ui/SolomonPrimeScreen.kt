package com.solomonprime.tricorder.ui

import android.speech.tts.TextToSpeech
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.solomonprime.tricorder.data.SolomonPrimeClient
import com.solomonprime.tricorder.data.SolomonPrimeConfigStore
import com.solomonprime.tricorder.ui.theme.LcarsBlue
import com.solomonprime.tricorder.ui.theme.LcarsDarkPanel
import com.solomonprime.tricorder.ui.theme.LcarsOrange
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale

@Composable
fun SolomonPrimeScreen() {
    val context = LocalContext.current
    val store = remember { SolomonPrimeConfigStore(context.applicationContext) }
    val client = remember { SolomonPrimeClient(store) }
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(store.baseUrl) }
    var key by remember { mutableStateOf("") }
    var prompt by remember { mutableStateOf("") }
    var output by remember { mutableStateOf("Configure a trusted HTTPS gateway, then test the connection.") }
    var busy by remember { mutableStateOf(false) }
    var speakReplies by remember { mutableStateOf(true) }
    val tts = remember { TextToSpeech(context) { } }
    DisposableEffect(Unit) { tts.language = Locale.US; onDispose { tts.shutdown() } }

    fun run(block: () -> SolomonPrimeClient.Result) {
        if (busy) return
        busy = true
        scope.launch {
            val result = withContext(Dispatchers.IO) { block() }
            output = result.text
            busy = false
            if (result.ok && speakReplies) tts.speak(result.text.take(3500), TextToSpeech.QUEUE_FLUSH, null, "solomon-reply")
        }
    }

    Column(Modifier.fillMaxSize().background(Color.Black).padding(12.dp).verticalScroll(rememberScrollState())) {
        Text("SOLOMONPRIME LINK", color = LcarsOrange, fontFamily = FontFamily.Monospace)
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(url, { url = it }, label = { Text("HTTPS gateway URL") }, modifier = Modifier.fillMaxWidth())
        OutlinedTextField(key, { key = it }, label = { Text("Tricorder token (shown once in Admin)") }, modifier = Modifier.fillMaxWidth())
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            LcarsButton("SAVE", onClick = { store.baseUrl = url; if (key.isNotBlank()) { store.saveApiKey(key); key = "" }; output = "Limited Tricorder token stored with Android Keystore-backed encryption." })
            LcarsButton("TEST", onClick = { store.baseUrl = url; run { client.health() } })
            LcarsButton("FORGET TOKEN", onClick = { store.clearApiKey(); output = "Local Tricorder token removed." })
        }
        Spacer(Modifier.height(12.dp))
        Row { androidx.compose.material3.Switch(speakReplies, { speakReplies = it }); Text(" Speak replies", color = LcarsBlue) }
        OutlinedTextField(prompt, { prompt = it }, label = { Text("Ask SolomonPrime") }, modifier = Modifier.fillMaxWidth(), minLines = 3)
        LcarsButton(if (busy) "WORKING" else "SEND", onClick = {
            val message = prompt.trim()
            if (message.isNotEmpty()) run { client.chat(message) }
        })
        Spacer(Modifier.height(12.dp))
        Box(Modifier.fillMaxWidth().background(LcarsDarkPanel).padding(12.dp)) {
            Text(output, color = LcarsBlue, fontFamily = FontFamily.Monospace)
        }
        Spacer(Modifier.height(8.dp))
        Text("Chat uses SolomonPrime's governed tool bridge. Device-control approvals remain in Admin; voice alone never authorizes a critical action.", color = LcarsOrange)
    }
}
