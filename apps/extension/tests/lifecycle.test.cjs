const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function flush() { for (let i = 0; i < 40; i += 1) await Promise.resolve(); }
function timers() {
  let id = 0;
  const pending = new Map();
  return {
    setTimeout(fn, ms) { pending.set(++id, { fn, ms }); return id; },
    clearTimeout(id) { pending.delete(id); },
    run(ms) {
      const entry = [...pending].find(([, timer]) => timer.ms === ms);
      assert.ok(entry, `missing ${ms}ms timer`);
      pending.delete(entry[0]); entry[1].fn();
    },
    pending,
  };
}
function load(name, globals) {
  const context = vm.createContext({ console, ...globals });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src', name), 'utf8'), context);
  return context;
}
function stream() {
  const track = { stops: 0, stop() { this.stops += 1; } };
  return { track, getTracks: () => [track] };
}
function offscreenHarness() {
  const clock = timers();
  const messages = [], sockets = [], processors = [], contexts = [], mediaRequests = [];
  let listener;
  class Socket {
    static OPEN = 1;
    constructor() {
      this.readyState = 0; this.bufferedAmount = 0; this.sent = []; this.listeners = {};
      sockets.push(this);
    }
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
    emit(name, data) { for (const fn of this.listeners[name] || []) fn(data); }
    open() { this.readyState = 1; this.emit('open'); }
    message(payload) { this.emit('message', { data: JSON.stringify(payload) }); }
    send(payload) { this.sent.push(payload); }
    close() { this.readyState = 3; this.emit('close'); }
  }
  const audioNode = () => ({ connect(node) { return node; }, disconnect() {} });
  class Context {
    constructor() {
      this.state = 'suspended'; this.destination = audioNode(); this.closed = 0;
      this.audioWorklet = { addModule: async () => {} }; contexts.push(this);
    }
    async resume() { this.state = 'running'; }
    async close() { this.closed += 1; this.state = 'closed'; }
    createMediaStreamSource() { return audioNode(); }
    createGain() { return { ...audioNode(), gain: {} }; }
  }
  class Worklet {
    constructor() { Object.assign(this, audioNode()); this.port = {}; processors.push(this); }
  }
  const context = load('offscreen.js', {
    setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
    WebSocket: Socket, AudioContext: Context, AudioWorkletNode: Worklet,
    navigator: { mediaDevices: { getUserMedia() {
      const request = deferred(); mediaRequests.push(request); return request.promise;
    } } },
    chrome: { runtime: {
      sendMessage: async (message) => { messages.push(message); },
      onMessage: { addListener(fn) { listener = fn; } },
    } },
  });
  const send = (type, extras = {}) => new Promise((resolve) => {
    listener({ target: 'offscreen', type: `offscreen.capture.${type}`, ...extras }, {}, resolve);
  });
  const start = (captureToken) => send('start', {
    captureToken, tabId: 7, streamId: 'stream', config: { gateway: 'ws://test' },
  });
  async function ready(token) {
    const promise = start(token); await flush();
    const media = stream(); mediaRequests.at(-1).resolve(media); await flush();
    const ws = sockets.at(-1); ws.open(); ws.message({ type: 'session.ready', session_id: token });
    await promise; return { ws, media, processor: processors.at(-1) };
  }
  async function finish(token, ws) {
    const promise = send('stop', { captureToken: token }); await flush();
    ws?.message({ type: 'session.stopped', metrics: { token } });
    await promise;
  }
  return { context, clock, messages, sockets, processors, contexts, mediaRequests, start, ready, send, finish };
}

test('Stop cancels pending getUserMedia and late stream is disposed', async () => {
  const h = offscreenHarness();
  const starting = h.start('old'); await flush();
  await h.send('stop', { captureToken: 'old' });
  const media = stream(); h.mediaRequests[0].resolve(media);
  const result = await starting;
  assert.equal(result.ok, false);
  assert.equal(media.track.stops, 1);
  assert.equal(h.contexts.length, 0);
  assert.equal(h.sockets.length, 0);
});

test('late module startup failure cannot dispose a newer capture', async () => {
  const h = offscreenHarness();
  const old = h.start('old'); await flush();
  // Delay resume so the old lifecycle can be cancelled at an await boundary.
  const resume = deferred();
  vm.runInContext('AudioContext.prototype.resume = function () { return pendingResume.promise; }',
    Object.assign(h.context, { pendingResume: resume }));
  h.mediaRequests[0].resolve(stream()); await flush();
  await h.send('stop', { captureToken: 'old' });
  vm.runInContext('AudioContext.prototype.resume = async function () { this.state = "running"; }', h.context);
  const fresh = await h.ready('new');
  resume.reject(new Error('old resume failure'));
  assert.equal((await old).ok, false);
  assert.equal(fresh.media.track.stops, 0);
  assert.equal(h.contexts.at(-1).closed, 0);
  fresh.processor.port.onmessage({ data: new ArrayBuffer(320) });
  assert.ok(fresh.ws.sent.at(-1) instanceof ArrayBuffer);
  await h.finish('new', fresh.ws);
});

test('old socket subtitles/errors/ACK and old worklet PCM cannot affect new lifecycle', async () => {
  const h = offscreenHarness();
  const old = await h.ready('old'); await h.finish('old', old.ws);
  const fresh = await h.ready('new');
  const sentBefore = fresh.ws.sent.length, notifications = h.messages.length;
  old.processor.port.onmessage({ data: new ArrayBuffer(320) });
  old.ws.message({ type: 'subtitle.final', id: 'stale' });
  old.ws.message({ type: 'session.error', message: 'stale error' });
  old.ws.message({ type: 'session.stopped', metrics: { stale: true } });
  old.ws.close(); await flush();
  assert.equal(fresh.ws.sent.length, sentBefore);
  assert.equal(h.messages.length, notifications);
  assert.equal(fresh.ws.readyState, 1);
  let resolved = false;
  const stopping = h.send('stop', { captureToken: 'new' }).then((value) => { resolved = true; return value; });
  await flush(); old.ws.close(); old.ws.message({ type: 'session.stopped' }); await flush();
  assert.equal(resolved, false);
  fresh.ws.message({ type: 'subtitle.final', id: 'last' });
  fresh.ws.message({ type: 'session.stopped', metrics: { actual: true } });
  const stopped = await stopping;
  assert.equal(stopped.metrics.actual, true);
  assert.equal(h.messages.at(-3).type, 'subtitle.event');
  const count = h.messages.length;
  fresh.ws.message({ type: 'subtitle.translation', id: 'late' }); await flush();
  assert.equal(h.messages.length, count);
});

test('old reconnect finalizer never overwrites new lifecycle task', async () => {
  const h = offscreenHarness();
  const old = await h.ready('old'); old.ws.close(); await flush();
  const oldTimer = [...h.clock.pending].find(([, value]) => value.ms === 500);
  await h.send('stop', { captureToken: 'old' });
  const fresh = await h.ready('new'); fresh.ws.close(); await flush();
  const newTask = vm.runInContext('activeCapture.reconnectTask', h.context);
  oldTimer[1].fn(); h.clock.pending.delete(oldTimer[0]); await flush();
  assert.equal(vm.runInContext('activeCapture.reconnectTask', h.context), newTask);
  assert.ok(newTask);
  await h.send('stop', { captureToken: 'new' }); h.clock.run(500); await flush();
});

test('reconnect ready then immediate close is retried instead of lost', async () => {
  const h = offscreenHarness();
  const capture = await h.ready('session'); capture.ws.close(); await flush();
  h.clock.run(500); await flush();
  const reconnect = h.sockets.at(-1);
  reconnect.open(); reconnect.message({ type: 'session.ready' }); reconnect.close(); await flush();
  h.clock.run(1000); await flush();
  assert.equal(h.sockets.length, 3);
  const healthy = h.sockets.at(-1);
  healthy.open(); healthy.message({ type: 'session.ready' }); await flush();
  assert.equal(vm.runInContext('activeCapture.connection.ready', h.context), true);
  await h.finish('session', healthy);
});

test('server session.error after readiness is terminal and preserves its cause', async () => {
  const h = offscreenHarness();
  const capture = await h.ready('session');
  capture.ws.message({ type: 'session.error', code: 'stream_failed', message: 'ASR authentication denied' });
  await flush();
  const failure = h.messages.find((message) => message.type === 'offscreen.capture.error');
  assert.equal(failure.error, 'stream_failed: ASR authentication denied');
  assert.equal(capture.media.track.stops, 1);
  assert.equal(h.contexts[0].closed, 1);
  assert.equal(h.sockets.length, 1);
  assert.equal(h.clock.pending.size, 0);
  assert.equal(vm.runInContext('activeCapture', h.context), null);
});

test('terminal server error before ready during reconnect stops the entire capture', async () => {
  const h = offscreenHarness();
  const capture = await h.ready('session');
  capture.ws.close(); await flush();
  h.clock.run(500); await flush();
  const retry = h.sockets.at(-1);
  retry.open(); retry.message({ type: 'session.error', message: 'Workspace access denied', retryable: false });
  await flush();
  assert.equal(h.sockets.length, 2);
  assert.equal(h.clock.pending.size, 0);
  assert.equal(capture.media.track.stops, 1);
  assert.equal(h.messages.filter((message) => message.type === 'offscreen.capture.error').length, 1);
});

test('repeated ready/close cycles share one five-attempt reconnect budget', async () => {
  const h = offscreenHarness();
  const capture = await h.ready('session');
  capture.ws.close(); await flush();
  for (const ms of [500, 1000, 2000, 4000, 8000]) {
    h.clock.run(ms); await flush();
    const ws = h.sockets.at(-1);
    ws.open(); ws.message({ type: 'session.ready' }); await flush();
    ws.close(); await flush();
  }
  assert.equal(h.sockets.length, 6);
  assert.equal(h.clock.pending.size, 0);
  const failure = h.messages.find((message) => message.type === 'offscreen.capture.error');
  assert.match(failure.error, /after 5 attempts/);
  assert.equal(capture.media.track.stops, 1);
  assert.equal(vm.runInContext('activeCapture', h.context), null);
});

test('explicit retryable server errors still use the bounded transport recovery path', async () => {
  const h = offscreenHarness();
  const capture = await h.ready('session');
  capture.ws.message({ type: 'session.error', message: 'temporary upstream failure', retryable: true });
  await flush();
  assert.equal(h.messages.some((message) => message.type === 'offscreen.capture.error'), false);
  h.clock.run(500); await flush();
  const recovered = h.sockets.at(-1);
  recovered.open(); recovered.message({ type: 'session.ready' }); await flush();
  await h.finish('session', recovered);
});

test('AudioContext must actually become running', async () => {
  const h = offscreenHarness();
  vm.runInContext('AudioContext.prototype.resume = async function () {}', h.context);
  const starting = h.start('session'); await flush();
  const media = stream(); h.mediaRequests[0].resolve(media);
  assert.match((await starting).error, /running/);
  assert.equal(media.track.stops, 1);
  assert.equal(h.contexts[0].closed, 1);
});

function backgroundHarness() {
  const state = {}, overlayMessages = [], runtimeMessages = [], streamRequests = [], startRequests = [];
  let listener, uuid = 0, stopResponse = null;
  const event = () => ({ addListener() {} });
  const context = load('background.js', {
    crypto: { randomUUID: () => `token-${++uuid}` },
    chrome: {
      runtime: {
        getURL: (name) => name, getContexts: async () => [{}],
        onMessage: { addListener(fn) { listener = fn; } },
        async sendMessage(message) {
          runtimeMessages.push(message);
          if (message.type === 'offscreen.capture.start') {
            const request = deferred(); startRequests.push(request); return request.promise;
          }
          return stopResponse ? stopResponse.promise : { ok: true };
        },
      },
      storage: {
        session: { async get() { return structuredClone(state); }, async set(value) { Object.assign(state, structuredClone(value)); } },
        local: { async get() { return {}; } },
      },
      tabs: {
        async query() { return [{ id: 7 }]; },
        async sendMessage(tabId, message) { overlayMessages.push({ tabId, ...message }); return { ok: true }; },
        onRemoved: event(), onReplaced: event(), onUpdated: event(),
      },
      tabCapture: {
        getMediaStreamId() { const request = deferred(); streamRequests.push(request); return request.promise; },
        onStatusChanged: event(),
      },
      scripting: { async executeScript() {} }, offscreen: { async createDocument() {} },
      commands: { onCommand: event() },
    },
  });
  const send = (message) => new Promise((resolve) => listener(message, {}, resolve));
  const emit = (message) => listener(message, {}, () => {});
  async function ready() {
    const promise = send({ type: 'capture.start', config: { gateway: 'ws://test' } }); await flush();
    streamRequests.at(-1).resolve('stream'); await flush(); startRequests.at(-1).resolve({ ok: true });
    await promise; return state.captureState.captureToken;
  }
  return { context, state, overlayMessages, runtimeMessages, streamRequests, startRequests, send, emit, ready,
    delayStop() { stopResponse = deferred(); return stopResponse; } };
}

test('background Stop invalidates pending streamId before offscreen startup', async () => {
  const h = backgroundHarness();
  const old = h.send({ type: 'capture.start', config: {} }); await flush();
  const stop = await h.send({ type: 'capture.stop' });
  assert.equal(stop.state.status, 'idle');
  h.streamRequests[0].resolve('late'); assert.equal((await old).ok, false);
  assert.equal(h.startRequests.length, 0);
  assert.equal(h.state.captureState.status, 'idle');
});

test('background ignores late old start error and messages, allows current stop finals', async () => {
  const h = backgroundHarness();
  const old = h.send({ type: 'capture.start', config: {} }); await flush();
  h.streamRequests[0].resolve('stream'); await flush();
  const oldToken = h.state.captureState.captureToken;
  await h.send({ type: 'capture.stop' });
  const newToken = await h.ready();
  const stopCount = h.runtimeMessages.filter((m) => m.type === 'offscreen.capture.stop').length;
  h.startRequests[0].resolve({ ok: false, error: 'old failed' });
  assert.equal((await old).ok, false);
  for (const type of ['offscreen.capture.error', 'offscreen.capture.stats', 'offscreen.capture.metrics', 'offscreen.capture.state', 'subtitle.event']) {
    h.emit({ type, tabId: 7, captureToken: oldToken, error: 'old', status: 'error', event: { type: 'subtitle.final' } });
  }
  await flush();
  assert.equal(h.state.captureState.captureToken, newToken);
  assert.equal(h.state.captureState.status, 'capturing');
  assert.equal(h.runtimeMessages.filter((m) => m.type === 'offscreen.capture.stop').length, stopCount);
  assert.equal(h.overlayMessages.filter((m) => m.type === 'overlay.subtitle').length, 0);
  const delayedStop = h.delayStop();
  const stopping = h.send({ type: 'capture.stop' }); await flush();
  h.emit({ type: 'subtitle.event', tabId: 7, captureToken: newToken, event: { type: 'subtitle.final' } });
  await flush();
  assert.equal(h.overlayMessages.filter((m) => m.type === 'overlay.subtitle').length, 1);
  delayedStop.resolve({ ok: true }); await stopping;
  h.emit({ type: 'subtitle.event', tabId: 7, captureToken: newToken, event: { type: 'subtitle.translation' } });
  await flush();
  assert.equal(h.overlayMessages.filter((m) => m.type === 'overlay.subtitle').length, 1);
});

function contentHarness(delayMs = 0) {
  const clock = timers(), raf = [];
  const roots = new Map(); let listener, fullscreen;
  class Node {
    constructor() {
      this.style = { setProperty() {} }; this.dataset = {}; this.children = [];
      this.textContent = ''; this.isConnected = false; this.popover = false; this.shows = 0;
    }
    setAttribute() {}
    appendChild(node) { this.children.push(node); node.isConnected = true; if (node.id) roots.set(node.id, node); return node; }
    replaceChildren() { this.children = []; }
    get childElementCount() { return this.children.length; }
    attachShadow() {
      const lines = new Node(), status = new Node();
      this.shadowRoot = { querySelector: (name) => name === '.lines' ? lines : status };
      return this.shadowRoot;
    }
    matches() { return this.popover; }
    showPopover() { assert.equal(this.isConnected, true); this.popover = true; this.shows += 1; }
    hidePopover() { this.popover = false; }
    remove() { this.isConnected = false; roots.delete(this.id); }
  }
  const context = load('content.js', {
    setTimeout: clock.setTimeout, clearTimeout: clock.clearTimeout,
    requestAnimationFrame: (fn) => { raf.push(fn); },
    document: {
      documentElement: new Node(), getElementById: (id) => roots.get(id),
      createElement: () => new Node(), addEventListener: (_name, fn) => { fullscreen = fn; },
    },
    chrome: {
      storage: { local: { get: async () => ({ subtitleDelayMs: delayMs }) }, onChanged: { addListener() {} } },
      runtime: { onMessage: { addListener(fn) { listener = fn; } } },
    },
  });
  const send = (message) => listener(message, {}, () => {});
  const show = (captureToken = 'token') => send({ type: 'overlay.show', captureToken,
    state: { status: 'capturing', captureToken } });
  const subtitle = (captureToken = 'token') => send({ type: 'overlay.subtitle', captureToken,
    event: { type: 'subtitle.final', id: 'one', revision: 1, source: 'hello', is_final: true } });
  return { context, clock, raf, send, show, subtitle, fullscreen: () => fullscreen(),
    host: () => roots.get('veilsub-overlay-root') };
}

test('temporary hide restores display on next subtitle, fullscreen rAF ignores detached host', async () => {
  const h = contentHarness(); await flush(); h.show(); h.subtitle();
  const host = h.host(); h.clock.run(6500);
  assert.equal(host.style.display, 'none');
  h.subtitle(); assert.equal(host.style.display, 'block'); assert.equal(host.popover, true);
  h.fullscreen(); h.send({ type: 'overlay.hide', captureToken: 'token' });
  h.show('new'); const fresh = h.host();
  assert.notEqual(fresh, host);
  const shows = host.shows; h.raf[0](); assert.equal(host.shows, shows);
});

test('Stop clears delayed subtitles and rejects ended capture events', async () => {
  const h = contentHarness(500); await flush(); h.show(); h.subtitle();
  assert.equal(h.clock.pending.size, 1);
  h.send({ type: 'overlay.hide', captureToken: 'token' });
  assert.equal(h.clock.pending.size, 0);
  h.subtitle(); assert.equal(h.host(), undefined);
  h.show('new'); h.subtitle('token'); assert.equal(h.clock.pending.size, 0);
  h.send({ type: 'overlay.hide', captureToken: 'token' }); assert.ok(h.host());
});

test('graceful stop ACK wait is bounded and disposes audio without ACK', async () => {
  const h = offscreenHarness();
  const capture = await h.ready('session');
  const stopping = h.send('stop', { captureToken: 'session' }); await flush();
  h.clock.run(35_000);
  assert.equal((await stopping).ok, true);
  assert.equal(capture.media.track.stops, 1);
  assert.equal(h.contexts[0].closed, 1);
  assert.equal(capture.ws.readyState, 3);
});

test('queued background stats/metrics updates merge latest capture state', async () => {
  const h = backgroundHarness();
  const token = await h.ready();
  h.emit({ type: 'offscreen.capture.stats', tabId: 7, captureToken: token, droppedAudioMs: 42 });
  h.emit({ type: 'offscreen.capture.metrics', tabId: 7, captureToken: token, metrics: { calls: 3 } });
  await flush();
  assert.equal(h.state.captureState.status, 'capturing');
  assert.equal(h.state.captureState.droppedAudioMs, 42);
  assert.equal(h.state.captureState.lastMetrics.calls, 3);
  await h.send({ type: 'capture.stop' });
});
