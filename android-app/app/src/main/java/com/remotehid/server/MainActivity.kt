package com.remotehid.server

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.wifi.WifiManager
import android.os.Bundle
import android.view.View
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.camera.core.ImageAnalysis
import androidx.camera.mlkit.vision.MlKitAnalyzer
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.remotehid.server.input.KeyboardView
import com.remotehid.server.input.TrackpadView
import com.remotehid.server.net.WsServer
import com.remotehid.server.protocol.mapToJson
import java.io.IOException
import java.net.InetAddress
import java.net.Socket

private const val PORT = 8765

class MainActivity : AppCompatActivity() {

    private var server: WsServer? = null
    private lateinit var statusText: TextView
    private lateinit var trackpad: TrackpadView
    private lateinit var keyboard: KeyboardView
    private lateinit var expandButton: TextView
    private lateinit var scanButton: TextView
    private lateinit var qrPreview: PreviewView
    private var expanded = false
    private var inScanMode = false
    private lateinit var cameraController: LifecycleCameraController
    private var cameraControllerReady = false

    private val cameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                bindCamera()
            } else {
                statusText.text = "Camera permission denied"
                stopScanning()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        statusText = findViewById(R.id.statusText)
        trackpad = findViewById(R.id.trackpad)
        keyboard = findViewById(R.id.keyboard)
        expandButton = findViewById(R.id.expandButton)
        scanButton = findViewById(R.id.scanButton)
        qrPreview = findViewById(R.id.qrPreview)

        statusText.text = getString(R.string.status_idle)

        trackpad.onEvent = { event -> server?.sendToClient(mapToJson(event)) }
        keyboard.onEvent = { event -> server?.sendToClient(mapToJson(event)) }

        expandButton.setOnClickListener { toggleExpanded() }
        scanButton.setOnClickListener { toggleScan() }
    }

    private fun toggleExpanded() {
        expanded = !expanded
        keyboard.visibility = if (expanded) View.GONE else View.VISIBLE
        expandButton.text = if (expanded) "keyboard" else "expand"
    }

    private fun toggleScan() {
        if (inScanMode) stopScanning() else startScanning()
    }

    private fun startScanning() {
        inScanMode = true
        trackpad.visibility = View.GONE
        keyboard.visibility = View.GONE
        qrPreview.visibility = View.VISIBLE
        scanButton.text = "cancel"

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA)
            != PackageManager.PERMISSION_GRANTED
        ) {
            cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
        } else {
            bindCamera()
        }
    }

    private fun bindCamera() {
        val options = BarcodeScannerOptions.Builder()
            .setBarcodeFormats(Barcode.FORMAT_QR_CODE)
            .build()
        val scanner = BarcodeScanning.getClient(options)

        cameraController = LifecycleCameraController(this)
        cameraController.bindToLifecycle(this)
        cameraControllerReady = true
        cameraController.setImageAnalysisAnalyzer(
            ContextCompat.getMainExecutor(this),
            MlKitAnalyzer(
                listOf(scanner),
                ImageAnalysis.COORDINATE_SYSTEM_VIEW_REFERENCED,
                ContextCompat.getMainExecutor(this),
            ) { result: MlKitAnalyzer.Result? ->
                if (!inScanMode) return@MlKitAnalyzer
                val barcodes = result?.getValue(scanner)
                val value = barcodes?.firstOrNull()?.rawValue ?: return@MlKitAnalyzer
                stopScanning()
                sendAnnounce(value)
            },
        )
        qrPreview.controller = cameraController
    }

    private fun stopScanning() {
        inScanMode = false
        if (cameraControllerReady) {
            cameraController.unbind()
        }
        qrPreview.visibility = View.GONE
        trackpad.visibility = View.VISIBLE
        keyboard.visibility = if (expanded) View.GONE else View.VISIBLE
        scanButton.text = "scan"
    }

    /**
     * Connects briefly to the rendezvous address encoded in the
     * desktop's QR code, and sends this phone's own ws:// address —
     * the desktop is listening there specifically to receive this and
     * auto-fill/auto-connect, so the human never has to type an IP.
     * This phone's WebSocket server keeps running exactly as before;
     * this is a one-shot side-channel handshake, not a role reversal.
     */
    private fun sendAnnounce(rendezvousAddress: String) {
        statusText.text = "Pairing..."
        Thread {
            try {
                val parts = rendezvousAddress.split(":")
                val host = parts[0]
                val port = parts[1].toInt()
                val myAddress = "ws://${localIpAddress() ?: "unknown"}:$PORT"
                Socket(host, port).use { socket ->
                    socket.getOutputStream().write((myAddress + "\n").toByteArray())
                }
                runOnUiThread { statusText.text = statusLine() }
            } catch (e: Exception) {
                runOnUiThread { statusText.text = "Pairing failed: ${e.message}" }
            }
        }.start()
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
