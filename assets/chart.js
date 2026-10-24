/* BodyChart — measurements only, with explicit device-comparison estimates. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.BodyChart = api;
})(typeof window !== 'undefined' ? window : null, function () {
  'use strict';

  const DAY = 86400000;
  const ZONE = 8 * 3600000;
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const FIELDS = Object.freeze({
    weight: { label: '体重', unit: 'kg', precision: 2, delta: 'weight_delta' },
    body_fat: { label: '体脂率', unit: '%', precision: 1, delta: 'body_fat_delta' },
    muscle_mass: { label: '肌肉量', unit: 'kg', precision: 1 },
    skeletal_mass: { label: '骨骼肌量', unit: 'kg', precision: 1 },
    waist: { label: '腰围', unit: 'cm', precision: 1 }
  });
  let chartSequence = 0;

  // Do not let the browser's locale turn a Shanghai measurement into another day.
  function parseTime(input) {
    if (typeof input !== 'string') return null;
    const match = input.trim().match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?)?(Z|[+-]\d{2}:?\d{2})?$/);
    if (!match) return null;
    const [year, month, day, hour, minute, second] = match.slice(1, 7).map(v => Number(v || 0));
    if (year < 1000 || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return null;
    const calendar = new Date(Date.UTC(year, month - 1, day, hour, minute, second));
    if (calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day) return null;
    let offset = ZONE;
    if (match[8] === 'Z') offset = 0;
    else if (match[8]) {
      const zone = match[8].match(/^([+-])(\d{2}):?(\d{2})$/);
      if (Number(zone[2]) > 23 || Number(zone[3]) > 59) return null;
      offset = (Number(zone[2]) * 60 + Number(zone[3])) * 60000 * (zone[1] === '+' ? 1 : -1);
    }
    return calendar.getTime() + Number((match[7] || '').padEnd(3, '0')) - offset;
  }

  function localParts(time) {
    const date = new Date(time + ZONE);
    const pad = value => String(value).padStart(2, '0');
    const day = `${date.getUTCFullYear()}-${pad(date.getUTCMonth() + 1)}-${pad(date.getUTCDate())}`;
    return { day, clock: `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}`, seconds: pad(date.getUTCSeconds()) };
  }

  function localISO(time) {
    const p = localParts(time);
    return `${p.day}T${p.clock}:${p.seconds}+08:00`;
  }

  function numberValue(value) {
    if (typeof value !== 'number' && typeof value !== 'string') return null;
    if (typeof value === 'string' && !/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function isInferred(record) {
    const markers = [record.source, record.kind, record.type, record.provenance];
    return record.inferred === true || record.derived === true || record.is_inferred === true ||
      markers.some(marker => {
        const name = typeof marker === 'object' && marker ? marker.type || marker.kind : marker;
        return typeof name === 'string' && /^(inferred|derived|device_comparison)$/i.test(name);
      });
  }

  function buildSeries(records, field, range) {
    const key = Object.prototype.hasOwnProperty.call(FIELDS, field) ? field : 'weight';
    const meta = FIELDS[key];
    const selectedRange = ['7', '30', '90', 'all'].includes(String(range)) ? String(range) : '30';
    const source = (Array.isArray(records) ? records : [])
      .filter(record => record && typeof record === 'object' && !isInferred(record))
      .map((record, index) => ({ record, time: parseTime(record.measured_at), index }))
      .filter(item => item.time !== null)
      .sort((a, b) => a.time - b.time || a.index - b.index);
    const base = { field: key, range: selectedRange, label: meta.label, unit: meta.unit, precision: meta.precision,
      points: [], inferred: [], pointCount: 0, inferredCount: 0, start: null, end: null, message: '' };
    if (!source.length) {
      base.message = `还没有可用的测量记录。保存第一条${meta.label}数据后，这里会显示变化。`;
      return base;
    }
    const latest = source[source.length - 1].time;
    const dayStart = Math.floor((latest + ZONE) / DAY) * DAY - ZONE;
    const cutoff = selectedRange === 'all' ? -Infinity : dayStart - (Number(selectedRange) - 1) * DAY;
    const actualDays = new Set();
    const actual = [];
    for (const item of source) {
      const value = numberValue(item.record[key]);
      if (value === null) continue;
      actualDays.add(localParts(item.time).day);
      actual.push({ id: item.record.id ?? null, timestamp: item.time, measured_at: localISO(item.time), value, kind: 'actual' });
    }
    const estimates = new Map();
    if (meta.delta) {
      for (const item of source) {
        const comparison = item.record.device_comparison;
        const current = numberValue(item.record[key]);
        if (!comparison || typeof comparison !== 'object' || current === null) continue;
        const delta = numberValue(comparison[meta.delta]);
        const time = parseTime(comparison.measured_at);
        if (delta === null || time === null || time >= item.time) continue;
        const day = localParts(time).day;
        if (actualDays.has(day)) continue;
        const value = Number((current - delta).toFixed(8));
        if (!Number.isFinite(value)) continue;
        // The newest originating report wins if several reports refer to one day.
        estimates.set(day, { id: `inferred-${String(item.record.id ?? item.index)}-${key}`, timestamp: time,
          measured_at: localISO(time), value, kind: 'inferred', source_id: item.record.id ?? null,
          source_measured_at: localISO(item.time), source_value: current, delta });
      }
    }
    base.points = actual.filter(point => point.timestamp >= cutoff && point.timestamp <= latest);
    base.inferred = Array.from(estimates.values())
      .filter(point => point.timestamp >= cutoff && point.timestamp <= latest)
      .sort((a, b) => a.timestamp - b.timestamp);
    base.pointCount = base.points.length;
    base.inferredCount = base.inferred.length;
    const firstTime = Math.min(source[0].time, ...base.inferred.map(point => point.timestamp));
    base.start = localISO(selectedRange === 'all' ? firstTime : cutoff);
    base.end = localISO(latest);
    const p = localParts(latest);
    const prefix = `截至最新记录 ${p.day} ${p.clock}，${selectedRange === 'all' ? '全部记录' : `近 ${selectedRange} 天`}`;
    const estimateNote = base.inferredCount ? `另有 ${base.inferredCount} 个设备对比推算点（空心金色），不连接实测线。` : '';
    if (!base.pointCount && !base.inferredCount) {
      base.message = `${prefix}暂无${meta.label}数据。可以补录该指标，或切换时间范围。`;
    } else if (!base.pointCount) {
      base.message = `${prefix}暂无${meta.label}实测点。${estimateNote}推算值不足以判断趋势。`;
    } else if (base.pointCount === 1) {
      base.message = `${prefix}有 1 个${meta.label}实测点，暂不连成趋势线。${estimateNote}`;
    } else {
      base.message = `${prefix}有 ${base.pointCount} 个${meta.label}实测点。折线仅连接测量点，不代表期间每日变化。${estimateNote}`;
    }
    return base;
  }

  function niceStep(span) {
    const raw = span / 4;
    const magnitude = Math.pow(10, Math.floor(Math.log10(raw)));
    const fraction = raw / magnitude;
    return (fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10) * magnitude;
  }

  function render(svg, records, field, range) {
    if (!svg || !svg.ownerDocument) throw new TypeError('BodyChart.render requires an SVG element.');
    const series = buildSeries(records, field, range);
    const doc = svg.ownerDocument;
    const make = (tag, attrs, text, parent = svg) => {
      const element = doc.createElementNS(SVG_NS, tag);
      for (const [name, value] of Object.entries(attrs || {})) element.setAttribute(name, String(value));
      if (text !== undefined) element.textContent = String(text);
      parent.appendChild(element);
      return element;
    };
    const text = (x, y, content, options = {}) => make('text', {
      x, y, 'text-anchor': options.anchor || 'start',
      style: `font-family:ui-monospace,"Microsoft YaHei",sans-serif;font-size:${options.size || 11}px;fill:${options.fill || '#8fa3b5'};${options.bold ? 'font-weight:600;' : ''}`,
      ...options.attributes
    }, content, options.parent || svg);
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    const oldClass = (svg.getAttribute('class') || '').split(/\s+/).filter(Boolean);
    if (!oldClass.includes('chart')) oldClass.push('chart');
    svg.setAttribute('class', oldClass.join(' '));
    svg.setAttribute('role', 'img');
    svg.setAttribute('viewBox', '0 0 660 230');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
    const titleId = `body-chart-title-${++chartSequence}`;
    svg.setAttribute('aria-labelledby', titleId);
    make('title', { id: titleId }, `${series.label}变化。${series.message}`);
    make('desc', {}, '蓝色实心点表示实测，金色空心点表示设备历史对比推算。横坐标为上海当地测量时间，纵坐标为指标数值。');
    const all = [...series.points, ...series.inferred].sort((a, b) => a.timestamp - b.timestamp);
    const left = 57, right = 632, top = 42, bottom = 177;
    const result = { pointCount: series.pointCount, inferredCount: series.inferredCount, start: series.start,
      end: series.end, message: series.message, unit: series.unit, label: series.label };
    text(left, 20, `${series.label} / ${series.unit}`, { size: 10, fill: '#b8c6d1' });
    if (!all.length) {
      make('path', { d: `M${left} 68H${right}M${left} 110H${right}M${left} 152H${right}`, stroke: '#29343f', 'stroke-dasharray': '3 6' });
      text(345, 101, series.end ? `该时段暂无${series.label}数据` : `等待第一条${series.label}记录`, { anchor: 'middle', size: 15, fill: '#c9dce6' });
      text(345, 126, series.end ? '可补录该指标，或切换时间范围' : '录入数据后，在这里查看真实变化', { anchor: 'middle', size: 11 });
      if (series.end) text(345, 199, `截至最新记录 ${localParts(parseTime(series.end)).day}`, { anchor: 'middle', size: 10 });
      return result;
    }

    const values = all.map(point => point.value);
    const minValue = Math.min(...values), maxValue = Math.max(...values);
    const span = maxValue - minValue;
    const minSpan = series.field === 'weight' ? 0.4 : series.field === 'waist' ? 1 : 0.4;
    const padding = Math.max(span * 0.18, minSpan / 2);
    const step = niceStep(span + 2 * padding);
    const minY = Math.floor((minValue - padding) / step) * step;
    const maxY = Math.ceil((maxValue + padding) / step) * step;
    const firstTime = all[0].timestamp, lastTime = all[all.length - 1].timestamp;
    const timeSpan = lastTime - firstTime;
    const timePad = timeSpan ? Math.max(timeSpan * 0.055, 1000) : 12 * 3600000;
    const minX = firstTime - timePad, maxX = lastTime + timePad;
    const x = time => left + (time - minX) / (maxX - minX) * (right - left);
    const y = value => bottom - (value - minY) / (maxY - minY) * (bottom - top);
    let axisDecimals = 0;
    while (axisDecimals < 6 && Math.abs(Number(step.toFixed(axisDecimals)) - step) > step * 1e-7) axisDecimals++;
    const tickCount = Math.round((maxY - minY) / step);
    for (let i = 0; i <= tickCount; i++) {
      const value = minY + i * step;
      const yPos = y(value);
      make('line', { x1: left, y1: yPos, x2: right, y2: yPos, stroke: '#4a5e703b', 'stroke-width': 1, 'stroke-dasharray': '3 6' });
      text(left - 12, yPos + 4, (Object.is(value, -0) ? 0 : value).toFixed(axisDecimals), { anchor: 'end', size: 10 });
    }

    const sameDay = localParts(firstTime).day === localParts(lastTime).day;
    const crossesYear = localParts(firstTime).day.slice(0, 4) !== localParts(lastTime).day.slice(0, 4);
    const uniqueTimes = [...new Set(all.map(point => point.timestamp))];
    // Tick labels use actual timestamps, never invented daily measurement points.
    const tickIndexes = uniqueTimes.length <= 4 ? uniqueTimes.map((_, i) => i) : [0, Math.floor((uniqueTimes.length - 1) / 3), Math.floor((uniqueTimes.length - 1) * 2 / 3), uniqueTimes.length - 1];
    for (const index of tickIndexes) {
      const time = uniqueTimes[index], p = localParts(time);
      text(x(time), 201, sameDay && uniqueTimes.length > 1 ? p.clock : crossesYear ? p.day : p.day.slice(5).replace('-', '/'), { anchor: 'middle', size: 10 });
    }
    if (sameDay && uniqueTimes.length > 1) text(right, 221, `${localParts(firstTime).day} · 上海时间`, { anchor: 'end', size: 9 });

    if (series.points.length > 1) {
      const points = series.points.map(point => `${x(point.timestamp)},${y(point.value)}`).join(' ');
      make('polyline', { points, fill: 'none', stroke: '#7edfea', 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: '.8', 'vector-effect': 'non-scaling-stroke' });
    }
    const formatValue = value => value.toFixed(series.precision);
    const latestActual = series.points[series.points.length - 1];
    const showAllLabels = all.length <= 3;
    const placedLabels = [];
    const drawPoint = point => {
      const isEstimate = point.kind === 'inferred';
      const px = x(point.timestamp), py = y(point.value);
      const p = localParts(point.timestamp);
      let label = `${p.day} ${p.clock}，${series.label} ${formatValue(point.value)} ${series.unit}，${isEstimate ? '设备对比推算' : '实测'}`;
      if (isEstimate) {
        const source = localParts(parseTime(point.source_measured_at));
        label += `。根据 ${source.day} ${source.clock} 报告，${formatValue(point.source_value)} 减去变化值 ${point.delta}，推算得到 ${formatValue(point.value)}；不是该日完整测量报告。`;
      }
      const group = make('g', { 'data-kind': point.kind, 'data-time': point.measured_at });
      if (point === latestActual) make('circle', { cx: px, cy: py, r: 10, fill: '#7edfea16', 'pointer-events': 'none' }, undefined, group);
      const circle = make('circle', { cx: px, cy: py, r: isEstimate ? 5.2 : 4.5,
        fill: isEstimate ? '#141b23' : '#9cebf5', stroke: isEstimate ? '#d4b17b' : '#d7faff',
        'stroke-width': isEstimate ? 1.8 : 1, tabindex: 0, focusable: 'true', role: 'img', 'aria-label': label,
        style: 'outline-offset:4px;cursor:help;' }, undefined, group);
      make('title', {}, label, circle);
      if (showAllLabels || point === latestActual) {
        const valueLabel = `${formatValue(point.value)}${isEstimate ? ' *' : ''}`;
        const width = valueLabel.length * 7.2 + 15;
        const labelX = Math.max(left + width / 2, Math.min(right - width / 2, px));
        let labelY = py - 17;
        if (placedLabels.some(prev => Math.abs(prev.x - labelX) < (prev.width + width) / 2 && Math.abs(prev.y - labelY) < 24)) labelY = py + 24;
        if (placedLabels.some(prev => Math.abs(prev.x - labelX) < (prev.width + width) / 2 && Math.abs(prev.y - labelY) < 24)) return;
        placedLabels.push({ x: labelX, y: labelY, width });
        make('rect', { x: labelX - width / 2, y: labelY - 13, width, height: 20, rx: 3,
          fill: isEstimate ? '#28231b' : '#18313b', stroke: isEstimate ? '#6b583c' : '#355f70', 'stroke-width': '.6', 'pointer-events': 'none' }, undefined, group);
        text(labelX, labelY + 1, valueLabel, { parent: group, anchor: 'middle', size: 11, fill: isEstimate ? '#dfc18e' : '#c8f6fb', bold: true, attributes: { 'pointer-events': 'none' } });
      }
    };
    // Inferences have their own markers and never enter the actual polyline.
    // Reserve the latest actual label first so crowded older points cannot hide it.
    if (latestActual) drawPoint(latestActual);
    series.inferred.forEach(drawPoint);
    series.points.filter(point => point !== latestActual).forEach(drawPoint);
    return result;
  }

  return Object.freeze({ buildSeries, render });
});
