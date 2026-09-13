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

private data class KeySpec(
    val label: String,
    val code: String,
    val sticky: Boolean = false,
    val inert: Boolean = false,
    val weight: Float = 1f,
    val fnLabel: String? = null,
    val fnCode: String? = null,
)

/**
 * Full on-screen keyboard: number row (with F1-F12 under Fn), three
 * letter rows, a modifier dock (including a standalone Windows/Super
 * key), and an arrow cluster that doubles as Home/End/PageUp/PageDown
 * under Fn — matching how a real laptop keyboard's Fn row works.
 *
 * Ctrl/Alt/Shift are sticky: tap arms it (highlighted white/black), the
 * armed set is attached to the next normal key's "mods", then cleared.
 * Fn is a persistent toggle, not sticky-per-keypress: swaps the number
 * row and arrow cluster to their secondary functions until tapped
 * again. 123 is still inert — see android-app/README.md.
 *
 * Row height is fixed (not stretched to fill whatever space the parent
 * gives it) — see activity_main.xml, where this view is wrap_content
 * height and the trackpad absorbs the remaining space.
 *
 * Emits key events as protocol-shaped maps via onEvent — this view
 * knows nothing about WebSockets or JSON.
 */
class KeyboardView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : LinearLayout(context, attrs) {

    var onEvent: ((Map<String, Any?>) -> Unit)? = null

    private val keyRadiusPx = 8f * resources.displayMetrics.density
    private val rowHeightPx = (ROW_HEIGHT_DP * resources.displayMetrics.density).toInt()

    private val armedMods = mutableSetOf<String>()
    private data class StickyInfo(val view: TextView, val restColor: Int, val restPressedColor: Int)
    private val modifierButtons = mutableMapOf<String, StickyInfo>()

    private var fnActive = false
    private val fnSwappableKeys = mutableListOf<Pair<TextView, KeySpec>>()

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
        KeySpec("1", "Digit1", fnLabel = "F1", fnCode = "F1"),
        KeySpec("2", "Digit2", fnLabel = "F2", fnCode = "F2"),
        KeySpec("3", "Digit3", fnLabel = "F3", fnCode = "F3"),
        KeySpec("4", "Digit4", fnLabel = "F4", fnCode = "F4"),
        KeySpec("5", "Digit5", fnLabel = "F5", fnCode = "F5"),
        KeySpec("6", "Digit6", fnLabel = "F6", fnCode = "F6"),
        KeySpec("7", "Digit7", fnLabel = "F7", fnCode = "F7"),
        KeySpec("8", "Digit8", fnLabel = "F8", fnCode = "F8"),
        KeySpec("9", "Digit9", fnLabel = "F9", fnCode = "F9"),
        KeySpec("0", "Digit0", fnLabel = "F10", fnCode = "F10"),
        KeySpec("-", "Minus", fnLabel = "F11", fnCode = "F11"),
        KeySpec("=", "Equal", fnLabel = "F12", fnCode = "F12"),
    )

    private fun qwertyRow() = "qwertyuiop".map { KeySpec(it.toString(), "Key${it.uppercaseChar()}") }

    private fun asdfRow() = "asdfghjkl".map { KeySpec(it.toString(), "Key${it.uppercaseChar()}") }

    private fun zxcvRow(): List<KeySpec> {
        val letters = "zxcvbnm".map { KeySpec(it.toString(), "Key${it.uppercaseChar()}") }
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
        KeySpec("123", "123", inert = true),
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
        val isModifierLook = key.code in setOf("ctrl", "alt", "fn", "Meta")
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
                key.code == "fn" -> toggleFn(view, restColor, restPressedColor)
                key.inert -> { /* not implemented yet — see android-app/README.md */ }
                key.sticky -> toggleModifier(key.code, view, restColor, restPressedColor)
                else -> {
                    val activeCode = if (fnActive && key.fnCode != null) key.fnCode else key.code
                    sendKey(activeCode)
                }
            }
        }

        if (key.sticky) {
            modifierButtons[key.code] = StickyInfo(view, restColor, restPressedColor)
        }
        if (key.fnCode != null) {
            fnSwappableKeys.add(view to key)
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

    private fun toggleFn(view: TextView, restColor: Int, restPressedColor: Int) {
        fnActive = !fnActive
        style(
            view,
            if (fnActive) ARMED_COLOR else restColor,
            if (fnActive) ARMED_PRESSED_COLOR else restPressedColor,
            if (fnActive) TEXT_COLOR_DARK else TEXT_COLOR_LIGHT,
        )
        for ((btnView, spec) in fnSwappableKeys) {
            btnView.text = if (fnActive) (spec.fnLabel ?: spec.label) else spec.label
        }
    }

    private fun sendKey(code: String) {
        val mods = armedMods.toList()
        onEvent?.invoke(mapOf("t" to "key", "code" to code, "action" to "down", "mods" to mods))
        onEvent?.invoke(mapOf("t" to "key", "code" to code, "action" to "up", "mods" to mods))
        clearModifiers()
    }

    private fun clearModifiers() {
        armedMods.clear()
        for (info in modifierButtons.values) {
            style(info.view, info.restColor, info.restPressedColor, TEXT_COLOR_LIGHT)
        }
    }
}
