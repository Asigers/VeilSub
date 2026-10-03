package com.veilsub.android.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.veilsub.android.settings.UserSettings
import com.veilsub.android.state.CaptureState
import com.veilsub.android.state.CaptureStatus
import java.util.Locale

@Composable
fun HomeScreen(
    settings: UserSettings,
    captureState: CaptureState,
    overlayGranted: Boolean,
    onGatewayChange: (String) -> Unit,
    onSourceLanguageChange: (String) -> Unit,
    onTargetLanguageChange: (String) -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    onRequestOverlay: () -> Unit,
) {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                text = "VeilSub",
                style = MaterialTheme.typography.headlineMedium,
            )
            Text(
                text = "Android playback-capture diagnostic",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            CaptureStateCard(captureState)

            OutlinedTextField(
                value = settings.gatewayUrl,
                onValueChange = onGatewayChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Gateway") },
                supportingText = {
                    Text("A2 will connect this URL. A1 only validates playback PCM capture.")
                },
                singleLine = true,
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                OutlinedTextField(
                    value = settings.sourceLanguage,
                    onValueChange = onSourceLanguageChange,
                    modifier = Modifier.weight(1f),
                    label = { Text("Source") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = settings.targetLanguage,
                    onValueChange = onTargetLanguageChange,
                    modifier = Modifier.weight(1f),
                    label = { Text("Target") },
                    singleLine = true,
                )
            }

            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text("Permissions", style = MaterialTheme.typography.titleMedium)
                    Text(
                        if (overlayGranted) {
                            "Overlay: granted"
                        } else {
                            "Overlay: not granted (not required for A1 PCM diagnostics)"
                        },
                    )
                    if (!overlayGranted) {
                        OutlinedButton(onClick = onRequestOverlay) {
                            Text("Grant display-over-apps permission")
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(2.dp))

            val active = captureState.status !in setOf(
                CaptureStatus.IDLE,
                CaptureStatus.ERROR,
            )
            Button(
                onClick = onStart,
                modifier = Modifier.fillMaxWidth(),
                enabled = !active,
            ) {
                Text("Start playback capture")
            }

            OutlinedButton(
                onClick = onStop,
                modifier = Modifier.fillMaxWidth(),
                enabled = active,
            ) {
                Text("Stop")
            }

            Text(
                text = "A1 does not store captured audio. It counts converted 16 kHz PCM bytes only.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CaptureStateCard(state: CaptureState) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            Text("Capture", style = MaterialTheme.typography.titleMedium)
            Text("State: ${state.status}")

            state.inputSampleRateHz?.let {
                Text("Input sample rate: $it Hz")
            }

            if (state.bytesCaptured > 0) {
                val seconds = state.bytesCaptured / 32_000.0
                Text(
                    "16 kHz PCM captured: " +
                        String.format(Locale.US, "%.1f s", seconds),
                )
            }

            state.message?.let { message ->
                Text(
                    text = message,
                    color = if (state.status == CaptureStatus.ERROR) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
        }
    }
}
