package com.veilsub.android.capture

import android.Manifest
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ActivityCompat
import com.veilsub.android.notification.CaptureNotification
import com.veilsub.android.state.CaptureSessionStore
import com.veilsub.android.state.CaptureStatus
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class SubtitleCaptureService : Service() {
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var projectionSession: MediaProjectionSession? = null
    private var playbackCapture: PlaybackAudioCapture? = null
    private var totalPcm16kBytes = 0L
    private var shuttingDown = false

    override fun onCreate() {
        super.onCreate()
        CaptureNotification.ensureChannel(this)
    }

    override fun onStartCommand(
        intent: Intent?,
        flags: Int,
        startId: Int,
    ): Int {
        when (intent?.action) {
            ACTION_STOP -> stopCapture(userInitiated = true)
            ACTION_START -> startCapture(intent)
        }
        return START_NOT_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun startCapture(intent: Intent) {
        if (projectionSession != null || playbackCapture != null) return

        if (
            ActivityCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            CaptureSessionStore.fail(
                "Record-audio permission is required for Android playback capture.",
            )
            stopSelf()
            return
        }

        startProjectionForeground()

        val resultCode = intent.getIntExtra(EXTRA_PROJECTION_RESULT_CODE, Int.MIN_VALUE)
        val resultData = intent.projectionData()
        if (resultCode == Int.MIN_VALUE || resultData == null) {
            CaptureSessionStore.fail("MediaProjection permission result is missing.")
            stopCapture(userInitiated = false)
            return
        }

        serviceScope.launch {
            runCatching {
                val projection = MediaProjectionSession(
                    context = this@SubtitleCaptureService,
                    resultCode = resultCode,
                    resultData = resultData,
                    onRevoked = ::onProjectionRevoked,
                )
                projectionSession = projection

                val capture = PlaybackAudioCapture(projection.projection)
                playbackCapture = capture
                totalPcm16kBytes = 0

                capture.start(
                    scope = serviceScope,
                    onPcm16kFrame = { frame ->
                        totalPcm16kBytes += frame.size
                        CaptureSessionStore.updateAudioStats(
                            bytesCaptured = totalPcm16kBytes,
                            inputSampleRateHz = capture.inputSampleRateHz,
                        )
                        // A2 sends this exact 16 kHz mono PCM16 frame to GatewayClient.
                    },
                    onFailure = { error ->
                        CaptureSessionStore.fail(
                            error.message ?: "Playback audio capture failed.",
                        )
                        stopCapture(userInitiated = false)
                    },
                )

                CaptureSessionStore.transition(
                    CaptureStatus.AUDIO_CAPTURE_READY,
                    "Playback PCM capture active. Gateway integration is the next A2 step.",
                )
            }.onFailure { error ->
                CaptureSessionStore.fail(
                    error.message ?: "Could not start playback audio capture.",
                )
                stopCapture(userInitiated = false)
            }
        }
    }

    private fun startProjectionForeground() {
        val notification = CaptureNotification.build(this)
        startForeground(
            CaptureNotification.NOTIFICATION_ID,
            notification,
            ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION,
        )
    }

    private fun onProjectionRevoked() {
        if (shuttingDown) return
        CaptureSessionStore.fail("Android stopped the MediaProjection session.")
        stopCapture(userInitiated = false)
    }

    private fun stopCapture(userInitiated: Boolean) {
        if (shuttingDown) return
        shuttingDown = true

        if (userInitiated) {
            runCatching { CaptureSessionStore.transition(CaptureStatus.STOPPING) }
        }

        playbackCapture?.stop()
        playbackCapture = null

        projectionSession?.close()
        projectionSession = null

        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()

        if (userInitiated) {
            runCatching { CaptureSessionStore.transition(CaptureStatus.IDLE) }
                .onFailure { CaptureSessionStore.reset() }
        }

        shuttingDown = false
    }

    override fun onDestroy() {
        playbackCapture?.stop()
        playbackCapture = null
        projectionSession?.close()
        projectionSession = null
        serviceScope.cancel()
        super.onDestroy()
    }

    @Suppress("DEPRECATION")
    private fun Intent.projectionData(): Intent? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            getParcelableExtra(EXTRA_PROJECTION_DATA, Intent::class.java)
        } else {
            getParcelableExtra(EXTRA_PROJECTION_DATA)
        }
    }

    companion object {
        const val ACTION_START = "com.veilsub.android.action.START_CAPTURE"
        const val ACTION_STOP = "com.veilsub.android.action.STOP_CAPTURE"
        const val EXTRA_PROJECTION_RESULT_CODE = "projection_result_code"
        const val EXTRA_PROJECTION_DATA = "projection_data"
    }
}
