package com.btcore.taskmanager.data

import org.json.JSONObject
import java.io.BufferedReader
import java.net.HttpURLConnection
import java.net.URL

class ApiException(message: String) : Exception(message)

/**
 * Cliente HTTP mínimo contra `src/api/server.py`.
 *
 * Sin Retrofit ni OkHttp a propósito: el MVP solo necesita JSON y un header
 * de auth. Menos dependencias = build más rápido y menos que auditar.
 */
class ApiClient(
    private val baseUrl: String,
    private val token: String,
) {

    private fun open(path: String, method: String): HttpURLConnection {
        val url = URL(baseUrl.trimEnd('/') + path)
        return (url.openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 8_000
            readTimeout = 60_000  // /hoy puede llamar a DeepSeek
            setRequestProperty("Accept", "application/json")
            if (token.isNotBlank()) {
                setRequestProperty("Authorization", "Bearer $token")
            }
        }
    }

    private fun read(connection: HttpURLConnection): String {
        val stream = if (connection.responseCode in 200..299) {
            connection.inputStream
        } else {
            connection.errorStream
        }
        val body = stream?.bufferedReader()?.use(BufferedReader::readText).orEmpty()
        if (connection.responseCode !in 200..299) {
            throw ApiException("HTTP ${connection.responseCode}: ${body.take(300)}")
        }
        return body
    }

    fun getRaw(path: String): String {
        val connection = open(path, "GET")
        return try {
            read(connection)
        } finally {
            connection.disconnect()
        }
    }

    fun postRaw(path: String, body: JSONObject): String {
        val connection = open(path, "POST")
        connection.doOutput = true
        connection.setRequestProperty("Content-Type", "application/json")
        return try {
            connection.outputStream.use { it.write(body.toString().toByteArray()) }
            read(connection)
        } finally {
            connection.disconnect()
        }
    }

    fun today(): Today {
        val json = JSONObject(getRaw("/hoy"))
        return Today(
            ok = json.optBoolean("ok", false),
            quick = json.optJSONObject("quick")?.let(Card::from),
            deep = json.optJSONObject("deep")?.let(Card::from),
            staleCount = json.optInt("stale_count", 0),
            reason = json.optString("reason", "").takeIf { it.isNotBlank() },
        )
    }

    fun closeDecision(decisionId: Int, executed: Boolean, hours: Double?) {
        val body = JSONObject().apply {
            put("executed", executed)
            if (hours != null) put("hours", hours)
        }
        postRaw("/decisions/$decisionId/close", body)
    }

    fun addTask(title: String) {
        postRaw("/tasks", JSONObject().apply { put("title", title) })
    }
}
