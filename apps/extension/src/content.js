(() => {
  if (globalThis.__veilsubContentLoaded) return;
  globalThis.__veilsubContentLoaded = true;

  const ROOT_ID = 'veilsub-overlay-root';
  const MAX_HISTORY = 50;
  const MAX_VISIBLE_SEGMENTS = 2;
  const FINAL_EXPIRY_MS = 6500;
  const SETTINGS_KEYS = [
    'displayMode',
    'fontSize',
    'verticalPosition',
    'backgroundOpacity',
    'subtitleDelayMs',
  ];

  const settings = {
    displayMode: 'bilingual',
    fontSize: 21,
    verticalPosition: 9,
    backgroundOpacity: 72,
    subtitleDelayMs: 0,
  };

  let overlayVisible = false;
  let expiryTimer = null;

  const segments = new Map();
  const segmentOrder = [];
  const pendingSubtitleTimers = new Set();

  chrome.storage.local.get(SETTINGS_KEYS).then((saved) => {
    Object.assign(settings, normalizeSettings(saved));
    applySettings();
    renderSegments();
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== 'local') return;

    let changed = false;
    for (const key of SETTINGS_KEYS) {
      if (!changes[key]) continue;
      settings[key] = normalizeSetting(key, changes[key].newValue);
      changed = true;
    }

    if (!changed) return;
    applySettings();
    renderSegments();
  });

  function normalizeSettings(values) {
    const normalized = {};
    for (const key of SETTINGS_KEYS) {
      if (values[key] !== undefined) {
        normalized[key] = normalizeSetting(key, values[key]);
      }
    }
    return normalized;
  }

  function normalizeSetting(key, value) {
    if (key === 'displayMode') {
      return ['bilingual', 'translation', 'source'].includes(value)
        ? value
        : 'bilingual';
    }

    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return settings[key];

    if (key === 'fontSize') return Math.min(36, Math.max(14, numeric));
    if (key === 'verticalPosition') return Math.min(40, Math.max(3, numeric));
    if (key === 'backgroundOpacity') return Math.min(95, Math.max(20, numeric));
    if (key === 'subtitleDelayMs') return Math.min(3000, Math.max(0, numeric));
    return value;
  }

  function createOverlay() {
    let host = document.getElementById(ROOT_ID);
    if (host) return host;

    host = document.createElement('div');
    host.id = ROOT_ID;
    host.setAttribute('popover', 'manual');

    const shadow = host.attachShadow({ mode: 'open' });
    shadow.innerHTML = `
      <style>
        :host {
          --veilsub-target-size: 21px;
          --veilsub-source-size: 17px;
          --veilsub-bottom: 9vh;
          --veilsub-bg-opacity: 0.72;
          position: fixed;
          left: 50%;
          right: auto;
          top: auto;
          bottom: max(var(--veilsub-bottom), env(safe-area-inset-bottom, 0px));
          transform: translateX(-50%);
          margin: 0;
          border: 0;
          padding: 0;
          width: auto;
          height: auto;
          max-width: min(900px, 88vw);
          background: transparent;
          color: #fff;
          overflow: visible;
          pointer-events: none;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
            "Noto Sans CJK JP", "Noto Sans CJK SC", sans-serif;
        }

        :host::backdrop {
          background: transparent;
        }

        .panel {
          box-sizing: border-box;
          width: max-content;
          max-width: min(900px, 88vw);
          padding: 10px 16px;
          border-radius: 10px;
          background: rgba(0, 0, 0, var(--veilsub-bg-opacity));
          text-align: center;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
          overflow-wrap: anywhere;
        }

        .lines {
          display: grid;
          gap: 8px;
        }

        .segment {
          min-width: 0;
        }

        .segment.previous {
          opacity: 0.72;
        }

        .source {
          font-size: var(--veilsub-source-size);
          line-height: 1.35;
        }

        .target {
          margin-top: 2px;
          font-size: var(--veilsub-target-size);
          font-weight: 650;
          line-height: 1.35;
        }

        .status {
          margin-top: 5px;
          font-size: 12px;
          line-height: 1.3;
          opacity: 0.78;
        }

        .status:empty,
        .lines:empty {
          display: none;
        }
      </style>
      <div class="panel">
        <div class="lines" role="status" aria-live="polite" aria-atomic="true"></div>
        <div class="status"></div>
      </div>
    `;

    document.documentElement.appendChild(host);
    applySettings(host);
    return host;
  }

  function parts(host = createOverlay()) {
    const shadow = host.shadowRoot;
    return {
      lines: shadow.querySelector('.lines'),
      status: shadow.querySelector('.status'),
    };
  }

  function applySettings(host = document.getElementById(ROOT_ID)) {
    if (!host) return;

    const targetSize = Math.round(settings.fontSize);
    const sourceSize = Math.max(12, Math.round(targetSize * 0.82));
    host.style.setProperty('--veilsub-target-size', `${targetSize}px`);
    host.style.setProperty('--veilsub-source-size', `${sourceSize}px`);
    host.style.setProperty('--veilsub-bottom', `${settings.verticalPosition}vh`);
    host.style.setProperty(
      '--veilsub-bg-opacity',
      String(settings.backgroundOpacity / 100)
    );
  }

  function showOverlay() {
    const host = createOverlay();
    overlayVisible = true;

    if (typeof host.showPopover === 'function') {
      if (!host.matches(':popover-open')) {
        host.showPopover();
      }
      return;
    }

    host.style.display = 'block';
  }

  function hideOverlay({ remove = true } = {}) {
    const host = document.getElementById(ROOT_ID);
    overlayVisible = false;
    clearExpiry();
    if (remove) {
      clearPendingSubtitleTimers();
    }
    if (!host) return;

    if (typeof host.hidePopover === 'function' && host.matches(':popover-open')) {
      host.hidePopover();
    }

    if (remove) {
      host.remove();
    } else {
      host.style.display = 'none';
    }
  }

  function refreshTopLayer() {
    if (!overlayVisible) return;

    const host = createOverlay();
    if (typeof host.showPopover !== 'function') return;

    if (host.matches(':popover-open')) {
      host.hidePopover();
    }

    requestAnimationFrame(() => {
      if (overlayVisible && !host.matches(':popover-open')) {
        host.showPopover();
      }
    });
  }

  function rememberSegment(event) {
    if (!event.id) return;

    const existing = segments.get(event.id);
    const incomingRevision = Number.isInteger(event.revision) ? event.revision : 0;

    if (existing && incomingRevision < existing.revision) {
      return;
    }

    if (!existing) {
      segmentOrder.push(event.id);
    }

    const isTranslation = event.type === 'subtitle.translation';
    const next = {
      id: event.id,
      revision: incomingRevision,
      source: event.source || existing?.source || '',
      target: existing?.target || '',
      isFinal: event.is_final ?? existing?.isFinal ?? false,
    };

    if (isTranslation) {
      if (existing && incomingRevision !== existing.revision) {
        return;
      }
      next.target = event.target || '';
    } else {
      if (!existing || incomingRevision > existing.revision) {
        next.target = '';
      }
      if (event.target) {
        next.target = event.target;
      }
    }

    segments.set(event.id, next);

    while (segmentOrder.length > MAX_HISTORY) {
      const removed = segmentOrder.shift();
      if (removed) segments.delete(removed);
    }

    renderSegments();
    scheduleExpiry();
  }

  function visibleSegments() {
    return segmentOrder
      .map((id) => segments.get(id))
      .filter(Boolean)
      .slice(-MAX_VISIBLE_SEGMENTS);
  }

  function renderSegments() {
    const host = document.getElementById(ROOT_ID);
    if (!host) return;

    applySettings(host);
    const { lines } = parts(host);
    lines.replaceChildren();

    const visible = visibleSegments();

    for (const [index, segment] of visible.entries()) {
      const row = document.createElement('div');
      row.className = index < visible.length - 1 ? 'segment previous' : 'segment';
      row.dataset.segmentId = segment.id;

      const showSource = settings.displayMode !== 'translation';
      const showTarget = settings.displayMode !== 'source';

      if (showSource && segment.source) {
        const source = document.createElement('div');
        source.className = 'source';
        source.textContent = segment.source;
        row.appendChild(source);
      }

      if (showTarget && segment.target) {
        const target = document.createElement('div');
        target.className = 'target';
        target.textContent = segment.target;
        row.appendChild(target);
      }

      if (row.childElementCount > 0) {
        lines.appendChild(row);
      }
    }

    if (lines.childElementCount > 0) {
      showOverlay();
    } else if (!parts(host).status.textContent) {
      hideOverlay({ remove: false });
    }
  }

  function clearExpiry() {
    if (expiryTimer) {
      clearTimeout(expiryTimer);
      expiryTimer = null;
    }
  }

  function clearPendingSubtitleTimers() {
    for (const timer of pendingSubtitleTimers) {
      clearTimeout(timer);
    }
    pendingSubtitleTimers.clear();
  }

  function scheduleExpiry() {
    clearExpiry();

    const latest = visibleSegments().at(-1);
    if (!latest?.isFinal) return;

    expiryTimer = setTimeout(() => {
      const host = document.getElementById(ROOT_ID);
      if (!host) return;

      const { lines } = parts(host);
      lines.replaceChildren();

      if (!parts(host).status.textContent) {
        hideOverlay({ remove: false });
      }
    }, FINAL_EXPIRY_MS);
  }

  function renderSubtitleNow(event) {
    if (!event.type?.startsWith('subtitle.')) return;

    const host = createOverlay();
    parts(host).status.textContent = '';
    rememberSegment(event);
  }

  function renderSubtitle(event) {
    const delayMs = settings.subtitleDelayMs;
    if (delayMs <= 0) {
      renderSubtitleNow(event);
      return;
    }

    const timer = setTimeout(() => {
      pendingSubtitleTimers.delete(timer);
      renderSubtitleNow(event);
    }, delayMs);
    pendingSubtitleTimers.add(timer);
  }

  function renderState(state) {
    const host = createOverlay();
    const { status } = parts(host);

    if (state?.status === 'starting') {
      status.textContent = 'VeilSub · Connecting…';
      showOverlay();
      return;
    }

    if (state?.status === 'reconnecting') {
      const attempt = state.reconnectAttempt ? ` · attempt ${state.reconnectAttempt}` : '';
      status.textContent = `VeilSub · Reconnecting…${attempt}`;
      showOverlay();
      return;
    }

    if (state?.status === 'error') {
      status.textContent = `VeilSub · ${state.error || 'Capture failed'}`;
      showOverlay();
      return;
    }

    if (state?.status === 'idle') {
      segments.clear();
      segmentOrder.length = 0;
      hideOverlay();
      return;
    }

    if (state?.status === 'capturing') {
      status.textContent = '';
      renderSegments();
    }
  }

  document.addEventListener('fullscreenchange', refreshTopLayer);

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === 'overlay.ping') {
      sendResponse({ ok: true });
      return undefined;
    }

    if (message.type === 'overlay.show') {
      showOverlay();
      if (message.state) renderState(message.state);
      return undefined;
    }

    if (message.type === 'overlay.hide') {
      segments.clear();
      segmentOrder.length = 0;
      hideOverlay();
      return undefined;
    }

    if (message.type === 'overlay.state') {
      renderState(message.state);
      return undefined;
    }

    if (message.type === 'overlay.subtitle') {
      renderSubtitle(message.event);
    }

    return undefined;
  });
})();
