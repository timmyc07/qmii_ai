'use strict';
const $ = id => document.getElementById(id);
let csrf = '', selected = [], timer, installPrompt, submitting = false;
const cards = new Map();
$('workflow').onchange = renderParameters;
let settings = { presets: [], preciseMode: false, revision: '' }, dirty = false, editingId = null, libraryOffset = 0;

function browserPlatform() {
  const ua = navigator.userAgent;
  const os = /iPhone|iPad/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) ? 'iOS / iPadOS' : /Android/.test(ua) ? 'Android' : /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'macOS' : /Linux/.test(ua) ? 'Linux' : '未知系統';
  const browser = /Edg/.test(ua) ? 'Edge' : /Firefox|FxiOS/.test(ua) ? 'Firefox' : /Chrome|CriOS/.test(ua) ? 'Chrome' : /Safari/.test(ua) ? 'Safari' : '瀏覽器';
  return `${os} · ${browser}${window.matchMedia('(display-mode: standalone)').matches || navigator.standalone ? ' · PWA' : ' · 網頁'}`;
}

let identity = {};
try { identity = JSON.parse(localStorage.getItem('qianmi-identity') || '{}') || {}; } catch {}
identity = { device_id: typeof identity.device_id === 'string' && /^[a-zA-Z0-9-]{1,64}$/.test(identity.device_id) ? identity.device_id : crypto.randomUUID(),
  user: typeof identity.user === 'string' ? identity.user.slice(0, 100) : '', device: typeof identity.device === 'string' ? identity.device.slice(0, 100) : '' };
try { localStorage.setItem('qianmi-identity', JSON.stringify(identity)); } catch {}
$('identity-user').value = identity.user; $('identity-device').value = identity.device;
$('save-identity').onclick = () => {
  identity.user = $('identity-user').value.trim(); identity.device = $('identity-device').value.trim();
  try { localStorage.setItem('qianmi-identity', JSON.stringify(identity)); toast('已儲存，之後的任務會使用此名稱。'); }
  catch { toast('瀏覽器無法儲存，本次連線仍會使用此名稱。'); }
};
function jobOrigin() {
  return { ...identity, user: identity.user || '未命名使用者', device: identity.device || '未命名瀏覽器設備', platform: browserPlatform() };
}
function jobTime(value) { return value ? new Date(value * 1000).toLocaleString('zh-TW', { hour12: false }) : '未記錄'; }

function parameterKey() { return $('workflow').value; }
function currentParameters() { return Object.fromEntries(Object.entries(settings.generation?.[parameterKey()] || {}).filter(([, value]) => value !== null)); }
function renderParameters() {
  const superduper = parameterKey() === 'superduper';
  const nsfwAdv = parameterKey() === 'nsfw_adv';
  const fields = [
    ['width', '寬度 Width', 256, 2048, 32, '1024', '調高會增加水平空間、細節、耗時與記憶體；調低會更快但細節減少。須為 32 的倍數。'],
    ['height', '高度 Height', 256, 2048, 32, (superduper || nsfwAdv) ? '1536' : '1024', '調高會增加垂直空間、細節、耗時與記憶體；調低會更快但細節減少。須為 32 的倍數。'],
    ['steps', '步數 Steps', 4, 60, 1, superduper ? '40' : nsfwAdv ? '10' : '8', superduper ? '雙階段取樣的總步數。調高可能更穩定但更慢；調低更快，但結構與細節容易不足。' : nsfwAdv ? '作者範例為 10 步；調高更慢且可能偏離 Lightning 配方，調低可能損失細節。' : '8 是 Turbo 官方配方。調高會變慢且不保證更清晰；調低會更快，但細節與穩定度通常下降。'],
    ['cfg', '提示詞引導 CFG', 1, 15, .1, superduper ? '2' : '1', superduper ? '第二階段的提示詞強度。調高會更貼近描述，過高容易僵硬或出現瑕疵；調低更自由但可能偏題。' : nsfwAdv ? '作者建議 CFG 1；調高可能破壞 LoKr 與 Lightning 的平衡。' : '1 是 Turbo 原生值。調高會加強提示詞約束，但更慢且過高容易失真；最低為 1。'],
    ['seed', '種子（留白隨機）', 0, 9007199254740991, 1, '隨機', '相同設定與種子可重現結果。數字大小沒有強弱之分，換數字就是換構圖與細節。'],
    ['negative', '負面提示詞', undefined, undefined, undefined, '留白', '描述不想出現的內容；CFG=1 時幾乎不起作用，提高 CFG 後才會較明顯。']
  ];
  if (superduper) fields.push(['lora_strength', 'LoRA 強度', 0, 2, .05, '.8', '調高會加強 pussyV2 特徵，過高可能扭曲或產生雜訊；調低更接近基礎模型，0 等同關閉。']);
  if (nsfwAdv) fields.push(
    ['lokr_strength', 'NSFW Adv LoKr 強度', 0, 2, .05, '1', '作者建議 1.0。調高會放大人體細節與瑕疵風險；調低會減弱效果，0 等同關閉。'],
    ['lightning_strength', 'Lightning 強度', 0, 2, .05, '.45', '作者建議 0.4～0.5。調高蒸餾效果更強但可能失去細節；調低更接近原模型。']);
  $('generation-parameters').replaceChildren();
  for (const [key, title, min, max, step, placeholder, help] of fields) {
    const label = document.createElement('label'); label.textContent = title;
    const input = document.createElement('input'); input.dataset.parameter = key; input.type = key === 'negative' ? 'text' : 'number';
    if (min !== undefined) { input.min = min; input.max = max; input.step = step; } else input.maxLength = 4000;
    input.placeholder = placeholder; input.value = currentParameters()[key] ?? '';
    input.oninput = () => {
      if (!input.checkValidity()) return;
      settings.generation ||= {}; const values = currentParameters();
      if (input.value === '') delete values[key]; else values[key] = key === 'negative' ? input.value : Number(input.value);
      settings.generation[parameterKey()] = values; dirty = true;
      $('settings-status').textContent = '參數尚未儲存；提交任務會使用目前值。';
    };
    const note = document.createElement('small'); note.className = 'parameter-help'; note.textContent = help;
    label.append(input, note); $('generation-parameters').append(label);
  }
  $('files').disabled = submitting || superduper || nsfwAdv;
}
$('reset-parameters').onclick = () => { if (settings.generation) delete settings.generation[parameterKey()]; dirty = true; renderParameters(); };

function applySettings(value) {
  settings = { presets: value.presets, preciseMode: value.preciseMode ?? false, revision: value.revision, generation: value.generation || {} };
  renderParameters();
  $('precise-mode').checked = settings.preciseMode;
  dirty = false; renderPresets(); $('settings-status').textContent = '已與主機同步';
}

function renderPresets() {
  $('presets').replaceChildren();
  for (const preset of settings.presets) {
    const row = document.createElement('div'); row.className = 'preset-row';
    const button = document.createElement('button'); button.type = 'button'; button.textContent = preset.name;
    button.onclick = () => { $('prompt').value = preset.prompt; $('composer').requestSubmit(); };
    const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = '編輯';
    edit.setAttribute('aria-label', `編輯${preset.name}`); edit.onclick = () => openPreset(preset);
    row.append(button, edit); $('presets').append(row);
  }
}

function openPreset(preset) {
  editingId = preset?.id || null;
  $('preset-name').value = preset?.name || ''; $('preset-prompt').value = preset?.prompt || '';
  $('delete-preset').classList.toggle('hidden', !preset); $('preset-editor').showModal();
}

async function saveSettings(presets = settings.presets) {
  for (const input of $('generation-parameters').querySelectorAll('input')) if (!input.reportValidity()) return false;
  try {
    const value = await api('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ presets, preciseMode: $('precise-mode').checked, generation: settings.generation || {}, revision: settings.revision }) });
    applySettings(value); toast('共用設定已儲存。'); return true;
  } catch (error) { toast(error.message); return false; }
}

async function loadLibrary(reset = false) {
  if (reset) { libraryOffset = 0; $('artworks').replaceChildren(); }
  try {
    const value = await api(`/api/library?offset=${libraryOffset}`);
    for (const artwork of value.items) {
      const figure = document.createElement('figure'); figure.className = 'result';
      const image = document.createElement('img'); image.src = artwork.url; image.alt = '作品'; image.loading = 'lazy';
      const preview = document.createElement('button'); preview.type = 'button'; preview.className = 'artwork-preview';
      preview.setAttribute('aria-label', '預覽作品'); preview.append(image);
      preview.onclick = () => { $('preview-image').src = artwork.url; $('preview-download').href = artwork.url;
        $('preview-download').download = `千迷AI-${artwork.id.slice(0, 12)}`; $('preview').showModal(); };
      const link = document.createElement('a'); link.href = artwork.url; link.download = `千迷AI-${artwork.id.slice(0, 12)}`; link.textContent = '↓ 下載作品';
      figure.append(preview, link); $('artworks').append(figure);
    }
    libraryOffset = value.next; $('more-artworks').classList.toggle('hidden', value.next === null);
  } catch (error) { toast(error.message); }
}

function toast(message) {
  $('toast').textContent = message; $('toast').classList.remove('hidden');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => $('toast').classList.add('hidden'), 4500);
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && options.method !== 'GET' && csrf) headers.set('X-Qianmi-CSRF', csrf);
  const response = await fetch(path, { ...options, headers, credentials: 'same-origin', cache: 'no-store' });
  if (!response.ok) {
    let detail = `連線錯誤 (${response.status})`;
    try { const error = await response.json(); if (typeof error.detail === 'string') detail = error.detail; } catch {}
    if (response.status === 401 && path !== '/api/login') showLogin();
    throw new Error(detail);
  }
  return response.json();
}

const jsonPost = (path, value) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });

function showLogin() {
  csrf = ''; clearTimeout(timer); cards.clear();
  document.querySelectorAll('.job').forEach(node => node.remove());
  selected.forEach(value => URL.revokeObjectURL(value.url)); selected = []; renderTray();
  $('studio').classList.add('hidden'); $('logout').classList.add('hidden'); $('login-view').classList.remove('hidden');
  $('precise-mode').checked = false; $('prompt').value = ''; $('presets').replaceChildren(); $('artworks').replaceChildren();
  $('preset-editor').close(); $('preview').close(); $('preview-image').removeAttribute('src');
  settings = { presets: [], preciseMode: false, revision: '' }; dirty = false;
}

async function studio(session) {
  csrf = session.csrf;
  $('login-view').classList.add('hidden'); $('studio').classList.remove('hidden'); $('logout').classList.remove('hidden');
  $('code').value = ''; applySettings(session);
  renderParameters();
  await refresh();
}

function renderJob(job) {
  let card = cards.get(job.id);
  if (!card) {
    card = document.createElement('article'); card.className = 'job'; card.dataset.id = job.id;
    const user = document.createElement('div'); user.className = 'user-message';
    if (job.sources.length) {
      for (const url of job.sources) { const img = document.createElement('img'); img.src = url; img.alt = '已送出的圖片'; user.append(img); }
      if (job.prompt) {
        const prompt = document.createElement('div'); prompt.textContent = job.prompt; user.prepend(prompt);
      }
    } else user.textContent = job.prompt;
    if (job.parameters && Object.keys(job.parameters).length) { const params = document.createElement('p'); params.className = 'note'; params.textContent = '參數：' + JSON.stringify(job.parameters); user.append(params); }
    const status = document.createElement('div'); status.className = 'job-status'; status.setAttribute('role', 'status');
    const metadata = document.createElement('div'); metadata.className = 'job-metadata';
    card.append(user, metadata, status); cards.set(job.id, card); $('feed').append(card);
  }
  const origin = job.origin || {};
  card.querySelector('.job-metadata').textContent = `提交：${jobTime(job.created)}
開始：${job.started ? jobTime(job.started) : '尚未開始／未記錄'} · ${job.status === 'failed' ? '失敗' : '完成'}：${job.finished ? jobTime(job.finished) : '尚未結束／未記錄'}
平台：${origin.platform || '未記錄'}
設備：${origin.device || '未記錄'}
使用者（來源回報）：${origin.user || '未記錄'}
設備識別碼：${origin.device_id || '未記錄'}
任務編號：${job.id}`;
  const status = card.querySelector('.job-status'); status.textContent = job.message; status.classList.toggle('failed', job.status === 'failed');
  job.results.forEach((url, index) => {
    if (card.querySelector(`[data-result="${index}"]`)) return;
    const figure = document.createElement('figure'); figure.className = 'result'; figure.dataset.result = index;
    const image = document.createElement('img'); image.src = url; image.alt = '千迷AI生成圖片'; image.loading = 'lazy';
    const link = document.createElement('a'); link.href = url; link.download = `千迷AI-${job.id.slice(0, 8)}-${index + 1}.png`; link.textContent = '↓ 儲存圖片';
    figure.append(image, link); card.append(figure);
  });
}

async function refresh() {
  clearTimeout(timer);
  try {
    const { jobs } = await api('/api/jobs'); jobs.forEach(renderJob);
    $('connection').textContent = '● 已連接私人工作室';
    if (!dirty && !$('preset-editor').open) {
      const current = await api('/api/settings');
      if (current.revision !== settings.revision) applySettings(current);
    }
    $('welcome').classList.toggle('hidden', jobs.length > 0);
    $('welcome').querySelector('p').textContent = '寫下想法，或上傳圖片開始改造。';
    if (csrf) timer = setTimeout(refresh, jobs.some(job => ['queued', 'running'].includes(job.status)) ? 2000 : 10000);
  } catch (error) {
    if (csrf) { $('connection').textContent = '○ 主機離線或連線中斷，正在重新連線…'; timer = setTimeout(refresh, 5000); }
  }
}

function renderTray() {
  renderParameters();
  $('tray').replaceChildren();
  selected.forEach((value, index) => {
    const wrap = document.createElement('div'); wrap.className = 'thumb';
    const img = document.createElement('img'); img.src = value.url; img.alt = '待處理圖片';
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', '移除圖片');
    remove.onclick = () => { if (submitting) return; URL.revokeObjectURL(value.url); selected.splice(index, 1); renderTray(); };
    wrap.append(img, remove); $('tray').append(wrap);
  });
}

$('files').onchange = event => {
  if (submitting) return;
  for (const file of event.target.files) {
    if (selected.length >= 4) { toast('一次最多四張圖片。'); break; }
    if (file.size > 12 * 1024 * 1024) { toast('單張圖片不可超過 12 MB。'); continue; }
    selected.push({ file, url: URL.createObjectURL(file) });
  }
  event.target.value = ''; renderTray();
};

$('login-form').onsubmit = async event => {
  event.preventDefault(); $('login-button').disabled = true; $('login-error').textContent = '';
  try { await jsonPost('/api/login', { code: $('code').value }); await studio(await api('/api/session')); }
  catch (error) { $('login-error').textContent = error.message; }
  finally { $('login-button').disabled = false; }
};

$('composer').onsubmit = async event => {
  event.preventDefault(); if (submitting) return;
  for (const input of $('generation-parameters').querySelectorAll('input')) if (!input.reportValidity()) return;
  const prompt = $('prompt').value.trim();
  if (!prompt || prompt.length > 8000) { toast('請輸入提示詞，合計最多 8000 字。'); return; }
  if ($('workflow').value === 'reference' && selected.length < 2) { toast('多圖參考至少需要 2 張參考圖片。'); return; }
  if (['superduper', 'nsfw_adv'].includes($('workflow').value) && selected.length) { toast('這個 ComfyUI 工作流目前只支援文字生成，請先移除圖片。'); return; }
  submitting = true; $('send').disabled = true; $('files').disabled = true; $('send').textContent = '上傳中…';
  try {
    for (const value of selected) {
      if (!value.id) value.id = (await api('/api/uploads', { method: 'POST', headers: { 'Content-Type': value.file.type || 'application/octet-stream' }, body: value.file })).id;
    }
    // Retain the request ID after an uncertain response so retry cannot duplicate a GPU task.
    const signature = JSON.stringify([prompt, $('workflow').value, selected.map(value => value.id), currentParameters(), $('precise-mode').checked]);
    if ($('composer').pendingSignature !== signature) { $('composer').pendingSignature = signature; $('composer').pendingId = crypto.randomUUID().replaceAll('-', ''); }
    const job = await jsonPost('/api/jobs', { prompt, workflow: $('workflow').value, images: selected.map(value => value.id), precise_mode: $('precise-mode').checked, request_id: $('composer').pendingId, origin: jobOrigin(), parameters: currentParameters() });
    renderJob(job); $('welcome').classList.add('hidden'); $('prompt').value = '';
    $('composer').pendingSignature = ''; selected.forEach(value => URL.revokeObjectURL(value.url)); selected = []; renderTray();
    toast('已交給你的電腦處理。'); await refresh();
  } catch (error) { toast(error.message); }
  finally { submitting = false; $('send').disabled = false; renderParameters(); $('send').textContent = '送出 ↑'; }
};

$('logout').onclick = async () => { try { await api('/api/logout', { method: 'POST' }); showLogin(); } catch (error) { toast(error.message); } };
$('precise-mode').onchange = () => { dirty = true; $('settings-status').textContent = '尚未儲存'; };
$('save-settings').onclick = () => saveSettings();
$('reload-settings').onclick = async () => { try { applySettings(await api('/api/settings')); } catch (error) { toast(error.message); } };
$('new-preset').onclick = () => openPreset();
$('cancel-preset').onclick = () => $('preset-editor').close();
$('preset-form').onsubmit = async event => {
  event.preventDefault();
  const preset = { id: editingId || crypto.randomUUID(), name: $('preset-name').value.trim(), prompt: $('preset-prompt').value.trim() };
  if (!preset.name || !preset.prompt) return;
  const next = editingId ? settings.presets.map(value => value.id === editingId ? preset : value) : [...settings.presets, preset];
  if (await saveSettings(next)) $('preset-editor').close();
};
$('delete-preset').onclick = async () => { if (await saveSettings(settings.presets.filter(value => value.id !== editingId))) $('preset-editor').close(); };
$('show-library').onclick = () => { $('library').classList.remove('hidden'); $('feed').classList.add('hidden'); $('composer').classList.add('hidden'); loadLibrary(true); };
$('close-library').onclick = () => { $('library').classList.add('hidden'); $('feed').classList.remove('hidden'); $('composer').classList.remove('hidden'); };
$('more-artworks').onclick = () => loadLibrary();
$('close-preview').onclick = () => $('preview').close();
window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); installPrompt = event; $('install').classList.remove('hidden'); });
$('install').onclick = async () => { if (installPrompt) { await installPrompt.prompt(); installPrompt = null; $('install').classList.add('hidden'); } };
document.addEventListener('visibilitychange', () => { if (!document.hidden && csrf) refresh(); });
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
api('/api/session').then(studio).catch(() => showLogin());
