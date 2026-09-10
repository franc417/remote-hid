package com.remotehid.server

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.remotehid.server.net.WsServer
import java.io.IOException
import java.net.InetAddress

private const val PORT = 8765

class MainActivity : AppCompatActivity() {

    private var server: WsServer? = null
    private lateinit var statusText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        statusText = findViewById(R.id.statusText)
        statusText.text = getString(R.string.status_idle)
    }

    override fun onStart() {
        super.onStart()

        val ws = WsServer(
            port = PORT,
            onMessage = { _ ->
                // Next milestone: dispatch to an InputBackend, same shape
                // as linux-client/handler.py. Nothing to inject into yet
                // on this end — this device is the server, not the one
                // receiving cursor/key events.
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
