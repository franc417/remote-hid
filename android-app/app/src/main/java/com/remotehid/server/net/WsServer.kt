package com.remotehid.server.net

import android.util.Log
import com.remotehid.server.protocol.ProtocolError
import com.remotehid.server.protocol.parseMessage
import fi.iki.elonen.NanoHTTPD
import fi.iki.elonen.NanoWSD
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.Executors

private const val TAG = "WsServer"

/** Must match REPLACED_REASON in linux-client/protocol.py: clients use it to tell a deliberate takeover from a network drop. */
const val REPLACED_REASON = "replaced by a newer connection"

/**
 * Embedded WebSocket server. Runs on the phone; the desktop client
 * connects to it. Each incoming frame is decoded as JSON, validated
 * against the wire protocol (protocol/Protocol.kt), and handed to
 * onMessage as a plain Map.
 *
 * This class is Android-only (NanoHTTPD + org.json), so unlike
 * Protocol.kt it is NOT covered by the plain-JVM unit tests — it's
 * exercised for the first time by the real Android build in CI, not by
 * me locally. If the build fails here, it's most likely this file.
 */
class WsServer(
    port: Int,
    private val onMessage: (Map<String, Any?>) -> Unit,
    private val onClientConnected: (() -> Unit)? = null,
    private val onClientDisconnected: (() -> Unit)? = null,
) : NanoWSD(port) {

    @Volatile
    private var activeSocket: WebSocket? = null

    // sendToClient() is called directly from touch/click UI callbacks
    // (TrackpadView, KeyboardView), so it runs on the main thread by
    // default. socket.send() below does a blocking network write —
    // doing that on the main thread throws NetworkOnMainThreadException
    // and crashes the app on literally the first touch. Confirmed from
    // a real crash report, not found by inspection. A single-thread
    // executor moves the actual write off the main thread while still
    // processing sends strictly in order (important: out-of-order
    // cursor deltas would be worse than a dropped one), without paying
    // thread-creation overhead on every touch-move event.
    private val sendExecutor = Executors.newSingleThreadExecutor()

    // Closing a replaced socket writes a close frame to a link that may be
    // dead. That must never block the NEW connection's thread (onOpen) or
    // the in-order send queue, so it gets its own thread.
    private val closeExecutor = Executors.newSingleThreadExecutor()

    // Cursor and scroll deltas are additive, so when the network write is
    // slower than the touch stream (Wi-Fi hiccup, 240Hz touch panel) they
    // are summed here and sent as ONE message instead of queueing up. A
    // queue would add its whole length to the cursor's lag; a sum arrives
    // as fast as the link allows and loses nothing. When the link keeps
    // up there is exactly one pending delta per message, so this adds no
    // delay at all. Any other message (click, key) drains the pending
    // motion first, so the order the user produced events in is preserved.
    private val motionLock = Any()
    private var pendingDx = 0f
    private var pendingDy = 0f
    private var pendingScroll = 0f
    private var motionQueued = false

    /** Sends a message to the currently connected desktop client, if any. */
    fun sendToClient(json: String) {
        sendExecutor.execute {
            flushMotion()
            sendNow(json)
        }
    }

    /** Adds a cursor delta to be sent with the next write (see above). */
    fun sendMove(dx: Float, dy: Float) {
        synchronized(motionLock) {
            pendingDx += dx
            pendingDy += dy
            if (motionQueued) return
            motionQueued = true
        }
        sendExecutor.execute { flushMotion() }
    }

    /** Adds a scroll delta to be sent with the next write (see above). */
    fun sendScroll(dy: Float) {
        synchronized(motionLock) {
            pendingScroll += dy
            if (motionQueued) return
            motionQueued = true
        }
        sendExecutor.execute { flushMotion() }
    }

    /** Runs on sendExecutor only: takes whatever motion has accumulated and sends it. */
    private fun flushMotion() {
        var dx = 0f
        var dy = 0f
        var scroll = 0f
        synchronized(motionLock) {
            dx = pendingDx
            dy = pendingDy
            scroll = pendingScroll
            pendingDx = 0f
            pendingDy = 0f
            pendingScroll = 0f
            motionQueued = false
        }
        if (dx != 0f || dy != 0f) sendNow("{\"t\":\"move\",\"dx\":$dx,\"dy\":$dy}")
        if (scroll != 0f) sendNow("{\"t\":\"scroll\",\"dy\":$scroll}")
    }

    /** Runs on sendExecutor only. */
    private fun sendNow(json: String) {
        val socket = activeSocket
        if (socket == null) {
            Log.w(TAG, "no client connected, dropping outbound message")
            return
        }
        try {
            socket.send(json)
        } catch (e: IOException) {
            Log.w(TAG, "failed to send to client: ${e.message}")
        }
    }

    /**
     * Nagle's algorithm is on by default for accepted sockets. NanoWSD writes
     * each frame as several tiny writes (header byte, length byte, payload),
     * so with Nagle the later pieces wait for the ACK of the first, and the
     * receiver's delayed ACK turns that into stalls of tens of milliseconds
     * per frame: the cursor lags and moves in clumps. TCP_NODELAY sends every
     * piece immediately.
     */
    override fun createClientHandler(finalAccept: Socket, inputStream: InputStream): NanoHTTPD.ClientHandler {
        try {
            finalAccept.tcpNoDelay = true
        } catch (e: SocketException) {
            Log.w(TAG, "could not set TCP_NODELAY: ${e.message}")
        }
        return super.createClientHandler(finalAccept, inputStream)
    }

    override fun stop() {
        super.stop()
        sendExecutor.shutdown()
        closeExecutor.shutdown()
    }

    override fun serveHttp(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        return newFixedLengthResponse("remote-hid server — connect via WebSocket, not HTTP")
    }

    override fun openWebSocket(handshake: NanoHTTPD.IHTTPSession): WebSocket {
        return object : WebSocket(handshake) {

            override fun onOpen() {
                // The newest connection always wins. After a cable
                // unplug/replug the OLD socket is usually still "open"
                // from this side (no FIN ever arrived), so keeping it
                // as the active one would send to a dead link, and its
                // eventual timeout would wipe out the new session (see
                // onClose below). Close the old one explicitly.
                val previous = activeSocket
                activeSocket = this
                if (previous != null && previous !== this) {
                    closeExecutor.execute {
                        try {
                            previous.close(WebSocketFrame.CloseCode.GoingAway, REPLACED_REASON, false)
                        } catch (e: IOException) {
                            Log.w(TAG, "closing the replaced connection failed: ${e.message}")
                        }
                    }
                }
                Log.i(TAG, "client connected")
                onClientConnected?.invoke()
            }

            override fun onClose(code: WebSocketFrame.CloseCode?, reason: String?, initiatedByRemote: Boolean) {
                // Only the ACTIVE socket may clear state. A stale socket
                // closing late (read timeout on an unplugged cable) used
                // to null out activeSocket and report "disconnected"
                // while a fresh connection was working: the intermittent
                // USB failure.
                if (activeSocket !== this) {
                    Log.i(TAG, "stale connection closed ($reason), ignoring")
                    return
                }
                activeSocket = null
                Log.i(TAG, "client disconnected: $reason")
                onClientDisconnected?.invoke()
            }

            override fun onMessage(message: WebSocketFrame) {
                val text = message.getTextPayload()
                try {
                    val decoded = jsonToMap(JSONObject(text))
                    onMessage(parseMessage(decoded))
                } catch (e: ProtocolError) {
                    Log.w(TAG, "dropping malformed message: ${e.message}")
                } catch (e: JSONException) {
                    Log.w(TAG, "dropping non-JSON frame: $text")
                }
            }

            override fun onPong(pong: WebSocketFrame) {}

            override fun onException(exception: IOException) {
                Log.e(TAG, "websocket error", exception)
            }
        }
    }
}

private fun jsonToMap(obj: JSONObject): Map<String, Any?> {
    val map = mutableMapOf<String, Any?>()
    val keys = obj.keys()
    while (keys.hasNext()) {
        val key = keys.next()
        val value = obj.get(key)
        map[key] = if (value is JSONArray) (0 until value.length()).map { value.get(it) } else value
    }
    return map
}
