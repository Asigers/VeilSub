const OFFSCREEN_DOCUMENT_PATH = 'src/offscreen.html';
const DEFAULT_CAPTURE_STATE = {
  status: 'idle',
  tabId: null,
  error: null,
  startedAt: null,
  sessionId: null,
  reconnectAttempt: 0,
  droppedAudioMs: 0,
};

let creatingOffscreen = null;

async function ensureOffscreenDocument() {
  const offscreenUrl = chrome.runtime.getURL(OFFSCREEN_DOCUMENT_PATH);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ['OFFSCREEN_DOCUMENT'],
    documentUrls: [offscreenUrl],
  });

  if (contexts.length > 0) return;
  if (creatingOffscreen) return creatingOffscreen;

  creatingOffscreen = chrome.offscreen.createDocument({
    url: OFFSCREEN_DOCUMENT_PATH,
    reasons: ['USER_MEDIA'],
    justification: 'Capture current tab audio for live subtitles',
  });

  try {
    await creatingOffscreen;
  } finally {
    creatingOffscreen = null;
  }
}

async function getCaptureState() {
  const stored = await chrome.storage.session.get('captureState');
  return stored.captureState || { ...DEFAULT_CAPTURE_STATE };
}

async function ensureContentScript(tabId) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, { type: 'overlay.ping' });
    if (response?.ok) return;
  } catch (_) {
    // Missing content script: inject the packaged script below.
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ['src/content.js'],
  });
}

async function sendOverlayMessage(tabId, message) {
  if (!tabId) return;

  try {
    await ensureContentScript(tabId);
    await chrome.tabs.sendMessage(tabId, message);
  } catch (_) {
    // Restricted pages (chrome://, extension stores, etc.) cannot be scripted.
  }
}

async function setCaptureState(state) {
  const next = { ...DEFAULT_CAPTURE_STATE, ...state };
  await chrome.storage.session.set({ captureState: next });

  if (next.tabId) {
    await sendOverlayMessage(next.tabId, {
      type: 'overlay.state',
      state: next,
    });
  }

  return next;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error('No active tab');
  return tab;
}

async function hideOverlay(tabId) {
  await sendOverlayMessage(tabId, { type: 'overlay.hide' });
}

async function stopOffscreenCapture() {
  await ensureOffscreenDocument();
  const response = await chrome.runtime.sendMessage({
    target: 'offscreen',
    type: 'offscreen.capture.stop',
  });
  if (response && response.ok === false) {
    throw new Error(response.error || 'Failed to stop offscreen capture');
  }
}

async function stopCapture({ finalState = DEFAULT_CAPTURE_STATE, hide = true } = {}) {
  const current = await getCaptureState();
  const capturedTabId = current.tabId;

  if (current.status !== 'idle') {
    await setCaptureState({
      ...current,
      status: 'stopping',
      error: null,
    });
  }

  await stopOffscreenCapture().catch(() => undefined);

  if (hide) {
    await hideOverlay(capturedTabId);
  }

  return setCaptureState(finalState);
}

async function startCapture(config) {
  const existing = await getCaptureState();
  if (existing.status !== 'idle') {
    await stopCapture();
  }

  const tab = await activeTab();
  await ensureContentScript(tab.id);

  const startingState = await setCaptureState({
    status: 'starting',
    tabId: tab.id,
    error: null,
    startedAt: Date.now(),
    sessionId: null,
    reconnectAttempt: 0,
    droppedAudioMs: 0,
  });

  try {
    await ensureOffscreenDocument();
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });

    await sendOverlayMessage(tab.id, {
      type: 'overlay.show',
      state: startingState,
    });

    const response = await chrome.runtime.sendMessage({
      target: 'offscreen',
      type: 'offscreen.capture.start',
      streamId,
      tabId: tab.id,
      config,
    });

    if (!response?.ok) {
      throw new Error(response?.error || 'VeilSub capture failed to start');
    }

    return setCaptureState({
      ...startingState,
      status: 'capturing',
      sessionId: response.sessionId || null,
    });
  } catch (error) {
    await stopOffscreenCapture().catch(() => undefined);
    await setCaptureState({
      status: 'error',
      tabId: tab.id,
      error: error instanceof Error ? error.message : String(error),
      startedAt: null,
    });
    throw error;
  }
}

async function failCapturedSession(message) {
  const current = await getCaptureState();
  const tabId = current.tabId;

  await setCaptureState({
    ...current,
    status: 'stopping',
    error: null,
  });
  await stopOffscreenCapture().catch(() => undefined);
  await setCaptureState({
    status: 'error',
    tabId,
    error: message,
    startedAt: null,
    droppedAudioMs: current.droppedAudioMs || 0,
  });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target === 'offscreen') return undefined;

  if (message.type === 'capture.start') {
    startCapture(message.config)
      .then((state) => sendResponse({ ok: true, state }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === 'capture.stop') {
    stopCapture()
      .then((state) => sendResponse({ ok: true, state }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === 'capture.getState') {
    getCaptureState()
      .then((state) => sendResponse({ ok: true, state }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === 'offscreen.capture.error') {
    failCapturedSession(message.error || 'Capture session failed').catch(console.error);
    return undefined;
  }

  if (message.type === 'offscreen.capture.state') {
    getCaptureState().then((current) => {
      if (current.tabId !== message.tabId) return;
      setCaptureState({
        ...current,
        status: message.status || current.status,
        error: null,
        sessionId: message.sessionId ?? current.sessionId,
        reconnectAttempt: message.reconnectAttempt ?? current.reconnectAttempt,
      }).catch(console.error);
    });
    return undefined;
  }

  if (message.type === 'offscreen.capture.stats') {
    getCaptureState().then((current) => {
      if (current.tabId !== message.tabId) return;
      setCaptureState({
        ...current,
        droppedAudioMs: message.droppedAudioMs ?? current.droppedAudioMs,
      }).catch(console.error);
    });
    return undefined;
  }

  if (message.type === 'subtitle.event' && message.tabId) {
    sendOverlayMessage(message.tabId, {
      type: 'overlay.subtitle',
      event: message.event,
    });
  }

  return undefined;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  getCaptureState().then((state) => {
    if (state.tabId !== tabId) return;
    stopCapture({
      hide: false,
      finalState: {
        status: 'error',
        tabId: null,
        error: 'The captured tab was closed.',
        startedAt: null,
      },
    }).catch(console.error);
  });
});

chrome.tabs.onReplaced.addListener((_addedTabId, removedTabId) => {
  getCaptureState().then((state) => {
    if (state.tabId !== removedTabId) return;
    stopCapture({
      hide: false,
      finalState: {
        status: 'error',
        tabId: null,
        error: 'The captured tab was replaced.',
        startedAt: null,
      },
    }).catch(console.error);
  });
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status !== 'complete') return;

  getCaptureState().then(async (state) => {
    if (state.tabId !== tabId) return;

    await sendOverlayMessage(tabId, {
      type: 'overlay.show',
      state,
    });
  });
});

chrome.tabCapture.onStatusChanged.addListener((info) => {
  getCaptureState().then((state) => {
    if (state.tabId !== info.tabId) return;
    if (state.status === 'stopping' || state.status === 'idle') return;

    if (info.status === 'error') {
      failCapturedSession('Chrome reported a tab-capture error.').catch(console.error);
      return;
    }

    if (info.status === 'stopped' && ['capturing', 'reconnecting'].includes(state.status)) {
      failCapturedSession('Tab capture stopped unexpectedly.').catch(console.error);
    }
  });
});
