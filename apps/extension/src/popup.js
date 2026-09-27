const gateway = document.querySelector('#gateway');
const source = document.querySelector('#source');
const target = document.querySelector('#target');
const status = document.querySelector('#status');

const saved = await chrome.storage.local.get(['gateway', 'sourceLanguage', 'targetLanguage']);
gateway.value = saved.gateway || gateway.value;
source.value = saved.sourceLanguage || source.value;
target.value = saved.targetLanguage || target.value;

document.querySelector('#start').addEventListener('click', async () => {
  status.textContent = 'Starting…';
  const config = {
    gateway: gateway.value.trim(),
    sourceLanguage: source.value.trim(),
    targetLanguage: target.value.trim(),
  };
  await chrome.storage.local.set(config);
  const response = await chrome.runtime.sendMessage({ type: 'capture.start', config });
  status.textContent = response?.ok ? 'Capturing current tab' : (response?.error || 'Failed to start');
});

document.querySelector('#stop').addEventListener('click', async () => {
  const response = await chrome.runtime.sendMessage({ type: 'capture.stop' });
  status.textContent = response?.ok ? 'Stopped' : (response?.error || 'Failed to stop');
});
