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

/**
 * Trackpad surface: one-finger drag moves the cursor, a short one-finger
 * tap clicks, two-finger drag scrolls. While touched, draws a small
 * cluster of glowing hexagons orbiting the live touch point (not a
 * historical trail) — they move together with your finger and fade out
 * over ~250ms after release.
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
                touching = true
                touchX = event.x
                touchY = event.y
                postInvalidateOnAnimation()
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
                    touchX = averageX(event)
                    touchY = y
                } else {
                    val dx = event.x - lastX
                    val dy = event.y - lastY
                    totalMovement += abs(dx) + abs(dy)
                    if (dx != 0f || dy != 0f) {
                        onEvent?.invoke(mapOf("t" to "move", "dx" to dx, "dy" to dy))
                    }
                    lastX = event.x
                    lastY = event.y
                    touchX = event.x
                    touchY = event.y
                }
                postInvalidateOnAnimation()
            }

            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                val duration = event.eventTime - downTime
                if (event.actionMasked == MotionEvent.ACTION_UP &&
                    !usedMultitouch && totalMovement < TAP_MOVE_THRESHOLD_PX && duration < TAP_MAX_DURATION_MS
                ) {
                    onEvent?.invoke(mapOf("t" to "click", "button" to "left"))
                }
                touching = false
                releasedAt = System.currentTimeMillis()
                postInvalidateOnAnimation()
            }
        }
        return true
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
