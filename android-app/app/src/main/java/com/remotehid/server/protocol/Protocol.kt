package com.remotehid.server.protocol

/**
 * Wire protocol for phone -> desktop input events. Mirrors protocol.py
 * in linux-client/ — keep the two in sync. See PROTOCOL.md at the repo
 * root for the full spec.
 *
 * Deliberately pure Kotlin with no Android/org.json dependency, so it
 * can be unit tested on a plain JVM with plain JUnit — no Robolectric,
 * no emulator required. JSON-string decoding (org.json -> Map<String,
 * Any?>) happens separately, in net/WsServer.kt, right where the
 * WebSocket server receives a frame. org.json is only real at runtime
 * on an actual Android device, so it isn't something this module can
 * depend on and still be testable here.
 */

const val MSG_MOVE = "move"
const val MSG_CLICK = "click"
const val MSG_SCROLL = "scroll"
const val MSG_KEY = "key"

val VALID_TYPES = setOf(MSG_MOVE, MSG_CLICK, MSG_SCROLL, MSG_KEY)
val VALID_BUTTONS = setOf("left", "right", "middle")
val VALID_CLICK_ACTIONS = setOf("click", "down", "up")
val VALID_KEY_ACTIONS = setOf("down", "up")
val VALID_MODIFIERS = setOf("ctrl", "alt", "shift", "meta")

class ProtocolError(message: String) : Exception(message)

/**
 * Validates an already-decoded message. Throws ProtocolError with a
 * human-readable reason on anything malformed; callers should catch
 * this and drop the one bad frame rather than tearing down the whole
 * connection.
 */
@Throws(ProtocolError::class)
fun parseMessage(raw: Map<String, Any?>): Map<String, Any?> {
    val type = raw["t"] as? String
    if (type == null || type !in VALID_TYPES) {
        throw ProtocolError("unknown message type: ${raw["t"]}")
    }

    when (type) {
        MSG_MOVE -> {
            requireNumber(raw, "dx")
            requireNumber(raw, "dy")
        }

        MSG_CLICK -> {
            val button = raw["button"] as? String ?: "left"
            if (button !in VALID_BUTTONS) {
                throw ProtocolError("invalid button: $button")
            }
            val action = raw["action"] as? String ?: "click"
            if (action !in VALID_CLICK_ACTIONS) {
                throw ProtocolError("invalid click action: $action")
            }
        }

        MSG_SCROLL -> {
            requireNumber(raw, "dy")
        }

        MSG_KEY -> {
            if (raw["code"] !is String) {
                throw ProtocolError("key message missing string 'code'")
            }
            val action = raw["action"] as? String
            if (action == null || action !in VALID_KEY_ACTIONS) {
                throw ProtocolError("invalid key action: ${raw["action"]}")
            }
            val mods = (raw["mods"] as? List<*>) ?: emptyList<Any?>()
            for (m in mods) {
                if (m !is String || m !in VALID_MODIFIERS) {
                    throw ProtocolError("invalid modifier: $m")
                }
            }
        }
    }

    return raw
}

private fun requireNumber(raw: Map<String, Any?>, field: String) {
    val value = raw[field]
    if (value !is Int && value !is Double && value !is Long && value !is Float) {
        throw ProtocolError("'$field' must be a number, got $value")
    }
}
