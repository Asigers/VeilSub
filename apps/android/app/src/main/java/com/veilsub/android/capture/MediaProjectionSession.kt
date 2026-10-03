package com.veilsub.android.capture

import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Handler
import android.os.Looper
import java.io.Closeable

class MediaProjectionSession(
    context: Context,
    resultCode: Int,
    resultData: Intent,
    private val onRevoked: () -> Unit,
) : Closeable {
    private val manager =
        context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager

    val projection: MediaProjection = manager.getMediaProjection(resultCode, resultData)

    private var closing = false
    private val callback = object : MediaProjection.Callback() {
        override fun onStop() {
            if (!closing) {
                onRevoked()
            }
        }
    }

    init {
        projection.registerCallback(callback, Handler(Looper.getMainLooper()))
    }

    override fun close() {
        if (closing) return
        closing = true
        runCatching { projection.unregisterCallback(callback) }
        runCatching { projection.stop() }
    }
}
