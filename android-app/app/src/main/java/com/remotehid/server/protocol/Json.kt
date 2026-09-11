package com.remotehid.server.protocol

/**
 * Serializes a protocol message map to a JSON string for sending to the
 * desktop client. Deliberately pure Kotlin, like Protocol.kt — outbound
 * messages are simple enough (flat maps of strings/numbers/string-lists)
 * that hand-rolling this avoids pulling in org.json just to keep it
 * unit-testable without Robolectric or a real device.
 *
 * This only needs to handle the shapes handler code actually produces;
 * it isn't a general-purpose JSON encoder.
 */
fun mapToJson(map: Map<String, Any?>): String {
    val entries = map.entries.joinToString(",") { (key, value) ->
        "\"${escape(key)}\":${encodeValue(value)}"
    }
    return "{$entries}"
}

private fun encodeValue(value: Any?): String = when (value) {
    null -> "null"
    is String -> "\"${escape(value)}\""
    is Boolean -> value.toString()
    is Int, is Long -> value.toString()
    is Float, is Double -> value.toString()
    is List<*> -> "[${value.joinToString(",") { encodeValue(it) }}]"
    else -> throw IllegalArgumentException("cannot encode value of type ${value::class}")
}

private fun escape(s: String): String = buildString {
    for (c in s) {
        when (c) {
            '"' -> append("\\\"")
            '\\' -> append("\\\\")
            '\n' -> append("\\n")
            else -> append(c)
        }
    }
}
