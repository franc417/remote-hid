package com.remotehid.server.input

import android.content.Context
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.util.AttributeSet
import android.view.Gravity
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

private val KEY_COLOR = Color.parseColor("#1E1E1E")
private val KEY_PRESSED_COLOR = Color.parseColor("#333333")
private val MODIFIER_COLOR = Color.parseColor("#4A4A4A")
private val MODIFIER_PRESSED_COLOR = Color.parseColor("#5E5E5E")
private val ARMED_COLOR = Color.parseColor("#E8E8E8")
private val ARMED_PRESSED_COLOR = Color.parseColor("#D0D0D0")
private const val TEXT_COLOR_LIGHT = Color.WHITE
private const val TEXT_COLOR_DARK = Color.BLACK
private const val ROW_HEIGHT_DP = 56f
private const val KEY_TEXT_SP = 17f
private const val PREVIEW_MAX_CHARS = 200

// US QWERTY shift-symbol mapping, for the typing preview only.
private val SHIFT_SYMBOLS = mapOf(
    "Digit1" to "!", "Digit2" to "@", "Digit3" to "#", "Digit4" to "$",
    "Digit5" to "%", "Digit6" to "^", "Digit7" to "&", "Digit8" to "*",
    "Digit9" to "(", "Digit0" to ")", "Minus" to "_", "Equal" to "+",
)

// Punctuation keys — real physical keys, 100% reliable on any
// receiving system. Each maps to (unshifted, shifted) for the preview.
private val PUNCTUATION_CHARS = mapOf(
    "Period" to ("." to ">"),
    "Comma" to ("," to "<"),
    "Semicolon" to (";" to ":"),
    "Quote" to ("'" to "\""),
    "Slash" to ("/" to "?"),
    "Backslash" to ("\\" to "|"),
    "BracketLeft" to ("[" to "{"),
    "BracketRight" to ("]" to "}"),
    "Backquote" to ("`" to "~"),
)

private data class KeySpec(
    val label: String,
    val code: String,
    val sticky: Boolean = false,
    val weight: Float = 1f,
    val fnLabel: String? = null,
    val fnCode: String? = null,
    val symbolLabel: String? = null,
    // Tier 1: a real physical key + forced mods (e.g. Shift+, = "<").
    // 100% reliable — this is exactly what a physical keyboard sends.
    val symbolCode: String? = null,
    val symbolForcedMods: List<String> = emptyList(),
    // Tier 2: no physical key exists for this character at all (€, π,
    // ×, ...). Sent via the Ctrl+Shift+U Unicode-entry sequence, which
    // depends on the receiving desktop using IBus (GNOME's default)
    // and the focused app supporting it — best effort, not guaranteed
    // the way every other key on this keyboard is.
    val symbolUnicodeHex: String? = null,
)

/**
 * Full on-screen keyboard. Ctrl/Alt/Shift are sticky (tap to arm, next
 * key only, then cleared). Fn and 123 are persistent, mutually
 * exclusive toggles — Fn swaps the number row to F-keys and the arrow
 * cluster to Home/End/PageUp/PageDown; 123 swaps the *entire alphabet
 * block* to a symbol layer:
 * - Number row -> punctuation (. , ; ' / \ [ ] `) — real keys, had no
 *   UI access at all before.
 * - qwerty row -> the shifted variants of that same punctuation
 *   (< > : " ? | { } _) as dedicated single-tap keys — also real
 *   physical keys (Shift + the punctuation key above), just exposed
 *   directly instead of needing Shift armed separately first.
 * - asdf/zxcv rows -> characters with no physical key at all (currency,
 *   math symbols) via the Ctrl+Shift+U Unicode-entry sequence — see
 *   symbolUnicodeHex's doc comment above for the reliability caveat.
 *
 * Row height is fixed (not stretched to fill available space) — see
 * activity_main.xml, where this view is wrap_content height and the
 * trackpad absorbs the remaining space.
 *
 * Emits key events as protocol-shaped maps via onEvent, and a live
 * local echo of what's been typed via onPreviewTextChanged (a
 * reconstruction from which keys were tapped, not a readback of what
 * landed in a text field on the desktop — this view knows nothing
 * about WebSockets, JSON, or the far end).
 */
class KeyboardView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : LinearLayout(context, attrs) {

    var onEvent: ((Map<String, Any?>) -> Unit)? = null
    var onPreviewTextChanged: ((String) -> Unit)? = null

    private val previewBuffer = StringBuilder()

    private val keyRadiusPx = 8f * resources.displayMetrics.density
    private val rowHeightPx = (ROW_HEIGHT_DP * resources.displayMetrics.density).toInt()

    private val armedMods = mutableSetOf<String>()
    private data class StickyInfo(val view: TextView, val restColor: Int, val restPressedColor: Int)
    private val modifierButtons = mutableMapOf<String, StickyInfo>()

    private data class ToggleInfo(val view: TextView, val restColor: Int, val restPressedColor: Int)
    private var fnButtonInfo: ToggleInfo? = null
    private var symbolsButtonInfo: ToggleInfo? = null

    private var fnActive = false
    private var symbolsActive = false
    private val swappableKeys = mutableListOf<Pair<TextView, KeySpec>>()

    init {
        orientation = VERTICAL
        setBackgroundColor(Color.BLACK)

        addRow(digitsRow())
        addRow(qwertyRow())
        addRow(asdfRow())
        addRow(zxcvRow())
        addRow(modDockRow())
        addRow(bottomRow())
    }

    private fun digitsRow() = listOf(
        KeySpec("1", "Digit1", fnLabel = "F1", fnCode = "F1", symbolLabel = ".", symbolCode = "Period"),
        KeySpec("2", "Digit2", fnLabel = "F2", fnCode = "F2", symbolLabel = ",", symbolCode = "Comma"),
        KeySpec("3", "Digit3", fnLabel = "F3", fnCode = "F3", symbolLabel = ";", symbolCode = "Semicolon"),
        KeySpec("4", "Digit4", fnLabel = "F4", fnCode = "F4", symbolLabel = "'", symbolCode = "Quote"),
        KeySpec("5", "Digit5", fnLabel = "F5", fnCode = "F5", symbolLabel = "/", symbolCode = "Slash"),
        KeySpec("6", "Digit6", fnLabel = "F6", fnCode = "F6", symbolLabel = "\\", symbolCode = "Backslash"),
        KeySpec("7", "Digit7", fnLabel = "F7", fnCode = "F7", symbolLabel = "[", symbolCode = "BracketLeft"),
        KeySpec("8", "Digit8", fnLabel = "F8", fnCode = "F8", symbolLabel = "]", symbolCode = "BracketRight"),
        KeySpec("9", "Digit9", fnLabel = "F9", fnCode = "F9", symbolLabel = "`", symbolCode = "Backquote"),
        KeySpec("0", "Digit0", fnLabel = "F10", fnCode = "F10"),
        KeySpec("-", "Minus", fnLabel = "F11", fnCode = "F11"),
        KeySpec("=", "Equal", fnLabel = "F12", fnCode = "F12"),
    )

    // Tier 1: shifted variants of the punctuation above — real keys.
    private fun qwertyRow() = listOf(
        KeySpec("q", "KeyQ", symbolLabel = "<", symbolCode = "Comma", symbolForcedMods = listOf("shift")),
        KeySpec("w", "KeyW", symbolLabel = ">", symbolCode = "Period", symbolForcedMods = listOf("shift")),
        KeySpec("e", "KeyE", symbolLabel = ":", symbolCode = "Semicolon", symbolForcedMods = listOf("shift")),
        KeySpec("r", "KeyR", symbolLabel = "\"", symbolCode = "Quote", symbolForcedMods = listOf("shift")),
        KeySpec("t", "KeyT", symbolLabel = "?", symbolCode = "Slash", symbolForcedMods = listOf("shift")),
        KeySpec("y", "KeyY", symbolLabel = "|", symbolCode = "Backslash", symbolForcedMods = listOf("shift")),
        KeySpec("u", "KeyU", symbolLabel = "{", symbolCode = "BracketLeft", symbolForcedMods = listOf("shift")),
        KeySpec("i", "KeyI", symbolLabel = "}", symbolCode = "BracketRight", symbolForcedMods = listOf("shift")),
        KeySpec("o", "KeyO", symbolLabel = "~", symbolCode = "Backquote", symbolForcedMods = listOf("shift")),
        KeySpec("p", "KeyP", symbolLabel = "_", symbolCode = "Minus", symbolForcedMods = listOf("shift")),
    )

    // Tier 2: currency — no physical key, sent via Unicode entry.
    private fun asdfRow() = listOf(
        KeySpec("a", "KeyA", symbolLabel = "€", symbolUnicodeHex = "20ac"),
        KeySpec("s", "KeyS", symbolLabel = "£", symbolUnicodeHex = "a3"),
        KeySpec("d", "KeyD", symbolLabel = "¥", symbolUnicodeHex = "a5"),
        KeySpec("f", "KeyF", symbolLabel = "¢", symbolUnicodeHex = "a2"),
        KeySpec("g", "KeyG", symbolLabel = "×", symbolUnicodeHex = "d7"),
        KeySpec("h", "KeyH", symbolLabel = "÷", symbolUnicodeHex = "f7"),
        KeySpec("j", "KeyJ", symbolLabel = "±", symbolUnicodeHex = "b1"),
        KeySpec("k", "KeyK", symbolLabel = "≈", symbolUnicodeHex = "2248"),
        KeySpec("l", "KeyL", symbolLabel = "§", symbolUnicodeHex = "a7"),
    )

    // Tier 2: math comparison/misc — no physical key either.
    private fun zxcvRow(): List<KeySpec> {
        val letters = listOf(
            KeySpec("z", "KeyZ", symbolLabel = "≠", symbolUnicodeHex = "2260"),
            KeySpec("x", "KeyX", symbolLabel = "≤", symbolUnicodeHex = "2264"),
            KeySpec("c", "KeyC", symbolLabel = "≥", symbolUnicodeHex = "2265"),
            KeySpec("v", "KeyV", symbolLabel = "•", symbolUnicodeHex = "2022"),
            KeySpec("b", "KeyB", symbolLabel = "√", symbolUnicodeHex = "221a"),
            KeySpec("n", "KeyN", symbolLabel = "π", symbolUnicodeHex = "3c0"),
            KeySpec("m", "KeyM", symbolLabel = "∞", symbolUnicodeHex = "221e"),
        )
        return listOf(KeySpec("⇧", "shift", sticky = true)) + letters + KeySpec("⌫", "Backspace")
    }

    private fun modDockRow() = listOf(
        KeySpec("esc", "Escape"),
        KeySpec("prtsc", "PrintScreen"),
        KeySpec("win", "Meta"),
        KeySpec("ctrl", "ctrl", sticky = true),
        KeySpec("alt", "alt", sticky = true),
        KeySpec("fn", "fn"),
        KeySpec("space", "Space", weight = 3f),
        KeySpec("▲", "ArrowUp", fnLabel = "PgUp", fnCode = "PageUp"),
    )

    private fun bottomRow() = listOf(
        KeySpec("123", "123"),
        KeySpec("◀", "ArrowLeft", fnLabel = "Home", fnCode = "Home"),
        KeySpec("▼", "ArrowDown", fnLabel = "PgDn", fnCode = "PageDown"),
        KeySpec("▶", "ArrowRight", fnLabel = "End", fnCode = "End"),
        KeySpec("enter", "Enter", weight = 2f),
    )

    private fun addRow(keys: List<KeySpec>) {
        val row = LinearLayout(context).apply {
            orientation = HORIZONTAL
            layoutParams = LayoutParams(LayoutParams.MATCH_PARENT, rowHeightPx)
        }
        for (key in keys) {
            row.addView(buildKeyView(key))
        }
        addView(row)
    }

    private fun buildKeyView(key: KeySpec): TextView {
        val isModifierLook = key.code in setOf("ctrl", "alt", "fn", "123", "Meta")
        val restColor = if (isModifierLook) MODIFIER_COLOR else KEY_COLOR
        val restPressedColor = if (isModifierLook) MODIFIER_PRESSED_COLOR else KEY_PRESSED_COLOR

        val view = TextView(context).apply {
            text = key.label
            gravity = Gravity.CENTER
            textSize = KEY_TEXT_SP
            layoutParams = LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, key.weight).apply {
                setMargins(3, 3, 3, 3)
            }
        }
        style(view, restColor, restPressedColor, TEXT_COLOR_LIGHT)

        view.setOnClickListener {
            when {
                key.code == "fn" -> toggleFn()
                key.code == "123" -> toggleSymbols()
                key.sticky -> toggleModifier(key.code, view, restColor, restPressedColor)
                fnActive && key.fnCode != null -> sendKey(key.fnCode)
                symbolsActive && key.symbolUnicodeHex != null ->
                    sendUnicodeChar(key.symbolUnicodeHex, key.symbolLabel ?: "?")
                symbolsActive && key.symbolCode != null -> sendKey(key.symbolCode, key.symbolForcedMods)
                else -> sendKey(key.code)
            }
        }

        if (key.sticky) {
            modifierButtons[key.code] = StickyInfo(view, restColor, restPressedColor)
        }
        if (key.code == "fn") {
            fnButtonInfo = ToggleInfo(view, restColor, restPressedColor)
        }
        if (key.code == "123") {
            symbolsButtonInfo = ToggleInfo(view, restColor, restPressedColor)
        }
        if (key.fnCode != null || key.symbolCode != null || key.symbolUnicodeHex != null) {
            swappableKeys.add(view to key)
        }

        return view
    }

    private fun style(view: TextView, restColor: Int, pressedColor: Int, textColor: Int) {
        view.setTextColor(textColor)
        val normal = GradientDrawable().apply { setColor(restColor); cornerRadius = keyRadiusPx }
        val pressed = GradientDrawable().apply { setColor(pressedColor); cornerRadius = keyRadiusPx }
        view.background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_pressed), pressed)
            addState(intArrayOf(), normal)
        }
    }

    private fun toggleModifier(mod: String, view: TextView, restColor: Int, restPressedColor: Int) {
        if (armedMods.contains(mod)) {
            armedMods.remove(mod)
            style(view, restColor, restPressedColor, TEXT_COLOR_LIGHT)
        } else {
            armedMods.add(mod)
            style(view, ARMED_COLOR, ARMED_PRESSED_COLOR, TEXT_COLOR_DARK)
        }
    }

    private fun toggleFn() {
        fnActive = !fnActive
        if (fnActive && symbolsActive) {
            symbolsActive = false
            restyleToggleButton(symbolsButtonInfo, active = false)
        }
        restyleToggleButton(fnButtonInfo, active = fnActive)
        updateSwappableLabels()
    }

    private fun toggleSymbols() {
        symbolsActive = !symbolsActive
        if (symbolsActive && fnActive) {
            fnActive = false
            restyleToggleButton(fnButtonInfo, active = false)
        }
        restyleToggleButton(symbolsButtonInfo, active = symbolsActive)
        updateSwappableLabels()
    }

    private fun restyleToggleButton(info: ToggleInfo?, active: Boolean) {
        val target = info ?: return
        style(
            target.view,
            if (active) ARMED_COLOR else target.restColor,
            if (active) ARMED_PRESSED_COLOR else target.restPressedColor,
            if (active) TEXT_COLOR_DARK else TEXT_COLOR_LIGHT,
        )
    }

    private fun updateSwappableLabels() {
        for ((btnView, spec) in swappableKeys) {
            btnView.text = when {
                fnActive && spec.fnLabel != null -> spec.fnLabel
                symbolsActive && spec.symbolLabel != null -> spec.symbolLabel
                else -> spec.label
            }
        }
    }

    private fun sendRaw(code: String, mods: List<String>) {
        onEvent?.invoke(mapOf("t" to "key", "code" to code, "action" to "down", "mods" to mods))
        onEvent?.invoke(mapOf("t" to "key", "code" to code, "action" to "up", "mods" to mods))
    }

    private fun sendKey(code: String, extraMods: List<String> = emptyList()) {
        val mods = (armedMods + extraMods).distinct()
        sendRaw(code, mods)
        updatePreview(code, "shift" in mods)
        clearModifiers()
    }

    /**
     * Sends a character with no physical key via GTK/IBus's Unicode
     * entry sequence: Ctrl+Shift+U, the hex codepoint, Enter to commit.
     * Best-effort — needs the receiving desktop's input method to be
     * IBus (GNOME's default) and the focused app to support it; unlike
     * every other key here, this isn't guaranteed to work everywhere.
     * Deliberately ignores any armed Ctrl/Alt/Shift, since combining
     * them with this sequence has no well-defined meaning.
     */
    private fun sendUnicodeChar(hex: String, previewChar: String) {
        clearModifiers()
        sendRaw("KeyU", listOf("ctrl", "shift"))
        for (digit in hex) {
            val digitCode = if (digit.isDigit()) "Digit$digit" else "Key${digit.uppercaseChar()}"
            sendRaw(digitCode, emptyList())
        }
        sendRaw("Enter", emptyList())

        previewBuffer.append(previewChar)
        if (previewBuffer.length > PREVIEW_MAX_CHARS) {
            previewBuffer.delete(0, previewBuffer.length - PREVIEW_MAX_CHARS)
        }
        onPreviewTextChanged?.invoke(previewBuffer.toString())
    }

    private fun updatePreview(code: String, shiftArmed: Boolean) {
        when (code) {
            "Backspace" -> if (previewBuffer.isNotEmpty()) previewBuffer.deleteCharAt(previewBuffer.length - 1)
            "Enter" -> previewBuffer.clear()
            else -> {
                val char = previewCharFor(code, shiftArmed) ?: return
                previewBuffer.append(char)
                if (previewBuffer.length > PREVIEW_MAX_CHARS) {
                    previewBuffer.delete(0, previewBuffer.length - PREVIEW_MAX_CHARS)
                }
            }
        }
        onPreviewTextChanged?.invoke(previewBuffer.toString())
    }

    private fun previewCharFor(code: String, shiftArmed: Boolean): String? = when {
        code.startsWith("Key") && code.length == 4 -> {
            val letter = code.substring(3)
            if (shiftArmed) letter else letter.lowercase()
        }
        code.startsWith("Digit") -> if (shiftArmed) SHIFT_SYMBOLS[code] else code.removePrefix("Digit")
        code == "Minus" -> if (shiftArmed) "_" else "-"
        code == "Equal" -> if (shiftArmed) "+" else "="
        code == "Space" -> " "
        PUNCTUATION_CHARS.containsKey(code) -> {
            val (base, shifted) = PUNCTUATION_CHARS.getValue(code)
            if (shiftArmed) shifted else base
        }
        else -> null
    }

    private fun clearModifiers() {
        armedMods.clear()
        for (info in modifierButtons.values) {
            style(info.view, info.restColor, info.restPressedColor, TEXT_COLOR_LIGHT)
        }
    }
}
