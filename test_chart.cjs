// All measurements and timestamps below are fictional test fixtures.
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { buildSeries, render } = require('./assets/chart.js');
const record = (measured_at, weight, extra = {}) => ({ id: measured_at, measured_at, weight, ...extra });

test('seven-day window is inclusive at Shanghai midnight and ends at latest record', () => {
  const records = [record('2024-05-17T23:59', 63), record('2024-05-18T00:00', 75.9), record('2024-05-24T08:15', 75.25)];
  const series = buildSeries(records, 'weight', '7');
  assert.deepEqual(series.points.map(p => p.value), [75.9, 75.25]);
  assert.equal(series.start, '2024-05-18T00:00:00+08:00');
  assert.equal(series.end, '2024-05-24T08:15:00+08:00');
  assert.match(series.message, /截至最新记录 2024-05-24 08:15/);
});

test('UTC timestamps are filtered according to the corresponding Shanghai date', () => {
  const s = buildSeries([record('2024-05-17T15:59Z', 63), record('2024-05-17T16:00Z', 75.9), record('2024-05-24T00:15Z', 75.25)], 'weight', '7');
  assert.deepEqual(s.points.map(p => p.value), [75.9, 75.25]);
});

test('30 and 90 days remain calendar windows across month and year boundaries', () => {
  assert.equal(buildSeries([record('2024-01-05T10:00', 62)], 'weight', '30').start, '2023-12-07T00:00:00+08:00');
  assert.equal(buildSeries([record('2024-01-05T10:00', 62)], 'weight', '90').start, '2023-10-08T00:00:00+08:00');
});

test('null, blank, boolean, infinity and absent fields never become zero', () => {
  const vals = [null, '', '  ', false, undefined, NaN, Infinity, 'no', '0x10'];
  const records = vals.map((v, i) => record(`2024-05-${String(i + 1).padStart(2, '0')}T10:00`, v));
  assert.equal(buildSeries(records, 'weight', 'all').pointCount, 0);
  assert.equal(buildSeries([record('2024-05-01T10:00', '75.25')], 'weight', 'all').points[0].value, 75.25);
});

test('an explicitly recorded zero is preserved, without coercing a missing value', () => {
  const s = buildSeries([record('2024-05-01T10:00', null, { waist: 0 })], 'waist', 'all');
  assert.equal(s.points[0].value, 0);
});

test('latest record anchors the window even if the selected field is missing', () => {
  const s = buildSeries([record('2024-05-10T10:00', 62), record('2024-05-24T10:00', null)], 'weight', '7');
  assert.equal(s.pointCount, 0);
  assert.match(s.message, /截至最新记录 2024-05-24/);
});

test('inferences use current minus delta and retain their report provenance', () => {
  const comparison = { measured_at: '2024-05-11T07:40', weight_delta: -0.4, body_fat_delta: -0.2 };
  const records = [record('2024-05-24T08:15', 75.25, { body_fat: 20.1, device_comparison: comparison })];
  const s = buildSeries(records, 'weight', '30');
  assert.equal(s.pointCount, 1);
  assert.equal(s.inferredCount, 1);
  assert.equal(s.inferred[0].value, 75.65);
  assert.equal(s.inferred[0].kind, 'inferred');
  assert.equal(s.inferred[0].source_measured_at, '2024-05-24T08:15:00+08:00');
  assert.equal(buildSeries(records, 'body_fat', '30').inferred[0].value, 20.3);
  assert.equal(buildSeries(records, 'weight', '7').inferredCount, 0);
});

test('actual values suppress inferred points on the same date, independently per field', () => {
  const records = [record('2024-05-11T08:00', 75.8, { body_fat: null }), record('2024-05-24T08:15', 75.25, {
    body_fat: 20.1, device_comparison: { measured_at: '2024-05-11T07:40', weight_delta: -0.4, body_fat_delta: -0.2 }
  })];
  assert.equal(buildSeries(records, 'weight', '30').inferredCount, 0);
  assert.equal(buildSeries(records, 'body_fat', '30').inferredCount, 1);
});

test('repeated device comparisons are deduplicated by past date, newest origin wins', () => {
  const comparison = { measured_at: '2024-05-11T07:40', weight_delta: -0.4 };
  const records = [record('2024-05-24T08:15', 75.25, { device_comparison: comparison }), record('2024-05-23T08:15', 75.3, { device_comparison: comparison })];
  const s = buildSeries(records, 'weight', 'all');
  assert.equal(s.inferredCount, 1);
  assert.equal(s.inferred[0].value, 75.65);
});

test('same-time or future comparisons, null deltas and unsupported metrics are ignored', () => {
  for (const measured_at of ['2024-05-24T08:15', '2024-05-25T08:15']) {
    assert.equal(buildSeries([record('2024-05-24T08:15', 62, { device_comparison: { measured_at, weight_delta: 1 } })], 'weight', 'all').inferredCount, 0);
  }
  const records = [record('2024-05-24T08:15', 62, { muscle_mass: 55.2, device_comparison: { measured_at: '2024-05-11T08:15', weight_delta: null, muscle_mass_delta: 1 } })];
  assert.equal(buildSeries(records, 'weight', 'all').inferredCount, 0);
  assert.equal(buildSeries(records, 'muscle_mass', 'all').inferredCount, 0);
});

test('derived records do not become actual points or shift the latest timestamp', () => {
  const records = [record('2024-05-24T08:15', 75.25), record('2024-06-01T10:00', 62, { source: 'inferred' }), record('2024-06-02T10:00', 61, { source: 'derived' }), record('2024-06-03T10:00', 61, { derived: true }), record('2024-06-04T10:00', 61, { source: { type: 'inferred' } })];
  const s = buildSeries(records, 'weight', 'all');
  assert.equal(s.pointCount, 1);
  assert.equal(s.end, '2024-05-24T08:15:00+08:00');
});

test('sorting preserves every same-day measurement and does not mutate input', () => {
  const records = [record('2024-05-24T08:15', 75.25), record('2024-05-24T08:14', 75.3), record('2024-05-23T10:00', 75.45)];
  const before = JSON.stringify(records);
  const s = buildSeries(records, 'weight', 'all');
  assert.deepEqual(s.points.map(p => p.value), [75.45, 75.3, 75.25]);
  assert.equal(s.points[2].timestamp - s.points[1].timestamp, 60000);
  assert.equal(JSON.stringify(records), before);
});

test('invalid dates and unsafe numeric strings are rejected', () => {
  const records = ['2024-02-30T10:00', '2024-05-24T24:01', 'not-a-date', '2024-05-24T08:15+99:00'].map(t => record(t, 62));
  records.push(record('2024-05-24T10:00', '<script>alert(1)</script>'));
  assert.equal(buildSeries(records, 'weight', 'all').pointCount, 0);
  assert.equal(buildSeries(null, 'bad', 'bad').field, 'weight');
});

test('all range includes historical inferred date while a lone point has no trend claim', () => {
  const s = buildSeries([record('2024-05-24T08:15', 62, { device_comparison: { measured_at: '2023-01-01T10:00', weight_delta: -1 } })], 'weight', 'all');
  assert.equal(s.start, '2023-01-01T10:00:00+08:00');
  assert.match(s.message, /暂不连成趋势线/);
});

class Element {
  constructor(tag, doc) { this.tagName = tag; this.ownerDocument = doc; this.children = []; this.attrs = {}; this.textContent = ''; }
  appendChild(child) { this.children.push(child); return child; }
  removeChild(child) { this.children.splice(this.children.indexOf(child), 1); }
  get firstChild() { return this.children[0] || null; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  set innerHTML(_) { throw new Error('innerHTML must never be used'); }
}
const document = { createElementNS(_ns, tag) { return new Element(tag, document); } };
const descendants = element => element.children.flatMap(child => [child, ...descendants(child)]);

test('render gives empty data a friendly accessible state and safely clears old content', () => {
  const svg = new Element('svg', document);
  svg.setAttribute('class', 'chart existing');
  svg.appendChild(new Element('old', document));
  const result = render(svg, [], 'weight', '7');
  assert.equal(result.pointCount, 0);
  assert.equal(svg.getAttribute('viewBox'), '0 0 660 230');
  assert.equal(svg.getAttribute('class'), 'chart existing');
  assert.equal(svg.getAttribute('role'), 'img');
  assert.ok(descendants(svg).some(node => /等待第一条体重记录/.test(node.textContent)));
  assert.ok(!descendants(svg).some(node => node.tagName === 'old'));
});

test('render never connects an inferred point to a single measured point', () => {
  const svg = new Element('svg', document);
  const result = render(svg, [record('2024-05-24T08:15', 75.25, { device_comparison: { measured_at: '2024-05-11T07:40', weight_delta: -0.4 } })], 'weight', '30');
  const nodes = descendants(svg);
  assert.equal(result.inferredCount, 1);
  assert.equal(nodes.filter(n => n.tagName === 'polyline').length, 0);
  const focusable = nodes.filter(n => n.getAttribute('tabindex') === '0');
  assert.equal(focusable.length, 2);
  assert.ok(focusable.every(n => n.children.some(child => child.tagName === 'title')));
  assert.ok(focusable.some(n => /推算/.test(n.getAttribute('aria-label'))));
});

test('same-day times occupy a useful horizontal span, with linear rather than smooth path', () => {
  const svg = new Element('svg', document);
  render(svg, [record('2024-05-24T08:14', 75.3), record('2024-05-24T08:15', 75.25)], 'weight', '7');
  const nodes = descendants(svg);
  const points = nodes.filter(n => n.getAttribute('tabindex') === '0');
  assert.ok(Math.abs(Number(points[1].getAttribute('cx')) - Number(points[0].getAttribute('cx'))) > 400);
  assert.equal(nodes.filter(n => n.tagName === 'polyline').length, 1);
  assert.ok(nodes.some(n => n.textContent === '08:14'));
  assert.ok(nodes.some(n => n.textContent === '08:15'));
  assert.ok(!JSON.stringify(svg.attrs).includes('NaN'));
});

test('polyline contains only actual points, and repeated rendering gets unique aria title IDs', () => {
  const svg = new Element('svg', document);
  const records = [record('2024-05-23T10:00', 75.45), record('2024-05-24T08:15', 75.25, { device_comparison: { measured_at: '2024-05-11T07:40', weight_delta: -0.4 } })];
  render(svg, records, 'weight', '30');
  const titleId = svg.getAttribute('aria-labelledby');
  const line = descendants(svg).find(n => n.tagName === 'polyline');
  assert.equal(line.getAttribute('points').split(' ').length, 2);
  render(svg, records, 'body_fat', 'all');
  assert.notEqual(svg.getAttribute('aria-labelledby'), titleId);
  assert.equal(descendants(svg).filter(n => n.tagName === 'polyline').length, 0);
});
