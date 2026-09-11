package com.remotehid.server.input

import android.content.Context
import android.graphics.Color
import android.util.AttributeSet
import android.view.Gravity
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

private val ARMED_COLOR = Color.parseColor("#3A3A3A")
private val NORMAL_COLOR = Color.parseColor("#1C1C1C")
private const val LABEL_COLOR = Color.WHITE

private data class KeySpec(
    val label: String,
    val code: String,
    val sticky: Boolean = false,
    val inert: Boolean = false,
    val weight: Float = 1f,
)

/**
 * Full on-screen keyboard: number row, three letter rows, a modifier
 * dock, and an arrow cluster — matching the split-view design mockups.
 *
 * Ctrl/Alt/Shift are sticky: tap arms it (highlighted), the armed set
 * is attached to the next normal key's "mods", then cleared. Fn and 123
 * are present but inert for now — see android-app/README.md for what's
 * not wired up yet (F-row swap, symbol row).
 *
 * Emits key events as protocol-shaped maps via onEvent — this view
 * knows nothing about WebSockets or JSON.
 */
class KeyboardView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : LinearLayout(context, attrs) {

    var onEvent: ((Map<String, Any?>) -> Unit)? = null

    private val armedMods = mutableSetOf<String>()
    private val modifierButtons = mutableMapOf<String, TextView>()

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
        KeySpec("1", "Digit1"), KeySpec("2", "Digit2"), KeySpec("3", "Digit3"),
        KeySpec("4", "Digit4"), KeySpec("5", "Digit5"), KeySpec("6", "Digit6"),
        KeySpec("7", "Digit7"), KeySpec("8", "Digit8"), KeySpec("9", "Digit9"),
        KeySpec("0", "Digit0"),
    )

    private fun qwertyRow() = "qwertyuiop".map { KeySpec(it.toString(), "Key${it.uppercaseChar()}") }

    private fun asdfRow() = "asdfghjkl".map { KeySpec(it.toString(), "Key${it.uppercaseChar()}") }

    private fun zxcvRow(): List<KeySpec> {
        val letters = "zxcvbnm".map { KeySpec(it.toString(), "Key${it.uppercaseChar()}") }
        return listOf(KeySpec("⇧", "shift", sticky = true)) + letters + KeySpec("⌫", "Backspace")
    }

    private fun modDockRow() = listOf(
        KeySpec("ctrl", "ctrl", sticky = true),
        KeySpec("alt", "alt", sticky = true),
        KeySpec("fn", "fn", inert = true),
        KeySpec("space", "Space", weight = 5f),
        KeySpec("▲", "ArrowUp"),
    )

    private fun bottomRow() = listOf(
        KeySpec("123", "123", inert = true),
        KeySpec("◀", "ArrowLeft"),
        KeySpec("▼", "ArrowDown"),
        KeySpec("▶", "ArrowRight"),
        KeySpec("enter", "Enter", weight = 2f),
    )

    private fun addRow(keys: List<KeySpec>) {
        val row = LinearLayout(context).apply {
            orientation = HORIZONTAL
            layoutParams = LayoutParams(LayoutParams.MATCH_PARENT, 0, 1f)
        }
        for (key in keys) {
            row.addView(buildKeyView(key))
        }
        addView(row)
    }

    private fun buildKeyView(key: KeySpec): TextView {
        val view = TextView(context).apply {
            text = key.label
            gravity = Gravity.CENTER
            setTextColor(LABEL_COLOR)
            setBackgroundColor(NORMAL_COLOR)
            textSize = 14f
            layoutParams = LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, key.weight).apply {
                setMargins(2, 2, 2, 2)
            }
        }

        view.setOnClickListener {
            when {
                key.inert -> { /* not implemented yet — see android-app/README.md */ }
                key.sticky -> toggleModifier(key.code, view)
                else -> sendKey(key.code)
            }
        }

        if (key.sticky) modifierButtons[key.code] = view

        return view
    }

    private fun toggleModifier(mod: String, view: TextView) {
        if (armedMods.contains(mod)) {
            armedMods.remove(mod)
            view.setBackgroundColor(NORMAL_COLOR)
        } else {
            armedMods.add(mod)
            view.setBackgroundColor(ARMED_COLOR)
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
        for (btn in modifierButtons.values) {
            btn.setBackgroundColor(NORMAL_COLOR)
        }
    }
}
