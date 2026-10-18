package com.remotehid.server

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.graphics.Color
import android.graphics.Typeface
import android.text.SpannableStringBuilder
import android.text.style.ForegroundColorSpan
import android.text.style.StyleSpan
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
import com.remotehid.server.input.LayoutText
import com.remotehid.server.input.TrackpadView
import com.remotehid.server.input.TypingModel
import com.remotehid.server.net.RemoteHidService
import com.remotehid.server.net.collectLocalAddresses
import com.remotehid.server.net.describeAddresses
import com.remotehid.server.protocol.mapToJson
import java.net.Socket

private const val PORT = 8765

// v2: the default layout changed (arrows moved to 123, tab -> prtsc, larger keys). A layout saved
// by the previous version is deliberately not loaded; copy/paste in the layout editor brings one back.
private const val KEYBOARD_LAYOUT_PREF = "keyboard_layout_v2"
private const val HAPTIC_LEVEL_PREF = "haptic_level"
private const val STATUS_REFRESH_MS = 2000L

class MainActivity : AppCompatActivity() {

    private var service: RemoteHidService? = null
    private lateinit var statusText: TextView
    private lateinit var trackpad: TrackpadView
    private lateinit var keyboard: KeyboardView
    private lateinit var expandButton: TextView
    private lateinit var scanButton: TextView
    private lateinit var layoutButton: TextView
    private lateinit var qrPreview: PreviewView
    private lateinit var typingPreview: TextView
    private lateinit var typingBar: View
    private lateinit var typingLabel: TextView
    private val typingModel = TypingModel()
    private val uiHandler = Handler(Looper.getMainLooper())
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

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* best-effort */ }

    private val serviceConnection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName?, binder: IBinder?) {
            val bound = (binder as RemoteHidService.LocalBinder).getService()
            service = bound
            bound.onClientConnected = {
                runOnUiThread {
                    typingModel.onDisconnected()  // a new session starts without any old field
                    renderTyping()
                    statusText.text = "Client connected"
                }
            }
            bound.onClientDisconnected = {
                runOnUiThread {
                    typingModel.onDisconnected()
                    renderTyping()
                    statusText.text = statusLine()
                }
            }
            // The desktop tells us which text box is focused and what is in it.
            bound.onMessage = { msg ->
                if (msg["t"] == "field") {
                    runOnUiThread {
                        typingModel.onFieldMessage(msg)
                        renderTyping()
                    }
                }
            }
            statusText.text = if (bound.isServerRunning) statusLine() else "Server not started"
        }

        override fun onServiceDisconnected(name: ComponentName?) {
            service = null
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
        layoutButton = findViewById(R.id.layoutButton)
        qrPreview = findViewById(R.id.qrPreview)
        typingPreview = findViewById(R.id.typingPreview)
        typingBar = findViewById(R.id.typingBar)
        typingLabel = findViewById(R.id.typingLabel)

        statusText.text = getString(R.string.status_idle)

        trackpad.onEvent = { event ->
            // Motion goes through the coalescing path (see WsServer); every
            // other event keeps its place in line behind pending motion.
            when (event["t"]) {
                "move" -> service?.sendMove((event["dx"] as Number).toFloat(), (event["dy"] as Number).toFloat())
                "scroll" -> service?.sendScroll((event["dy"] as Number).toFloat())
                else -> service?.sendToClient(mapToJson(event))
            }
        }
        keyboard.onEvent = { event -> service?.sendToClient(mapToJson(event)) }
        // Local echo: only used while the desktop is not reporting its real text field.
        keyboard.onPreviewTextChanged = { text ->
            typingModel.onLocalEcho(text)
            renderTyping()
        }

        expandButton.setOnClickListener { toggleExpanded() }
        scanButton.setOnClickListener { toggleScan() }

        // Keyboard layout: load the saved one (if it still parses), save after every edit.
        val uiPrefs = getSharedPreferences("remote_hid_ui", Context.MODE_PRIVATE)
        uiPrefs.getString(KEYBOARD_LAYOUT_PREF, null)?.let { saved ->
            LayoutText.parse(saved).layout?.let { keyboard.setLayout(it) }
        }
        keyboard.onLayoutChanged = { layout ->
            uiPrefs.edit().putString(KEYBOARD_LAYOUT_PREF, LayoutText.serialize(layout)).apply()
        }
        keyboard.onEditModeChanged = { editing -> layoutButton.text = if (editing) "done" else "layout" }
        keyboard.setVibrationLevel(uiPrefs.getInt(HAPTIC_LEVEL_PREF, 2))
        keyboard.onHapticLevelChanged = { level -> uiPrefs.edit().putInt(HAPTIC_LEVEL_PREF, level).apply() }
        layoutButton.setOnClickListener {
            if (inScanMode) stopScanning()
            if (expanded) toggleExpanded()  // the keyboard has to be visible to edit it
            keyboard.setEditMode(!keyboard.editMode)
        }

        // Independent of this Activity's lifecycle — this is the fix for
        // a real bug where backgrounding the app (screen lock, switching
        // apps) silently killed the connection, because the server used
        // to be owned directly by onStart()/onStop() here.
        ContextCompat.startForegroundService(this, Intent(this, RemoteHidService::class.java))

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    override fun onStart() {
        super.onStart()
        bindService(Intent(this, RemoteHidService::class.java), serviceConnection, Context.BIND_AUTO_CREATE)
    }

    override fun onStop() {
        super.onStop()
        // Only unbinds — the service was started independently above,
        // so it (and the connection) keeps running while backgrounded.
        // We just stop receiving direct callbacks/reference until the
        // next onStart() rebinds.
        unbindService(serviceConnection)
        service = null
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
                Socket(host, port).use { socket ->
                    // The address this socket left from is, by definition, the one the desktop
                    // can reach us on: the Wi-Fi address over Wi-Fi, the tether address over a
                    // cable. (This used to always send the Wi-Fi address, wrong or missing
                    // whenever the desktop was reached another way.)
                    val reachable = socket.localAddress?.hostAddress?.takeIf { ':' !in it }
                        ?: collectLocalAddresses().firstOrNull()?.ip
                        ?: "unknown"
                    socket.getOutputStream().write(("ws://$reachable:$PORT\n").toByteArray())
                }
                runOnUiThread { statusText.text = statusLine() }
            } catch (e: Exception) {
                runOnUiThread { statusText.text = "Pairing failed: ${e.message}" }
            }
        }.start()
    }

    private fun statusLine(): String = describeAddresses(collectLocalAddresses(), PORT)

    /** Draws the typing bar from the model: the field's name, its text, and a caret. */
    private fun renderTyping() {
        val shown = typingModel.shown()
        if (!shown.visible) {
            typingBar.visibility = View.GONE
            return
        }
        typingBar.visibility = View.VISIBLE
        typingLabel.visibility = if (shown.label.isEmpty()) View.GONE else View.VISIBLE
        typingLabel.text = shown.label
        val text = SpannableStringBuilder(shown.before)
        if (shown.caret) {
            val start = text.length
            text.append("|")
            text.setSpan(ForegroundColorSpan(Color.WHITE), start, text.length, 0)
            text.setSpan(StyleSpan(Typeface.BOLD), start, text.length, 0)
        }
        text.append(shown.after)
        typingPreview.text = text
    }

    // While nothing is connected the addresses can change under us (cable plugged in, Wi-Fi
    // joined); USB tethering is not a "network" Android notifies about, so just look again.
    private val statusRefresh = object : Runnable {
        override fun run() {
            val current = statusText.text.toString()
            if (service?.isServerRunning == true && (current.startsWith("Listening") || current.startsWith("No network"))) {
                statusText.text = statusLine()
            }
            uiHandler.postDelayed(this, STATUS_REFRESH_MS)
        }
    }

    override fun onResume() {
        super.onResume()
        uiHandler.postDelayed(statusRefresh, STATUS_REFRESH_MS)
    }

    override fun onPause() {
        uiHandler.removeCallbacks(statusRefresh)
        super.onPause()
    }
}
