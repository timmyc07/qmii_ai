'use strict';
const $ = id => document.getElementById(id);
let csrf = '', selected = [], timer, installPrompt, submitting = false;
const cards = new Map();

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
}

async function studio(session) {
  csrf = session.csrf;
  $('login-view').classList.add('hidden'); $('studio').classList.remove('hidden'); $('logout').classList.remove('hidden');
  $('code').value = ''; $('presets').replaceChildren();
  for (const preset of session.presets || []) {
    const button = document.createElement('button'); button.type = 'button'; button.textContent = preset.name;
    button.onclick = () => { $('prompt').value = preset.prompt; $('prompt').focus(); };
    $('presets').append(button);
  }
  await refresh();
}

function renderJob(job) {
  let card = cards.get(job.id);
  if (!card) {
    card = document.createElement('article'); card.className = 'job'; card.dataset.id = job.id;
    const user = document.createElement('div'); user.className = 'user-message';
    if (job.sources.length) {
      for (const url of job.sources) { const img = document.createElement('img'); img.src = url; img.alt = '已送出的圖片'; user.append(img); }
    } else user.textContent = job.prompt;
    const status = document.createElement('div'); status.className = 'job-status'; status.setAttribute('role', 'status');
    card.append(user, status); cards.set(job.id, card); $('feed').append(card);
  }
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
    $('welcome').classList.toggle('hidden', jobs.length > 0);
    $('welcome').querySelector('p').textContent = '寫下想法，或上傳圖片開始改造。';
    if (csrf) timer = setTimeout(refresh, jobs.some(job => ['queued', 'running'].includes(job.status)) ? 2000 : 10000);
  } catch (error) {
    if (csrf) { toast('暫時連不上電腦，正在重新連線…'); timer = setTimeout(refresh, 5000); }
  }
}

function renderTray() {
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
  const prompt = [$('fixed').value.trim(), $('prompt').value.trim()].filter(Boolean).join('\n\n');
  if (!prompt || prompt.length > 8000) { toast('請輸入提示詞，合計最多 8000 字。'); return; }
  submitting = true; $('send').disabled = true; $('files').disabled = true; $('send').textContent = '上傳中…';
  try {
    for (const value of selected) {
      if (!value.id) value.id = (await api('/api/uploads', { method: 'POST', headers: { 'Content-Type': value.file.type || 'application/octet-stream' }, body: value.file })).id;
    }
    // Retain the request ID after an uncertain response so retry cannot duplicate a GPU task.
    const signature = JSON.stringify([prompt, $('workflow').value, selected.map(value => value.id)]);
    if ($('composer').pendingSignature !== signature) { $('composer').pendingSignature = signature; $('composer').pendingId = crypto.randomUUID().replaceAll('-', ''); }
    const job = await jsonPost('/api/jobs', { prompt, workflow: $('workflow').value, images: selected.map(value => value.id), request_id: $('composer').pendingId });
    renderJob(job); $('welcome').classList.add('hidden'); $('prompt').value = '';
    $('composer').pendingSignature = ''; selected.forEach(value => URL.revokeObjectURL(value.url)); selected = []; renderTray();
    toast('已交給你的電腦處理。'); await refresh();
  } catch (error) { toast(error.message); }
  finally { submitting = false; $('send').disabled = false; $('files').disabled = false; $('send').textContent = '送出 ↑'; }
};

$('logout').onclick = async () => { try { await api('/api/logout', { method: 'POST' }); showLogin(); } catch (error) { toast(error.message); } };
window.addEventListener('beforeinstallprompt', event => { event.preventDefault(); installPrompt = event; $('install').classList.remove('hidden'); });
$('install').onclick = async () => { if (installPrompt) { await installPrompt.prompt(); installPrompt = null; $('install').classList.add('hidden'); } };
document.addEventListener('visibilitychange', () => { if (!document.hidden && csrf) refresh(); });
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(() => {});
api('/api/session').then(studio).catch(() => showLogin());
