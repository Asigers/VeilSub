const ROOT_ID = 'veilsub-overlay-root';

function ensureOverlay() {
  let root = document.getElementById(ROOT_ID);
  if (root) return root;

  root = document.createElement('div');
  root.id = ROOT_ID;
  root.innerHTML = [
    '<div class="veilsub-source"></div>',
    '<div class="veilsub-target"></div>',
    '<div class="veilsub-status"></div>',
  ].join('');
  document.documentElement.appendChild(root);
  return root;
}

function renderSubtitle(event) {
  const root = ensureOverlay();
  if (!event.type?.startsWith('subtitle.')) return;

  root.querySelector('.veilsub-source').textContent = event.source || '';
  root.querySelector('.veilsub-target').textContent = event.target || '';
  root.querySelector('.veilsub-status').textContent = '';
  root.dataset.segmentId = event.id || '';
  root.style.display = 'block';
}

function renderState(state) {
  const root = ensureOverlay();
  const status = root.querySelector('.veilsub-status');

  if (state?.status === 'starting') {
    status.textContent = 'VeilSub · Connecting…';
    root.style.display = 'block';
    return;
  }

  if (state?.status === 'reconnecting') {
    status.textContent = 'VeilSub · Reconnecting…';
    root.style.display = 'block';
    return;
  }

  if (state?.status === 'error') {
    status.textContent = `VeilSub · ${state.error || 'Capture failed'}`;
    root.style.display = 'block';
    return;
  }

  if (state?.status === 'idle') {
    root.style.display = 'none';
    return;
  }

  if (state?.status === 'capturing') {
    status.textContent = '';
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'overlay.show') {
    const root = ensureOverlay();
    root.style.display = 'block';
    if (message.state) renderState(message.state);
  }

  if (message.type === 'overlay.hide') {
    const root = document.getElementById(ROOT_ID);
    if (root) root.style.display = 'none';
  }

  if (message.type === 'overlay.state') {
    renderState(message.state);
  }

  if (message.type === 'overlay.subtitle') {
    renderSubtitle(message.event);
  }
});
