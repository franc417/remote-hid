package com.remotehid.server.net

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat

private const val CHANNEL_ID = "remote_hid_server"
private const val NOTIFICATION_ID = 1
private const val PORT = 8765

/**
 * Keeps the WebSocket server alive as a foreground service, independent
 * of MainActivity's lifecycle.
 *
 * This exists because of a real bug found in actual use, not a
 * hypothetical: with the server owned directly by MainActivity
 * (started in onStart, stopped in onStop), any backgrounding of the
 * app — screen lock, switching apps, even briefly — killed the
 * connection outright. Two independent test sessions on two different
 * machines both showed symptoms consistent with this: one where the
 * desktop connected successfully and then the connection died
 * (ConnectionClosedError) with nothing on the phone side having
 * visibly changed from the user's perspective, and one where the
 * desktop couldn't connect at all (ConnectionRefusedError) despite the
 * app appearing to be running.
 *
 * MainActivity now binds to this service instead of owning a WsServer
 * directly. The service is independently started (survives unbind),
 * and the Activity binds only while visible, to get a live reference
 * and wire up UI callbacks.
 *
 * Uses the "dataSync" foreground service type, not "connectedDevice" —
 * a real crash on Android 14 corrected this. connectedDevice requires
 * holding at least one companion permission (Bluetooth, NFC, USB,
 * CHANGE_WIFI_STATE, etc.) on top of its own permission; this app has
 * no genuine reason to hold any of those, and Android throws a
 * SecurityException at startForeground() if you declare the type
 * without one. dataSync has no such extra requirement, and its actual
 * description — transferring data between a device and another device
 * or the cloud over a network — is a more honest match for what this
 * service does anyway.
 */
class RemoteHidService : Service() {

    private var server: WsServer? = null

    var onClientConnected: (() -> Unit)? = null
    var onClientDisconnected: (() -> Unit)? = null
    var onMessage: ((Map<String, Any?>) -> Unit)? = null

    val isServerRunning: Boolean get() = server != null
    val port: Int get() = PORT

    inner class LocalBinder : Binder() {
        fun getService(): RemoteHidService = this@RemoteHidService
    }

    private val binder = LocalBinder()

    override fun onBind(intent: Intent?): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Starting..."))
        startServerIfNeeded()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startServerIfNeeded()
        return START_STICKY
    }

    private fun startServerIfNeeded() {
        if (server != null) return

        val ws = WsServer(
            port = PORT,
            onMessage = { msg -> onMessage?.invoke(msg) },
            onClientConnected = {
                updateNotification("Client connected")
                onClientConnected?.invoke()
            },
            onClientDisconnected = {
                updateNotification("Waiting for a connection")
                onClientDisconnected?.invoke()
            },
        )
        try {
            // NanoHTTPD's no-arg start() defaults to SOCKET_READ_TIMEOUT =
            // 5000ms, applied directly to the raw socket the instant it's
            // accepted — and it silently persists after the WebSocket
            // upgrade. This is a well-documented NanoHTTPD/NanoWSD issue
            // specifically for WebSockets (confirmed against the library's
            // own source and multiple independent bug reports describing
            // this exact symptom), not something specific to this app.
            //
            // The desktop's Python `websockets` library already runs its
            // own robust keepalive by default — a Ping every 20s, dropping
            // the connection if no Pong comes back within 20s. That's a
            // correct, complete liveness mechanism already. The actual bug
            // was that Android's 5s timeout was *shorter* than the
            // desktop's already-existing 20s ping interval, so the two were
            // never compatible — any normal idle gap tripped Android's
            // timeout long before the desktop's own keepalive ever got a
            // chance to matter. 60s gives 3x margin over that 20s cadence
            // for network jitter, while still bounding how long a stuck
            // connection could linger — no separate ping scheduler needed
            // here, since the desktop side already does this correctly.
            ws.start(60_000, false)
            server = ws
            updateNotification("Waiting for a connection")
        } catch (e: Exception) {
            updateNotification("Failed to start: ${e.message}")
        }
    }

    fun sendToClient(json: String) {
        server?.sendToClient(json)
    }

    override fun onDestroy() {
        server?.stop()
        server = null
        super.onDestroy()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "remote-hid server",
                NotificationManager.IMPORTANCE_LOW,
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("remote-hid")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.sym_def_app_icon)
            .setOngoing(true)
            .build()
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(NotificationManager::class.java)
        manager.notify(NOTIFICATION_ID, buildNotification(text))
    }
}
