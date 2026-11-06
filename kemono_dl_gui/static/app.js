/* kemono-dl GUI — application logic
   The GUI is a thin, opinionated front-end: every action is translated into a
   real `python -m kemono_dl ...` invocation by the local server. */

'use strict';

const TOKEN = document.querySelector('meta[name="gui-token"]').content;
const STORAGE_KEY = 'kemono-dl-gui.config.v2';
const THEME_KEY = 'kemono-dl-gui.theme';
const MODE_KEY = 'kemono-dl-gui.mode';
const $ = (id) => document.getElementById(id);

const DATE_DEFS = [
  { key: 'date', label: '指定日期', hint: '--date', desc: '仅下载这一天的帖子' },
  { key: 'datebefore', label: '早于', hint: '--datebefore', desc: '只下载此日期之前的帖子' },
  { key: 'dateafter', label: '晚于', hint: '--dateafter', desc: '只下载此日期之后的帖子' },
];
const DATE_TYPES = [
  ['published', '发布时间'],
  ['added', '添加时间'],
  ['edited', '编辑时间'],
];
const TEMPLATE_PRESETS = [
  ['默认 (服务 / 作者 / 帖子 / 文件名)', '{service}/{creator_id}/{post_id}/{filename}'],
  ['仅用帖子标题命名 (不含编号)', '{service}/{creator_id}/{post_title}/{filename}'],
  ['帖子标题 + 编号', '{service}/{creator_id}/{post_title} [{post_id}]/{filename}'],
  ['按帖子标题分类', '{service}/{creator_id}/{post_id} - {post_title}/{filename}'],
  ['按发布日期分类', '{service}/{creator_id}/{published:%Y-%m-%d}/{post_id}/{filename}'],
  ['按作者名分类', '{service}/{creator_name}/{post_id}/{filename}'],
  ['扁平文件名', '{service}_{creator_id}_{post_id}_{filename}'],
  ['按扩展名分类', '{service}/{creator_id}/{post_id}/{file_ext}/{filename}'],
];
const VAR_ORDER = [
  'service', 'creator_id', 'creator_name', 'post_id', 'post_title',
  'published', 'added', 'edited', 'attachments_count',
  'index', 'filename', 'file_name', 'file_ext', 'server_filename', 'sha256',
];
const STATUS_LABELS = {
  queued: '排队中', running: '下载中', done: '已完成', failed: '失败', stopped: '已停止',
};

const APP = {
  meta: null,
  selectedJobId: null,
  since: 0,
  pollTimer: null,
  refreshTimer: null,
  failures: 0,
  lastJobSignature: '',
  logs: new Map(),
  lists: { batchFiles: [], cookies: [], skipExtensions: [] },
  templates: { attachments: '', content: '', json: '' },
  dates: {},
  logins: {},
  lastTemplateInput: null,
  fsMode: 'dir',
  fsState: null,
  fsSelectedFile: null,
  fsCallback: null,
  running: false,
  jobFailures: [],
  mode: 'simple',
};

/* ── tiny helpers ─────────────────────────────────────────── */

async function api(path, body) {
  const options = { headers: { 'X-GUI-Token': TOKEN } };
  if (body !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const detail = (data && data.errors && data.errors.length) ? data.errors.join('；')
      : (data && data.error) || `请求失败 (HTTP ${response.status})`;
    const error = new Error(detail);
    error.payload = data;
    throw error;
  }
  return data;
}

async function apiRaw(path) {
  return fetch(path, { headers: { 'X-GUI-Token': TOKEN } });
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function formatBytes(bytes) {
  let value = Number(bytes) || 0;
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

function formatDuration(seconds) {
  if (!isFinite(seconds) || seconds < 0) return '—';
  const total = Math.floor(seconds);
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return `${minutes}m ${String(rest).padStart(2, '0')}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, '0')}m`;
}

function clockOf(ts) {
  if (!ts) return '';
  const date = new Date(ts * 1000);
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function toast(message, kind = 'info') {
  const wrap = $('toasts');
  const el = document.createElement('div');
  el.className = `toast is-${kind}`;
  const icon = document.createElement('svg');
  icon.setAttribute('class', 'icon');
  icon.innerHTML = `<use href="#${kind === 'err' ? 'i-x' : kind === 'ok' ? 'i-check' : 'i-info'}"/>`;
  const text = document.createElement('span');
  text.textContent = message;
  el.append(icon, text);
  wrap.append(el);
  setTimeout(() => {
    el.classList.add('is-out');
    setTimeout(() => el.remove(), 220);
  }, kind === 'err' ? 5200 : 3200);
}

/* ── configuration ────────────────────────────────────────── */

function defaultConfig() {
  const path = (APP.meta && APP.meta.defaultPath) || '';
  const template = (APP.meta && APP.meta.defaultTemplate) || '{service}/{creator_id}/{post_id}/{filename}';
  return {
    urls: '',
    batchFiles: [],
    path,
    templates: { attachments: template, content: template, json: template },
    templateSplit: false,
    restrictNames: false,
    noTmp: false,
    writeContent: false,
    writeJson: false,
    customVars: '',
    archive: '',
    dates: {
      date: { enabled: false, type: 'published', value: '' },
      datebefore: { enabled: false, type: 'published', value: '' },
      dateafter: { enabled: false, type: 'published', value: '' },
    },
    skipExtensions: [],
    skipAttachments: false,
    requestInterval: 1,
    cookies: [],
    logins: {
      kemono: { user: '', password: '' },
      coomer: { user: '', password: '' },
      pawchive: { user: '', password: '' },
    },
    favorite: { kemono: false, coomer: false, pawchive: false },
  };
}

function normalise(cfg) {
  const base = defaultConfig();
  const out = { ...base, ...cfg };
  out.templates = { ...base.templates, ...(cfg && cfg.templates) };
  out.dates = { ...base.dates, ...(cfg && cfg.dates) };
  out.logins = { ...base.logins, ...(cfg && cfg.logins) };
  out.favorite = { ...base.favorite, ...(cfg && cfg.favorite) };
  for (const key of ['batchFiles', 'cookies', 'skipExtensions']) {
    if (!Array.isArray(out[key])) out[key] = [];
  }
  return out;
}

function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return normalise(JSON.parse(raw));
  } catch { /* corrupted storage — fall through */ }
  return normalise(null);
}

const saveConfig = debounce(() => {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(collect())); } catch { /* quota */ }
}, 400);

function intervalValue() {
  const raw = $('requestInterval').value.trim();
  if (raw === '') return 1;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) return 1;
  return Math.min(60, value);
}

function collect() {
  return {
    urls: $('urls').value,
    batchFiles: [...APP.lists.batchFiles],
    path: $('outPath').value.trim(),
    templates: {
      attachments: APP.templates.attachments || $('templateInput').value,
      content: APP.templates.content || $('templateInput').value,
      json: APP.templates.json || $('templateInput').value,
    },
    templateSplit: $('swSplit').checked,
    restrictNames: $('swRestrict').checked,
    noTmp: $('swNoTmp').checked,
    writeContent: $('swWriteContent').checked,
    writeJson: $('swWriteJson').checked,
    customVars: $('customVars').value,
    archive: $('archivePath').value.trim(),
    dates: {
      date: dateOf('date'),
      datebefore: dateOf('datebefore'),
      dateafter: dateOf('dateafter'),
    },
    skipExtensions: [...APP.lists.skipExtensions],
    skipAttachments: $('swSkipAttachments').checked,
    requestInterval: intervalValue(),
    cookies: [...APP.lists.cookies],
    logins: {
      kemono: { user: $('kemonoUser').value.trim(), password: $('kemonoPass').value },
      coomer: { user: $('coomerUser').value.trim(), password: $('coomerPass').value },
      pawchive: { user: $('pawchiveUser').value.trim(), password: $('pawchivePass').value },
    },
    favorite: {
      kemono: $('favKemono').checked,
      coomer: $('favCoomer').checked,
      pawchive: $('favPawchive').checked,
    },
  };
}

function dateOf(key) {
  const row = document.querySelector(`.date-row[data-key="${key}"]`);
  if (!row) return { enabled: false, type: 'published', value: '' };
  return {
    enabled: row.querySelector('[data-role="enabled"]').checked,
    type: row.querySelector('[data-role="type"]').value,
    value: row.querySelector('[data-role="value"]').value,
  };
}

function applyConfig(cfg) {
  $('urls').value = cfg.urls || '';
  $('outPath').value = cfg.path || '';
  $('templateInput').value = cfg.templates.attachments || '';
  $('tAttachments').value = cfg.templates.attachments || '';
  $('tContent').value = cfg.templates.content || '';
  $('tJson').value = cfg.templates.json || '';
  APP.templates = { ...cfg.templates };
  $('swSplit').checked = !!cfg.templateSplit;
  $('splitFields').hidden = !cfg.templateSplit;
  $('swRestrict').checked = !!cfg.restrictNames;
  $('swNoTmp').checked = !!cfg.noTmp;
  $('swWriteContent').checked = !!cfg.writeContent;
  $('swWriteJson').checked = !!cfg.writeJson;
  $('swSkipAttachments').checked = !!cfg.skipAttachments;
  $('requestInterval').value = cfg.requestInterval === undefined ? 1 : cfg.requestInterval;
  $('customVars').value = cfg.customVars || '';
  $('archivePath').value = cfg.archive || '';
  APP.lists.batchFiles = [...cfg.batchFiles];
  APP.lists.cookies = [...cfg.cookies];
  APP.lists.skipExtensions = [...cfg.skipExtensions];

  $('favKemono').checked = !!cfg.favorite.kemono;
  $('favCoomer').checked = !!cfg.favorite.coomer;
  $('favPawchive').checked = !!cfg.favorite.pawchive;

  for (const site of ['kemono', 'coomer', 'pawchive']) {
    $(`${site}User`).value = cfg.logins[site].user || '';
    $(`${site}Pass`).value = cfg.logins[site].password || '';
  }

  for (const def of DATE_DEFS) {
    const row = document.querySelector(`.date-row[data-key="${def.key}"]`);
    const data = cfg.dates[def.key] || {};
    row.querySelector('[data-role="enabled"]').checked = !!data.enabled;
    row.querySelector('[data-role="type"]').value = data.type || 'published';
    row.querySelector('[data-role="value"]').value = data.value || '';
  }

  renderFileList('batchList', APP.lists.batchFiles, 'batchFiles');
  renderFileList('cookieList', APP.lists.cookies, 'cookies');
  renderExtChips();
  syncDateRows();
  syncLoginStates();
  syncTemplateMode();
  syncTitleNames();
}

/* ── rendering of dynamic bits ────────────────────────────── */

function renderFileList(containerId, items, listKey) {
  const box = $(containerId);
  box.textContent = '';
  for (const item of items) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const label = document.createElement('span');
    label.textContent = basename(item);
    label.title = item;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.title = '移除';
    remove.innerHTML = '<svg class="icon"><use href="#i-x"/></svg>';
    remove.addEventListener('click', (event) => {
      event.stopPropagation();
      APP.lists[listKey] = APP.lists[listKey].filter((entry) => entry !== item);
      renderFileList(containerId, APP.lists[listKey], listKey);
      changed();
    });
    chip.append(label, remove);
    box.append(chip);
  }
}

function renderExtChips() {
  const box = $('extChips');
  box.textContent = '';
  for (const ext of APP.lists.skipExtensions) {
    const chip = document.createElement('span');
    chip.className = 'chip is-static';
    const label = document.createElement('span');
    label.textContent = ext;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.title = '移除';
    remove.innerHTML = '<svg class="icon"><use href="#i-x"/></svg>';
    remove.addEventListener('click', () => {
      APP.lists.skipExtensions = APP.lists.skipExtensions.filter((item) => item !== ext);
      renderExtChips();
      changed();
    });
    chip.append(label, remove);
    box.append(chip);
  }
}

function basename(path) {
  if (!path) return '';
  const parts = String(path).split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

function syncDateRows() {
  document.querySelectorAll('.date-row').forEach((row) => {
    const on = row.querySelector('[data-role="enabled"]').checked;
    row.classList.toggle('is-on', on);
    row.querySelector('[data-role="type"]').disabled = !on;
    row.querySelector('[data-role="value"]').disabled = !on;
  });
}

function syncLoginStates() {
  for (const site of ['kemono', 'coomer', 'pawchive']) {
    const state = document.querySelector(`.login-state[data-state="${site}"]`);
    if (!state) continue;
    const user = $(`${site}User`).value.trim();
    const pass = $(`${site}Pass`).value;
    let text = '未填写';
    let cls = '';
    if (user && pass) { text = '已填写'; cls = 'is-set'; }
    else if (user || pass) { text = '不完整'; }
    state.textContent = text;
    state.className = `login-state ${cls}`;
  }
}

function syncTemplateMode() {
  const split = $('swSplit').checked;
  $('splitFields').hidden = !split;
  $('templateInput').disabled = split;
  if (split) {
    if (!APP.templates.content) APP.templates.content = APP.templates.attachments;
    if (!APP.templates.json) APP.templates.json = APP.templates.attachments;
    if (!$('tContent').value) $('tContent').value = APP.templates.content;
    if (!$('tJson').value) $('tJson').value = APP.templates.json;
    if (!$('tAttachments').value) $('tAttachments').value = APP.templates.attachments;
  }
}

function renderVarChips() {
  const box = $('varChips');
  box.textContent = '';
  const available = (APP.meta && APP.meta.sampleVariables) || VAR_ORDER;
  const ordered = [...VAR_ORDER, ...available.filter((name) => !VAR_ORDER.includes(name))];
  for (const name of ordered) {
    if (!available.includes(name)) continue;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = `{${name}}`;
    chip.title = '点击插入模板';
    chip.addEventListener('click', () => insertVariable(name));
    box.append(chip);
  }
}

function insertVariable(name) {
  const target = (APP.lastTemplateInput && !APP.lastTemplateInput.disabled)
    ? APP.lastTemplateInput
    : ($('swSplit').checked ? $('tAttachments') : $('templateInput'));
  if (!target || target.disabled) return;
  const start = target.selectionStart ?? target.value.length;
  const end = target.selectionEnd ?? start;
  const token = `{${name}}`;
  target.value = target.value.slice(0, start) + token + target.value.slice(end);
  target.focus();
  target.setSelectionRange(start + token.length, start + token.length);
  changed();
}

function renderPresets() {
  const select = $('presetSelect');
  select.textContent = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = '预设…';
  select.append(placeholder);
  TEMPLATE_PRESETS.forEach(([label, value], index) => {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = label;
    option.dataset.template = value;
    select.append(option);
  });
}

function renderPathPresets() {
  const box = $('pathPresets');
  box.textContent = '';
  if (!APP.meta) return;
  const repo = APP.meta.repoRoot || '';
  const choices = [
    ['默认目录', APP.meta.defaultPath],
    ['项目内 downloads', `${repo}\\downloads`],
    ['项目目录', repo],
  ];
  for (const [label, value] of choices) {
    if (!value) continue;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = label;
    chip.title = value;
    chip.addEventListener('click', () => {
      $('outPath').value = value;
      changed();
    });
    box.append(chip);
  }
}

function renderDateRows() {
  const box = $('dateRows');
  box.textContent = '';
  for (const def of DATE_DEFS) {
    const row = document.createElement('div');
    row.className = 'date-row';
    row.dataset.key = def.key;

    const toggle = document.createElement('label');
    toggle.className = 'switch-row';
    toggle.innerHTML = `<input type="checkbox" data-role="enabled"><span class="switch"></span>
      <span class="switch-text"><b>${def.label}</b><em>${def.hint}</em></span>`;

    const type = document.createElement('select');
    type.className = 'select';
    type.dataset.role = 'type';
    for (const [value, label] of DATE_TYPES) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label;
      type.append(option);
    }

    const value = document.createElement('input');
    value.type = 'date';
    value.className = 'input';
    value.dataset.role = 'value';
    value.title = def.desc;

    row.append(toggle, type, value);
    box.append(row);
  }
}

/* ── meta / status ────────────────────────────────────────── */

function applyMeta() {
  const meta = APP.meta;
  if (!meta) return;
  $('badgeVersion').textContent = `v${meta.version}`;
  $('badgeVersion').title = `kemono-dl ${meta.version} · GUI ${meta.guiVersion}`;
  const deps = $('badgeDeps');
  deps.textContent = meta.frozen ? '便携版' : (meta.hasRequests ? '依赖就绪' : '缺少 requests');
  deps.className = `badge ${meta.frozen || meta.hasRequests ? 'badge-ok' : 'badge-warn'}`;
  $('depsBanner').hidden = !!meta.hasRequests || !!meta.frozen;

  $('aboutVersion').textContent = meta.version;
  $('aboutGui').textContent = meta.guiVersion;
  $('aboutPython').textContent = meta.frozen ? `${meta.pythonVersion}（内置，无需安装）` : meta.pythonVersion;
  $('aboutDeps').textContent = meta.frozen ? '已内置' : (meta.hasRequests ? '已安装' : '未安装');
  $('aboutPythonPath').textContent = meta.frozen ? '打包在 exe 内部，宿主机无需 Python' : meta.python;
  $('aboutRepo').textContent = meta.repoRoot;
  $('aboutDepsBanner').hidden = !!meta.hasRequests || !!meta.frozen;

  renderVarChips();
  renderPathPresets();
}

async function refreshMeta() {
  try {
    APP.meta = await api('/api/meta');
    applyMeta();
    setConnection(true);
  } catch (error) {
    setConnection(false, error.message);
  }
}

function setConnection(ok, message) {
  const pill = $('connPill');
  pill.innerHTML = '';
  const dot = document.createElement('i');
  dot.className = `dot ${ok ? 'dot-ok' : 'dot-err'}`;
  const text = document.createElement('span');
  text.textContent = ok ? '本地服务已连接' : (message || '本地服务已断开');
  pill.append(dot, text);
}

/* ── preview + validation ─────────────────────────────────── */

async function refreshPreviewAndValidate() {
  const config = collect();
  try {
    const [preview, validation] = await Promise.all([
      api('/api/preview', config),
      api('/api/validate', config),
    ]);
    applyPreview(preview);
    applyValidation(validation);
    setConnection(true);
  } catch (error) {
    $('errorMsg').textContent = error.message;
    $('btnStart').disabled = true;
  }
}

function applyPreview(preview) {
  const map = { attachments: 'previewAttachments', content: 'previewContent', json: 'previewJson' };
  for (const [type, id] of Object.entries(map)) {
    const value = preview.paths ? preview.paths[type] : null;
    const el = $(id);
    el.classList.remove('is-err');
    if (!value) { el.textContent = '—'; continue; }
    if (typeof value === 'string') { el.textContent = value; }
    else if (value.error) { el.textContent = value.error; el.classList.add('is-err'); }
    else { el.textContent = JSON.stringify(value); }
  }

  const msg = $('customVarsMsg');
  const errors = (preview.errors || []).filter((item) => String(item).includes('自定义变量'));
  if (errors.length) {
    msg.textContent = errors.join('；');
    msg.className = 'msg is-err';
  } else if ($('customVars').value.trim()) {
    try {
      const parsed = JSON.parse($('customVars').value);
      const count = parsed && typeof parsed === 'object' ? Object.keys(parsed).length : 0;
      msg.textContent = `已定义 ${count} 个变量`;
      msg.className = 'msg is-ok';
    } catch {
      msg.textContent = 'JSON 尚未写完…';
      msg.className = 'msg';
    }
  } else {
    msg.textContent = '';
    msg.className = 'msg';
  }
}

function applyValidation(validation) {
  $('cmdPreview').textContent = validation.command || 'kemono-dl …';
  $('cmdPreview').title = validation.command || '';
  const errors = validation.errors || [];
  const warnings = validation.warnings || [];
  $('errorMsg').textContent = errors.length ? errors[0] : '';
  $('errorMsg').title = errors.join('\n');
  $('warnMsg').textContent = warnings.length ? warnings[0] : '';
  $('warnMsg').title = warnings.join('\n');
  $('btnStart').disabled = errors.length > 0;
  $('swSplit').closest('.card').querySelectorAll('.preview-line code').forEach((el) => {
    /* preview errors are already coloured by applyPreview */
  });
}

const scheduleRefresh = debounce(() => { refreshPreviewAndValidate(); }, 320);

function changed() {
  saveConfig();
  renderExtChips();
  syncLoginStates();
  scheduleRefresh();
}

/* ── uploads ──────────────────────────────────────────────── */

async function uploadFiles(fileList, listKey, accept) {
  const files = [...fileList].filter((file) => !accept || accept.test(file.name));
  if (!files.length) { toast('没有可用的文件', 'err'); return; }
  for (const file of files) {
    try {
      const text = await file.text();
      const result = await api('/api/upload', { filename: file.name, content: text });
      if (!APP.lists[listKey].includes(result.path)) APP.lists[listKey].push(result.path);
      toast(`已添加 ${file.name}`, 'ok');
    } catch (error) {
      toast(`读取 ${file.name} 失败：${error.message}`, 'err');
    }
  }
  renderFileList(listKey === 'cookies' ? 'cookieList' : 'batchList', APP.lists[listKey], listKey);
  changed();
}

function wireDropzone(zoneId, inputId, listKey, accept) {
  const zone = $(zoneId);
  const input = $(inputId);
  input.addEventListener('change', () => {
    uploadFiles(input.files, listKey, accept);
    input.value = '';
  });
  ['dragenter', 'dragover'].forEach((type) => {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.add('is-over');
    });
  });
  ['dragleave', 'drop'].forEach((type) => {
    zone.addEventListener(type, (event) => {
      event.preventDefault();
      zone.classList.remove('is-over');
    });
  });
  zone.addEventListener('drop', (event) => {
    if (event.dataTransfer && event.dataTransfer.files.length) {
      uploadFiles(event.dataTransfer.files, listKey, accept);
    }
  });
  zone.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      input.click();
    }
  });
}

/* ── jobs ─────────────────────────────────────────────────── */

async function startJob(configOverride) {
  const config = configOverride || collect();
  $('btnStart').disabled = true;
  try {
    const result = await api('/api/run', config);
    if (result.job) {
      toast(`已加入队列：${result.job.title}`, 'ok');
      selectJob(result.job.id, true);
      if (result.warnings && result.warnings.length) {
        setTimeout(() => toast(result.warnings[0], 'info'), 400);
      }
    }
    await tick();
  } catch (error) {
    const payload = error.payload || {};
    const messages = (payload.errors && payload.errors.length) ? payload.errors : [error.message];
    $('errorMsg').textContent = messages[0];
    $('errorMsg').title = messages.join('\n');
    toast(messages[0], 'err');
    if (payload.errors && payload.errors.length > 1) {
      messages.slice(1, 3).forEach((message, index) => {
        setTimeout(() => toast(message, 'err'), 300 * (index + 1));
      });
    }
  } finally {
    $('btnStart').disabled = false;
    refreshPreviewAndValidate();
  }
}

function selectJob(jobId, resetLog) {
  if (APP.selectedJobId !== jobId || resetLog) {
    APP.selectedJobId = jobId;
    APP.since = 0;
    if (resetLog) {
      APP.logs.delete(jobId);
      clearLog();
    }
  }
}

function clearLog() {
  const box = $('logBox');
  box.textContent = '';
  const empty = document.createElement('div');
  empty.className = 'log-empty';
  empty.id = 'logEmpty';
  empty.textContent = '输出会显示在这里…';
  box.append(empty);
}

function jobSignature(jobs) {
  return jobs.map((job) => `${job.id}:${job.status}:${job.lineCount}:${Math.round(job.progress.percent)}`).join('|');
}

function renderJobs(jobs) {
  const signature = jobSignature(jobs) + `#${APP.selectedJobId}`;
  if (signature === APP.lastJobSignature) return;
  APP.lastJobSignature = signature;

  const list = $('jobList');
  list.textContent = '';
  if (!jobs.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.id = 'jobEmpty';
    empty.innerHTML = `<svg class="icon"><use href="#i-download"/></svg>
      <p>还没有任务</p><span>填好左侧表单后点击「开始下载」</span>`;
    list.append(empty);
    $('jobDetail').hidden = true;
    return;
  }
  $('jobDetail').hidden = false;

  for (const job of jobs) {
    const item = document.createElement('div');
    item.className = `job-item is-${job.status}${job.id === APP.selectedJobId ? ' is-active' : ''}`;
    item.dataset.jobId = job.id;

    const dot = document.createElement('i');
    dot.className = 'job-item-dot';

    const main = document.createElement('div');
    main.className = 'job-item-main';
    const title = document.createElement('div');
    title.className = 'job-item-title';
    title.textContent = job.title;
    title.title = job.command || job.title;
    const sub = document.createElement('div');
    sub.className = 'job-item-sub';
    sub.textContent = subLabel(job);
    main.append(title, sub);

    const time = document.createElement('span');
    time.className = 'job-item-time';
    time.textContent = clockOf(job.finishedAt || job.startedAt || job.createdAt);

    item.append(dot, main, time);
    item.addEventListener('click', () => {
      selectJob(job.id, true);
      APP.lastJobSignature = '';
      tick();
    });
    list.append(item);
  }
}

function subLabel(job) {
  if (job.status === 'running') {
    const p = job.progress;
    const parts = [`${(p.percent || 0).toFixed(1)}%`];
    if (p.posts) parts.push(`${p.posts} 帖`);
    if (p.files) parts.push(`${p.files} 文件`);
    if (p.speed) parts.push(p.speed);
    return parts.join(' · ');
  }
  if (job.status === 'queued') return '等待中…';
  if (job.status === 'done') return `完成 · ${job.progress.files || 0} 个文件`;
  if (job.status === 'failed') return `退出码 ${job.exitCode ?? '?'}`;
  if (job.status === 'stopped') return '已停止';
  return job.status;
}

function renderSelectedJob(job) {
  if (!job) { $('jobDetail').hidden = true; return; }
  $('jobDetail').hidden = false;
  $('jobDetail').classList.toggle('is-running', job.status === 'running');

  $('jobTitle').textContent = job.title;
  $('jobTitle').title = job.command || '';

  const chip = $('jobStatus');
  chip.textContent = STATUS_LABELS[job.status] || job.status;
  chip.className = `status-chip is-${job.status}`;

  const percent = Math.max(0, Math.min(100, job.progress.percent || 0));
  const bar = $('jobProgressBar');
  const indeterminate = job.status === 'running' && percent <= 0.01;
  bar.classList.toggle('is-indeterminate', indeterminate);
  bar.style.width = indeterminate ? '' : `${percent}%`;

  $('jobPercent').textContent = indeterminate
    ? '准备中…'
    : `${percent.toFixed(1)}%${job.progress.total ? ` · ${job.progress.total}` : ''}`;
  const done = job.progress.downloaded || 0;
  const left = job.progress.remaining || 0;
  const skipped = job.progress.skipped || 0;
  const skipNote = skipped ? ` · 跳过 ${skipped}` : '';
  $('jobSize').textContent = done ? `已下载 ${formatBytes(done)}${skipNote}` : (skipped ? `跳过 ${skipped}` : '—');
  $('jobSpeed').textContent = job.progress.speed || '—';
  $('jobEta').textContent = job.progress.eta ? `剩余 ${job.progress.eta}` : '—';

  $('jobPosts').textContent = job.progress.posts || 0;
  $('jobFiles').textContent = job.progress.files || 0;
  const pending = job.progress.pending || 0;
  $('jobPending').textContent = job.status === 'done' ? 0 : pending;
  $('jobRemaining').textContent = left > 0 ? `≈${formatBytes(left)}` : '—';
  $('jobRemaining').title = left > 0
    ? `按已完成文件的平均大小估算${job.progress.bytesPerFile ? `（平均 ${formatBytes(job.progress.bytesPerFile)}/个）` : ''}`
    : '';
  const start = job.startedAt || job.createdAt;
  const end = job.finishedAt || (job.startedAt ? Date.now() / 1000 : null);
  $('jobElapsed').textContent = end ? formatDuration(end - start) : '—';

  $('btnStop').disabled = !(job.status === 'running' || job.status === 'queued');
  $('btnRetry').disabled = !(job.status === 'failed' || job.status === 'stopped' || job.status === 'done');

  renderFailures(job.failures || []);
}

/**
 * 失败的附件连同「它属于哪个帖子」一起列出来。
 * 只给文件链接没用 —— 用户要能点回帖子，才知道是哪一篇没下全。
 */
function renderFailures(failures) {
  APP.jobFailures = failures;
  const block = $('failureBlock');
  block.hidden = failures.length === 0;
  if (!failures.length) return;
  $('failureCount').textContent = failures.length;

  const list = $('failureList');
  list.textContent = '';
  const grouped = new Map();
  for (const item of failures) {
    const key = item.postUrl || '';
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(item);
  }
  for (const [postUrl, items] of grouped) {
    const li = document.createElement('li');
    const head = document.createElement('div');
    head.className = 'failure-post';
    if (postUrl) {
      const link = document.createElement('a');
      link.href = postUrl;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = postUrl;
      link.title = '打开帖子页面';
      head.append(link);
    } else {
      head.append(document.createTextNode('（未知帖子）'));
    }
    li.append(head);
    for (const item of items) {
      const row = document.createElement('div');
      row.className = 'failure-file';
      const name = item.fileUrl ? item.fileUrl.split('f=').pop() : '';
      const label = document.createElement('span');
      label.textContent = name ? decodeURIComponent(name) : item.fileUrl || '—';
      label.title = item.fileUrl || '';
      const why = document.createElement('em');
      why.textContent = `${item.message || '失败'} · 第 ${item.attempt || 1}/${item.total || 1} 次`;
      row.append(label, why);
      li.append(row);
    }
    list.append(li);
  }
}

/* ── log ──────────────────────────────────────────────────── */

const LOG_RULES = [
  [/^\[Error\]/i, 'is-err'],
  [/^\[warning\]/i, 'is-warn'],
  [/^\[info\]/i, 'is-info'],
  [/^\[skip\]/i, 'is-skip'],
  [/^\[writing\]/i, 'is-write'],
  [/^\[gui\]/i, 'is-gui'],
  [/^\[downloading\]\s+Destination:/i, 'is-ok'],
  [/^\[downloading\]\s+Resuming/i, 'is-skip'],
  [/^\[downloading\]\s+\d/, 'is-progress'],
];

function classify(line) {
  for (const [pattern, cls] of LOG_RULES) {
    if (pattern.test(line)) return cls;
  }
  return '';
}

function appendLines(jobId, lines) {
  if (!lines.length) return;
  const box = $('logBox');
  const empty = $('logEmpty');
  if (empty) empty.remove();

  let cache = APP.logs.get(jobId);
  if (!cache) { cache = []; APP.logs.set(jobId, cache); }

  const fragment = document.createDocumentFragment();
  for (const line of lines) {
    if (!line.trim()) continue;
    cache.push(line);
    const cls = classify(line);
    if (cls === 'is-progress') {
      const last = box.lastElementChild;
      if (last && last.classList.contains('is-progress')) {
        last.lastElementChild.textContent = line.replace(/^\[downloading\]\s*/, '');
        continue;
      }
    }
    const el = document.createElement('div');
    el.className = `log-line ${cls}`.trim();
    const marker = document.createElement('i');
    marker.className = 'marker';
    const text = document.createElement('span');
    text.className = 'text';
    text.textContent = line;
    el.append(marker, text);
    fragment.append(el);
  }
  if (cache.length > 5000) cache.splice(0, cache.length - 5000);
  box.append(fragment);

  while (box.childElementCount > 900) box.firstElementChild.remove();

  if ($('autoScroll').checked) box.scrollTop = box.scrollHeight;
}

/* ── polling ──────────────────────────────────────────────── */

async function tick() {
  const params = new URLSearchParams({ since: String(APP.since) });
  if (APP.selectedJobId) params.set('job', APP.selectedJobId);
  let data;
  try {
    data = await api(`/api/state?${params}`);
    APP.failures = 0;
    setConnection(true);
  } catch (error) {
    APP.failures += 1;
    setConnection(false, APP.failures > 2 ? '本地服务已断开' : '正在重连…');
    return;
  }

  renderJobs(data.jobs || []);

  if (!APP.selectedJobId) {
    const active = (data.jobs || []).find((job) => job.status === 'running' || job.status === 'queued');
    if (active) { APP.selectedJobId = active.id; APP.since = 0; }
  }

  const job = data.job;
  if (job && job.id !== APP.selectedJobId) {
    APP.selectedJobId = job.id;
    APP.since = 0;
    clearLog();
  }
  if (job) {
    renderSelectedJob(job);
    announceFailures(job);
    if (typeof data.base === 'number') {
      APP.since = data.base + (data.lines ? data.lines.length : 0);
    }
    appendLines(job.id, data.lines || []);
  } else if (!APP.selectedJobId) {
    $('jobDetail').hidden = true;
  }

  const running = (data.jobs || []).some((item) => item.status === 'running' || item.status === 'queued');
  APP.running = running;
  const delay = APP.failures ? 3000 : (running ? 700 : 1500);
  schedulePoll(delay);
}

function schedulePoll(delay) {
  clearTimeout(APP.pollTimer);
  APP.pollTimer = setTimeout(tick, delay);
}

/**
 * 任务结束后如果还有失败的文件，主动提示一次，并把失败清单亮出来。
 * 只提示一次，避免每次轮询都弹。
 */
function announceFailures(job) {
  const count = (job.failures || []).length;
  const finished = job.status === 'done' || job.status === 'failed';
  if (!count || !finished) return;
  if (APP.announcedFailures === job.id) return;
  APP.announcedFailures = job.id;
  toast(`${count} 个文件下载失败，已在任务详情里列出对应帖子链接`, 'warn');
}

/* ── filesystem picker ────────────────────────────────────── */

async function openFsModal(mode, startPath, callback, title) {
  APP.fsMode = mode;
  APP.fsCallback = callback;
  APP.fsSelectedFile = null;
  $('fsModal').querySelector('h3').textContent = title || (mode === 'file' ? '选择文件' : '选择文件夹');
  $('fsHint').textContent = mode === 'file' ? '点击文件选中，或直接输入完整路径' : '进入目标文件夹后点击「选择此文件夹」';
  $('fsChoose').textContent = mode === 'file' ? '使用此路径' : '选择此文件夹';
  $('fsModal').hidden = false;
  await loadFs(startPath || $('outPath').value || '');
}

async function loadFs(path) {
  try {
    const query = new URLSearchParams({ path: path || '' });
    if (APP.fsMode === 'file') query.set('files', '1');
    const data = await api(`/api/fs?${query}`);
    APP.fsState = data;
    renderFs(data);
  } catch (error) {
    toast(error.message, 'err');
  }
}

function renderFs(data) {
  $('fsPath').value = data.path || '';
  const drives = $('fsDrives');
  drives.textContent = '';
  for (const drive of data.drives || []) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'fs-drive';
    btn.textContent = drive;
    btn.addEventListener('click', () => loadFs(drive));
    drives.append(btn);
  }

  const list = $('fsList');
  list.textContent = '';

  if (data.parent) {
    const up = document.createElement('div');
    up.className = 'fs-row is-up';
    up.innerHTML = '<svg class="icon"><use href="#i-chevron"/></svg>';
    up.querySelector('.icon').style.transform = 'rotate(180deg)';
    const label = document.createElement('span');
    label.textContent = '返回上一级';
    up.append(label);
    up.addEventListener('click', () => loadFs(data.parent));
    list.append(up);
  }

  for (const dir of data.dirs || []) {
    const row = document.createElement('div');
    row.className = 'fs-row';
    row.innerHTML = '<svg class="icon"><use href="#i-folder"/></svg>';
    const label = document.createElement('span');
    label.textContent = dir.name;
    row.append(label);
    row.addEventListener('click', () => {
      list.querySelectorAll('.fs-row').forEach((item) => item.classList.remove('is-active'));
      list.append();
      renderFsSelection(null);
      loadFs(dir.path);
    });
    list.append(row);
  }

  if (APP.fsMode === 'file') {
    for (const file of data.files || []) {
      const row = document.createElement('div');
      row.className = 'fs-row fs-file';
      row.innerHTML = '<svg class="icon"><use href="#i-file"/></svg>';
      const label = document.createElement('span');
      label.textContent = file.name;
      row.append(label);
      row.addEventListener('click', () => {
        list.querySelectorAll('.fs-row').forEach((item) => item.classList.remove('is-active'));
        row.classList.add('is-active');
        APP.fsSelectedFile = file.path;
        $('fsPath').value = file.path;
      });
      row.addEventListener('dblclick', () => {
        APP.fsSelectedFile = file.path;
        chooseFs();
      });
      list.append(row);
    }
  }

  if (!(data.dirs || []).length && !(data.files || []).length) {
    const empty = document.createElement('div');
    empty.className = 'fs-empty';
    empty.textContent = data.error ? `无法读取：${data.error}` : '此文件夹是空的';
    list.append(empty);
  }
}

function renderFsSelection() { /* reserved for future multi-select */ }

function chooseFs() {
  if (!APP.fsState) return;
  let chosen;
  if (APP.fsMode === 'file') {
    const typed = $('fsPath').value.trim();
    chosen = APP.fsSelectedFile || typed;
    if (!chosen) { toast('请选择或输入一个文件路径', 'err'); return; }
  } else {
    chosen = APP.fsState.path;
  }
  if (typeof APP.fsCallback === 'function') APP.fsCallback(chosen);
  closeFsModal();
}

function closeFsModal() {
  $('fsModal').hidden = true;
  APP.fsSelectedFile = null;
}

/* ── modals & theme ───────────────────────────────────────── */

function openAbout() {
  $('aboutModal').hidden = false;
  refreshMeta();
}

function closeModals() {
  $('aboutModal').hidden = true;
  $('settingsModal').hidden = true;
  $('historyModal').hidden = true;
  closeFsModal();
}

/* ── download history ─────────────────────────────────────── */

function formatStamp(seconds) {
  if (!seconds) return '—';
  const date = new Date(seconds * 1000);
  const pad = (value) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function renderHistory(data) {
  const rows = $('historyRows');
  rows.textContent = '';
  const creators = (data && data.creators) || [];
  $('historyEmpty').hidden = creators.length > 0;
  $('historySummary').textContent = creators.length
    ? `${creators.length} 位作者 · ${data.posts} 篇帖子`
    : '';
  $('historyPath').textContent = data && data.path
    ? `${data.portable === false ? '记录文件（程序目录不可写，已改存到用户数据目录）：' : '记录文件（与程序同目录）：'}${data.path}`
    : '';

  for (const creator of creators) {
    const tr = document.createElement('tr');

    const author = document.createElement('td');
    const name = document.createElement('b');
    name.textContent = creator.creatorId;
    const site = document.createElement('em');
    site.className = 'muted';
    site.textContent = [creator.site, creator.service].filter(Boolean).join(' · ');
    author.append(name, document.createElement('br'), site);

    const posts = document.createElement('td');
    posts.textContent = String(creator.posts);
    if (creator.failures) {
      const bad = document.createElement('em');
      bad.className = 'muted';
      bad.textContent = ` · ${creator.failures} 失败`;
      posts.append(bad);
    }

    const last = document.createElement('td');
    last.textContent = formatStamp(creator.lastTs);

    const latest = document.createElement('td');
    if (creator.latest && creator.latest.url) {
      const link = document.createElement('a');
      link.href = creator.latest.url;
      link.target = '_blank';
      link.rel = 'noreferrer';
      link.textContent = creator.latest.title || creator.latest.postId || '帖子';
      link.title = creator.latest.url;
      latest.append(link);
    } else {
      latest.textContent = '—';
    }

    tr.append(author, posts, last, latest);
    rows.append(tr);
  }
}

function refreshHistory() {
  return api('/api/history')
    .then(renderHistory)
    .catch((error) => toast(`下载记录读取失败：${error.message}`, 'error'));
}

function openHistory() {
  $('historyModal').hidden = false;
  refreshHistory();
}

function exportHistory() {
  apiRaw('/api/history/export')
    .then((response) => {
      if (!response.ok) throw new Error(`导出失败 (HTTP ${response.status})`);
      return response.blob();
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'kemono-dl-history.csv';
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      toast('已导出 CSV', 'ok');
    })
    .catch((error) => toast(`导出失败：${error.message}`, 'error'));
}

function clearHistory() {
  if (!window.confirm('清空下载记录？只删除记录，已下载的文件不受影响。')) return;
  api('/api/history/clear', {})
    .then((data) => {
      renderHistory(data.history || { creators: [], posts: 0 });
      toast('下载记录已清空', 'ok');
    })
    .catch((error) => toast(`清空失败：${error.message}`, 'error'));
}

function copyFailures() {
  const failures = APP.jobFailures || [];
  if (!failures.length) return;
  const lines = [];
  const seen = new Set();
  for (const item of failures) {
    const key = item.postUrl || item.fileUrl;
    if (seen.has(key)) continue;
    seen.add(key);
    lines.push(item.postUrl || '(未知帖子)');
  }
  navigator.clipboard.writeText(lines.join('\n'))
    .then(() => toast(`已复制 ${lines.length} 条帖子链接`, 'ok'))
    .catch(() => toast('复制失败，请手动选择链接', 'error'));
}

function quitApp() {
  const running = APP.running;
  const question = running
    ? '当前还有下载任务在运行，退出会先停止它。确定退出吗？'
    : '退出后本页面将断开连接，需要重新双击 kemono-dl-gui.exe 才能再次打开。确定退出吗？';
  if (!window.confirm(question)) return;
  const farewell = () => {
    if (APP.pollTimer) clearInterval(APP.pollTimer);
    if (APP.refreshTimer) clearTimeout(APP.refreshTimer);
    APP.pollTimer = null;
    APP.refreshTimer = null;
    document.body.classList.add('is-quit');
    $('quitOverlay').hidden = false;
  };
  api('/api/quit', {}).then(farewell).catch(farewell);
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  const icon = $('themeIcon').querySelector('use');
  icon.setAttribute('href', theme === 'dark' ? '#i-sun' : '#i-moon');
  $('themeLabel').textContent = theme === 'dark' ? '浅色主题' : '深色主题';
  const settingsThemeLabel = $('settingsThemeLabel');
  if (settingsThemeLabel) settingsThemeLabel.textContent = theme === 'dark' ? '切换浅色主题' : '切换深色主题';
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* ignore */ }
}

function initTheme() {
  let theme = 'dark';
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored) theme = stored;
    else if (window.matchMedia('(prefers-color-scheme: light)').matches) theme = 'light';
  } catch { /* ignore */ }
  applyTheme(theme);
}

/* ── 简单模式 / 专业模式 ─────────────────────────────────── */

const TITLE_TEMPLATE = '{service}/{creator_id}/{post_title}/{filename}';
const TITLE_ID_TEMPLATE = '{service}/{creator_id}/{post_title} [{post_id}]/{filename}';
const FALLBACK_TEMPLATE = '{service}/{creator_id}/{post_id}/{filename}';

const SAMPLE_VARS = {
  service: 'patreon',
  creator_id: '12345',
  creator_name: 'Some Creator',
  post_id: '67890',
  post_title: '限定・ステッカー セット',
  filename: 'attachment.png',
  file_name: 'attachment',
  file_ext: 'png',
  server_filename: 'ke20190416_1.jpg',
  index: '1',
};

function activeTemplate() {
  if ($('swSplit').checked) return ($('tAttachments').value || '').trim();
  return ($('templateInput').value || '').trim();
}

function previewPathFor(template) {
  const source = (template || '').trim() || FALLBACK_TEMPLATE;
  const rendered = source.replace(/\{([a-z_]+)\}/g, (whole, name) => (
    Object.prototype.hasOwnProperty.call(SAMPLE_VARS, name) ? SAMPLE_VARS[name] : whole
  ));
  return rendered.replace(/[\\/]+/g, '/').replace(/^\/+/, '');
}

function syncTitleNames() {
  const template = activeTemplate();
  const on = template === TITLE_TEMPLATE || template === TITLE_ID_TEMPLATE;
  const toggle = $('swTitleNames');
  if (toggle) toggle.checked = on;
  const preview = $('simpleNamePreview');
  if (preview) preview.textContent = previewPathFor(template);
}

function applyMode(mode, persist = true) {
  const next = mode === 'pro' ? 'pro' : 'simple';
  APP.mode = next;
  document.body.dataset.mode = next;
  const pillText = $('modePillText');
  if (pillText) pillText.textContent = next === 'pro' ? '专业模式' : '简单模式';
  const pill = $('modePill');
  if (pill) pill.title = next === 'pro' ? '当前：专业模式 · 点击打开设置' : '当前：简单模式 · 点击打开设置';
  const toggle = $('swProMode');
  if (toggle) toggle.checked = next === 'pro';
  if (persist) {
    try { localStorage.setItem(MODE_KEY, next); } catch { /* ignore */ }
  }
  syncTitleNames();
}

function loadMode() {
  try {
    const stored = localStorage.getItem(MODE_KEY);
    if (stored === 'pro' || stored === 'simple') return stored;
  } catch { /* ignore */ }
  return 'simple';
}

function openSettings() {
  $('settingsModal').hidden = false;
}

/* ── wiring ───────────────────────────────────────────────── */

function wireEvents() {
  const textIds = ['urls', 'outPath', 'templateInput', 'tAttachments', 'tContent', 'tJson',
    'customVars', 'archivePath', 'kemonoUser', 'kemonoPass', 'coomerUser', 'coomerPass',
    'pawchiveUser', 'pawchivePass', 'requestInterval'];
  for (const id of textIds) {
    const el = $(id);
    el.addEventListener('input', () => {
      if (id.startsWith('t') || id === 'templateInput') {
        APP.templates = {
          attachments: $('swSplit').checked ? $('tAttachments').value : $('templateInput').value,
          content: $('tContent').value || (APP.meta ? APP.meta.defaultTemplate : ''),
          json: $('tJson').value || (APP.meta ? APP.meta.defaultTemplate : ''),
        };
      }
      changed();
      if (id === 'templateInput' || id.startsWith('t')) syncTitleNames();
    });
    el.addEventListener('focus', () => {
      if (['templateInput', 'tAttachments', 'tContent', 'tJson'].includes(id)) APP.lastTemplateInput = el;
    });
  }

  const boolIds = ['swRestrict', 'swNoTmp', 'swWriteContent', 'swWriteJson', 'swSkipAttachments',
    'swSplit', 'favKemono', 'favCoomer', 'favPawchive'];
  for (const id of boolIds) {
    $(id).addEventListener('change', () => {
      if (id === 'swSplit') {
        syncTemplateMode();
        APP.templates.attachments = $('templateInput').value;
      }
      changed();
    });
  }

  $('presetSelect').addEventListener('change', (event) => {
    const option = event.target.selectedOptions[0];
    if (!option || !option.dataset.template) return;
    $('templateInput').value = option.dataset.template;
    if (!$('swSplit').checked) {
      APP.templates = { attachments: option.dataset.template, content: option.dataset.template, json: option.dataset.template };
    } else {
      $('tAttachments').value = option.dataset.template;
      APP.templates.attachments = option.dataset.template;
    }
    event.target.value = '';
    syncTitleNames();
    changed();
  });

  $('extInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ',') {
      event.preventDefault();
      const raw = event.target.value.trim().replace(/^\./, '').toLowerCase();
      if (raw) {
        const parts = raw.split(/[,，\s]+/).filter(Boolean);
        for (const part of parts) {
          if (!APP.lists.skipExtensions.includes(part)) APP.lists.skipExtensions.push(part);
        }
        event.target.value = '';
        renderExtChips();
        changed();
      }
    } else if (event.key === 'Backspace' && !event.target.value && APP.lists.skipExtensions.length) {
      event.preventDefault();
      APP.lists.skipExtensions.pop();
      renderExtChips();
      changed();
    }
  });
  $('extInput').addEventListener('blur', () => {
    const value = $('extInput').value.trim().replace(/^\./, '').toLowerCase();
    if (value) {
      for (const part of value.split(/[,，\s]+/).filter(Boolean)) {
        if (!APP.lists.skipExtensions.includes(part)) APP.lists.skipExtensions.push(part);
      }
      $('extInput').value = '';
      renderExtChips();
      changed();
    }
  });

  $('dateRows').addEventListener('change', (event) => {
    if (event.target.closest('.date-row')) {
      syncDateRows();
      changed();
    }
  });
  $('dateRows').addEventListener('input', (event) => {
    if (event.target.matches('[data-role="value"]')) changed();
  });

  $('btnClearUrls').addEventListener('click', () => { $('urls').value = ''; changed(); });
  $('browsePath').addEventListener('click', () => {
    openFsModal('dir', $('outPath').value, (path) => { $('outPath').value = path; changed(); });
  });
  $('openPath').addEventListener('click', () => openFolder($('outPath').value));
  $('browseArchive').addEventListener('click', () => {
    openFsModal('file', $('archivePath').value, (path) => { $('archivePath').value = path; changed(); }, '选择归档文件');
  });
  $('archiveInput').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    if (file) {
      try {
        const result = await api('/api/upload', { filename: file.name, content: await file.text() });
        $('archivePath').value = result.path;
        changed();
      } catch (error) { toast(error.message, 'err'); }
    }
    event.target.value = '';
  });

  wireDropzone('batchDrop', 'batchInput', 'batchFiles', /\.(txt|list)$/i);
  wireDropzone('cookieDrop', 'cookieInput', 'cookies', null);

  $('btnVarsExample').addEventListener('click', () => {
    $('customVars').value = '{\n  "titleTrunc": "\'{post_title}\'[:40]",\n  "publishedYear": "\'{published}\'[:4]"\n}';
    changed();
  });

  $('btnStart').addEventListener('click', () => startJob());
  $('btnCopyCmd').addEventListener('click', async () => {
    const text = $('cmdPreview').textContent;
    try {
      await navigator.clipboard.writeText(text);
      toast('已复制命令', 'ok');
    } catch {
      toast('复制失败，请手动选择文本', 'err');
    }
  });
  $('btnRefreshMeta').addEventListener('click', refreshMeta);
  $('btnClearJobs').addEventListener('click', async () => {
    try { await api('/api/clear', {}); APP.lastJobSignature = ''; tick(); } catch (error) { toast(error.message, 'err'); }
  });
  $('btnStop').addEventListener('click', async () => {
    if (!APP.selectedJobId) return;
    try { await api('/api/stop', { jobId: APP.selectedJobId }); toast('已发送停止信号', 'info'); } catch (error) { toast(error.message, 'err'); }
  });
  $('btnRetry').addEventListener('click', async () => {
    const jobs = APP.currentJobs || [];
    const job = jobs.find((item) => item.id === APP.selectedJobId);
    if (!job) return;
    startJob(job.config);
  });
  $('btnOpenTarget').addEventListener('click', () => {
    const jobs = APP.currentJobs || [];
    const job = jobs.find((item) => item.id === APP.selectedJobId);
    const path = (job && job.config && job.config.path) || $('outPath').value;
    openFolder(path);
  });
  $('btnSaveLog').addEventListener('click', () => {
    const jobId = APP.selectedJobId;
    const lines = (jobId && APP.logs.get(jobId)) || [];
    if (!lines.length) { toast('当前没有日志', 'err'); return; }
    const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `kemono-dl-${jobId || 'log'}.txt`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 2000);
  });

  $('openAbout').addEventListener('click', openAbout);
  $('openHistory').addEventListener('click', openHistory);
  $('btnHistoryExport').addEventListener('click', exportHistory);
  $('btnHistoryClear').addEventListener('click', clearHistory);
  $('btnCopyFailures').addEventListener('click', copyFailures);
  $('toggleTheme').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  $('btnInstallDeps').addEventListener('click', installDeps);
  $('btnInstallDeps2').addEventListener('click', installDeps);
  $('btnReset').addEventListener('click', () => {
    localStorage.removeItem(STORAGE_KEY);
    applyConfig(normalise(null));
    APP.lists = { batchFiles: [], cookies: [], skipExtensions: [] };
    renderFileList('batchList', [], 'batchFiles');
    renderFileList('cookieList', [], 'cookies');
    renderExtChips();
    changed();
    toast('已恢复默认设置', 'ok');
  });

  $('btnQuit').addEventListener('click', quitApp);

  $('openSettings').addEventListener('click', openSettings);
  $('modePill').addEventListener('click', openSettings);
  $('openSettingsLink').addEventListener('click', openSettings);
  $('settingsAbout').addEventListener('click', () => {
    $('settingsModal').hidden = true;
    openAbout();
  });
  $('settingsTheme').addEventListener('click', () => {
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  });
  $('swProMode').addEventListener('change', (event) => {
    applyMode(event.target.checked ? 'pro' : 'simple');
    $('settingsModal').hidden = true;
    toast(event.target.checked
      ? '已打开专业模式：全部选项都会显示。'
      : '已切回简单模式：高级选项先收起来，之前的设置仍然保留。', 'info');
  });
  $('swTitleNames').addEventListener('change', () => {
    const template = $('swTitleNames').checked
      ? TITLE_ID_TEMPLATE
      : ((APP.meta && APP.meta.defaultTemplate) ? APP.meta.defaultTemplate : FALLBACK_TEMPLATE);
    $('templateInput').value = template;
    $('tAttachments').value = template;
    $('tContent').value = template;
    $('tJson').value = template;
    APP.templates = { attachments: template, content: template, json: template };
    syncTitleNames();
    changed();
  });

  document.querySelectorAll('[data-close]').forEach((btn) => btn.addEventListener('click', closeModals));
  document.querySelectorAll('.modal').forEach((modal) => {
    modal.addEventListener('mousedown', (event) => {
      if (event.target === modal) closeModals();
    });
  });
  $('fsGo').addEventListener('click', () => loadFs($('fsPath').value));
  $('fsPath').addEventListener('keydown', (event) => { if (event.key === 'Enter') loadFs($('fsPath').value); });
  $('fsChoose').addEventListener('click', chooseFs);

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeModals();
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (!$('btnStart').disabled) startJob();
    }
  });

  document.querySelectorAll('.rail-link[href^="#"]').forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      const target = document.querySelector(link.getAttribute('href'));
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

async function installDeps() {
  try {
    toast('开始安装依赖，日志会实时输出…', 'info');
    const result = await api('/api/install-deps', {});
    if (result.job) { selectJob(result.job.id, true); APP.lastJobSignature = ''; tick(); }
    setTimeout(refreshMeta, 3000);
  } catch (error) {
    toast(error.message, 'err');
  }
}

async function openFolder(path) {
  if (!path) { toast('请先选择目录', 'err'); return; }
  try { await api('/api/open', { path }); } catch (error) { toast(error.message, 'err'); }
}

/* ── scroll spy ───────────────────────────────────────────── */

function initScrollSpy() {
  const links = [...document.querySelectorAll('.rail-link[href^="#"]')];
  const sections = links
    .map((link) => document.querySelector(link.getAttribute('href')))
    .filter(Boolean);
  if (!('IntersectionObserver' in window) || !sections.length) return;
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      const link = links.find((item) => item.getAttribute('href') === `#${entry.target.id}`);
      if (!link) continue;
      links.forEach((item) => item.classList.toggle('is-active', item === link));
    }
  }, { rootMargin: '-45% 0px -50% 0px', threshold: 0 });
  sections.forEach((section) => observer.observe(section));
}

/* ── boot ─────────────────────────────────────────────────── */

async function boot() {
  initTheme();
  applyMode(loadMode(), false);
  renderDateRows();
  renderPresets();
  renderVarChips();

  try {
    APP.meta = await api('/api/meta');
    applyMeta();
  } catch (error) {
    toast(`无法连接本地服务：${error.message}`, 'err');
  }

  applyConfig(loadConfig());
  wireEvents();
  initScrollSpy();
  refreshPreviewAndValidate();
  tick();
}

document.addEventListener('DOMContentLoaded', boot);
