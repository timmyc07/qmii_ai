const { invoke, convertFileSrc } = window.__TAURI__.core;
const { open } = window.__TAURI__.dialog;
const { listen } = window.__TAURI__.event;

const state = { presets: [], preciseMode: false, revision: '', images: [], generating: false, jobs: [], workflow: 'quick', generation: {} };
const MAX_REFERENCE_IMAGES = 4;
const $ = (id) => document.getElementById(id);
const presetList = $('preset-list');
const feed = $('feed');
const modalRoot = $('modal-root');
const promptInput = $('prompt');
const conversation = $('conversation');
let followingLatest = true, scrollFrame = 0, previousScrollTop = 0;

function jobTime(value) {
  return value ? new Date(value * 1000).toLocaleString('zh-TW', { hour12: false }) : '未記錄';
}

function renderSharedJob(job) {
  const origin = job.origin || {};
  const workflows = { quick: '快速生成', reference: '多圖參考', superduper: 'SuperDuper + pussyV2', nsfw_adv: 'NSFW Adv 群組' };
  const endLabel = job.status === 'failed' ? '失敗' : '完成';
  return `<article class="shared-job">
    <div class="shared-job-heading"><b>${escapeHtml(workflows[job.workflow] || job.workflow)}</b><span>${escapeHtml(job.message)}</span></div>
    <p class="job-meta">提交：${escapeHtml(jobTime(job.created))}<br>開始：${escapeHtml(job.started ? jobTime(job.started) : '尚未開始／未記錄')} · ${endLabel}：${escapeHtml(job.finished ? jobTime(job.finished) : '尚未結束／未記錄')}</p>
    <dl class="job-origin"><dt>平台</dt><dd>${escapeHtml(origin.platform || '未記錄')}</dd><dt>設備</dt><dd>${escapeHtml(origin.device || '未記錄')}</dd><dt>使用者（來源回報）</dt><dd>${escapeHtml(origin.user || '未記錄')}</dd><dt>設備識別碼</dt><dd>${escapeHtml(origin.device_id || '未記錄')}</dd><dt>任務編號</dt><dd>${escapeHtml(job.id)}</dd></dl>
    <p class="job-meta">參數：${escapeHtml(JSON.stringify(job.parameters || {}))}</p><details data-job="${escapeHtml(job.id)}"><summary>查看完整 Prompt</summary><p class="job-prompt">${escapeHtml(job.prompt || '此舊任務未保留提示詞。')}</p></details>
    ${job.results.map(path => `<a href="${convertFileSrc(path)}" target="_blank" rel="noopener"><img src="${convertFileSrc(path)}" alt="共用任務作品" loading="lazy"></a>`).join('')}</article>`;
}

function setFollowingLatest(follow) {
  followingLatest = follow;
  $('latest-message').classList.toggle('hidden', follow);
}

function scrollFeed(force = false) {
  if (force) setFollowingLatest(true);
  if (!followingLatest || scrollFrame) return;
  scrollFrame = requestAnimationFrame(() => {
    scrollFrame = 0;
    if (followingLatest) {
      conversation.scrollTop = conversation.scrollHeight;
      previousScrollTop = conversation.scrollTop;
    }
  });
}

function setupConversationScroll() {
  const stopFollowing = () => {
    if (conversation.scrollHeight > conversation.clientHeight + 2) setFollowingLatest(false);
  };
  conversation.addEventListener('scroll', () => {
    const top = conversation.scrollTop;
    if (conversation.scrollHeight - conversation.clientHeight - top <= 2) setFollowingLatest(true);
    else if (top < previousScrollTop) setFollowingLatest(false);
    previousScrollTop = top;
  }, { passive: true });
  conversation.addEventListener('wheel', event => { if (event.deltaY < 0) stopFollowing(); }, { passive: true });
  let touchY = 0;
  conversation.addEventListener('touchstart', event => { touchY = event.touches[0].clientY; }, { passive: true });
  conversation.addEventListener('touchmove', event => {
    const nextY = event.touches[0].clientY;
    if (nextY > touchY) stopFollowing();
    touchY = nextY;
  }, { passive: true });
  conversation.addEventListener('keydown', event => {
    if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || (event.key === ' ' && event.shiftKey)) stopFollowing();
  });
  $('latest-message').onclick = () => scrollFeed(true);
  const observer = new ResizeObserver(() => scrollFeed());
  observer.observe(feed);
  observer.observe(conversation);
}

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

function setSidebarCollapsed(collapsed) {
  $('app-shell').classList.toggle('sidebar-collapsed', collapsed);
  $('sidebar-collapse').setAttribute('aria-expanded', String(!collapsed));
  $('sidebar-collapse').setAttribute('aria-label', collapsed ? '左側欄已收起' : '收起左側欄');
  $('sidebar-collapse').title = collapsed ? '左側欄已收起' : '收起左側欄';
  $('sidebar-toggle').setAttribute('aria-expanded', String(!collapsed));
  $('sidebar-toggle').setAttribute('aria-label', collapsed ? '展開魔法按鈕' : '收起魔法按鈕');
  localStorage.setItem('qianmi-sidebar-collapsed', String(collapsed));
}

function resizePrompt() {
  promptInput.style.height = 'auto';
  const maximum = parseFloat(getComputedStyle(promptInput).maxHeight);
  promptInput.style.height = Math.min(promptInput.scrollHeight, maximum) + 'px';
}

function setupWorkflowPicker() {
  const native = $('workflow-mode');
  const trigger = $('workflow-trigger');
  const menu = $('workflow-menu');
  const value = $('workflow-value');
  const options = [...menu.querySelectorAll('[data-value]')];
  const setOpen = open => {
    menu.classList.toggle('is-open', open);
    trigger.setAttribute('aria-expanded', String(open));
    trigger.classList.toggle('is-open', open);
  };
  const select = nextValue => {
    if (state.generating) return;
    if (native.querySelector(`option[value="${nextValue}"]`)?.disabled) return;
    native.value = nextValue;
    value.textContent = options.find(option => option.dataset.value === nextValue)?.textContent ?? nextValue;
    options.forEach(option => option.setAttribute('aria-selected', String(option.dataset.value === nextValue)));
    native.dispatchEvent(new Event('change', { bubbles: true }));
    setOpen(false);
  };
  state.selectWorkflow = select;
  trigger.onclick = () => { if (!state.generating) setOpen(!menu.classList.contains('is-open')); };
  options.forEach(option => option.onclick = () => select(option.dataset.value));
  trigger.onkeydown = event => {
    if (event.key === 'Escape') setOpen(false);
    if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setOpen(true); }
  };
  document.addEventListener('click', event => {
    if (!event.target.closest('.workflow-picker')) setOpen(false);
  });
}

function setCreationOpen(open) {
  $('app-shell').classList.toggle('creation-open', open);
  $('creation-toggle').setAttribute('aria-expanded', String(open));
  if (open) setSidebarOpen(false);
}

function renderWorkflow() {
  renderParameters();
  $('workflow-help').textContent = state.workflow === 'reference'
    ? '上傳 2～4 張圖片，由 Qwen Image Turbo 融合參考生成一張作品。'
    : state.workflow === 'superduper'
      ? 'ComfyUI 雙階段工作流，套用 pussyV2 LoRA 與四段局部細修；目前只支援文字生成。'
      : state.workflow === 'nsfw_adv'
        ? '作者建議配置群組：NSFW Adv LoKr 1.0、Lightning 0.45、res_2s、bong_tangent、10 Steps、CFG 1。'
      : 'Qwen Image Turbo 文字生圖；有圖片時逐張修改。';
  $('upload-images').disabled = state.generating || ['superduper', 'nsfw_adv'].includes(state.workflow);
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

function renderPreciseState() {
  $('precise-state').textContent = state.preciseMode ? '開啟' : '關閉';
  $('precise-state').style.color = state.preciseMode ? '#8b69b5' : '';
  $('precise-mode').setAttribute('aria-pressed', String(state.preciseMode));
}

function parameterKey() { return state.workflow; }
function currentParameters() { return Object.fromEntries(Object.entries(state.generation[parameterKey()] || {}).filter(([, value]) => value !== null)); }

function parameterFields() {
  const superduper = state.workflow === 'superduper';
  const nsfwAdv = state.workflow === 'nsfw_adv';
  const fields = [
    { key: 'width', label: '寬度 Width', min: 256, max: 2048, step: 32, defaultValue: 1024, help: '輸出圖片的水平像素。調高：畫面更寬、細節、耗時與顯存用量增加。調低：更快更省顯存，但細節與可容納內容減少。必須是 32 的倍數。' },
    { key: 'height', label: '高度 Height', min: 256, max: 2048, step: 32, defaultValue: (superduper || nsfwAdv) ? 1536 : 1024, help: '輸出圖片的垂直像素。調高：畫面更高、細節、耗時與顯存用量增加。調低：更快更省顯存，但細節減少。必須是 32 的倍數。' },
    { key: 'steps', label: '步數 Steps', min: 4, max: 60, step: 1, defaultValue: superduper ? 40 : nsfwAdv ? 10 : 8, help: superduper ? '雙階段取樣的總去噪步數，會依原工作流比例切成前後兩段。調高：細化時間更長、可能更穩定但耗時增加；調低：更快，但結構與細節容易不足。' : nsfwAdv ? '作者範例使用 10 步。調高會增加細化時間但可能削弱 Lightning 配方；調低更快，但細節與結構可能不足。' : '模型反覆去除雜訊的次數。8 是 Turbo 官方蒸餾配方。調高：明顯變慢且不保證更清晰；調低：更快，但細節、文字與構圖穩定度通常下降。' },
    { key: 'cfg', label: '提示詞引導 CFG', min: 1, max: 15, step: .1, defaultValue: superduper ? 2 : 1, help: superduper ? '控制第二階段貼近提示詞的強度。調高：提示詞約束與對比更強，過高會僵硬、過曝或出現瑕疵；調低：畫面更自由自然，但可能偏離描述。' : nsfwAdv ? '作者建議 CFG 1。調高會加強提示詞約束，但可能破壞 LoKr 與 Lightning 的原始平衡；最低為 1。' : '控制模型貼近提示詞的強度。1 是 Turbo 原生值。調高：提示詞約束增強，但更慢且過高容易失真；最低為 1。' },
    { key: 'seed', label: '種子 Seed', min: 0, max: 9007199254740991, step: 1, defaultValue: '隨機', help: '決定初始雜訊；相同提示詞、尺寸與其他參數搭配相同種子可重現結果。數字大小沒有強弱之分，換一個數字只是換一種構圖與細節。留白會每次隨機。' },
    { key: 'negative', label: '負面提示詞 Negative prompt', defaultValue: '留白', help: '描述不希望出現的內容。CFG=1 時 Turbo 幾乎不使用負面提示詞；提高 CFG 後作用才會變明顯。內容越多不一定越好，過度限制可能破壞構圖。' }
  ];
  if (superduper) fields.push({ key: 'lora_strength', label: 'LoRA 強度', min: 0, max: 2, step: .05, defaultValue: .8, help: '控制 pussyV2 LoRA 對模型與文字編碼的影響。調高：LoRA 特徵與觸發詞效果更明顯，過高可能扭曲或產生雜訊；調低：更接近基礎模型，設為 0 等同關閉 LoRA。' });
  if (nsfwAdv) fields.push(
    { key: 'lokr_strength', label: 'NSFW Adv LoKr 強度', min: 0, max: 2, step: .05, defaultValue: 1, help: '作者建議 1.0，用於加強人體細節。調高會放大 LoKr 特徵，也更容易產生形體瑕疵；調低會減弱效果，0 等同關閉。' },
    { key: 'lightning_strength', label: 'Lightning 強度', min: 0, max: 2, step: .05, defaultValue: .45, help: '作者建議 0.4～0.5，用來配合低步數加速。調高會加重蒸餾效果，過高可能失去細節；調低會接近原模型，但 10 步可能不足，0 等同關閉。' });
  return fields;
}

function renderParameters() {
  const values = currentParameters();
  $('generation-parameters').innerHTML = parameterFields().map(field => `<div class="parameter-field"><label>${field.label}<input data-parameter="${field.key}" type="${field.key === 'negative' ? 'text' : 'number'}" ${field.min === undefined ? 'maxlength="4000"' : `min="${field.min}" max="${field.max}" step="${field.step}"`} placeholder="${escapeHtml(field.defaultValue)}" value="${escapeHtml(values[field.key] ?? '')}"></label><p>${escapeHtml(field.help)}</p></div>`).join('');
  $('generation-parameters').querySelectorAll('input').forEach(input => input.oninput = () => {
    if (!input.checkValidity()) return;
    const values = currentParameters();
    if (input.value === '') delete values[input.dataset.parameter];
    else values[input.dataset.parameter] = input.dataset.parameter === 'negative' ? input.value : Number(input.value);
    state.generation[parameterKey()] = values;
  });
  $('recipe-lock').textContent = state.workflow === 'superduper'
    ? '配方固定：ComfyUI、雙 KSampler、APG、FreSca，以及四段 Impact Pack 局部細修。'
    : state.workflow === 'nsfw_adv'
      ? '群組固定：Qwen Image FP8、NSFW Adv LoKr、Lightning 8-step LoRA、res_2s 採樣器與 bong_tangent 排程。'
    : '配方固定：Euler 採樣器、Turbo 8-step Sigma 排程。步數不是 8 時會改用模型的一般排程。';
  $('save-parameters').onclick = async () => { if (await persistSettings()) toast('此模式參數已儲存，所有設備共用'); };
  $('reset-parameters').onclick = async () => {
    const previous = state.generation[parameterKey()];
    delete state.generation[parameterKey()];
    if (!await persistSettings()) state.generation[parameterKey()] = previous;
    renderParameters();
  };
}

async function persistSettings(settings = { presets: state.presets, preciseMode: state.preciseMode }) {
  for (const input of $('generation-parameters').querySelectorAll('input')) if (!input.reportValidity()) return false;
  try { const saved = await invoke('save_settings', { settings: { generation: state.generation, ...settings, revision: state.revision } }); state.revision = saved.revision; return true; }
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
    const saved = await persistSettings({ presets: nextPresets, preciseMode: state.preciseMode });
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
      if (!await persistSettings({ presets: nextPresets, preciseMode: state.preciseMode })) return;
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

async function togglePreciseMode() {
  const previous = state.preciseMode;
  state.preciseMode = !previous;
  renderPreciseState();
  if (!await persistSettings()) { state.preciseMode = previous; renderPreciseState(); return; }
  toast(state.preciseMode ? '精準模式已開啟，會先重寫提示詞' : '精準模式已關閉');
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

function appendUserMessage(text, images, workflow) {
  const node = document.createElement('article'); node.className = 'message user-message';
  if (images.length) {
    if (workflow === 'reference') {
      const prompt = document.createElement('div'); prompt.className = 'reference-prompt'; prompt.textContent = text; node.appendChild(prompt);
    }
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
  $('workflow-trigger').disabled = value;
  $('workflow-menu').classList.remove('is-open');
  $('workflow-trigger').classList.remove('is-open');
  $('workflow-trigger').setAttribute('aria-expanded', 'false');
  renderWorkflow();
  $('send').classList.toggle('busy', value);
  $('send').innerHTML = value ? '<span>✧</span>' : '<span>↑</span>';
}

async function submitPrompt() {
  for (const input of $('generation-parameters').querySelectorAll('input')) if (!input.reportValidity()) return;
  if (state.generating) return;
  const typed = promptInput.value.trim();
  const finalPrompt = typed;
  if (!finalPrompt) { toast('先寫下想法吧 ♡'); promptInput.focus(); return; }
  const images = [...state.images];
  const parameters = currentParameters();
  if (state.workflow === 'reference' && images.length < 2) { toast('多圖參考生成至少需要 2 張參考圖片'); return; }
  if (['superduper', 'nsfw_adv'].includes(state.workflow) && images.length) { toast('這個 ComfyUI 工作流目前只支援文字生成，請先移除圖片'); return; }
  $('welcome').classList.add('hidden');
  appendUserMessage(finalPrompt, images, state.workflow);
  const progress = document.createElement('div'); progress.className = 'message progress-card'; progress.innerHTML = '<span class="spinner"></span><span>正在準備模型…</span>'; feed.appendChild(progress);
  state.currentProgress = progress; promptInput.value = ''; resizePrompt(); state.images = []; renderImageTray(); setBusy(true); scrollFeed(true);
  try { await invoke('generate_images', { prompt: finalPrompt, images, workflow: state.workflow, parameters, preciseMode: state.preciseMode }); }
  catch (e) { progress.className = 'message error-card'; progress.textContent = `工作無法啟動：${e}`; setBusy(false); toast('生成啟動失敗'); }
}

function renderImageTray() {
  renderWorkflow();
  const tray = $('image-tray'); tray.innerHTML = '';
  tray.classList.toggle('hidden', !state.images.length);
  state.images.forEach((path, index) => {
    const wrap = document.createElement('div'); wrap.className = 'thumb-wrap';
    wrap.innerHTML = `<img src="${convertFileSrc(path)}" alt="待處理圖片"><button title="移除圖片">×</button>`;
    wrap.querySelector('button').onclick = () => { state.images.splice(index, 1); renderImageTray(); };
    tray.appendChild(wrap);
  });
  if (!state.images.length) { $('batch-label').textContent = ''; return; }
  $('batch-label').textContent = state.workflow === 'reference'
    ? `${state.images.length} 張參考圖${state.images.length >= 2 ? ' · 會融合參考' : ''}`
    : `${state.images.length} 張圖片${state.images.length > 1 ? ' · 會依序修改' : ''}`;
}

async function chooseImages() {
  try {
    const picked = await open({ multiple: true, directory: false, title: '選擇要修改的圖片', filters: [{ name: '圖片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }] });
    if (!picked) return;
    const paths = Array.isArray(picked) ? picked : [picked];
    for (const file of paths) {
      if (state.images.length >= MAX_REFERENCE_IMAGES) {
        toast(`一次最多 ${MAX_REFERENCE_IMAGES} 張圖片`);
        break;
      }
      if (!state.images.includes(file)) state.images.push(file);
    }
    renderImageTray();
  } catch (e) { toast(`選擇圖片失敗：${e}`); }
}

listen('generation-progress', event => {
  const data = event.payload;
  if (data.image) {
    state.jobs.push(data.image);
    const card = document.createElement('article'); card.className = 'message assistant-result';
    const title = document.createElement('div'); title.className = 'assistant-label'; title.textContent = '✿ 圖片完成'; card.appendChild(title);
    const img = document.createElement('img'); img.className = 'result-image'; img.src = convertFileSrc(data.image); img.alt = '生成圖片';
    card.appendChild(img);
    const download = document.createElement('a'); download.href = convertFileSrc(data.image); download.download = data.image.split(/[\\/]/).pop(); download.textContent = '下載作品'; card.appendChild(download);
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
  setupConversationScroll();
  $('welcome').classList.remove('hidden');
  $('manage-presets').onclick = openPresetManager;
  $('shared-jobs').onclick = () => {
    let closed = false, refreshTimer;
    openModal('共用任務', '<div id="shared-job-list" role="status">正在讀取主機佇列…</div>', () => { closed = true; clearTimeout(refreshTimer); });
    const refresh = async () => {
      try {
        const { jobs } = await invoke('studio_jobs');
        const list = $('shared-job-list');
        if (closed || !list) return;
        const expanded = new Set([...list.querySelectorAll('details[open]')].map(node => node.dataset.job));
        list.innerHTML = jobs.length ? [...jobs].reverse().map(renderSharedJob).join('') : '目前沒有任務。';
        list.querySelectorAll('details').forEach(node => { node.open = expanded.has(node.dataset.job); });
        refreshTimer = setTimeout(refresh, 5000);
      } catch (error) { const list = $('shared-job-list'); if (list && !closed) { list.textContent = String(error); refreshTimer = setTimeout(refresh, 5000); } }
    };
    refresh();
  };
  // Do not pass the click event as the optional preset argument. Otherwise the
  // editor mistakes the event object for an existing preset and opens in edit mode.
  $('new-preset-shortcut').onclick = () => openPresetEditor();
  $('precise-mode').onclick = togglePreciseMode;
  $('mobile-connection').onclick = openMobileConnection;
  $('sidebar-collapse').onclick = () => setSidebarCollapsed(true);
  $('sidebar-toggle').onclick = () => {
    if (window.matchMedia('(max-width: 48rem)').matches) setSidebarOpen(!$('app-shell').classList.contains('sidebar-open'));
    else setSidebarCollapsed(!$('app-shell').classList.contains('sidebar-collapsed'));
  };
  $('sidebar-backdrop').onclick = () => setSidebarOpen(false);
  $('open-output').onclick = async () => { try { await invoke('open_output_folder'); } catch (e) { toast(`無法開啟作品集：${e}`); } };
  $('upload-images').onclick = chooseImages;
  $('send').onclick = submitPrompt;
  setupWorkflowPicker();
  $('creation-toggle').onclick = () => setCreationOpen(!$('app-shell').classList.contains('creation-open'));
  $('creation-close').onclick = () => setCreationOpen(false);
  $('creation-backdrop').onclick = () => setCreationOpen(false);
  $('workflow-mode').onchange = event => {
    state.workflow = event.target.value;
    renderImageTray();
    toast(state.workflow === 'reference'
        ? '請上傳 2～4 張參考圖，模型會依提示詞融合創作一張新圖'
        : state.workflow === 'superduper' ? '已切換為 SuperDuper 文字生成'
          : state.workflow === 'nsfw_adv' ? '已切換為 NSFW Adv 群組' : '已切換為快速生成');
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
      else { setSidebarOpen(false); setCreationOpen(false); }
    }
  });
  document.querySelectorAll('.idea-chip').forEach(chip => chip.onclick = () => { promptInput.value = chip.dataset.prompt; resizePrompt(); promptInput.focus(); });
  try {
    const settings = await invoke('load_settings');
    state.presets = Array.isArray(settings.presets) ? settings.presets : [];
    state.preciseMode = settings.preciseMode ?? false;
    state.revision = settings.revision ?? ''; state.generation = settings.generation || {};
  } catch (e) { toast(`載入設定失敗：${e}`); }
  setSidebarCollapsed(localStorage.getItem('qianmi-sidebar-collapsed') === 'true');
  renderPresets(); renderPreciseState(); resizePrompt(); renderWorkflow();
  refreshMobileConnection();
  setInterval(async () => {
    if (document.hidden || state.generating || modalRoot.firstChild) return;
    try {
      const settings = await invoke('load_settings');
      if (settings.revision !== state.revision) {
        state.presets = settings.presets; state.preciseMode = settings.preciseMode; state.revision = settings.revision; state.generation = settings.generation || {};
        renderParameters(); renderPresets(); renderPreciseState();
      }
    } catch {}
  }, 5000);
}

init();
