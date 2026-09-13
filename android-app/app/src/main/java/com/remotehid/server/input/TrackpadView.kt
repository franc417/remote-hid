package com.remotehid.server.input

import android.content.Context
import android.graphics.BlurMaskFilter
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.view.MotionEvent
import android.view.View
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

private const val TAP_MOVE_THRESHOLD_PX = 12f
private const val TAP_MAX_DURATION_MS = 200L
private const val SCROLL_DIVISOR = 4f
private const val HEX_COUNT = 3
private const val HEX_RADIUS_PX = 16f
private const val ORBIT_RADIUS_PX = 34f
private const val ORBIT_DEGREES_PER_MS = 0.09f
private const val RELEASE_FADE_MS = 250L
private const val DOUBLE_TAP_WINDOW_MS = 300L
private const val DOUBLE_TAP_DISTANCE_PX = 50f
private const val THREE_FINGER_THRESHOLD_PX = 70f

/**
 * Trackpad surface. Gestures:
 * - One-finger drag: move the cursor
 * - One-finger tap: click
 * - One-finger tap, then a second tap-and-hold-drag at roughly the same
 *   spot within 300ms: click-and-drag (press, drag, release) — the
 *   standard trackpad gesture for text selection and drag-and-drop.
 *   The first tap still sends a normal click; the second touch's
 *   down/move/up becomes click(down)/move.../click(up), which is
 *   exactly the raw sequence a real double-click-drag produces, so the
 *   receiving OS's own text-selection heuristics do the rest.
 * - Two-finger drag: scroll
 * - Three-finger horizontal swipe: switch workspace (Ctrl+Alt+Left/
 *   Right) — confirmed as the default binding across GNOME, Cinnamon
 *   (Linux Mint's own default desktop), MATE, and XFCE, not a
 *   GNOME-only convention. KDE Plasma and tiling window managers
 *   (i3, sway) often bind this differently, so it may need adjusting
 *   there.
 * - Three-finger vertical swipe: swipe up sends Super/Meta alone
 *   (opens an app overview/launcher on most desktop environments,
 *   though the exact resulting UI differs by DE); swipe down sends
 *   Escape (back/close). This vertical mapping is more of an
 *   assumption than the horizontal one — easy to change if it's not
 *   the right direction.
 *
 * Also draws a small cluster of glowing hexagons orbiting the live
 * touch point — purely visual, doesn't affect what gets sent.
 *
 * Emits already protocol-shaped messages (as Map<String, Any?>) via
 * onEvent — this view knows nothing about WebSockets or JSON.
 *
 * Every gesture above is untested beyond compiling — touch feel,
 * timing thresholds, and whether three fingers register cleanly as a
 * single gesture rather than fighting the one/two-finger paths can
 * only be judged on a real touchscreen.
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

    private var lastReleaseTime = 0L
    private var lastReleaseX = 0f
    private var lastReleaseY = 0f
    private var dragArmed = false
    private var dragActive = false

    private var threeFingerStartX = 0f
    private var threeFingerStartY = 0f
    private var threeFingerTriggered = false

    private var touching = false
    private var touchX = 0f
    private var touchY = 0f
    private var releasedAt = 0L

    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 5f
        color = Color.WHITE
        maskFilter = BlurMaskFilter(14f, BlurMaskFilter.Blur.NORMAL)
    }
    private val corePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 2.5f
        color = Color.WHITE
    }

    init {
        setLayerType(LAYER_TYPE_SOFTWARE, null)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                lastX = event.x
                lastY = event.y
                downTime = event.eventTime
                totalMovement = 0f
                usedMultitouch = false
                touching = true
                touchX = event.x
                touchY = event.y

                val dt = event.eventTime - lastReleaseTime
                val ddx = event.x - lastReleaseX
                val ddy = event.y - lastReleaseY
                dragArmed = dt in 0..DOUBLE_TAP_WINDOW_MS &&
                    (ddx * ddx + ddy * ddy) < DOUBLE_TAP_DISTANCE_PX * DOUBLE_TAP_DISTANCE_PX
                dragActive = false

                postInvalidateOnAnimation()
            }

            MotionEvent.ACTION_POINTER_DOWN -> {
                usedMultitouch = true
                dragArmed = false
                if (event.pointerCount == 2) {
                    lastTwoFingerY = averageY(event)
                } else if (event.pointerCount == 3) {
                    threeFingerStartX = averageX(event)
                    threeFingerStartY = averageY(event)
                    threeFingerTriggered = false
                }
            }

            MotionEvent.ACTION_MOVE -> {
                when (event.pointerCount) {
                    3 -> handleThreeFingerSwipe(event)
                    2 -> {
                        val y = averageY(event)
                        val dy = y - lastTwoFingerY
                        if (dy != 0f) {
                            onEvent?.invoke(mapOf("t" to "scroll", "dy" to (dy / SCROLL_DIVISOR)))
                        }
                        lastTwoFingerY = y
                        touchX = averageX(event)
                        touchY = y
                    }
                    else -> {
                        val dx = event.x - lastX
                        val dy = event.y - lastY
                        totalMovement += abs(dx) + abs(dy)

                        if (dragArmed && !dragActive && totalMovement > TAP_MOVE_THRESHOLD_PX) {
                            dragActive = true
                            onEvent?.invoke(mapOf("t" to "click", "button" to "left", "action" to "down"))
                        }

                        if (dx != 0f || dy != 0f) {
                            onEvent?.invoke(mapOf("t" to "move", "dx" to dx, "dy" to dy))
                        }
                        lastX = event.x
                        lastY = event.y
                        touchX = event.x
                        touchY = event.y
                    }
                }
                postInvalidateOnAnimation()
            }

            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val duration = event.eventTime - downTime
                if (dragActive) {
                    onEvent?.invoke(mapOf("t" to "click", "button" to "left", "action" to "up"))
                } else if (event.actionMasked == MotionEvent.ACTION_UP &&
                    !usedMultitouch && totalMovement < TAP_MOVE_THRESHOLD_PX && duration < TAP_MAX_DURATION_MS
                ) {
                    onEvent?.invoke(mapOf("t" to "click", "button" to "left"))
                }
                if (!usedMultitouch) {
                    lastReleaseTime = event.eventTime
                    lastReleaseX = event.x
                    lastReleaseY = event.y
                }
                touching = false
                releasedAt = System.currentTimeMillis()
                dragArmed = false
                dragActive = false
                postInvalidateOnAnimation()
            }
        }
        return true
    }

    private fun handleThreeFingerSwipe(event: MotionEvent) {
        if (threeFingerTriggered) return
        val dx = averageX(event) - threeFingerStartX
        val dy = averageY(event) - threeFingerStartY
        if (abs(dx) < THREE_FINGER_THRESHOLD_PX && abs(dy) < THREE_FINGER_THRESHOLD_PX) return

        threeFingerTriggered = true
        if (abs(dx) > abs(dy)) {
            // Confirmed default across GNOME, Cinnamon, MATE, and XFCE
            // (not GNOME-specific) — see the class doc comment.
            val code = if (dx < 0) "ArrowLeft" else "ArrowRight"
            sendShortcut(listOf("ctrl", "alt"), code)
        } else if (dy < 0) {
            // Swipe up: app overview/launcher on most desktop environments.
            sendShortcut(emptyList(), "Meta")
        } else {
            // Swipe down: back/close.
            sendShortcut(emptyList(), "Escape")
        }
    }

    private fun sendShortcut(mods: List<String>, code: String) {
        onEvent?.invoke(mapOf("t" to "key", "code" to code, "action" to "down", "mods" to mods))
        onEvent?.invoke(mapOf("t" to "key", "code" to code, "action" to "up", "mods" to mods))
    }

    private fun averageX(event: MotionEvent): Float {
        var sum = 0f
        for (i in 0 until event.pointerCount) sum += event.getX(i)
        return sum / event.pointerCount
    }

    private fun averageY(event: MotionEvent): Float {
        var sum = 0f
        for (i in 0 until event.pointerCount) sum += event.getY(i)
        return sum / event.pointerCount
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)

        val alphaFraction = if (touching) {
            1f
        } else {
            val sinceRelease = System.currentTimeMillis() - releasedAt
            if (sinceRelease >= RELEASE_FADE_MS) 0f else 1f - (sinceRelease.toFloat() / RELEASE_FADE_MS)
        }
        if (alphaFraction <= 0f) return

        val rotation = (System.currentTimeMillis() % 100000L) * ORBIT_DEGREES_PER_MS
        for (i in 0 until HEX_COUNT) {
            val angle = Math.toRadians((rotation + i * (360f / HEX_COUNT)).toDouble())
            val cx = touchX + ORBIT_RADIUS_PX * cos(angle).toFloat()
            val cy = touchY + ORBIT_RADIUS_PX * sin(angle).toFloat()
            val path = hexagonPath(cx, cy, HEX_RADIUS_PX)
            glowPaint.alpha = (180 * alphaFraction).toInt()
            corePaint.alpha = (255 * alphaFraction).toInt()
            canvas.drawPath(path, glowPaint)
            canvas.drawPath(path, corePaint)
        }

        if (touching || alphaFraction > 0f) {
            postInvalidateOnAnimation()
        }
    }

    private fun hexagonPath(cx: Float, cy: Float, radius: Float): Path {
        val path = Path()
        for (i in 0 until 6) {
            val angle = Math.toRadians((60 * i - 30).toDouble())
            val x = cx + radius * cos(angle).toFloat()
            val y = cy + radius * sin(angle).toFloat()
            if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
        }
        path.close()
        return path
    }
}
