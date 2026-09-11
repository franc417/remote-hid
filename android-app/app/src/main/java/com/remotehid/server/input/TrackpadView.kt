package com.remotehid.server.input

import android.content.Context
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs

private const val TAP_MOVE_THRESHOLD_PX = 12f
private const val TAP_MAX_DURATION_MS = 200L
private const val SCROLL_DIVISOR = 4f

/**
 * Trackpad surface: one-finger drag moves the cursor, a short one-finger
 * tap clicks, two-finger drag scrolls. Emits already protocol-shaped
 * messages (as Map<String, Any?>) via onEvent — this view knows nothing
 * about WebSockets or JSON, just gestures in, messages out.
 *
 * Known simplification: click-and-drag (press, drag, release without
 * lifting) isn't implemented yet — only click as a single down+up pair.
 * Not wired to anything until MainActivity sets onEvent, and untested
 * beyond compiling, since gesture behavior can't be exercised without a
 * real touchscreen.
 */
class TrackpadView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {

    var onEvent: ((Map<String, Any?>) -> Unit)? = null

    private var lastX = 0f
    private var lastY = 0f
    private var lastTwoFingerY = 0f
    private var downTime = 0L
    private var totalMovement = 0f
    private var usedMultitouch = false

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastX = event.x
                lastY = event.y
                downTime = event.eventTime
                totalMovement = 0f
                usedMultitouch = false
            }

            MotionEvent.ACTION_POINTER_DOWN -> {
                usedMultitouch = true
                if (event.pointerCount == 2) {
                    lastTwoFingerY = averageY(event)
                }
            }

            MotionEvent.ACTION_MOVE -> {
                if (event.pointerCount >= 2) {
                    val y = averageY(event)
                    val dy = y - lastTwoFingerY
                    if (dy != 0f) {
                        onEvent?.invoke(mapOf("t" to "scroll", "dy" to (dy / SCROLL_DIVISOR)))
                    }
                    lastTwoFingerY = y
                } else {
                    val dx = event.x - lastX
                    val dy = event.y - lastY
                    totalMovement += abs(dx) + abs(dy)
                    if (dx != 0f || dy != 0f) {
                        onEvent?.invoke(mapOf("t" to "move", "dx" to dx, "dy" to dy))
                    }
                    lastX = event.x
                    lastY = event.y
                }
            }

            MotionEvent.ACTION_UP -> {
                val duration = event.eventTime - downTime
                if (!usedMultitouch && totalMovement < TAP_MOVE_THRESHOLD_PX && duration < TAP_MAX_DURATION_MS) {
                    onEvent?.invoke(mapOf("t" to "click", "button" to "left"))
                }
            }
        }
        return true
    }

    private fun averageY(event: MotionEvent): Float {
        var sum = 0f
        for (i in 0 until event.pointerCount) sum += event.getY(i)
        return sum / event.pointerCount
    }
}
