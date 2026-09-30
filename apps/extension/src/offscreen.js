let stream = null;
let audioContext = null;
let socket = null;
let tabId = null;
let sessionReady = false;
let stopping = false;

async function notifyCaptureError(error) {
  await chrome.runtime.sendMessage({
    type: 'offscreen.capture.error',
    error,
  }).catch(() => undefined);
}

async function cleanup() {
  const ws = socket;
  socket = null;
  sessionReady = false;

  if (ws?.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'session.stop' }));
  }
  ws?.close();

  stream?.getTracks().forEach((track) => track.stop());
  stream = null;

  await audioContext?.close().catch(() => undefined);
  audioContext = null;
  tabId = null;
}

async function stop() {
  stopping = true;
  try {
    await cleanup();
  } finally {
    stopping = false;
  }
}

async function connectGateway(config, currentTabId) {
  const ws = new WebSocket(config.gateway);
  socket = ws;
  ws.binaryType = 'arraybuffer';

  return new Promise((resolve, reject) => {
    let settled = false;
    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error('Gateway did not become ready within 10 seconds'));
    }, 10_000);

    const rejectStartup = (error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      reject(error instanceof Error ? error : new Error(String(error)));
    };

    ws.addEventListener('open', () => {
      ws.send(JSON.stringify({
        type: 'session.start',
        source_language: config.sourceLanguage,
        target_language: config.targetLanguage,
        audio: { encoding: 'linear16', sample_rate_hz: 16000, channels: 1 },
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
        sessionReady = true;
        if (!settled) {
          settled = true;
          clearTimeout(timeout);
          resolve(payload);
        }
        return;
      }

      if (payload.type === 'session.error') {
        const error = new Error(payload.message || 'Gateway session failed');
        if (!sessionReady) {
          rejectStartup(error);
        } else {
          notifyCaptureError(error.message);
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
      if (!sessionReady) {
        rejectStartup(new Error('Could not connect to the VeilSub gateway'));
      }
    });

    ws.addEventListener('close', () => {
      clearTimeout(timeout);
      if (socket !== ws || stopping) return;

      if (!sessionReady) {
        rejectStartup(new Error('Gateway connection closed before session.ready'));
        return;
      }

      notifyCaptureError('Gateway connection closed unexpectedly');
    });
  });
}

async function start(message) {
  await stop();
  tabId = message.tabId;

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

    audioContext = new AudioContext({ sampleRate: 16000 });
    await audioContext.audioWorklet.addModule('pcm-worklet.js');

    const source = audioContext.createMediaStreamSource(stream);
    const processor = new AudioWorkletNode(audioContext, 'veilsub-pcm16');

    // tabCapture normally removes the captured tab audio from local playback.
    // Route the captured stream back to the destination so the user still hears it.
    source.connect(audioContext.destination);
    source.connect(processor);

    const silent = audioContext.createGain();
    silent.gain.value = 0;
    processor.connect(silent).connect(audioContext.destination);

    const ready = await connectGateway(message.config, message.tabId);

    processor.port.onmessage = ({ data }) => {
      if (
        sessionReady &&
        socket?.readyState === WebSocket.OPEN
      ) {
        socket.send(data);
      }
    };

    return ready;
  } catch (error) {
    await cleanup();
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
      .then(() => sendResponse({ ok: true }))
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
