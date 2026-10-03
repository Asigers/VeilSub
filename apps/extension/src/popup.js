const gateway = document.querySelector('#gateway');
const source = document.querySelector('#source');
const target = document.querySelector('#target');
const displayMode = document.querySelector('#displayMode');
const fontSize = document.querySelector('#fontSize');
const verticalPosition = document.querySelector('#verticalPosition');
const backgroundOpacity = document.querySelector('#backgroundOpacity');
const subtitleDelayMs = document.querySelector('#subtitleDelayMs');
const status = document.querySelector('#status');
const metrics = document.querySelector('#metrics');
const startButton = document.querySelector('#start');
const stopButton = document.querySelector('#stop');

const saved = await chrome.storage.local.get([
  'gateway',
  'sourceLanguage',
  'targetLanguage',
  'displayMode',
  'fontSize',
  'verticalPosition',
  'backgroundOpacity',
  'subtitleDelayMs',
]);

gateway.value = saved.gateway || gateway.value;
source.value = saved.sourceLanguage || source.value;
target.value = saved.targetLanguage || target.value;
displayMode.value = saved.displayMode || 'bilingual';
fontSize.value = saved.fontSize ?? 21;
verticalPosition.value = saved.verticalPosition ?? 9;
backgroundOpacity.value = saved.backgroundOpacity ?? 72;
subtitleDelayMs.value = saved.subtitleDelayMs ?? 0;

function formatMetric(value, suffix = 'ms') {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value)} ${suffix}`;
}

function renderMetrics(data) {
  if (!data) {
    metrics.style.display = 'none';
    metrics.textContent = '';
    return;
  }

  metrics.style.display = 'block';
  metrics.replaceChildren();
  const heading = document.createElement('strong');
  heading.textContent = 'Last session';
  metrics.appendChild(heading);
  const lines = [
    `TTFS: ${formatMetric(data.time_to_first_subtitle_ms)}`,
    `ASR final P50/P95: ${formatMetric(data.asr_final_latency_ms_p50)} / ${formatMetric(data.asr_final_latency_ms_p95)}`,
    `Translation P50/P95: ${formatMetric(data.translation_latency_ms_p50)} / ${formatMetric(data.translation_latency_ms_p95)}`,
    `Translation calls: ${data.translation_calls ?? 0} · failures: ${data.translation_failures ?? 0} · timeouts: ${data.translation_timeouts ?? 0}`,
    `Dropped: ${formatMetric(data.dropped_audio_ms)} · reconnects: ${data.reconnect_count ?? 0}`,
    `Audio: ${data.estimated_asr_seconds ?? 0}s · translated chars: ${data.translation_characters ?? 0}`,
  ];
  if (data.translation_last_error) {
    lines.push(`Last translation error: ${data.translation_last_error}`);
  }
  for (const text of lines) {
    const line = document.createElement('div');
    // Provider diagnostics are text, never trusted HTML.
    line.textContent = text;
    metrics.appendChild(line);
  }
}

function renderState(state) {
  renderMetrics(state?.lastMetrics);
  const labels = {
    idle: 'Idle',
    starting: 'Starting…',
    capturing: state?.droppedAudioMs
      ? `Capturing · dropped ${Math.round(state.droppedAudioMs)} ms`
      : 'Capturing current tab',
    stopping: 'Stopping…',
    reconnecting: state?.reconnectAttempt
      ? `Reconnecting · attempt ${state.reconnectAttempt}`
      : 'Reconnecting…',
    error: state?.error || 'Capture failed',
  };

  status.textContent = labels[state?.status] || state?.status || 'Idle';
  startButton.disabled = ['starting', 'capturing', 'stopping'].includes(state?.status);
  stopButton.disabled = !['starting', 'capturing', 'reconnecting', 'error'].includes(
    state?.status
  );
}

function bindRange(input, valueElement, suffix, storageKey) {
  const render = () => {
    valueElement.textContent = `${input.value}${suffix}`;
  };

  render();
  input.addEventListener('input', async () => {
    render();
    await chrome.storage.local.set({
      [storageKey]: Number(input.value),
    });
  });
}

bindRange(fontSize, document.querySelector('#fontSizeValue'), ' px', 'fontSize');
bindRange(
  verticalPosition,
  document.querySelector('#verticalPositionValue'),
  ' vh',
  'verticalPosition'
);
bindRange(
  backgroundOpacity,
  document.querySelector('#backgroundOpacityValue'),
  '%',
  'backgroundOpacity'
);
bindRange(
  subtitleDelayMs,
  document.querySelector('#subtitleDelayMsValue'),
  ' ms',
  'subtitleDelayMs'
);

async function refreshState() {
  const response = await chrome.runtime.sendMessage({ type: 'capture.getState' });
  if (response?.ok) renderState(response.state);
}

await refreshState();

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== 'session' || !changes.captureState) return;
  renderState(changes.captureState.newValue);
});

displayMode.addEventListener('change', async () => {
  await chrome.storage.local.set({ displayMode: displayMode.value });
});

startButton.addEventListener('click', async () => {
  const config = {
    gateway: gateway.value.trim(),
    sourceLanguage: source.value.trim(),
    targetLanguage: target.value.trim(),
    displayMode: displayMode.value,
  };

  await chrome.storage.local.set({
    gateway: config.gateway,
    sourceLanguage: config.sourceLanguage,
    targetLanguage: config.targetLanguage,
    displayMode: config.displayMode,
  });

  renderState({ status: 'starting' });
  const response = await chrome.runtime.sendMessage({ type: 'capture.start', config });
  if (!response?.ok) {
    renderState({ status: 'error', error: response?.error || 'Failed to start' });
  }
});

stopButton.addEventListener('click', async () => {
  const response = await chrome.runtime.sendMessage({ type: 'capture.stop' });
  if (!response?.ok) {
    renderState({ status: 'error', error: response?.error || 'Failed to stop' });
  }
});
