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
            ws.start()
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
