package com.btcore.taskmanager.data

import android.content.Context

/**
 * Ajustes locales del cliente. Las API keys de Gemini/DeepSeek NO viven acá:
 * las tiene el servidor en su `.env`. Acá solo va la URL del backend y el
 * token de dispositivo.
 */
class SettingsStore(context: Context) {

    private val prefs = context.getSharedPreferences("taskmanager", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = prefs.getString("base_url", DEFAULT_BASE_URL)?.ifBlank { DEFAULT_BASE_URL }
            ?: DEFAULT_BASE_URL
        set(value) = prefs.edit().putString("base_url", value.trim()).apply()

    var token: String
        get() = prefs.getString("token", "") ?: ""
        set(value) = prefs.edit().putString("token", value.trim()).apply()

    companion object {
        /** 10.0.2.2 es el alias del host (PC) visto desde el emulador. */
        const val DEFAULT_BASE_URL = "http://10.0.2.2:8787"
    }
}
