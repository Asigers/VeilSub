(() => {
  if (globalThis.__veilsubContentLoaded) return;
  globalThis.__veilsubContentLoaded = true;

  const ROOT_ID = 'veilsub-overlay-root';
  let overlayVisible = false;

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
          bottom: 9vh;
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
          max-width: min(900px, 88vw);
          padding: 10px 16px;
          border-radius: 10px;
          background: rgba(0, 0, 0, 0.72);
          text-align: center;
          text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
          overflow-wrap: anywhere;
        }

        .source {
          font-size: 18px;
          line-height: 1.35;
        }

        .target {
          margin-top: 3px;
          font-size: 21px;
          font-weight: 650;
          line-height: 1.35;
        }

        .status {
          margin-top: 4px;
          font-size: 12px;
          line-height: 1.3;
          opacity: 0.78;
        }

        .status:empty,
        .target:empty {
          display: none;
        }
      </style>
      <div class="panel">
        <div class="source"></div>
        <div class="target"></div>
        <div class="status"></div>
      </div>
    `;

    document.documentElement.appendChild(host);
    return host;
  }

  function parts(host = createOverlay()) {
    const shadow = host.shadowRoot;
    return {
      source: shadow.querySelector('.source'),
      target: shadow.querySelector('.target'),
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

  function hideOverlay() {
    const host = document.getElementById(ROOT_ID);
    overlayVisible = false;
    if (!host) return;

    if (typeof host.hidePopover === 'function' && host.matches(':popover-open')) {
      host.hidePopover();
    }

    host.remove();
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

  function renderSubtitle(event) {
    if (!event.type?.startsWith('subtitle.')) return;

    const host = createOverlay();
    const view = parts(host);
    view.source.textContent = event.source || '';
    view.target.textContent = event.target || '';
    view.status.textContent = '';
    host.dataset.segmentId = event.id || '';
    showOverlay();
  }

  function renderState(state) {
    const view = parts();

    if (state?.status === 'starting') {
      view.status.textContent = 'VeilSub · Connecting…';
      showOverlay();
      return;
    }

    if (state?.status === 'reconnecting') {
      const attempt = state.reconnectAttempt ? ` · attempt ${state.reconnectAttempt}` : '';
      view.status.textContent = `VeilSub · Reconnecting…${attempt}`;
      showOverlay();
      return;
    }

    if (state?.status === 'error') {
      view.status.textContent = `VeilSub · ${state.error || 'Capture failed'}`;
      showOverlay();
      return;
    }

    if (state?.status === 'idle') {
      hideOverlay();
      return;
    }

    if (state?.status === 'capturing') {
      view.status.textContent = '';
      showOverlay();
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
