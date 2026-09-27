let stream = null;
let audioContext = null;
let socket = null;
let tabId = null;

async function stop() {
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'session.stop' }));
  }
  socket?.close();
  socket = null;

  stream?.getTracks().forEach((track) => track.stop());
  stream = null;

  await audioContext?.close().catch(() => undefined);
  audioContext = null;
  tabId = null;
}

async function start(message) {
  await stop();
  tabId = message.tabId;

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

  source.connect(audioContext.destination);
  source.connect(processor);

  const silent = audioContext.createGain();
  silent.gain.value = 0;
  processor.connect(silent).connect(audioContext.destination);

  socket = new WebSocket(message.config.gateway);
  socket.binaryType = 'arraybuffer';

  socket.addEventListener('open', () => {
    socket.send(JSON.stringify({
      type: 'session.start',
      source_language: message.config.sourceLanguage,
      target_language: message.config.targetLanguage,
      audio: { encoding: 'linear16', sample_rate_hz: 16000, channels: 1 },
    }));
  });

  socket.addEventListener('message', (event) => {
    try {
      const payload = JSON.parse(event.data);
      chrome.runtime.sendMessage({ type: 'subtitle.event', tabId, event: payload });
    } catch (_) {
      // Ignore malformed frames.
    }
  });

  processor.port.onmessage = ({ data }) => {
    if (socket?.readyState === WebSocket.OPEN) socket.send(data);
  };
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'offscreen.capture.start') start(message).catch(console.error);
  if (message.type === 'offscreen.capture.stop') stop().catch(console.error);
});
