package com.remotehid.server

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.remotehid.server.input.KeyboardView
import com.remotehid.server.input.TrackpadView
import com.remotehid.server.net.WsServer
import com.remotehid.server.protocol.mapToJson
import java.io.IOException
import java.net.InetAddress

private const val PORT = 8765

class MainActivity : AppCompatActivity() {

    private var server: WsServer? = null
    private lateinit var statusText: TextView
    private lateinit var trackpad: TrackpadView
    private lateinit var keyboard: KeyboardView
    private lateinit var expandButton: TextView
    private var expanded = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        trackpad = findViewById(R.id.trackpad)
        keyboard = findViewById(R.id.keyboard)
        expandButton = findViewById(R.id.expandButton)

        statusText.text = getString(R.string.status_idle)

        trackpad.onEvent = { event -> server?.sendToClient(mapToJson(event)) }
        keyboard.onEvent = { event -> server?.sendToClient(mapToJson(event)) }

        expandButton.setOnClickListener { toggleExpanded() }
    }

    private fun toggleExpanded() {
        expanded = !expanded
        keyboard.visibility = if (expanded) View.GONE else View.VISIBLE
        expandButton.text = if (expanded) "keyboard" else "expand"
    }

    override fun onStart() {
        super.onStart()

        val ws = WsServer(
            port = PORT,
            onMessage = { _ ->
                // Messages received here would come from the desktop
                // client. Nothing to do with them on this end yet — this
                // device is the server, sending to the desktop, not
                // receiving input to inject. See WsServer.kt.
            },
            onClientConnected = { runOnUiThread { statusText.text = "Client connected" } },
            onClientDisconnected = { runOnUiThread { statusText.text = statusLine() } },
        )

        try {
            ws.start()
            server = ws
            statusText.text = statusLine()
        } catch (e: IOException) {
            statusText.text = "Failed to start server: ${e.message}"
        }
    }

    override fun onStop() {
        super.onStop()
        server?.stop()
        server = null
    }

    private fun statusLine(): String {
        val ip = localIpAddress() ?: "unknown IP"
        return "Listening on ws://$ip:$PORT"
    }

    private fun localIpAddress(): String? {
        val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
        val ipInt = wifiManager?.connectionInfo?.ipAddress ?: return null
        if (ipInt == 0) return null
        val bytes = byteArrayOf(
            (ipInt and 0xff).toByte(),
            (ipInt shr 8 and 0xff).toByte(),
            (ipInt shr 16 and 0xff).toByte(),
            (ipInt shr 24 and 0xff).toByte(),
        )
        return InetAddress.getByAddress(bytes).hostAddress
    }
}
