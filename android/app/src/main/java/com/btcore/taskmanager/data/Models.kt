package com.btcore.taskmanager.data

import org.json.JSONObject

/** Una propuesta de `next_action.py`, tal como llega por la API. */
data class Card(
    val decisionId: Int,
    val taskId: Int,
    val title: String,
    val project: String?,
    val priority: Int?,
    val slot: String,
    val score: Double,
    val why: String,
    val estimateHours: Double?,
    val estimateRange: List<Double>?,
    val blockHours: Double?,
    val firstStep: String,
    val alternatives: Int,
) {
    companion object {
        fun from(json: JSONObject): Card = Card(
            decisionId = json.optInt("decision_id", -1),
            taskId = json.optInt("task_id", -1),
            title = json.optString("title", "(sin título)"),
            project = json.nullableString("project"),
            priority = if (json.isNull("priority")) null else json.optInt("priority"),
            slot = json.optString("slot", ""),
            score = json.optDouble("score", 0.0),
            why = json.optString("why", ""),
            estimateHours = json.nullableDouble("estimate_hours"),
            estimateRange = json.optJSONArray("estimate_range")?.let { arr ->
                List(arr.length()) { arr.optDouble(it) }
            },
            blockHours = json.nullableDouble("block_hours"),
            firstStep = json.optString("first_step", ""),
            alternatives = json.optInt("alternatives_considered", 0),
        )
    }
}

/** Respuesta completa de `/hoy`: hasta dos propuestas. */
data class Today(
    val ok: Boolean,
    val quick: Card?,
    val deep: Card?,
    val staleCount: Int,
    val reason: String?,
)

private fun JSONObject.nullableString(key: String): String? {
    if (isNull(key)) return null
    val value = optString(key, "")
    return value.takeIf { it.isNotBlank() && it != "null" }
}

private fun JSONObject.nullableDouble(key: String): Double? =
    if (isNull(key)) null else optDouble(key)
