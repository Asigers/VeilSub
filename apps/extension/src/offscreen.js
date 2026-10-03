const MAX_RECONNECT_ATTEMPTS = 5;
const BASE_RECONNECT_DELAY_MS = 500;
const MAX_RECONNECT_DELAY_MS = 8000;
const MAX_SOCKET_BUFFERED_BYTES = 64 * 1024;
// Gateway stop can take close(7s) + result flush(10s) + translation drain(10s).
const STOP_ACK_TIMEOUT_MS = 35_000;
const SAMPLE_RATE_HZ = 16000;
const BYTES_PER_SAMPLE = 2;

let activeCapture = null;
let operation = 0;

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function current(capture) {
  return activeCapture === capture && !capture.ended;
}

function requireStarting(capture) {
  if (capture.failure) throw new Error(capture.failure);
  if (!current(capture) || capture.stopping) throw new Error('Capture start cancelled');
}

async function notify(capture, type, extras = {}) {
  if (!current(capture)) return;
  await chrome.runtime.sendMessage({
    type, tabId: capture.tabId, captureToken: capture.token, ...extras,
  }).catch(() => undefined);
}

function failCapture(capture, message) {
  if (!current(capture) || capture.stopping || capture.failure) return;
  capture.failure = message;
  // Deliver the cause before cleanup ends this token; do not wait for the
  // background handler to stop media or to suppress further reconnects.
  notify(capture, 'offscreen.capture.error', { error: message }).catch(() => undefined);
  cleanup(capture).catch(console.error);
}

async function publishStats(capture, force = false) {
  if (!current(capture)) return;
  const now = Date.now();
  if (!force && now - capture.lastStatsSentAt < 1000) return;
  capture.lastStatsSentAt = now;
  const stats = {
    reconnectCount: capture.reconnectCount,
    droppedAudioMs: Math.round(capture.droppedAudioMs),
  };
  await notify(capture, 'offscreen.capture.stats', stats);
  const connection = capture.connection;
  if (current(capture) && connection?.ready && connection.ws.readyState === WebSocket.OPEN) {
    connection.ws.send(JSON.stringify({
      type: 'client.stats', reconnect_count: stats.reconnectCount,
      dropped_audio_ms: stats.droppedAudioMs,
    }));
  }
}

async function closeGateway(capture, graceful) {
  const connection = capture.connection;
  if (!connection) return null;
  const ws = connection.ws;
  let payload = null;
  if (graceful && connection.ready && ws.readyState === WebSocket.OPEN) {
    const stopped = new Promise((resolve) => {
      connection.stopAck = (value) => { payload = value; resolve(); };
    });
    let timer;
    try {
      ws.send(JSON.stringify({
        type: 'client.stats', reconnect_count: capture.reconnectCount,
        dropped_audio_ms: Math.round(capture.droppedAudioMs),
      }));
      ws.send(JSON.stringify({ type: 'session.stop' }));
      await Promise.race([stopped, new Promise((resolve) => {
        timer = setTimeout(resolve, STOP_ACK_TIMEOUT_MS);
      })]);
    } catch (_) {
      // Best-effort final flush, bounded by STOP_ACK_TIMEOUT_MS.
    } finally {
      clearTimeout(timer);
      connection.stopAck = null;
    }
  }
  if (capture.connection === connection) capture.connection = null;
  try { ws.close(); } catch (_) { /* Ignore close races. */ }
  return payload;
}

function cleanup(capture, graceful = false) {
  if (!capture) return Promise.resolve(null);
  if (capture.cleanupTask) return capture.cleanupTask;
  capture.stopping = true;
  capture.cleanupTask = (async () => {
    const stopped = await closeGateway(capture, graceful);
    if (stopped?.metrics) {
      capture.metrics = stopped.metrics;
      await notify(capture, 'offscreen.capture.metrics', { metrics: capture.metrics });
    }
    capture.processor?.disconnect();
    capture.stream?.getTracks().forEach((track) => track.stop());
    await capture.audioContext?.close().catch(() => undefined);
    await publishStats(capture, true);
    capture.ended = true;
    if (activeCapture === capture) activeCapture = null;
    return capture.metrics;
  })();
  return capture.cleanupTask;
}

async function stop(token) {
  // Even a pending getUserMedia startup is cancelled synchronously.
  if (token && activeCapture && activeCapture.token !== token) return null;
  operation += 1;
  return cleanup(activeCapture, true);
}

function reconnectDelayMs(attempt) {
  return Math.min(BASE_RECONNECT_DELAY_MS * (2 ** Math.max(0, attempt - 1)),
    MAX_RECONNECT_DELAY_MS);
}

function scheduleReconnect(capture, reason) {
  if (!current(capture) || capture.stopping || capture.failure) return Promise.resolve();
  if (capture.reconnectTask) {
    capture.reconnectNeeded = true;
    return capture.reconnectTask;
  }
  capture.reconnectNeeded = false;
  capture.reconnectCount += 1;
  publishStats(capture, true).catch(() => undefined);
  const task = (async () => {
    let lastError = reason;
    // One budget per capture, not per close event. SDK startup can emit
    // session.ready before cloud authentication fails, so ready alone must
    // never replenish the retry budget.
    while (capture.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
      if (!current(capture) || capture.stopping) return;
      const attempt = ++capture.reconnectAttempts;
      await notify(capture, 'offscreen.capture.state', {
        status: 'reconnecting', reconnectAttempt: attempt,
      });
      if (!current(capture) || capture.stopping) return;
      await delay(reconnectDelayMs(attempt));
      if (!current(capture) || capture.stopping) return;
      try {
        const ready = await connectGatewayOnce(capture);
        if (!current(capture) || capture.stopping) return;
        // A ready socket can close before this continuation executes.
        if (!capture.connection?.ready) continue;
        await notify(capture, 'offscreen.capture.state', {
          status: 'capturing', sessionId: ready.session_id || null, reconnectAttempt: 0,
        });
        return;
      } catch (error) {
        lastError = error instanceof Error ? error.message : String(error);
      }
    }
    if (current(capture) && !capture.stopping) {
      capture.reconnectNeeded = false;
      failCapture(capture,
        `Gateway reconnect failed after ${MAX_RECONNECT_ATTEMPTS} attempts: ${lastError}`);

    }
  })().finally(() => {
    if (capture.reconnectTask !== task) return;
    capture.reconnectTask = null;
    if (current(capture) && !capture.stopping && capture.reconnectNeeded && !capture.connection) {
      scheduleReconnect(capture, 'Gateway closed after readiness').catch(() => undefined);
    }
  });
  capture.reconnectTask = task;
  return task;
}

function connectGatewayOnce(capture) {
  requireStarting(capture);
  if (!capture.config?.gateway) return Promise.reject(new Error('Gateway URL is missing'));
  const ws = new WebSocket(capture.config.gateway);
  const connection = { ws, ready: false, stopAck: null, failureReason: null };
  capture.connection = connection;
  ws.binaryType = 'arraybuffer';
  const ownsSocket = () => current(capture) && capture.connection === connection;
  return new Promise((resolve, reject) => {
    let settled = false;
    const rejectStartup = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(error);
      try { ws.close(); } catch (_) { /* Ignore close races. */ }
    };
    const timeout = setTimeout(() => {
      rejectStartup(new Error('Gateway did not become ready within 10 seconds'));
      ws.close();
    }, 10_000);
    ws.addEventListener('open', () => {
      if (!ownsSocket() || capture.stopping) { ws.close(); return; }
      ws.send(JSON.stringify({
        type: 'session.start', source_language: capture.config.sourceLanguage,
        target_language: capture.config.targetLanguage,
        audio: { encoding: 'linear16', sample_rate_hz: SAMPLE_RATE_HZ, channels: 1 },
      }));
    });
    ws.addEventListener('message', (event) => {
      // Keep the current socket's final subtitles and ACK during graceful stop.
      if (!ownsSocket()) return;
      let payload;
      try { payload = JSON.parse(event.data); } catch (_) { return; }
      if (payload.type === 'session.ready') {
        if (capture.stopping) return;
        connection.ready = true;
        if (!settled) { settled = true; clearTimeout(timeout); resolve(payload); }
      } else if (payload.type === 'session.stopped') {
        if (capture.stopping) connection.stopAck?.(payload);
      } else if (payload.type === 'session.error') {
        const message = payload.message || 'Gateway session failed';
        const reason = payload.code ? `${payload.code}: ${message}` : message;
        connection.failureReason = reason;
        if (!connection.ready) rejectStartup(new Error(reason));
        if (!capture.stopping && payload.retryable !== true) {
          // Explicit server errors are terminal before or after readiness
          // (e.g. credentials/configuration), including during a retry.
          failCapture(capture, reason);
        }
        ws.close();
      } else if (payload.type?.startsWith('subtitle.')) {
        notify(capture, 'subtitle.event', { event: payload }).catch(() => undefined);
      }
    });
    ws.addEventListener('error', () => {
      if (!connection.ready) rejectStartup(new Error('Could not connect to the VeilSub gateway'));
    });
    ws.addEventListener('close', () => {
      clearTimeout(timeout);
      connection.stopAck?.(null); // Resolver belongs only to this socket.
      if (!connection.ready) rejectStartup(new Error('Gateway connection closed before session.ready'));
      if (!ownsSocket()) return;
      capture.connection = null;
      if (!capture.stopping && connection.ready) {
        scheduleReconnect(capture, connection.failureReason || 'Gateway connection closed unexpectedly')
          .catch(() => undefined);
      }
    });
  });
}

function handleAudioFrame(capture, buffer) {
  if (!current(capture) || capture.stopping) return;
  const connection = capture.connection;
  if (!connection?.ready || connection.ws.readyState !== WebSocket.OPEN ||
      connection.ws.bufferedAmount > MAX_SOCKET_BUFFERED_BYTES) {
    capture.droppedAudioMs += (buffer.byteLength / BYTES_PER_SAMPLE / SAMPLE_RATE_HZ) * 1000;
    publishStats(capture).catch(() => undefined);
    return;
  }
  connection.ws.send(buffer);
}

async function start(message) {
  const id = ++operation;
  await cleanup(activeCapture);
  if (id !== operation) throw new Error('Capture start cancelled');
  const capture = {
    token: message.captureToken, tabId: message.tabId, config: message.config,
    stopping: false, ended: false, connection: null, reconnectTask: null,
    reconnectNeeded: false, reconnectAttempts: 0, failure: null,
    droppedAudioMs: 0, reconnectCount: 0,
    lastStatsSentAt: 0, metrics: null,
  };
  activeCapture = capture;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: 'tab', chromeMediaSourceId: message.streamId } },
      video: false,
    });
    if (!current(capture) || capture.stopping) {
      stream.getTracks().forEach((track) => track.stop());
      throw new Error('Capture start cancelled');
    }
    capture.stream = stream;
    const context = new AudioContext({ sampleRate: SAMPLE_RATE_HZ });
    capture.audioContext = context;
    await context.resume();
    requireStarting(capture);
    if (context.state !== 'running') throw new Error('AudioContext did not enter running state');
    await context.audioWorklet.addModule('pcm-worklet.js');
    requireStarting(capture);
    const source = context.createMediaStreamSource(stream);
    const processor = new AudioWorkletNode(context, 'veilsub-pcm16');
    capture.processor = processor;
    source.connect(context.destination);
    source.connect(processor);
    const silent = context.createGain();
    silent.gain.value = 0;
    processor.connect(silent).connect(context.destination);
    processor.port.onmessage = ({ data }) => handleAudioFrame(capture, data);
    const ready = await connectGatewayOnce(capture);
    requireStarting(capture);
    await publishStats(capture, true);
    requireStarting(capture);
    return ready;
  } catch (error) {
    await cleanup(capture);
    throw error;
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== 'offscreen') return undefined;
  if (message.type === 'offscreen.capture.start') {
    start(message).then((ready) => sendResponse({ ok: true, sessionId: ready.session_id || null }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  if (message.type === 'offscreen.capture.stop') {
    stop(message.captureToken).then((metrics) => sendResponse({ ok: true, metrics }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }
  return undefined;
});
