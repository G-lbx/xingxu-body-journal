/* Local Body Journal: all health data is read from and persisted by the loopback API. */
(() => {
  'use strict';
  const $ = (q, root = document) => root.querySelector(q);
  const $$ = (q, root = document) => [...root.querySelectorAll(q)];
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const fmt = (v, digits = 2) => Number.isFinite(v) ? Number(v.toFixed(digits)).toString() : '—';
  const delta = (v, unit = '') => Number.isFinite(v) ? `${v > 0 ? '+' : ''}${fmt(v)}${unit}` : '—';
  const dateText = (v) => v ? v.replace('T', ' ').slice(0, 16) : '—';
  const sourceNames = {manual: '手动录入', ocr_confirmed: '截图识别 · 已核对', assistant_verified: '首张截图 · 已核对'};
  const trainingNames = {rest: '休息 / 恢复', strength: '力量训练', cardio: '有氧活动', mixed: '力量 + 有氧'};
  const fields = [
    ['weight','体重','kg',1,500], ['body_fat','体脂率','%',0,80], ['muscle_mass','肌肉量','kg',0,400],
    ['skeletal_mass','骨骼肌量','kg',0,300], ['waist','腰围（可另行测量）','cm',20,300], ['bmi','BMI（设备原值）','',3,100],
    ['standard_weight','标准体重（设备）','kg',1,500], ['fat_mass','脂肪量','kg',0,400], ['water_pct','水分率','%',0,100],
    ['water_mass','水分量','kg',0,400], ['muscle_pct','肌肉率','%',0,100], ['protein_pct','蛋白质率','%',0,100],
    ['protein_mass','蛋白质量','kg',0,200], ['skeletal_pct','骨骼肌率','%',0,100], ['bmr','基础代谢（设备估算）','kcal/日',100,10000],
    ['visceral_fat','内脏脂肪等级','',0,100], ['bone_mass','骨量','kg',0,30], ['fat_free_mass','去脂体重','kg',0,500],
    ['score','设备评分','',0,100], ['body_age','身体年龄（设备）','',1,150], ['obesity_pct','肥胖度（设备）','%',-100,500],
    ['weight_control','体重控制量（设备）','kg',-300,300], ['muscle_control','肌肉控制量（设备）','kg',-300,300], ['fat_control','脂肪控制量（设备）','kg',-300,300]
  ];
  let state = null, metric = 'weight', range = '30', visibleRecords = 20, editing = null, deleting = null;
  let toastTimer, uploadBusy = false, tasksBusy = false, checkinDirty = false, loadSequence = 0;
  const currentShanghaiMinute = () => new Date(Date.now() + 8 * 3600000).toISOString().slice(0,16);
  function lockCheckin(busy) { tasksBusy = busy; $$('input[name="task"]').forEach(i => i.disabled = busy); toggleBusy($('#checkin-form button[type=submit]'),busy); }
  function icon(id) { const n = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); n.setAttribute('class', 'icon'); n.setAttribute('aria-hidden', 'true'); const u = document.createElementNS(n.namespaceURI, 'use'); u.setAttribute('href', `#${document.getElementById(id) ? id : 'i-spark'}`); n.append(u); return n; }
  function toast(message) { $('#toast').textContent = message; $('#toast').classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('show'), 4500); }
  function setError(id, message = '') { $(id).textContent = message; }
  function toggleBusy(button, busy) { button.disabled = busy; button.setAttribute('aria-busy', String(busy)); }
  async function api(path, method = 'GET', body) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), path === '/api/upload' ? 110000 : 45000);
    try {
      const response = await fetch(path, {method, signal: controller.signal, cache: 'no-store', headers: body === undefined ? {} : {'Content-Type':'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) { const e = new Error(data.error || `本机服务返回错误 (${response.status})`); e.data = data; throw e; }
      return data;
    } catch (e) {
      if (e.name === 'AbortError') throw new Error('操作等待超时。请刷新确认是否已保存，再重试。');
      if (e instanceof TypeError) throw new Error('无法连接本机服务，请运行“启动形序.cmd”后重试。');
      throw e;
    } finally { clearTimeout(timer); }
  }
  async function loadState() {
    const sequence = ++loadSequence;
    try {
      const next = await api('/api/state');
      if (sequence !== loadSequence) return;
      state = next; $('#offline-banner').hidden = true;
      $('.preview-badge').textContent = '本机已连接 · 数据持久保存';
      $('.preview-badge').classList.remove('offline');
      render();
    } catch (e) {
      $('#offline-banner').hidden = false;
      $('.preview-badge').textContent = '服务未连接'; $('.preview-badge').classList.add('offline');
      if (state) toast('刷新未完成，页面仍显示上次读取的数据。');
      else { $('#recent-date').textContent = '等待连接本机服务'; $('#plan-title').textContent = '启动本机服务后载入'; }
      throw e;
    }
  }
  async function refreshAfterSave(message) {
    try { await loadState(); toast(message); }
    catch { toast('已保存到本机，但页面刷新失败。请点击“重新连接”，无需重复提交。'); }
  }
  const latest = () => state?.records?.at(-1);
  function render() {
    const record = latest(), analysis = state.analysis || {};
    $('.metrics').classList.remove('metrics-loading');
    $('.topbar .date').textContent = state.today;
    $('#latest-time').textContent = record ? `最近测量 ${dateText(record.measured_at)}` : '暂无测量记录';
    ['weight','body_fat','muscle_mass','skeletal_mass'].forEach((field, i) => {
      const card = $$('.metric')[i]; $('.metric-value strong', card).textContent = fmt(record?.[field]);
      const previous = [...state.records].reverse().find(r => r.id !== record?.id && Number.isFinite(r[field]));
      let comparison = '本次记录 · 待积累对比数据';
      if (!record || !Number.isFinite(record[field])) comparison = '暂无该项测量数据';
      else if (previous) comparison = `${delta(record[field] - previous[field], field === 'body_fat' ? ' 个百分点' : ' kg')} · 较 ${previous.measured_at.slice(5,10)}`;
      else if (['weight','body_fat'].includes(field) && Number.isFinite(record.device_comparison?.[`${field}_delta`])) comparison = `${delta(record.device_comparison[`${field}_delta`], field === 'body_fat' ? ' 个百分点' : ' kg')} · 设备报告对比`;
      $('.metric-bottom', card).textContent = comparison;
    });
    const quality = analysis.data_quality || {}, banner = $('#health-banner'); banner.replaceChildren();
    banner.hidden = !(quality.bmi_mismatch || quality.low_bmi);
    if (!banner.hidden) {
      banner.append(node('strong', '', '先核对身高与设备资料，当前优先增肌和恢复'));
      banner.append(node('span', '', `按档案身高 ${fmt(state.profile.height)} cm 与最近体重计算，BMI 约 ${fmt(quality.profile_bmi)}；设备原值为 ${fmt(quality.device_bmi)}。${quality.low_bmi ? '目前不生成主动减重或热量缺口方案。' : ''}设备读数已保留，请核对体脂秤身高设置。BMI 仅作为筛查参考。`));
      const b = node('button','text-link','核对个人档案 →'); b.dataset.open = 'profile-dialog'; banner.append(document.createElement('br'), b);
    }
    renderChart(); renderAdvice(analysis); renderRecent(record); renderHistory(); renderCheckins();
    const details = $('.all-metrics'); details.replaceChildren();
    fields.slice(5).concat([fields[4]]).forEach(([key,label,unit]) => { const d = node('div','detail-metric'); d.append(node('span','',label), node('strong','',fmt(record?.[key])), node('small','',unit)); details.append(d); });
    $('#ocr-status').textContent = state.ocr_available ? 'Windows OCR 已就绪 · 图片仅在本机识别，核对后保存。' : '本机 OCR 不可用。仍可上传原图，并手动填写数值后保存。';
  }
  function renderChart() {
    if (!state) return;
    const info = BodyChart.render($('.chart'), state.records, metric, range);
    $('#chart-unit').textContent = `${info.label} / ${info.unit}`;
    $('#comparison-legend').hidden = info.inferredCount === 0; $('#chart-note').textContent = info.message;
    const m = state.analysis?.metrics?.[metric], summary = $('#chart-summary'); summary.replaceChildren();
    if (m) {
      const mean = node('span','','最近 7 日均值'); mean.append(node('strong','',`${fmt(m.week_mean)} ${info.unit}`));
      const change = node('span','','对比前 7 日'); change.append(node('strong','',delta(m.week_delta, metric === 'body_fat' ? ' 个百分点' : ` ${info.unit}`)));
      summary.append(mean, change, node('span','',`有效测量日 ${m.days_current || 0} / ${m.days_previous || 0} · 每期至少 3 天后比较`));
    }
  }
  function renderAdvice(a) {
    $('#plan-title').textContent = a.title || '先记录，再观察'; $('.plan-intro').textContent = a.summary || '补充测量记录和档案，形成可执行的下一步。';
    $('#plan-confidence').textContent = a.confidence || '等待记录';
    const teaser = $('.plan-items'); teaser.replaceChildren();
    (a.actions || []).slice(0,3).forEach(action => { const row = node('div','plan-item'), badge = node('span','plan-icon'), content = node('div'); badge.append(icon(action.icon)); content.append(node('strong','',action.title), node('p','',action.detail)); row.append(badge,content); teaser.append(row); });
    const p = state.profile; $('#profile-summary').textContent = `${fmt(p.age)} 岁 · ${fmt(p.height)} cm · ${p.sex === 'male' ? '男' : p.sex === 'female' ? '女' : '性别未填'} · 每周训练 ${fmt(p.training_days,0)} 天 · ${p.training_focus || '训练重点待补充'}${a.missing_profile?.length ? ` ｜ 待补充：${a.missing_profile.join('、')}` : ''}`;
    const insights = $('#insights'); insights.replaceChildren();
    (a.insights || []).forEach(i => { const n = node('article',`insight ${['attention','positive'].includes(i.tone) ? i.tone : ''}`); n.append(node('h3','',i.title),node('p','',i.text)); insights.append(n); });
    const actions = $('#advice-actions'); actions.replaceChildren();
    (a.actions || []).forEach(action => { const n = node('article','advice-item'), h = node('h3'); h.append(icon(action.icon), document.createTextNode(action.title)); n.append(h,node('p','',action.detail),node('small','',`依据：${action.reason}`)); actions.append(n); });
    const targets = $('#targets'); targets.replaceChildren(); const t = a.targets || {};
    if (Number.isFinite(t.protein_min)) targets.append(node('div','target-chip',`蛋白质参考 ${t.protein_min}–${t.protein_max} g / 日`));
    if (Number.isFinite(t.training_days)) targets.append(node('div','target-chip',`建议力量训练 ${t.training_days} 天 / 周`));
    $('#week-title').textContent = a.weekly?.title || '一周节奏'; $('#week-summary').textContent = a.weekly?.summary || '';
    const week = $('#week-grid'); week.replaceChildren();
    (a.weekly?.schedule || []).forEach(d => { const n = node('div',`week-day ${['strength','rest','recovery'].includes(d.type) ? d.type : ''}`); n.append(node('strong','',d.day),node('b','',d.title),node('p','',d.detail)); week.append(n); });
    $('#advice-limitations').textContent = [...(a.limitations || []), a.weekly?.review_date ? `下次复盘：${a.weekly.review_date}` : ''].join(' ');
    const sources = $('#source-links'); sources.replaceChildren();
    (a.sources || []).forEach(source => { if (!/^https:\/\//.test(source.url)) return; const link = node('a','',source.title); link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer'; sources.append(link); });
  }
  function renderRecent(record) {
    $('#recent-count').textContent = `${state.records.length} 条记录`;
    $('#recent-date').textContent = record ? dateText(record.measured_at) : '从第一份记录开始';
    $('#recent-values').textContent = record ? `体重 ${fmt(record.weight)} kg · 体脂 ${fmt(record.body_fat)}%` : '导入截图，或手动填写测量值';
    $('#recent-source').textContent = record ? sourceNames[record.source] || '本机记录' : '';
    $('#latest-thumb').hidden = !record?.upload_id;
    if (record?.upload_id) $('#latest-thumbnail').src = `/uploads/${encodeURIComponent(record.upload_id)}`;
    $$('[data-open="report-dialog"]').forEach(b => b.disabled = !record?.upload_id);
    $('#recent-note').textContent = record?.note || '记录、原图均保存在本机';
  }
  function actionButton(text, action, id, cls = '') { const b = node('button',`text-link ${cls}`,text); b.type = 'button'; b.dataset.action = action; b.dataset.id = id; return b; }
  function renderHistory() {
    const rows = $('#record-rows'); rows.replaceChildren();
    [...state.records].reverse().slice(0,visibleRecords).forEach(r => {
      const tr = node('tr'); [dateText(r.measured_at),fmt(r.weight),fmt(r.body_fat),fmt(r.muscle_mass),fmt(r.waist),sourceNames[r.source] || '本机记录'].forEach(v => tr.append(node('td','',v)));
      const actions = node('td','actions-cell'); if (r.upload_id) actions.append(actionButton('原图','report',r.id)); actions.append(actionButton('编辑','edit',r.id),actionButton('删除','delete',r.id,'danger-link')); tr.append(actions); rows.append(tr);
    });
    $('#record-count').textContent = `${state.records.length} 条已保存记录 · 按测量时间倒序`;
    $('#history-empty').hidden = state.records.length > 0; $('#more-records').hidden = visibleRecords >= state.records.length;
  }
  const checkinFor = (date) => state?.checkins.find(c => c.date === date) || {date,training:'rest',minutes:0,sleep:null,steps:null,energy:'normal',nutrition:false,note:'',tasks:[]};
  function populateCheckin() {
    if (!state) return; const c = checkinFor($('#checkin-date').value), form = $('#checkin-form');
    for (const key of ['training','minutes','sleep','steps','energy','note']) form.elements[key].value = c[key] ?? '';
    form.elements.nutrition.checked = !!c.nutrition; setError('#checkin-error');
  }
  function renderCheckins() {
    const ids = ['measure','movement','recovery'], tasks = checkinFor(state.today).tasks || [];
    $$('input[name="task"]').forEach((input,i) => { input.dataset.task = ids[i]; input.checked = tasks.includes(ids[i]); });
    const count = ids.filter(id => tasks.includes(id)).length; $('#task-count').textContent = `${count} / 3`; $('#task-progress').style.width = `${count / 3 * 100}%`;
    if (!$('#checkin-date').value) $('#checkin-date').value = state.today;
    $('#checkin-date').max = state.today; if (!checkinDirty) populateCheckin();
    const history = $('#checkin-history'); history.replaceChildren();
    [...state.checkins].reverse().slice(0,7).forEach(c => { const row = node('div','checkin-row'), button = actionButton('编辑','checkin',c.date); row.append(node('time','',c.date),node('span','',`${trainingNames[c.training]} ${c.minutes} 分钟`),node('span','',`睡眠 ${fmt(c.sleep)} h · 步数 ${fmt(c.steps,0)}`),button); history.append(row); });
    if (!state.checkins.length) history.append(node('p','rule-note','还没有训练与恢复日志，今天开始即可。'));
  }
  function addField(target, key, label, type = 'number', low, high, unit = '') {
    const wrapper = node('label','form-field',`${label}${unit ? ` / ${unit}` : ''}`), input = node('input'); input.name = key; input.type = type; input.autocomplete = 'off';
    if (type === 'number') { input.step = 'any'; input.min = low; input.max = high; input.placeholder = '未记录'; }
    if (key === 'measured_at' || key === 'weight') input.required = true;
    if (type === 'datetime-local') { input.min = '1900-01-01T00:00'; input.max = '2100-12-31T23:59'; }
    wrapper.append(input); $(target).append(wrapper);
  }
  addField('#record-main-fields','measured_at','测量时间（北京时间）','datetime-local');
  fields.forEach(([key,label,unit,low,high],i) => addField(i < 5 ? '#record-main-fields' : '#record-extra-fields',key,label,'number',low,high,unit));
  addField('#record-extra-fields','compare_date','报告中的上次测量时间','datetime-local');
  addField('#record-extra-fields','compare_weight','报告体重差值（本次－上次）','number',-300,300,'kg');
  addField('#record-extra-fields','compare_fat','报告体脂差值（本次－上次）','number',-80,80,'百分点');
  function openRecord(record, options = {}) {
    const form = $('#record-form'); form.reset(); editing = {record: record || {}, id: options.id || null, upload: options.upload || record?.upload_id || null, ocr: !!options.ocr};
    const r = record || {}; form.elements.measured_at.value = r.measured_at || (options.ocr ? '' : currentShanghaiMinute());
    fields.forEach(([key]) => { const input = form.elements[key]; input.value = r[key] ?? ''; input.closest('label').classList.toggle('field-not-found',!!options.ocr && r[key] == null && key !== 'waist'); });
    form.elements.note.value = r.note || '';
    form.elements.compare_date.value = r.device_comparison?.measured_at || '';
    form.elements.compare_weight.value = r.device_comparison?.weight_delta ?? '';
    form.elements.compare_fat.value = r.device_comparison?.body_fat_delta ?? '';
    $('#record-modal-title').textContent = options.id ? '编辑测量记录' : options.ocr ? '识别完成 · 请核对后保存' : '手动录入测量记录';
    $('#record-modal-subtitle').textContent = '日期与体重必填 · 其余项目可以留空 · 原始设备值不自动改写';
    $('#record-engine').textContent = options.ocr ? 'WINDOWS OCR / 本机识别' : options.id ? 'LOCAL ARCHIVE / 已保存记录' : 'MANUAL ENTRY / 手动填写';
    const warnings = $('#record-warnings'); warnings.replaceChildren(); warnings.hidden = !(options.warnings?.length);
    (options.warnings || []).forEach(w => warnings.append(node('div','',w)));
    $('#record-source').hidden = !editing.upload; $('#record-columns').style.gridTemplateColumns = editing.upload ? '' : '1fr';
    if (editing.upload) $('#record-image').src = `/uploads/${encodeURIComponent(editing.upload)}`;
    setError('#record-error'); $('#record-dialog').showModal();
  }
  function openReport(record) { if (!record?.upload_id) { toast('这条记录没有关联原图。'); return; } $('#full-report').src = `/uploads/${encodeURIComponent(record.upload_id)}`; $('#report-subtitle').textContent = `${dateText(record.measured_at)} · ${sourceNames[record.source] || '本机记录'}`; $('#report-dialog').showModal(); }
  function openProfile() { if (!state) { toast('请先连接本机服务。'); return; } const f = $('#profile-form'); for (const key of ['age','height','sex','training_level','training_days','training_focus','health_context','limitations']) f.elements[key].value = state.profile[key] ?? ''; setError('#profile-error'); $('#profile-dialog').showModal(); }
  function openDialog(id) {
    if (id === 'profile-dialog') return openProfile();
    if (id === 'report-dialog') return openReport(latest());
    if (id === 'upload-dialog' && !state) { toast('请先连接本机服务。'); return; }
    document.getElementById(id)?.showModal();
  }
  document.addEventListener('click', e => {
    const opener = e.target.closest('[data-open]'); if (opener) { e.preventDefault(); openDialog(opener.dataset.open); return; }
    const closer = e.target.closest('[data-close]'); if (closer) { e.preventDefault(); closer.closest('dialog').close(); return; }
    const b = e.target.closest('[data-action]'); if (!b || !state) return;
    const record = state.records.find(r => r.id === b.dataset.id);
    if (b.dataset.action === 'report') openReport(record);
    if (b.dataset.action === 'edit' && record) { $('#upload-dialog').close(); openRecord(record,{id:record.id}); }
    if (b.dataset.action === 'delete' && record) { deleting = record.id; $('#delete-description').textContent = `${dateText(record.measured_at)} · 体重 ${fmt(record.weight)} kg · 体脂率 ${fmt(record.body_fat)}%`; setError('#delete-error'); $('#delete-dialog').showModal(); }
    if (b.dataset.action === 'checkin') { $('#checkin-date').value = b.dataset.id; checkinDirty = false; populateCheckin(); $('#checkin-section').scrollIntoView({behavior:'smooth',block:'start'}); }
  });
  $('#preview-info').addEventListener('click', () => $('#info-dialog').showModal());
  $('#retry-load').addEventListener('click', () => loadState().catch(e => toast(e.message)));
  $('#manual-add').addEventListener('click', () => state ? openRecord(null) : toast('请先连接本机服务。'));
  $('#more-records').addEventListener('click', () => { visibleRecords += 30; renderHistory(); });
  $$('.nav a:not([data-open])').forEach(link => link.addEventListener('click', () => { $$('.nav a').forEach(a => {a.classList.remove('active');a.removeAttribute('aria-current');}); link.classList.add('active');link.setAttribute('aria-current','location'); }));
  ['metric','range'].forEach(type => $$(`[data-${type}]`).forEach(button => button.addEventListener('click', () => { if (type === 'metric') metric = button.dataset.metric; else range = button.dataset.range; $$(`[data-${type}]`).forEach(b => { b.classList.toggle('selected',b === button); b.setAttribute('aria-pressed',String(b === button)); }); renderChart(); })));
  function readFile(file) { return new Promise((resolve,reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('文件读取失败，请重新选择。')); reader.readAsDataURL(file); }); }
  async function upload(file) {
    if (!file || uploadBusy) return;
    setError('#upload-error');
    if (!['image/jpeg','image/png','image/webp'].includes(file.type)) return setError('#upload-error','请选择 JPG、PNG 或 WebP 图片。');
    if (file.size > 12 * 1024 * 1024) return setError('#upload-error','图片超过 12 MB，请压缩后重试。');
    uploadBusy = true; $('#ocr-busy').hidden = false; toggleBusy($('#choose-file'),true); $('#upload-dialog [data-close]').disabled = true;
    try {
      const result = await api('/api/upload','POST',{name:file.name,dataUrl:await readFile(file)});
      if (result.duplicate_record_id) {
        const error = $('#upload-error'); error.textContent = '这张截图已经保存，不会重复新增。'; error.append(document.createElement('br'),actionButton('打开已有记录','edit',result.duplicate_record_id));
      } else { $('#upload-dialog').close(); openRecord(result.fields,{upload:result.upload_id,ocr:true,warnings:result.warnings}); }
    } catch(e) { setError('#upload-error',e.message); }
    finally { uploadBusy = false; $('#ocr-busy').hidden = true; toggleBusy($('#choose-file'),false); $('#upload-dialog [data-close]').disabled = false; $('#file-input').value = ''; }
  }
  $('#upload-dialog').addEventListener('cancel',e => { if (uploadBusy) e.preventDefault(); });
  $('#choose-file').addEventListener('click', () => $('#file-input').click()); $('#file-input').addEventListener('change',e => upload(e.target.files[0]));
  ['dragenter','dragover'].forEach(type => $('#upload-zone').addEventListener(type,e => {e.preventDefault();$('#upload-zone').classList.add('dragover');}));
  ['dragleave','drop'].forEach(type => $('#upload-zone').addEventListener(type,e => {e.preventDefault();$('#upload-zone').classList.remove('dragover');if(type === 'drop') upload(e.dataTransfer.files[0]);}));
  $('#record-form').addEventListener('submit', async e => {
    e.preventDefault(); if (!editing) return; const f = e.currentTarget, button = $('#save-record'); setError('#record-error');
    const payload = {...editing.record,measured_at:f.elements.measured_at.value,note:f.elements.note.value,upload_id:editing.upload,source:editing.ocr ? 'ocr_confirmed' : 'manual'};
    fields.forEach(([key]) => payload[key] = f.elements[key].value === '' ? null : Number(f.elements[key].value));
    const compareDate = f.elements.compare_date.value;
    if (!compareDate && (f.elements.compare_weight.value || f.elements.compare_fat.value)) return setError('#record-error','填写历史差值时，请同时填写报告中的上次测量时间。');
    if (compareDate && compareDate >= payload.measured_at) return setError('#record-error','历史对比时间须早于本次测量时间。');
    payload.device_comparison = compareDate ? {measured_at:compareDate,weight_delta:f.elements.compare_weight.value === '' ? null : Number(f.elements.compare_weight.value),body_fat_delta:f.elements.compare_fat.value === '' ? null : Number(f.elements.compare_fat.value)} : null;
    toggleBusy(button,true);
    try { await api(editing.id ? `/api/records/${encodeURIComponent(editing.id)}` : '/api/records',editing.id ? 'PUT' : 'POST',payload); $('#record-dialog').close(); await refreshAfterSave('测量记录已保存，趋势与建议已更新。'); }
    catch(error) { setError('#record-error',error.message); if (error.data?.existing_id) $('#record-error').append(document.createElement('br'),actionButton('打开已有记录','edit',error.data.existing_id)); }
    finally { toggleBusy(button,false); }
  });
  $('#profile-form').addEventListener('submit', async e => {
    e.preventDefault(); const f = e.currentTarget, b = $('button[type=submit]',f), payload = {...state.profile};
    for (const key of ['age','height','training_days']) payload[key] = f.elements[key].value === '' ? null : Number(f.elements[key].value);
    for (const key of ['sex','training_level','training_focus','health_context','limitations']) payload[key] = f.elements[key].value;
    setError('#profile-error');toggleBusy(b,true);
    try { await api('/api/profile','PUT',payload); $('#profile-dialog').close(); await refreshAfterSave('档案已保存，行动方案已重新计算。'); }
    catch(error) { setError('#profile-error',error.message); } finally { toggleBusy(b,false); }
  });
  $('#checkin-date').addEventListener('change',() => { checkinDirty = false; populateCheckin(); });
  $('#checkin-form').addEventListener('input',() => checkinDirty = true);
  $('#checkin-form').addEventListener('change',() => checkinDirty = true);
  $('#checkin-form').addEventListener('submit', async e => {
    e.preventDefault(); if (!state || tasksBusy) return; const f = e.currentTarget, date = $('#checkin-date').value;
    if (!date || date > state.today) return setError('#checkin-error','请选择今天或过去的日期。');
    const payload = {...checkinFor(date),training:f.elements.training.value,energy:f.elements.energy.value,nutrition:f.elements.nutrition.checked,note:f.elements.note.value};
    for (const key of ['minutes','sleep','steps']) payload[key] = f.elements[key].value === '' ? null : Number(f.elements[key].value);
    setError('#checkin-error'); lockCheckin(true);
    try { await api(`/api/checkins/${date}`,'PUT',payload); checkinDirty = false; await refreshAfterSave('当日日志已保存。'); }
    catch(error) { setError('#checkin-error',error.message); } finally { lockCheckin(false); }
  });
  $$('input[name="task"]').forEach(input => input.addEventListener('change',async () => {
    if (!state || tasksBusy) { input.checked = !input.checked; return; } lockCheckin(true);
    const inputs = $$('input[name="task"]');
    const payload = {...checkinFor(state.today),tasks:inputs.filter(i => i.checked).map(i => i.dataset.task)};
    try { const result = await api(`/api/checkins/${state.today}`,'PUT',payload); state.checkins = state.checkins.filter(c => c.date !== state.today).concat(result.checkin).sort((a,b) => a.date.localeCompare(b.date)); const count = payload.tasks.length; $('#task-count').textContent = `${count} / 3`; $('#task-progress').style.width = `${count / 3 * 100}%`; toast('今日任务已保存。'); }
    catch(error) { input.checked = !input.checked; toast(error.message); } finally { lockCheckin(false); }
  }));
  $('#confirm-delete').addEventListener('click',async () => { if (!deleting) return; const b = $('#confirm-delete'); setError('#delete-error'); toggleBusy(b,true); try { await api(`/api/records/${encodeURIComponent(deleting)}`,'DELETE',{}); $('#delete-dialog').close(); deleting = null; await refreshAfterSave('记录已删除，趋势已更新。'); } catch(e) { setError('#delete-error',e.message); } finally { toggleBusy(b,false); } });
  $('#import-file').addEventListener('change',e => { const file = e.target.files[0]; $('#restore-backup').disabled = !file; $('#import-description').textContent = file ? `${file.name} · ${(file.size / 1024).toFixed(1)} KB · 点击“合并恢复”后写入本机档案` : '选择 JSON 或 ZIP 备份。'; $('#import-result').hidden = true;setError('#import-error'); });
  $('#restore-backup').addEventListener('click',async () => {
    const file = $('#import-file').files[0], b = $('#restore-backup'); if (!file) return; setError('#import-error');toggleBusy(b,true);
    try {
      const zip = /\.zip$/i.test(file.name); if (!zip && !/\.json$/i.test(file.name)) throw new Error('请选择形序导出的 JSON 或 ZIP 文件。');
      if (file.size > (zip ? 100 : 17) * 1024 * 1024) throw new Error('备份文件超过允许大小（JSON 17 MB / ZIP 100 MB）。');
      let payload; if (zip) payload = {dataBase64:(await readFile(file)).split(',')[1]}; else {try {payload = JSON.parse(await file.text());} catch {throw new Error('JSON 文件格式不正确。');}}
      const result = await api(zip ? '/api/restore' : '/api/import','POST',payload);
      const panel = $('#import-result'); panel.replaceChildren(node('strong','',`已导入 ${result.imported} 条测量、${result.checkins_imported} 条日志，恢复 ${result.images_restored || 0} 张原图。`),node('p','',`跳过 ${result.skipped} 条测量、${result.checkins_skipped} 条日志；个人档案${result.profile_updated ? '已补齐空白项' : '保持原值'}。`));
      (result.warnings || []).forEach(w => panel.append(node('p','',w))); (result.conflicts || []).slice(0,20).forEach(c => panel.append(node('p','',`跳过 ${c.id || ''}：${c.reason}`)));
      panel.hidden = false; await refreshAfterSave('备份合并完成。');
    } catch(e) { setError('#import-error',e.message); } finally { toggleBusy(b,false); }
  });
  $('#record-image').addEventListener('error', () => { $('#record-source').hidden = true; $('#record-columns').style.gridTemplateColumns = '1fr'; toast('关联原图不存在，可继续核对文字记录。'); });
  $('#full-report').addEventListener('error', () => { $('#report-subtitle').textContent = '关联原图未找到。如从 JSON 恢复，请使用包含原图的 ZIP 备份恢复。'; });
  loadState().catch(() => {});
})();
