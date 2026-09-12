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
import java.util.concurrent.Executors

private const val TAG = "WsServer"

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

    /** Sends a message to the currently connected desktop client, if any. */
    fun sendToClient(json: String) {
        sendExecutor.execute {
            val socket = activeSocket
            if (socket == null) {
                Log.w(TAG, "no client connected, dropping outbound message")
                return@execute
            }
            try {
                socket.send(json)
            } catch (e: IOException) {
                Log.w(TAG, "failed to send to client: ${e.message}")
            }
        }
    }

    override fun stop() {
        super.stop()
        sendExecutor.shutdown()
    }

    override fun serveHttp(session: NanoHTTPD.IHTTPSession): NanoHTTPD.Response {
        return newFixedLengthResponse("remote-hid server — connect via WebSocket, not HTTP")
    }

    override fun openWebSocket(handshake: NanoHTTPD.IHTTPSession): WebSocket {
        return object : WebSocket(handshake) {

            override fun onOpen() {
                activeSocket = this
                Log.i(TAG, "client connected")
                onClientConnected?.invoke()
            }

            override fun onClose(code: WebSocketFrame.CloseCode?, reason: String?, initiatedByRemote: Boolean) {
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
