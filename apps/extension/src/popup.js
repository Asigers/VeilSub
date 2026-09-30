const gateway = document.querySelector('#gateway');
const source = document.querySelector('#source');
const target = document.querySelector('#target');
const displayMode = document.querySelector('#displayMode');
const status = document.querySelector('#status');
const startButton = document.querySelector('#start');
const stopButton = document.querySelector('#stop');

const saved = await chrome.storage.local.get([
  'gateway',
  'sourceLanguage',
  'targetLanguage',
  'displayMode',
]);

gateway.value = saved.gateway || gateway.value;
source.value = saved.sourceLanguage || source.value;
target.value = saved.targetLanguage || target.value;
displayMode.value = saved.displayMode || 'bilingual';

function renderState(state) {
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
