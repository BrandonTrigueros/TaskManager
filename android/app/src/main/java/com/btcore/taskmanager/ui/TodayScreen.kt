package com.btcore.taskmanager.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.btcore.taskmanager.data.ApiClient
import com.btcore.taskmanager.data.Card as DecisionCard
import com.btcore.taskmanager.data.SettingsStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private sealed interface UiState {
    data object Loading : UiState
    data class Ready(
        val quick: DecisionCard?,
        val deep: DecisionCard?,
        val stale: Int,
        val note: String?,
    ) : UiState
    data class Failed(val message: String) : UiState
}

@Composable
fun TodayScreen(settings: SettingsStore) {
    var state by remember { mutableStateOf<UiState>(UiState.Loading) }
    var reload by remember { mutableIntStateOf(0) }
    var banner by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(reload) {
        state = UiState.Loading
        state = try {
            withContext(Dispatchers.IO) {
                val today = ApiClient(settings.baseUrl, settings.token).today()
                UiState.Ready(today.quick, today.deep, today.staleCount, today.reason)
            }
        } catch (e: Exception) {
            UiState.Failed(e.message ?: "error desconocido")
        }
    }

    fun act(card: DecisionCard, executed: Boolean, hours: Double?) {
        scope.launch {
            banner = try {
                withContext(Dispatchers.IO) {
                    ApiClient(settings.baseUrl, settings.token)
                        .closeDecision(card.decisionId, executed, hours)
                }
                reload++
                if (executed) "✅ Cerrada · ${hours ?: "?"}h reales" else "⏭ Anotado: hoy no"
            } catch (e: Exception) {
                "⚠️ ${e.message}"
            }
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Hoy", style = MaterialTheme.typography.headlineMedium)
            TextButton(onClick = { banner = null; reload++ }) { Text("Actualizar") }
        }

        banner?.let {
            Card(Modifier.fillMaxWidth()) {
                Text(it, Modifier.padding(12.dp), style = MaterialTheme.typography.bodyMedium)
            }
        }

        when (val current = state) {
            UiState.Loading -> Row(
                Modifier.fillMaxWidth().padding(24.dp),
                horizontalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator() }

            is UiState.Failed -> Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("No pude conectar", fontWeight = FontWeight.SemiBold)
                    Text(current.message, style = MaterialTheme.typography.bodySmall)
                    Text(
                        "Revisá la URL y el token en Ajustes. " +
                            "Desde el emulador, el host es 10.0.2.2.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }

            is UiState.Ready -> {
                if (current.note != null) {
                    Text(current.note, style = MaterialTheme.typography.bodyMedium)
                }
                val quick = current.quick
                val deep = current.deep

                if (quick == null && deep == null) {
                    Text("Nada pendiente. Cargá algo y volvé.")
                }
                quick?.let {
                    SlotCard("⚡ ARRANQUE", it,
                        onDone = { hours -> act(it, true, hours) },
                        onSkip = { act(it, false, null) })
                }
                deep?.let {
                    SlotCard("🧠 BLOQUE PROFUNDO", it,
                        onDone = { hours -> act(it, true, hours) },
                        onSkip = { act(it, false, null) })
                }
                if (current.stale > 0) {
                    Text(
                        "ℹ️ ${current.stale} tareas vencidas hace más de 30 días " +
                            "quedaron fuera de la propuesta.",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
    }
}

@Composable
private fun SlotCard(
    label: String,
    card: DecisionCard,
    onDone: (Double?) -> Unit,
    onSkip: () -> Unit,
) {
    var choosing by remember(card.decisionId) { mutableStateOf(false) }

    val options = remember(card.decisionId) {
        val base = card.estimateHours ?: 0.5
        listOf(0.5, 1.0, 1.5)
            .map { factor -> Math.round(base * factor * 10.0) / 10.0 }
            .distinct()
            .sorted()
    }

    Card(Modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(label, style = MaterialTheme.typography.labelMedium)
            Text(
                card.title,
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                card.project ?: "sin proyecto",
                style = MaterialTheme.typography.bodySmall,
            )

            card.estimateHours?.let { hours ->
                val range = card.estimateRange?.joinToString("–")
                val block = card.blockHours?.let { " · bloque de ${it}h" } ?: ""
                Text(
                    if (range != null) "~${hours}h ($range)$block" else "~${hours}h$block",
                    style = MaterialTheme.typography.bodyMedium,
                )
            }

            Text(card.why, style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.height(2.dp))
            Text("▶ ${card.firstStep}", style = MaterialTheme.typography.bodyMedium)

            if (!choosing) {
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = { choosing = true }) { Text("✅ Hecho") }
                    OutlinedButton(onClick = onSkip) { Text("⏭ Hoy no") }
                }
            } else {
                Text("¿Cuánto te tomó?", style = MaterialTheme.typography.labelMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    options.forEach { hours ->
                        OutlinedButton(onClick = { onDone(hours) }) { Text("${hours}h") }
                    }
                }
            }
        }
    }
}
