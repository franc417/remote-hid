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
private const val HEX_FADE_MS = 450L
private const val HEX_RADIUS_PX = 26f
private const val HEX_MAX_POINTS = 30
private const val HEX_MIN_SPACING_PX = 18f

/**
 * Trackpad surface: one-finger drag moves the cursor, a short one-finger
 * tap clicks, two-finger drag scrolls. Also draws a fading trail of
 * glowing hexagons following the touch point — purely visual, doesn't
 * affect what gets sent over the wire.
 *
 * Emits already protocol-shaped messages (as Map<String, Any?>) via
 * onEvent — this view knows nothing about WebSockets or JSON.
 *
 * Known simplification: click-and-drag isn't implemented — only click
 * as a single down+up pair. The glow animation and gesture handling are
 * both untested beyond compiling; touch feel and blur rendering can't
 * be verified without a real touchscreen.
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

    private data class HexPoint(val x: Float, val y: Float, val createdAt: Long)
    private val hexPoints = ArrayDeque<HexPoint>()

    private val glowPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 6f
        color = Color.WHITE
        maskFilter = BlurMaskFilter(18f, BlurMaskFilter.Blur.NORMAL)
    }
    private val corePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = 3f
        color = Color.WHITE
    }

    init {
        // BlurMaskFilter needs a software-rendered layer to reliably
        // show the glow — hardware-accelerated canvas support for it
        // is inconsistent across devices/API levels.
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
                addHexPoint(event.x, event.y)
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
                    addHexPoint(event.x, event.y)
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

    private fun addHexPoint(x: Float, y: Float) {
        val last = hexPoints.lastOrNull()
        if (last != null) {
            val dx = x - last.x
            val dy = y - last.y
            if (dx * dx + dy * dy < HEX_MIN_SPACING_PX * HEX_MIN_SPACING_PX) return
        }
        hexPoints.addLast(HexPoint(x, y, System.currentTimeMillis()))
        if (hexPoints.size > HEX_MAX_POINTS) hexPoints.removeFirst()
        postInvalidateOnAnimation()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val now = System.currentTimeMillis()
        val iterator = hexPoints.iterator()
        while (iterator.hasNext()) {
            val point = iterator.next()
            val age = now - point.createdAt
            if (age >= HEX_FADE_MS) {
                iterator.remove()
                continue
            }
            val fraction = 1f - (age.toFloat() / HEX_FADE_MS)
            val path = hexagonPath(point.x, point.y, HEX_RADIUS_PX * (0.7f + 0.3f * fraction))
            glowPaint.alpha = (200 * fraction).toInt()
            corePaint.alpha = (255 * fraction).toInt()
            canvas.drawPath(path, glowPaint)
            canvas.drawPath(path, corePaint)
        }
        if (hexPoints.isNotEmpty()) {
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
