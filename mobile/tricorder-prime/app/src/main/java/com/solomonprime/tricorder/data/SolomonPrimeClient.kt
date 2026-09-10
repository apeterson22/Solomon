package com.solomonprime.tricorder.data

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class SolomonPrimeClient(private val store: SolomonPrimeConfigStore) {
    data class Result(val ok: Boolean, val text: String)

    fun health(): Result = request("GET", "/health", null, authenticated = false) { body ->
        val json = JSONObject(body)
        "${json.optString("status", "unknown")} · ${json.optString("node_id", "unknown")} · v${json.optString("version", "?")}"
    }

    fun chat(message: String): Result {
        val payload = JSONObject()
            .put("model", "solomonprime")
            .put("stream", false)
            .put("messages", JSONArray().put(JSONObject().put("role", "user").put("content", message)))
        return request("POST", "/v1/chat/completions", payload.toString(), authenticated = true) { body ->
            JSONObject(body).getJSONArray("choices").getJSONObject(0)
                .getJSONObject("message").getString("content")
        }
    }

    private fun request(method: String, path: String, body: String?, authenticated: Boolean,
                        decode: (String) -> String): Result {
        val base = store.baseUrl
        val parsed = try { URI(base) } catch (_: Exception) { null }
        if (parsed?.scheme != "https") return Result(false, "A trusted HTTPS SolomonPrime URL is required.")
        val key = store.apiKey()
        if (authenticated && key.isBlank()) return Result(false, "The scope-limited Tricorder token is not configured.")
        return try {
            val connection = URL(base + path).openConnection() as HttpURLConnection
            connection.requestMethod = method
            connection.connectTimeout = 8_000
            connection.readTimeout = 180_000
            connection.setRequestProperty("Accept", "application/json")
            if (authenticated) connection.setRequestProperty("Authorization", "Bearer $key")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val status = connection.responseCode
            val response = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status !in 200..299) Result(false, "HTTP $status: ${response.take(500)}")
            else Result(true, decode(response))
        } catch (exc: Exception) {
            Result(false, "${exc.javaClass.simpleName}: ${exc.message ?: "connection failed"}")
        }
    }
}
