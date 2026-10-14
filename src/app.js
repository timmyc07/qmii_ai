const { invoke, convertFileSrc } = window.__TAURI__.core;
const { open } = window.__TAURI__.dialog;
const { listen } = window.__TAURI__.event;

const state = { presets: [], fixedPrompt: '', images: [], generating: false, jobs: [], workflow: 'quick' };
const $ = (id) => document.getElementById(id);
const presetList = $('preset-list');
const feed = $('feed');
const modalRoot = $('modal-root');
const promptInput = $('prompt');

function toast(text) {
  const node = $('toast'); node.textContent = text; node.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => node.classList.remove('show'), 2600);
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function setSidebarOpen(open) {
  $('app-shell').classList.toggle('sidebar-open', open);
  $('sidebar-toggle').setAttribute('aria-expanded', String(open));
  $('sidebar-toggle').setAttribute('aria-label', open ? '收起魔法按鈕' : '展開魔法按鈕');
}

function resizePrompt() {
  promptInput.style.height = 'auto';
  const maximum = parseFloat(getComputedStyle(promptInput).maxHeight);
  promptInput.style.height = Math.min(promptInput.scrollHeight, maximum) + 'px';
}

function renderPresets() {
  if (!state.presets.length) {
    presetList.innerHTML = '<div class="empty-presets">還沒有魔法按鈕，<br>點下方做一個吧 ♡</div>';
    return;
  }
  presetList.innerHTML = state.presets.map((p, i) => `<button class="preset-card" data-preset="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i * 35, 250)}ms"><span class="preset-emoji">${['🌷','🪻','🧁','🦋','🍓'][i % 5]}</span><span class="preset-copy"><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.prompt)}</small></span></button>`).join('');
  presetList.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => {
    const preset = state.presets.find(p => p.id === button.dataset.preset);
    if (preset && !state.generating) { setSidebarOpen(false); promptInput.value = preset.prompt; submitPrompt(); }
  }));
}

function renderFixedState() {
  $('fixed-state').textContent = state.fixedPrompt.trim() ? '已啟用' : '未設定';
  $('fixed-state').style.color = state.fixedPrompt.trim() ? '#8b69b5' : '';
}

async function persistSettings(settings = { presets: state.presets, fixedPrompt: state.fixedPrompt }) {
  try { await invoke('save_settings', { settings }); return true; }
  catch (e) { toast(`儲存失敗：${e}`); return false; }
}

function openModal(title, inner, onClose = () => {}) {
  setSidebarOpen(false);
  modalRoot.innerHTML = `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-head"><h2 id="modal-title">${title}</h2><button class="modal-close" aria-label="關閉">×</button></div>${inner}</section></div>`;
  const backdrop = modalRoot.querySelector('.modal-backdrop');
  modalRoot.querySelector('.modal-close').onclick = () => { modalRoot.innerHTML = ''; onClose(); };
  backdrop.addEventListener('click', e => { if (e.target === backdrop) { modalRoot.innerHTML = ''; onClose(); } });
  requestAnimationFrame(() => modalRoot.querySelector('input, textarea, .modal-close')?.focus());
  return modalRoot.querySelector('.modal');
}

function openPresetEditor(preset = null) {
  const editingId = preset?.id ?? null;
  const modal = openModal(preset ? '編輯魔法按鈕' : '做一個新按鈕 ♡', `
    <p class="modal-subtitle">儲存後會出現在左側，按一下就能直接送出提示詞。</p>
    <label class="form-field"><span>按鈕名稱</span><input id="preset-name" maxlength="32" placeholder="例：夢幻水彩" value="${escapeHtml(preset?.name ?? '')}"></label>
    <label class="form-field"><span>要送給模型的完整提示詞</span><textarea id="preset-prompt" placeholder="寫下這個按鈕要替你說的話…">${escapeHtml(preset?.prompt ?? '')}</textarea></label>
    <div class="modal-actions"><button class="secondary-button" id="preset-cancel">先不要</button><button class="primary-button" id="preset-save">♡ 儲存按鈕</button></div>`);
  modal.querySelector('#preset-cancel').onclick = () => { modalRoot.innerHTML = ''; };
  modal.querySelector('#preset-save').onclick = async () => {
    const save = modal.querySelector('#preset-save');
    if (save.disabled) return;
    const name = modal.querySelector('#preset-name').value.trim();
    const text = modal.querySelector('#preset-prompt').value.trim();
    if (!name || !text) { toast('名稱和提示詞都要填寫喔'); return; }
    const nextPresets = editingId
      ? state.presets.map(p => p.id === editingId ? { ...p, name, prompt: text } : p)
      : [...state.presets, { id: crypto.randomUUID(), name, prompt: text }];
    save.disabled = true;
    save.textContent = '正在儲存…';
    const saved = await persistSettings({ presets: nextPresets, fixedPrompt: state.fixedPrompt });
    save.disabled = false;
    save.textContent = '♡ 儲存按鈕';
    if (!saved) return;
    state.presets = nextPresets;
    renderPresets();
    if (modalRoot.contains(modal)) modalRoot.innerHTML = '';
    toast(editingId ? '按鈕更新好了 ♡' : '新按鈕做好囉，左側可以直接使用！');
  };
}

function openPresetManager() {
  const renderRows = () => state.presets.length
    ? state.presets.map(p => `<div class="manager-row" data-row="${escapeHtml(p.id)}"><span class="preset-emoji">🌷</span><div class="manager-row-main"><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.prompt)}</small></div><button class="mini-action edit" title="編輯">✎</button><button class="mini-action delete" title="刪除">⌫</button></div>`).join('')
    : '<div class="settings-tip">還沒有建立按鈕。按「新增按鈕」開始，儲存後會立即出現在左側喔。</div>';
  const modal = openModal('我的魔法按鈕', `<p class="modal-subtitle">管理、修改或刪除你常用的提示詞。</p><div id="manager-list" class="preset-manager-list">${renderRows()}</div><div class="modal-actions"><button class="secondary-button" id="manager-done">完成</button><button class="primary-button" id="manager-add">＋ 新增按鈕</button></div>`);
  const updateRows = () => { modal.querySelector('#manager-list').innerHTML = renderRows(); bindRows(); };
  const bindRows = () => modal.querySelectorAll('.manager-row').forEach(row => {
    const id = row.dataset.row;
    row.querySelector('.edit').onclick = () => {
      const item = state.presets.find(p => p.id === id);
      openPresetEditor(item);
    };
    row.querySelector('.delete').onclick = async () => {
      const nextPresets = state.presets.filter(p => p.id !== id);
      if (!await persistSettings({ presets: nextPresets, fixedPrompt: state.fixedPrompt })) return;
      state.presets = nextPresets;
      renderPresets(); updateRows(); toast('已移除這個按鈕');
    };
  });
  bindRows();
  modal.querySelector('#manager-done').onclick = () => { modalRoot.innerHTML = ''; };
  modal.querySelector('#manager-add').onclick = () => {
    // Close this list before editing; the editor saves once, then the left list refreshes immediately.
    modalRoot.innerHTML = '';
    openPresetEditor();
  };
}

function openFixedEditor() {
  const modal = openModal('固定提示詞 ✧', `
    <p class="modal-subtitle">每次創作都會自動附加在你輸入的內容前面。留白時也可以只使用固定提示詞。</p>
    <label class="form-field"><span>我的固定風格或規則</span><textarea id="fixed-prompt" placeholder="例：畫面保持溫柔自然的光線，保留主體的臉部特徵…">${escapeHtml(state.fixedPrompt)}</textarea></label>
    <div class="modal-actions"><button class="secondary-button" id="fixed-clear">清除</button><button class="secondary-button" id="fixed-cancel">取消</button><button class="primary-button" id="fixed-save">♡ 儲存</button></div>`);
  modal.querySelector('#fixed-cancel').onclick = () => { modalRoot.innerHTML = ''; };
  modal.querySelector('#fixed-save').onclick = async () => {
    const nextPrompt = modal.querySelector('#fixed-prompt').value.trim();
    if (!await persistSettings({ presets: state.presets, fixedPrompt: nextPrompt })) return;
    state.fixedPrompt = nextPrompt; renderFixedState(); modalRoot.innerHTML = ''; toast('固定提示詞已儲存');
  };
  modal.querySelector('#fixed-clear').onclick = async () => {
    if (!await persistSettings({ presets: state.presets, fixedPrompt: '' })) return;
    state.fixedPrompt = ''; renderFixedState(); modalRoot.innerHTML = ''; toast('固定提示詞已清除');
  };
}

const mobile = { status: null, busy: '', error: '', revision: 0, panel: null };

function renderMobileConnection() {
  const info = mobile.status;
  const badge = mobile.busy ? (mobile.busy.startsWith('停止') ? '停止中…' : '開啟中…') : '';
  $('mobile-state').textContent = badge || (mobile.error ? '需檢查' : info?.running ? '已開啟' : '未開啟');
  const panel = mobile.panel;
  if (!panel || !modalRoot.contains(panel)) return;
  panel.querySelector('#mobile-status').textContent = mobile.busy || info?.message || '正在查詢連線狀態…';
  panel.querySelector('#mobile-error').textContent = mobile.error;
  const ready = Boolean(info?.running && !mobile.busy && !mobile.error);
  panel.querySelector('#mobile-details').classList.toggle('hidden', !ready);
  panel.querySelector('#mobile-url').value = ready ? info.url : '';
  panel.querySelector('#mobile-code').value = ready ? info.code : '';
  const start = panel.querySelector('#mobile-start');
  start.textContent = info?.registered ? '重新連線' : '開啟手機連線';
  start.classList.toggle('hidden', ready);
  start.disabled = Boolean(mobile.busy || !info);
  panel.querySelector('#mobile-stop').disabled = Boolean(mobile.busy || !info?.registered);
  panel.querySelector('#mobile-refresh').disabled = Boolean(mobile.busy);
}

async function refreshMobileConnection() {
  if (mobile.busy) return;
  const revision = ++mobile.revision;
  try {
    const info = await invoke('mobile_status');
    if (revision !== mobile.revision) return;
    mobile.status = info; mobile.error = '';
  } catch (error) {
    if (revision !== mobile.revision) return;
    mobile.status = null; mobile.error = String(error);
  }
  renderMobileConnection();
}

async function controlMobileConnection(start) {
  if (mobile.busy) return;
  ++mobile.revision;
  mobile.busy = start ? '正在開啟…' : '停止中，等待目前生成完成…';
  mobile.error = '';
  renderMobileConnection();
  try {
    mobile.status = await invoke(start ? 'start_mobile' : 'stop_mobile');
    toast(start ? '手機連線已開啟' : '手機連線已停止');
  } catch (error) {
    mobile.status = null; mobile.error = String(error);
  } finally {
    mobile.busy = ''; renderMobileConnection();
  }
}

function openMobileConnection() {
  let timer;
  const panel = openModal('手機連線', `
    <p class="modal-subtitle">用手機瀏覽器連接這台電腦，生成、修改與下載圖片。</p>
    <p id="mobile-status" class="settings-tip" role="status" aria-live="polite"></p>
    <p id="mobile-error" class="mobile-error" role="alert"></p>
    <div id="mobile-details" class="hidden">
      <label class="form-field"><span>① 在手機開啟這個網址</span><input id="mobile-url" readonly aria-label="手機網址"></label>
      <button id="mobile-copy-url" class="secondary-button">複製網址</button>
      <label class="form-field"><span>② 輸入私人連線碼</span><input id="mobile-code" type="password" readonly aria-label="私人連線碼" autocomplete="off"></label>
      <div class="mobile-code-actions"><button id="mobile-show-code" class="secondary-button" aria-pressed="false">顯示連線碼</button><button id="mobile-copy-code" class="secondary-button">複製連線碼</button></div>
    </div>
    <p class="mobile-help">電腦需保持開機、連網並避免休眠。重新開啟後網址會變更，請勿分享私人連線碼。關閉桌面視窗後連線仍會保留，可回此面板停止。</p>
    <div class="modal-actions"><button id="mobile-refresh" class="secondary-button">重新整理</button><button id="mobile-stop" class="secondary-button">停止連線</button><button id="mobile-start" class="primary-button">開啟手機連線</button></div>`, () => { clearInterval(timer); });
  mobile.panel = panel;
  panel.querySelector('#mobile-start').onclick = () => controlMobileConnection(true);
  panel.querySelector('#mobile-stop').onclick = () => controlMobileConnection(false);
  panel.querySelector('#mobile-refresh').onclick = refreshMobileConnection;
  panel.querySelector('#mobile-show-code').onclick = event => {
    const input = panel.querySelector('#mobile-code');
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    event.currentTarget.textContent = show ? '隱藏連線碼' : '顯示連線碼';
    event.currentTarget.setAttribute('aria-pressed', String(show));
  };
  for (const field of ['url', 'code']) panel.querySelector(`#mobile-copy-${field}`).onclick = async () => {
    try {
      await navigator.clipboard.writeText(panel.querySelector(`#mobile-${field}`).value);
      toast(field === 'url' ? '手機網址已複製' : '私人連線碼已複製');
    } catch { toast('無法存取剪貼簿，請選取欄位內容手動複製。'); }
  };
  renderMobileConnection();
  refreshMobileConnection();
  timer = setInterval(() => {
    if (!modalRoot.contains(panel)) { clearInterval(timer); return; }
    refreshMobileConnection();
  }, 10000);
}

function appendUserMessage(text, images) {
  const node = document.createElement('article'); node.className = 'message user-message';
  if (images.length) {
    const row = document.createElement('div'); row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap';
    images.forEach(file => { const im = document.createElement('img'); im.src = convertFileSrc(file); im.style.cssText = 'width:62px;height:62px;object-fit:cover;border-radius:13px'; row.appendChild(im); }); node.appendChild(row);
  } else {
    const label = document.createElement('div'); label.textContent = text; node.appendChild(label);
  }
  feed.appendChild(node);
}

function setBusy(value) {
  state.generating = value; $('send').disabled = value; $('upload-images').disabled = value;
  $('workflow-mode').disabled = value;
  $('send').classList.toggle('busy', value);
  $('send').innerHTML = value ? '<span>✧</span>' : '<span>↑</span>';
}

async function submitPrompt() {
  if (state.generating) return;
  const typed = promptInput.value.trim();
  const finalPrompt = [state.fixedPrompt.trim(), typed].filter(Boolean).join('\n\n');
  if (!finalPrompt) { toast('先寫下想法，或設定固定提示詞吧 ♡'); promptInput.focus(); return; }
  const images = [...state.images];
  $('welcome').classList.add('hidden');
  appendUserMessage(finalPrompt, images);
  const progress = document.createElement('div'); progress.className = 'message progress-card'; progress.innerHTML = '<span class="spinner"></span><span>正在準備模型…</span>'; feed.appendChild(progress);
  state.currentProgress = progress; promptInput.value = ''; resizePrompt(); state.images = []; renderImageTray(); setBusy(true); scrollFeed();
  try { await invoke('generate_images', { prompt: finalPrompt, images, workflow: state.workflow }); }
  catch (e) { progress.className = 'message error-card'; progress.textContent = `工作無法啟動：${e}`; setBusy(false); toast('生成啟動失敗'); }
}

function scrollFeed() { $('conversation').scrollTo({ top: $('conversation').scrollHeight, behavior: 'smooth' }); }

function renderImageTray() {
  const tray = $('image-tray'); tray.innerHTML = '';
  tray.classList.toggle('hidden', !state.images.length);
  state.images.forEach((path, index) => {
    const wrap = document.createElement('div'); wrap.className = 'thumb-wrap';
    wrap.innerHTML = `<img src="${convertFileSrc(path)}" alt="待處理圖片"><button title="移除圖片">×</button>`;
    wrap.querySelector('button').onclick = () => { state.images.splice(index, 1); renderImageTray(); };
    tray.appendChild(wrap);
  });
  $('batch-label').textContent = state.images.length ? `${state.images.length} 張圖片${state.images.length > 1 ? ' · 會依序修改' : ''}` : '';
}

async function chooseImages() {
  try {
    const picked = await open({ multiple: true, directory: false, title: '選擇要修改的圖片', filters: [{ name: '圖片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }] });
    if (!picked) return;
    const paths = Array.isArray(picked) ? picked : [picked];
    for (const file of paths) if (!state.images.includes(file)) state.images.push(file);
    renderImageTray();
  } catch (e) { toast(`選擇圖片失敗：${e}`); }
}

listen('generation-progress', event => {
  const data = event.payload;
  if (data.image) {
    state.jobs.push(data.image);
    const card = document.createElement('article'); card.className = 'message assistant-result';
    const title = document.createElement('div'); title.className = 'assistant-label'; title.textContent = '✿ 圖片完成'; card.appendChild(title);
    const img = document.createElement('img'); img.className = 'result-image'; img.src = convertFileSrc(data.image); img.alt = '生成圖片'; img.addEventListener('load', scrollFeed, { once: true }); card.appendChild(img);
    const path = document.createElement('div'); path.className = 'result-path'; path.textContent = `已儲存至 ${data.image}`; card.appendChild(path); feed.appendChild(card);
  }
  if (data.error) {
    const error = document.createElement('div'); error.className = 'message error-card'; error.textContent = `${data.message}\n${data.error}`; feed.appendChild(error);
  }
  if (state.currentProgress) {
    if (data.done) {
      state.currentProgress.className = 'message assistant-label'; state.currentProgress.textContent = `♡ ${data.message}`;
      setBusy(false); toast(data.message);
    } else if (!data.image && !data.error) {
      state.currentProgress.innerHTML = `<span class="spinner"></span><span>${escapeHtml(data.message)}</span>`;
    } else {
      state.currentProgress.innerHTML = `<span class="spinner"></span><span>正在處理 ${data.index}/${data.total} 張圖片…</span>`;
    }
  }
  scrollFeed();
});

async function init() {
  $('welcome').classList.remove('hidden');
  $('manage-presets').onclick = openPresetManager;
  // Do not pass the click event as the optional preset argument. Otherwise the
  // editor mistakes the event object for an existing preset and opens in edit mode.
  $('new-preset-shortcut').onclick = () => openPresetEditor();
  $('fixed-settings').onclick = openFixedEditor;
  $('mobile-connection').onclick = openMobileConnection;
  $('sidebar-toggle').onclick = () => setSidebarOpen(!$('app-shell').classList.contains('sidebar-open'));
  $('sidebar-backdrop').onclick = () => setSidebarOpen(false);
  $('open-output').onclick = async () => { try { await invoke('open_output_folder'); } catch (e) { toast(`無法開啟作品集：${e}`); } };
  $('upload-images').onclick = chooseImages;
  $('send').onclick = submitPrompt;
  $('workflow-mode').onchange = event => {
    state.workflow = event.target.value;
    toast(state.workflow === 'pose' ? '已切換為 Qwen 2.1 工作流；需要時會自動啟動 ComfyUI' : '已切換為快速生成');
  };
  $('window-minimize').onclick = e => { e.stopPropagation(); invoke('window_minimize').catch(err => toast(String(err))); };
  $('window-maximize').onclick = e => { e.stopPropagation(); invoke('window_toggle_maximize').catch(err => toast(String(err))); };
  $('window-close').onclick = e => { e.stopPropagation(); invoke('window_close').catch(err => toast(String(err))); };
  $('native-titlebar').addEventListener('mousedown', e => {
    if (e.button === 0 && !e.target.closest('button')) invoke('window_start_dragging').catch(err => toast(String(err)));
  });
  $('native-titlebar').addEventListener('dblclick', e => {
    if (!e.target.closest('button')) invoke('window_toggle_maximize').catch(err => toast(String(err)));
  });
  promptInput.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submitPrompt(); } });
  promptInput.addEventListener('input', resizePrompt);
  window.addEventListener('resize', resizePrompt);
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (modalRoot.querySelector('.modal-close')) modalRoot.querySelector('.modal-close').click();
      else setSidebarOpen(false);
    }
  });
  document.querySelectorAll('.idea-chip').forEach(chip => chip.onclick = () => { promptInput.value = chip.dataset.prompt; resizePrompt(); promptInput.focus(); });
  try {
    const settings = await invoke('load_settings');
    state.presets = Array.isArray(settings.presets) ? settings.presets : [];
    state.fixedPrompt = settings.fixedPrompt ?? '';
  } catch (e) { toast(`載入設定失敗：${e}`); }
  renderPresets(); renderFixedState(); resizePrompt();
  refreshMobileConnection();
}

init();
