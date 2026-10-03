package com.veilsub.android.state

enum class CaptureStatus {
    IDLE,
    REQUESTING_PERMISSION,
    STARTING_CAPTURE,
    AUDIO_CAPTURE_READY,
    CONNECTING_GATEWAY,
    CAPTURING,
    RECONNECTING,
    STOPPING,
    ERROR,
}

data class CaptureState(
    val status: CaptureStatus = CaptureStatus.IDLE,
    val bytesCaptured: Long = 0,
    val inputSampleRateHz: Int? = null,
    val outputSampleRateHz: Int = 16_000,
    val message: String? = null,
)

class CaptureStateMachine(
    initial: CaptureState = CaptureState(),
) {
    var state: CaptureState = initial
        private set

    fun transition(
        status: CaptureStatus,
        message: String? = null,
    ): CaptureState {
        require(status in allowedNext(state.status)) {
            "Invalid capture transition: ${state.status} -> $status"
        }
        state = state.copy(status = status, message = message)
        return state
    }

    fun reset(): CaptureState {
        state = CaptureState()
        return state
    }

    fun updateAudioStats(
        bytesCaptured: Long,
        inputSampleRateHz: Int,
    ): CaptureState {
        state = state.copy(
            bytesCaptured = bytesCaptured,
            inputSampleRateHz = inputSampleRateHz,
        )
        return state
    }

    private fun allowedNext(from: CaptureStatus): Set<CaptureStatus> = when (from) {
        CaptureStatus.IDLE -> setOf(
            CaptureStatus.REQUESTING_PERMISSION,
            CaptureStatus.STARTING_CAPTURE,
            CaptureStatus.ERROR,
        )
        CaptureStatus.REQUESTING_PERMISSION -> setOf(
            CaptureStatus.STARTING_CAPTURE,
            CaptureStatus.IDLE,
            CaptureStatus.ERROR,
        )
        CaptureStatus.STARTING_CAPTURE -> setOf(
            CaptureStatus.AUDIO_CAPTURE_READY,
            CaptureStatus.STOPPING,
            CaptureStatus.ERROR,
        )
        CaptureStatus.AUDIO_CAPTURE_READY -> setOf(
            CaptureStatus.CONNECTING_GATEWAY,
            CaptureStatus.STOPPING,
            CaptureStatus.ERROR,
        )
        CaptureStatus.CONNECTING_GATEWAY -> setOf(
            CaptureStatus.CAPTURING,
            CaptureStatus.RECONNECTING,
            CaptureStatus.STOPPING,
            CaptureStatus.ERROR,
        )
        CaptureStatus.CAPTURING -> setOf(
            CaptureStatus.RECONNECTING,
            CaptureStatus.STOPPING,
            CaptureStatus.ERROR,
        )
        CaptureStatus.RECONNECTING -> setOf(
            CaptureStatus.CAPTURING,
            CaptureStatus.STOPPING,
            CaptureStatus.ERROR,
        )
        CaptureStatus.STOPPING -> setOf(
            CaptureStatus.IDLE,
            CaptureStatus.ERROR,
        )
        CaptureStatus.ERROR -> setOf(
            CaptureStatus.IDLE,
            CaptureStatus.REQUESTING_PERMISSION,
            CaptureStatus.STARTING_CAPTURE,
        )
    }
}
