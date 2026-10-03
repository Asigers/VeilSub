package com.veilsub.android.state

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

object CaptureSessionStore {
    private val machine = CaptureStateMachine()
    private val _state = MutableStateFlow(machine.state)

    val state: StateFlow<CaptureState> = _state.asStateFlow()

    @Synchronized
    fun transition(
        status: CaptureStatus,
        message: String? = null,
    ) {
        _state.value = machine.transition(status, message)
    }

    @Synchronized
    fun updateAudioStats(
        bytesCaptured: Long,
        inputSampleRateHz: Int,
    ) {
        _state.value = machine.updateAudioStats(bytesCaptured, inputSampleRateHz)
    }

    @Synchronized
    fun fail(message: String) {
        val current = machine.state.status
        if (current == CaptureStatus.ERROR) {
            _state.value = machine.state.copy(message = message)
            return
        }

        runCatching {
            machine.transition(CaptureStatus.ERROR, message)
        }.onSuccess {
            _state.value = it
        }.onFailure {
            machine.reset()
            _state.value = machine.transition(CaptureStatus.ERROR, message)
        }
    }

    @Synchronized
    fun reset() {
        _state.value = machine.reset()
    }
}
