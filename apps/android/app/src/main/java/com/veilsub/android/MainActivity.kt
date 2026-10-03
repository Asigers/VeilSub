package com.veilsub.android

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings as AndroidSettings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.veilsub.android.capture.SubtitleCaptureService
import com.veilsub.android.settings.SettingsRepository
import com.veilsub.android.settings.UserSettings
import com.veilsub.android.state.CaptureSessionStore
import com.veilsub.android.state.CaptureStatus
import com.veilsub.android.ui.HomeScreen
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private lateinit var projectionManager: MediaProjectionManager
    private lateinit var projectionLauncher: ActivityResultLauncher<Intent>
    private lateinit var permissionLauncher: ActivityResultLauncher<Array<String>>

    private var overlayGranted by mutableStateOf(false)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        projectionManager =
            getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        overlayGranted = AndroidSettings.canDrawOverlays(this)

        projectionLauncher = registerForActivityResult(
            ActivityResultContracts.StartActivityForResult(),
        ) { result ->
            if (result.resultCode != Activity.RESULT_OK || result.data == null) {
                runCatching {
                    CaptureSessionStore.transition(
                        CaptureStatus.IDLE,
                        "MediaProjection permission was not granted.",
                    )
                }.onFailure {
                    CaptureSessionStore.reset()
                }
                return@registerForActivityResult
            }

            CaptureSessionStore.transition(CaptureStatus.STARTING_CAPTURE)
            startCaptureService(
                resultCode = result.resultCode,
                resultData = requireNotNull(result.data),
            )
        }

        permissionLauncher = registerForActivityResult(
            ActivityResultContracts.RequestMultiplePermissions(),
        ) { grants ->
            val audioGranted =
                grants[Manifest.permission.RECORD_AUDIO] ==
                    true ||
                    ContextCompat.checkSelfPermission(
                        this,
                        Manifest.permission.RECORD_AUDIO,
                    ) == PackageManager.PERMISSION_GRANTED

            if (!audioGranted) {
                CaptureSessionStore.fail(
                    "Record-audio permission is required for playback capture.",
                )
                return@registerForActivityResult
            }

            launchProjectionConsent()
        }

        val settingsRepository = SettingsRepository(applicationContext)

        setContent {
            MaterialTheme {
                val captureState by CaptureSessionStore.state.collectAsStateWithLifecycle()
                val settings by settingsRepository.settings.collectAsStateWithLifecycle(
                    initialValue = UserSettings(),
                )
                val scope = rememberCoroutineScope()

                HomeScreen(
                    settings = settings,
                    captureState = captureState,
                    overlayGranted = overlayGranted,
                    onGatewayChange = {
                        scope.launch { settingsRepository.updateGatewayUrl(it) }
                    },
                    onSourceLanguageChange = {
                        scope.launch { settingsRepository.updateSourceLanguage(it) }
                    },
                    onTargetLanguageChange = {
                        scope.launch { settingsRepository.updateTargetLanguage(it) }
                    },
                    onStart = ::beginCaptureFlow,
                    onStop = ::stopCaptureService,
                    onRequestOverlay = ::openOverlaySettings,
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
        overlayGranted = AndroidSettings.canDrawOverlays(this)
    }

    private fun beginCaptureFlow() {
        runCatching {
            CaptureSessionStore.transition(CaptureStatus.REQUESTING_PERMISSION)
        }.onFailure {
            CaptureSessionStore.reset()
            CaptureSessionStore.transition(CaptureStatus.REQUESTING_PERMISSION)
        }

        val missing = buildList {
            if (
                ContextCompat.checkSelfPermission(
                    this@MainActivity,
                    Manifest.permission.RECORD_AUDIO,
                ) != PackageManager.PERMISSION_GRANTED
            ) {
                add(Manifest.permission.RECORD_AUDIO)
            }

            if (
                Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                ContextCompat.checkSelfPermission(
                    this@MainActivity,
                    Manifest.permission.POST_NOTIFICATIONS,
                ) != PackageManager.PERMISSION_GRANTED
            ) {
                add(Manifest.permission.POST_NOTIFICATIONS)
            }
        }

        if (missing.isNotEmpty()) {
            permissionLauncher.launch(missing.toTypedArray())
        } else {
            launchProjectionConsent()
        }
    }

    private fun launchProjectionConsent() {
        projectionLauncher.launch(projectionManager.createScreenCaptureIntent())
    }

    private fun startCaptureService(
        resultCode: Int,
        resultData: Intent,
    ) {
        val intent = Intent(this, SubtitleCaptureService::class.java)
            .setAction(SubtitleCaptureService.ACTION_START)
            .putExtra(SubtitleCaptureService.EXTRA_PROJECTION_RESULT_CODE, resultCode)
            .putExtra(SubtitleCaptureService.EXTRA_PROJECTION_DATA, resultData)

        ContextCompat.startForegroundService(this, intent)
    }

    private fun stopCaptureService() {
        startService(
            Intent(this, SubtitleCaptureService::class.java)
                .setAction(SubtitleCaptureService.ACTION_STOP),
        )
    }

    private fun openOverlaySettings() {
        startActivity(
            Intent(
                AndroidSettings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName"),
            ),
        )
    }
}
