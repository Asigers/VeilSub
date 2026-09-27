async function ensureOffscreenDocument() {
  const hasDocument = chrome.offscreen.hasDocument ? await chrome.offscreen.hasDocument() : false;
  if (hasDocument) return;

  await chrome.offscreen.createDocument({
    url: 'src/offscreen.html',
    reasons: ['USER_MEDIA'],
    justification: 'Capture current tab audio for live subtitles',
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error('No active tab');
  return tab;
}

async function startCapture(config) {
  const tab = await activeTab();
  await ensureOffscreenDocument();
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });

  await chrome.tabs.sendMessage(tab.id, { type: 'overlay.show' }).catch(() => undefined);
  await chrome.runtime.sendMessage({
    type: 'offscreen.capture.start',
    streamId,
    tabId: tab.id,
    config,
  });
}

async function stopCapture() {
  await chrome.runtime.sendMessage({ type: 'offscreen.capture.stop' });
  const tab = await activeTab().catch(() => null);
  if (tab?.id) {
    await chrome.tabs.sendMessage(tab.id, { type: 'overlay.hide' }).catch(() => undefined);
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === 'capture.start') {
    startCapture(message.config)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === 'capture.stop') {
    stopCapture()
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === 'subtitle.event' && message.tabId) {
    chrome.tabs.sendMessage(message.tabId, {
      type: 'overlay.subtitle',
      event: message.event,
    }).catch(() => undefined);
  }
});
