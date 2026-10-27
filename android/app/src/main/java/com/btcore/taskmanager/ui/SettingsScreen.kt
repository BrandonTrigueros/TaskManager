package com.btcore.taskmanager.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.btcore.taskmanager.data.SettingsStore

@Composable
fun SettingsScreen(settings: SettingsStore) {
    var url by remember { mutableStateOf(settings.baseUrl) }
    var token by remember { mutableStateOf(settings.token) }
    var saved by remember { mutableStateOf(false) }

    Column(
        Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Backend", style = MaterialTheme.typography.headlineSmall)

        OutlinedTextField(
            value = url,
            onValueChange = { url = it; saved = false },
            label = { Text("URL del servidor") },
            placeholder = { Text(SettingsStore.DEFAULT_BASE_URL) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        OutlinedTextField(
            value = token,
            onValueChange = { token = it; saved = false },
            label = { Text("Token de dispositivo") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )

        Button(onClick = {
            settings.baseUrl = url
            settings.token = token
            url = settings.baseUrl
            token = settings.token
            saved = true
        }) { Text("Guardar") }

        if (saved) {
            Text("Guardado. Volvé a Hoy y tocá Actualizar.")
        }

        Spacer(Modifier.height(8.dp))

        Text(
            "Las claves de Gemini y DeepSeek viven en el .env del servidor: " +
                "esta app nunca las recibe. Acá solo se guarda la URL y el token.",
            style = MaterialTheme.typography.bodySmall,
        )
        Text(
            "Emulador: el host de la PC se ve como 10.0.2.2. " +
                "Dispositivo físico: usá la IP de la PC en la LAN o Tailscale.",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}
