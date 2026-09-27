const ROOT_ID = 'veilsub-overlay-root';

function ensureOverlay() {
  let root = document.getElementById(ROOT_ID);
  if (root) return root;

  root = document.createElement('div');
  root.id = ROOT_ID;
  root.innerHTML = '<div class="veilsub-source"></div><div class="veilsub-target"></div>';
  document.documentElement.appendChild(root);
  return root;
}

function render(event) {
  const root = ensureOverlay();
  if (!event.type?.startsWith('subtitle.')) return;

  root.querySelector('.veilsub-source').textContent = event.source || '';
  root.querySelector('.veilsub-target').textContent = event.target || '';
  root.style.display = 'block';
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'overlay.show') ensureOverlay().style.display = 'block';

  if (message.type === 'overlay.hide') {
    const root = document.getElementById(ROOT_ID);
    if (root) root.style.display = 'none';
  }

  if (message.type === 'overlay.subtitle') render(message.event);
});
