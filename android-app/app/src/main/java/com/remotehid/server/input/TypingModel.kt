package com.remotehid.server.input

/** What the typing bar should show right now. */
data class TypingShown(
    val visible: Boolean,
    /** Small caption: the field's name (e.g. "Search"), or empty. */
    val label: String = "",
    val before: String = "",
    val after: String = "",
    /** Draw a caret between `before` and `after`. */
    val caret: Boolean = false,
)

private const val BULLET = '\u2022'

/**
 * Decides what the typing bar shows, with no Android types so it can be unit
 * tested.
 *
 * Two sources, and the real one always wins:
 *  - MIRROR: the desktop reports its actually focused text field (text, caret
 *    position, name). Once it has reported at all, the bar shows exactly that,
 *    and hides when no text box has focus. Deleting, clicking elsewhere,
 *    autocomplete and typing in another window all show up correctly.
 *  - LOCAL ECHO: for a desktop that cannot report (no accessibility support) the
 *    bar falls back to a reconstruction of the keys tapped, as it always did.
 */
class TypingModel {
    private var mirror = false
    private var focused = false
    private var text = ""
    private var caret = 0
    private var password = false
    private var name = ""
    private var echo = ""

    /** Applies a validated desktop `field` message (see Protocol.kt). */
    fun onFieldMessage(msg: Map<String, Any?>) {
        mirror = true
        focused = msg["focused"] == true
        if (!focused) {
            text = ""
            caret = 0
            password = false
            name = ""
            return
        }
        text = msg["text"] as? String ?: ""
        caret = (msg["caret"] as? Number)?.toInt() ?: text.length
        password = msg["password"] == true
        name = msg["name"] as? String ?: ""
    }

    fun onLocalEcho(newEcho: String) {
        echo = newEcho
    }

    /** The connection ended: forget the old field so a stale one is never shown. */
    fun onDisconnected() {
        mirror = false
        focused = false
        text = ""
        caret = 0
        password = false
        name = ""
    }

    fun shown(): TypingShown {
        if (!mirror) {
            return if (echo.isEmpty()) TypingShown(false) else TypingShown(true, before = echo)
        }
        if (!focused) return TypingShown(false)

        // A password is never displayed, even if the sender forgot to mask it.
        val visibleText = if (password) text.map { BULLET }.joinToString("") else text
        val at = caret.coerceIn(0, visibleText.length)
        val flat = { s: String -> s.replace("\r\n", " \u23CE ").replace("\n", " \u23CE ") }
        return TypingShown(
            visible = true,
            label = name.ifBlank { "Typing" },
            before = flat(visibleText.substring(0, at)),
            after = flat(visibleText.substring(at)),
            caret = true,
        )
    }
}
