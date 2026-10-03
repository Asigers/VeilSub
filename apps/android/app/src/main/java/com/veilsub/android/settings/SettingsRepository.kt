package com.veilsub.android.settings

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.veilSubDataStore by preferencesDataStore(name = "veilsub_settings")

class SettingsRepository(
    private val context: Context,
) {
    private object Keys {
        val gatewayUrl = stringPreferencesKey("gateway_url")
        val sourceLanguage = stringPreferencesKey("source_language")
        val targetLanguage = stringPreferencesKey("target_language")
        val displayMode = stringPreferencesKey("display_mode")
        val fontSizeSp = intPreferencesKey("font_size_sp")
        val backgroundOpacity = intPreferencesKey("background_opacity")
        val subtitleDelayMs = intPreferencesKey("subtitle_delay_ms")
    }

    val settings: Flow<UserSettings> = context.veilSubDataStore.data.map { values ->
        UserSettings(
            gatewayUrl = values[Keys.gatewayUrl] ?: "ws://10.0.2.2:8000/v1/live",
            sourceLanguage = values[Keys.sourceLanguage] ?: "ja-JP",
            targetLanguage = values[Keys.targetLanguage] ?: "zh-CN",
            displayMode = values[Keys.displayMode] ?: "bilingual",
            fontSizeSp = values[Keys.fontSizeSp] ?: 21,
            backgroundOpacityPercent = values[Keys.backgroundOpacity] ?: 72,
            subtitleDelayMs = values[Keys.subtitleDelayMs] ?: 0,
        )
    }

    suspend fun updateGatewayUrl(value: String) {
        context.veilSubDataStore.edit { it[Keys.gatewayUrl] = value.trim() }
    }

    suspend fun updateSourceLanguage(value: String) {
        context.veilSubDataStore.edit { it[Keys.sourceLanguage] = value.trim() }
    }

    suspend fun updateTargetLanguage(value: String) {
        context.veilSubDataStore.edit { it[Keys.targetLanguage] = value.trim() }
    }
}
