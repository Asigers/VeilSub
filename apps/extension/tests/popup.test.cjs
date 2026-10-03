const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('session translation failures and diagnostics are rendered as text, not HTML', () => {
  const metrics = {
    style: {}, children: [],
    replaceChildren() { this.children = []; },
    appendChild(node) { this.children.push(node); },
    set innerHTML(_) { throw new Error('Untrusted diagnostics must not use innerHTML'); },
  };
  const context = vm.createContext({
    metrics,
    document: { createElement: (tag) => ({ tag, textContent: '' }) },
  });
  const source = fs.readFileSync(path.join(__dirname, '../src/popup.js'), 'utf8');
  vm.runInContext(source.slice(source.indexOf('function formatMetric'),
    source.indexOf('function renderState')), context);
  const message = 'Aliyun MT code 10010: <img src=x onerror=alert(1)>';
  context.summary = { translation_calls: 3, translation_failures: 2,
    translation_timeouts: 1, translation_last_error: message };
  vm.runInContext('renderMetrics(summary)', context);
  const lines = metrics.children.map((node) => node.textContent);
  assert.ok(lines.some((text) => text.includes('calls: 3 · failures: 2 · timeouts: 1')));
  assert.equal(lines.at(-1), `Last translation error: ${message}`);
  assert.equal(metrics.children.at(-1).tag, 'div');
});
