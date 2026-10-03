const OFFSCREEN_DOCUMENT_PATH = 'src/offscreen.html';
const DEFAULT_CAPTURE_STATE = {
  captureToken: null,
  status: 'idle',
  tabId: null,
  error: null,
  startedAt: null,
  sessionId: null,
  reconnectAttempt: 0,
  droppedAudioMs: 0,
  reconnectCount: 0,
  lastMetrics: null,
};

let creatingOffscreen = null;
let operation = 0;
let activeToken;
let stateQueue = Promise.resolve();

function checkOperation(id) {
  if (id !== operation) throw new Error('Capture operation cancelled');
}

function matchesCapture(state, message) {
  return !!message.captureToken && message.captureToken === activeToken &&
    state.captureToken === message.captureToken && state.tabId === message.tabId &&
    ['starting', 'capturing', 'reconnecting', 'stopping'].includes(state.status);
}

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
  const state = stored.captureState || { ...DEFAULT_CAPTURE_STATE };
  if (activeToken === undefined) activeToken = state.captureToken;
  return state;
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
  const id = operation;
  try {
    await ensureContentScript(tabId);
    if (id !== operation) return;
    if (message.captureToken && message.type !== 'overlay.hide' &&
        message.captureToken !== activeToken) return;
    await chrome.tabs.sendMessage(tabId, message);
  } catch (_) {
    // Restricted pages (chrome://, extension stores, etc.) cannot be scripted.
  }
}

function setCaptureState(state, id = operation) {
  const task = stateQueue.then(async () => {
    if (id !== operation) return getCaptureState();
    const value = typeof state === 'function' ? state(await getCaptureState()) : state;
    if (!value || id !== operation) return getCaptureState();
    const next = { ...DEFAULT_CAPTURE_STATE, ...value };
    await chrome.storage.session.set({ captureState: next });
    if (id !== operation) return next;
    if (next.tabId) {
      await sendOverlayMessage(next.tabId, {
        type: 'overlay.state', captureToken: next.captureToken, state: next,
      });
    }
    return next;
  });
  stateQueue = task.catch(() => undefined);
  return task;
}

async function storedCaptureConfig() {
  const saved = await chrome.storage.local.get([
    'gateway',
    'sourceLanguage',
    'targetLanguage',
    'displayMode',
  ]);

  return {
    gateway: saved.gateway || 'ws://127.0.0.1:8000/v1/live',
    sourceLanguage: saved.sourceLanguage || 'ja-JP',
    targetLanguage: saved.targetLanguage || 'zh-CN',
    displayMode: saved.displayMode || 'bilingual',
  };
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error('No active tab');
  return tab;
}

async function hideOverlay(tabId, captureToken) {
  await sendOverlayMessage(tabId, { type: 'overlay.hide', captureToken });
}

async function stopOffscreenCapture(captureToken) {
  await ensureOffscreenDocument();
  const response = await chrome.runtime.sendMessage({
    target: 'offscreen',
    type: 'offscreen.capture.stop',
    captureToken,
  });
  if (response && response.ok === false) {
    throw new Error(response.error || 'Failed to stop offscreen capture');
  }
  return response || { ok: true, metrics: null };
}

async function stopCapture({ finalState = DEFAULT_CAPTURE_STATE, hide = true } = {}) {
  const id = ++operation;
  const token = activeToken;
  const current = await getCaptureState();
  checkOperation(id);
  const capturedTabId = current.tabId;
  if (current.status !== 'idle') {
    await setCaptureState({ ...current, status: 'stopping', error: null }, id);
    checkOperation(id);
  }
  const response = await stopOffscreenCapture(token || current.captureToken).catch(() => null);
  checkOperation(id);
  if (hide) await hideOverlay(capturedTabId, token || current.captureToken);
  checkOperation(id);
  activeToken = null;
  return setCaptureState({
    ...finalState, lastMetrics: response?.metrics || current.lastMetrics || null,
  }, id);
}

async function startCapture(config) {
  const id = ++operation;
  const token = crypto.randomUUID();
  const oldToken = activeToken;
  activeToken = token;
  let tab = null;
  try {
    const existing = await getCaptureState();
    checkOperation(id);
    if (existing.status !== 'idle') {
      await stopOffscreenCapture(oldToken || existing.captureToken).catch(() => undefined);
      checkOperation(id);
      await hideOverlay(existing.tabId, oldToken || existing.captureToken);
      checkOperation(id);
    }
    tab = await activeTab();
    checkOperation(id);
    await ensureContentScript(tab.id);
    checkOperation(id);
    const startingState = await setCaptureState({
      captureToken: token, status: 'starting', tabId: tab.id,
      startedAt: Date.now(), lastMetrics: existing.lastMetrics || null,
    }, id);
    checkOperation(id);
    await ensureOffscreenDocument();
    checkOperation(id);
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
    checkOperation(id);
    await sendOverlayMessage(tab.id, {
      type: 'overlay.show', captureToken: token, state: startingState,
    });
    checkOperation(id);
    const response = await chrome.runtime.sendMessage({
      target: 'offscreen', type: 'offscreen.capture.start', captureToken: token,
      streamId, tabId: tab.id, config,
    });
    checkOperation(id);
    if (!response?.ok) throw new Error(response?.error || 'VeilSub capture failed to start');
    return setCaptureState((latest) => latest.captureToken === token ? {
      ...latest, status: 'capturing', sessionId: response.sessionId || null,
    } : null, id);
  } catch (error) {
    if (id !== operation) throw error;
    await stopOffscreenCapture(token).catch(() => undefined);
    checkOperation(id);
    activeToken = null;
    await setCaptureState({
      captureToken: null, status: 'error', tabId: tab?.id || null, error: error.message,
    }, id);
    throw error;
  }
}

async function failCapturedSession(message, captureToken) {
  const id = operation;
  const current = await getCaptureState();
  if (id !== operation || current.captureToken !== captureToken || activeToken !== captureToken) return;
  return stopCapture({ hide: false, finalState: {
    ...current, status: 'error', error: message, startedAt: null, captureToken: null,
  } });
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

  if (message.type?.startsWith('offscreen.capture.') || message.type === 'subtitle.event') {
    const id = operation;
    getCaptureState().then(async (current) => {
      if (id !== operation || !matchesCapture(current, message)) return;
      if (message.type === 'offscreen.capture.error') {
        if (current.status !== 'stopping') {
          await failCapturedSession(message.error || 'Capture session failed', message.captureToken);
        }
      } else if (message.type === 'subtitle.event') {
        await sendOverlayMessage(message.tabId, {
          type: 'overlay.subtitle', captureToken: message.captureToken, event: message.event,
        });
      } else if (message.type === 'offscreen.capture.state') {
        if (current.status === 'stopping') return;
        await setCaptureState((latest) => matchesCapture(latest, message) &&
          latest.status !== 'stopping' ? {
          ...latest, status: message.status || latest.status, error: null,
          sessionId: message.sessionId ?? latest.sessionId,
          reconnectAttempt: message.reconnectAttempt ?? latest.reconnectAttempt,
        } : null, id);
      } else if (message.type === 'offscreen.capture.stats') {
        await setCaptureState((latest) => matchesCapture(latest, message) ? {
          ...latest, droppedAudioMs: message.droppedAudioMs ?? latest.droppedAudioMs,
          reconnectCount: message.reconnectCount ?? latest.reconnectCount,
        } : null, id);
      } else if (message.type === 'offscreen.capture.metrics') {
        await setCaptureState((latest) => matchesCapture(latest, message) ? {
          ...latest, lastMetrics: message.metrics || latest.lastMetrics,
        } : null, id);
      }
    }).catch(console.error);
  }

  return undefined;
});

chrome.tabs.onRemoved.addListener((tabId) => {
  const id = operation;
  getCaptureState().then((state) => {
    if (id !== operation || state.tabId !== tabId) return;
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
  const id = operation;
  getCaptureState().then((state) => {
    if (id !== operation || state.tabId !== removedTabId) return;
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

  const id = operation;
  getCaptureState().then(async (state) => {
    if (id !== operation || state.tabId !== tabId) return;

    await sendOverlayMessage(tabId, {
      type: 'overlay.show',
      captureToken: state.captureToken,
      state,
    });
  });
});

chrome.tabCapture.onStatusChanged.addListener((info) => {
  const id = operation;
  getCaptureState().then((state) => {
    if (id !== operation || state.tabId !== info.tabId) return;
    if (state.status === 'stopping' || state.status === 'idle') return;

    if (info.status === 'error') {
      failCapturedSession('Chrome reported a tab-capture error.', state.captureToken).catch(console.error);
      return;
    }

    if (info.status === 'stopped' && ['capturing', 'reconnecting'].includes(state.status)) {
      failCapturedSession('Tab capture stopped unexpectedly.', state.captureToken).catch(console.error);
    }
  });
});


chrome.commands.onCommand.addListener((command) => {
  if (command !== 'toggle-subtitles') return;

  const id = operation;
  getCaptureState()
    .then(async (state) => {
      if (id !== operation) return;
      if (['starting', 'capturing', 'reconnecting', 'stopping'].includes(state.status)) {
        await stopCapture();
        return;
      }

      const config = await storedCaptureConfig();
      if (id !== operation) return;
      await startCapture(config);
    })
    .catch(console.error);
});
