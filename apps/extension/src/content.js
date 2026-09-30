(() => {
  if (globalThis.__veilsubContentLoaded) return;
  globalThis.__veilsubContentLoaded = true;

  const ROOT_ID = 'veilsub-overlay-root';
  const MAX_HISTORY = 50;
  const MAX_VISIBLE_SEGMENTS = 2;
  const FINAL_EXPIRY_MS = 6500;

  let overlayVisible = false;
  let displayMode = 'bilingual';
  let expiryTimer = null;

  const segments = new Map();
  const segmentOrder = [];

  chrome.storage.local.get('displayMode').then((saved) => {
    displayMode = saved.displayMode || 'bilingual';
    renderSegments();
  });

  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== 'local' || !changes.displayMode) return;
    displayMode = changes.displayMode.newValue || 'bilingual';
    renderSegments();
  });

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
          position: fixed;
          left: 50%;
          right: auto;
          top: auto;
          bottom: max(9vh, env(safe-area-inset-bottom, 0px));
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
          background: rgba(0, 0, 0, 0.72);
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
          font-size: 17px;
          line-height: 1.35;
        }

        .target {
          margin-top: 2px;
          font-size: 21px;
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
        <div class="lines"></div>
        <div class="status"></div>
      </div>
    `;

    document.documentElement.appendChild(host);
    return host;
  }

  function parts(host = createOverlay()) {
    const shadow = host.shadowRoot;
    return {
      lines: shadow.querySelector('.lines'),
      status: shadow.querySelector('.status'),
    };
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
      // A newer source revision invalidates any translation of the older text.
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

    const { lines } = parts(host);
    lines.replaceChildren();

    const visible = visibleSegments();

    for (const [index, segment] of visible.entries()) {
      const row = document.createElement('div');
      row.className = index < visible.length - 1 ? 'segment previous' : 'segment';
      row.dataset.segmentId = segment.id;

      const showSource = displayMode !== 'translation';
      const showTarget = displayMode !== 'source';

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
    }
  }

  function clearExpiry() {
    if (expiryTimer) {
      clearTimeout(expiryTimer);
      expiryTimer = null;
    }
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

      // Keep the host available for connection/error status messages.
      if (!parts(host).status.textContent) {
        hideOverlay({ remove: false });
      }
    }, FINAL_EXPIRY_MS);
  }

  function renderSubtitle(event) {
    if (!event.type?.startsWith('subtitle.')) return;

    const host = createOverlay();
    parts(host).status.textContent = '';
    rememberSegment(event);
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
