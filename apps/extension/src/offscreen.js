const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 8000;
const MAX_SOCKET_BUFFERED_BYTES = 64 * 1024;
const STOP_ACK_TIMEOUT_MS = 5000;
const SAMPLE_RATE_HZ = 16000;
const BYTES_PER_SAMPLE = 2;

let stream = null;
let audioContext = null;
let processor = null;
let socket = null;
let tabId = null;
let activeConfig = null;
let sessionReady = false;
let stopping = false;
let reconnectTask = null;
let captureGeneration = 0;
let droppedAudioMs = 0;
let reconnectCount = 0;
let lastStatsSentAt = 0;
let stopAckResolver = null;
let lastSessionMetrics = null;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function notifyCaptureError(error) {
  await chrome.runtime.sendMessage({
    type: 'offscreen.capture.error',
    error,
  }).catch(() => undefined);
}

async function notifyCaptureState(status, extras = {}) {
  if (!tabId) return;
  await chrome.runtime.sendMessage({
    type: 'offscreen.capture.state',
    tabId,
    status,
    ...extras,
  }).catch(() => undefined);
}

async function publishStats(force = false) {
  if (!tabId) return;

  const now = Date.now();
  if (!force && now - lastStatsSentAt < 1000) return;
  lastStatsSentAt = now;

  const stats = {
    reconnectCount,
    droppedAudioMs: Math.round(droppedAudioMs),
  };

  await chrome.runtime.sendMessage({
    type: 'offscreen.capture.stats',
    tabId,
    ...stats,
  }).catch(() => undefined);

  if (sessionReady && socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({
      type: 'client.stats',
      reconnect_count: stats.reconnectCount,
      dropped_audio_ms: stats.droppedAudioMs,
    }));
  }
}

function frameDurationMs(buffer) {
  return (buffer.byteLength / BYTES_PER_SAMPLE / SAMPLE_RATE_HZ) * 1000;
}

function dropFrame(buffer) {
  droppedAudioMs += frameDurationMs(buffer);
  publishStats().catch(() => undefined);
}

async function closeGateway({ graceful = false } = {}) {
  const ws = socket;
  if (!ws) return null;

  let stoppedPayload = null;

  if (graceful && sessionReady && ws.readyState === WebSocket.OPEN) {
    const stopped = new Promise((resolve) => {
      stopAckResolver = (payload) => {
        stoppedPayload = payload || null;
        resolve();
      };
    });

    try {
      ws.send(JSON.stringify({
        type: 'client.stats',
        reconnect_count: reconnectCount,
        dropped_audio_ms: Math.round(droppedAudioMs),
      }));
      ws.send(JSON.stringify({ type: 'session.stop' }));
      await Promise.race([stopped, delay(STOP_ACK_TIMEOUT_MS)]);
    } catch (_) {
      // A normal stop has a bounded wait; cleanup continues either way.
    } finally {
      stopAckResolver = null;
    }
  }

  if (socket === ws) {
    socket = null;
    sessionReady = false;
  }

  try {
    ws.close();
  } catch (_) {
    // Ignore close races.
  }

  return stoppedPayload;
}

async function cleanup({ graceful = false } = {}) {
  captureGeneration += 1;
  reconnectTask = null;

  const stoppedPayload = await closeGateway({ graceful });
  if (stoppedPayload?.metrics) {
    lastSessionMetrics = stoppedPayload.metrics;
    await chrome.runtime.sendMessage({
      type: 'offscreen.capture.metrics',
      tabId,
      metrics: lastSessionMetrics,
    }).catch(() => undefined);
  }

  processor?.disconnect();
  processor = null;

  stream?.getTracks().forEach((track) => track.stop());
  stream = null;

  await audioContext?.close().catch(() => undefined);
  audioContext = null;

  await publishStats(true);
  tabId = null;
  activeConfig = null;
  return lastSessionMetrics;
}

async function stop() {
  stopping = true;
  try {
    return await cleanup({ graceful: true });
  } finally {
    stopping = false;
  }
}

function reconnectDelayMs(attempt) {
  return Math.min(
    BASE_RECONNECT_DELAY_MS * (2 ** Math.max(0, attempt - 1)),
    MAX_RECONNECT_DELAY_MS
  );
}

async function scheduleReconnect(reason, generation) {
  if (stopping || generation !== captureGeneration || reconnectTask) return;

  sessionReady = false;
  reconnectCount += 1;
  publishStats(true).catch(() => undefined);

  reconnectTask = (async () => {
    let lastError = reason;

    for (let attempt = 1; attempt <= MAX_RECONNECT_ATTEMPTS; attempt += 1) {
      if (stopping || generation !== captureGeneration) return;

      await notifyCaptureState('reconnecting', {
        reconnectAttempt: attempt,
      });
      await delay(reconnectDelayMs(attempt));

      if (stopping || generation !== captureGeneration) return;

      try {
        const ready = await connectGatewayOnce(activeConfig, tabId, generation);
        if (stopping || generation !== captureGeneration) return;

        await notifyCaptureState('capturing', {
          sessionId: ready.session_id || null,
          reconnectAttempt: 0,
        });
        return;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }

    if (!stopping && generation === captureGeneration) {
      await notifyCaptureError(
        `Gateway reconnect failed after ${MAX_RECONNECT_ATTEMPTS} attempts: ${lastError}`
      );
    }
  })().finally(() => {
    reconnectTask = null;
  });

  await reconnectTask;
}

function connectGatewayOnce(config, currentTabId, generation) {
  if (!config?.gateway) {
    return Promise.reject(new Error('Gateway URL is missing'));
  }

  const ws = new WebSocket(config.gateway);
  socket = ws;
  sessionReady = false;
  ws.binaryType = 'arraybuffer';

  return new Promise((resolve, reject) => {
    let settled = false;
    let readyForThisSocket = false;

    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      try {
        ws.close();
      } catch (_) {
        // Ignore close races.
      }
      reject(new Error('Gateway did not become ready within 10 seconds'));
    }, 10_000);

    const rejectStartup = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    ws.addEventListener('open', () => {
      if (generation !== captureGeneration || stopping) {
        ws.close();
        return;
      }

      ws.send(JSON.stringify({
        type: 'session.start',
        source_language: config.sourceLanguage,
        target_language: config.targetLanguage,
        audio: { encoding: 'linear16', sample_rate_hz: SAMPLE_RATE_HZ, channels: 1 },
      }));
    });

    ws.addEventListener('message', (event) => {
      let payload;
      try {
        payload = JSON.parse(event.data);
      } catch (_) {
        return;
      }

      if (payload.type === 'session.ready') {
        if (generation !== captureGeneration || socket !== ws) {
          ws.close();
          return;
        }

        readyForThisSocket = true;
        sessionReady = true;

        if (!settled) {
          settled = true;
          clearTimeout(timeout);
          resolve(payload);
        }
        return;
      }

      if (payload.type === 'session.stopped') {
        lastSessionMetrics = payload.metrics || null;
        stopAckResolver?.(payload);
        return;
      }

      if (payload.type === 'session.error') {
        const message = payload.message || 'Gateway session failed';

        if (!readyForThisSocket) {
          rejectStartup(new Error(message));
          return;
        }

        try {
          ws.close(1011, message.slice(0, 120));
        } catch (_) {
          ws.close();
        }
        return;
      }

      if (payload.type?.startsWith('subtitle.')) {
        chrome.runtime.sendMessage({
          type: 'subtitle.event',
          tabId: currentTabId,
          event: payload,
        }).catch(() => undefined);
      }
    });

    ws.addEventListener('error', () => {
      if (!readyForThisSocket) {
        rejectStartup(new Error('Could not connect to the VeilSub gateway'));
      }
    });

    ws.addEventListener('close', () => {
      clearTimeout(timeout);

      if (socket === ws) {
        socket = null;
        sessionReady = false;
      }

      if (stopping || generation !== captureGeneration) {
        stopAckResolver?.(null);
        return;
      }

      if (!readyForThisSocket) {
        rejectStartup(new Error('Gateway connection closed before session.ready'));
        return;
      }

      scheduleReconnect('Gateway connection closed unexpectedly', generation)
        .catch(() => undefined);
    });
  });
}

function handleAudioFrame(buffer) {
  if (stopping) return;

  if (
    !sessionReady ||
    socket?.readyState !== WebSocket.OPEN ||
    socket.bufferedAmount > MAX_SOCKET_BUFFERED_BYTES
  ) {
    dropFrame(buffer);
    return;
  }

  socket.send(buffer);
}

async function start(message) {
  await stop();

  stopping = false;
  captureGeneration += 1;
  const generation = captureGeneration;

  tabId = message.tabId;
  activeConfig = message.config;
  droppedAudioMs = 0;
  reconnectCount = 0;
  lastSessionMetrics = null;
  lastStatsSentAt = 0;

  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        mandatory: {
          chromeMediaSource: 'tab',
          chromeMediaSourceId: message.streamId,
        },
      },
      video: false,
    });

    audioContext = new AudioContext({ sampleRate: SAMPLE_RATE_HZ });
    await audioContext.audioWorklet.addModule('pcm-worklet.js');

    const source = audioContext.createMediaStreamSource(stream);
    processor = new AudioWorkletNode(audioContext, 'veilsub-pcm16');

    // tabCapture removes captured audio from local playback; restore it.
    source.connect(audioContext.destination);
    source.connect(processor);

    const silent = audioContext.createGain();
    silent.gain.value = 0;
    processor.connect(silent).connect(audioContext.destination);
    processor.port.onmessage = ({ data }) => handleAudioFrame(data);

    const ready = await connectGatewayOnce(message.config, message.tabId, generation);
    await publishStats(true);
    return ready;
  } catch (error) {
    stopping = true;
    await cleanup({ graceful: false });
    stopping = false;
    throw error;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== 'offscreen') return undefined;

  if (message.type === 'offscreen.capture.start') {
    start(message)
      .then((ready) => {
        sendResponse({
          ok: true,
          sessionId: ready.session_id || null,
        });
      })
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return true;
  }

  if (message.type === 'offscreen.capture.stop') {
    stop()
      .then((metrics) => sendResponse({ ok: true, metrics }))
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return true;
  }

  return undefined;
});
