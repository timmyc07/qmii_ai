const { invoke, convertFileSrc } = window.__TAURI__.core;
const { open } = window.__TAURI__.dialog;
const { listen } = window.__TAURI__.event;

const state = { presets: [], preciseMode: false, revision: '', images: [], generating: false, jobs: [], workflow: 'quick', generation: {}, studioMode: 'image', drafts: { image: { prompt: '', images: [] }, h3_image: { prompt: '', images: [] }, svi_image: { prompt: '', images: [] } }, chatScroll: { image: { top: 0, following: true }, h3_image: { top: 0, following: true }, svi_image: { top: 0, following: true } } };
const MAX_REFERENCE_IMAGES = 4;
const $ = (id) => document.getElementById(id);
const presetList = $('preset-list');
const feed = $('feed');
const modalRoot = $('modal-root');
const promptInput = $('prompt');
const conversation = $('conversation');
const videoFeed = $('video-results-h3_image');
let followingLatest = true, scrollFrame = 0, previousScrollTop = 0;

function currentFeed() { return state.studioMode === 'image' ? feed : $('video-results-' + state.studioMode); }

function videoParameters() {
  const values = { video_profile: $('video-profile').value,
    width: Number($('video-width').value), height: Number($('video-height').value), duration: Number($('video-duration').value),
    steps: Number($('video-steps').value), sampler: $('video-sampler').value,
    shift_video: Number($('video-shift-video').value), shift_audio: Number($('video-shift-audio').value),
    crop: $('video-crop').value, resize_method: $('video-resize').value, video_crf: Number($('video-crf').value),
    video_audio: $('video-audio').checked, identity_prompt: $('video-identity').checked, refmod: $('video-refmod').checked, end_frame: $('video-end-frame').value };
  if (values.video_profile !== 'base') values.lora_strength = Number($('video-lora').value);
  if ($('video-seed').value !== '') values.seed = Number($('video-seed').value);
  return values;
}

function updateVideoSettings() {
  const profile = $('video-profile').value, base = profile === 'base';
  $('video-steps').disabled = !base; $('video-lora').disabled = base;
  if (!base) $('video-steps').value = profile === 'turbo4' ? 4 : 8;
  const width = Number($('video-width').value), height = Number($('video-height').value);
  $('video-width').setCustomValidity(Math.min(width, height) > 768 ? '短邊最多 768 像素' : '');
  const size = `${width}x${height}`;
  $('video-size').value = [...$('video-size').options].some(option => option.value === size) ? size : 'custom';
  const length = Math.max(5, Math.round(Number($('video-duration').value) * 24));
  const frames = length + (5 - length % 17 + 17) % 17;
  $('video-summary').textContent = `${frames} 幀 · 實際約 ${(frames / 24).toFixed(2)} 秒 · 24 fps。${profile === 'turbo8' ? '8 步 LoRA 以 544p 訓練，建議先用 512 × 896；需要較長生成時間。' : '768p 需要更多時間與記憶體。'}`;
  $('video-last-controls').classList.toggle('hidden', $('video-end-frame').value !== 'custom');
  $('video-last-upload').disabled = state.generating;
  renderImageTray();
}

function loadVideoParameters(values = {}) {
  $('video-profile').value = values.video_profile ?? 'turbo4';
  const defaults = { duration: 12, width: 512, height: 896, seed: '', steps: 20, sampler: 'euler', crop: 'center',
    resize: 'lanczos', crf: 18, lora: 1, 'shift-video': values.video_profile === 'turbo8' || values.video_profile === 'base' ? 12 : 6,
    'shift-audio': 3, 'end-frame': 'none' };
  const keys = { resize: 'resize_method', crf: 'video_crf', lora: 'lora_strength', 'shift-video': 'shift_video', 'shift-audio': 'shift_audio', 'end-frame': 'end_frame' };
  for (const [id, fallback] of Object.entries(defaults)) $('video-' + id).value = values[keys[id] || id] ?? fallback;
  $('video-audio').checked = values.video_audio ?? true;
  $('video-identity').checked = values.identity_prompt ?? false;
  $('video-refmod').checked = values.refmod ?? false;
  updateVideoSettings();
}

function setStudioMode(mode) {
  if (mode === state.studioMode) return;
  state.drafts[state.studioMode] = { prompt: promptInput.value, images: [...state.images] };
  state.chatScroll[state.studioMode] = { top: conversation.scrollTop, following: followingLatest };
  if (state.studioMode === 'h3_image' && [...$('video-form').querySelectorAll('input, select')].every(input => input.checkValidity())) state.generation.h3_image = videoParameters();
  if (state.studioMode === 'svi_image' && [...$('svi-form').querySelectorAll('input')].every(input => input.checkValidity())) state.generation.svi_image = sviParameters();
  cancelAnimationFrame(scrollFrame); scrollFrame = 0;
  state.studioMode = mode;
  const h3 = mode === 'h3_image', svi = mode === 'svi_image', video = h3 || svi;
  setSidebarOpen(false); setCreationOpen(false);
  $('app-shell').classList.toggle('video-mode', video);
  $('app-shell').classList.toggle('svi-mode', svi);
  feed.classList.toggle('hidden', video); videoFeed.classList.toggle('hidden', !h3);
  $('video-results-svi_image').classList.toggle('hidden', !svi);
  $('image-settings').classList.toggle('hidden', video); $('video-form').classList.toggle('hidden', !h3);
  $('svi-form').classList.toggle('hidden', !svi); $('svi-prompts').classList.toggle('hidden', !svi);
  $('prompt-label').textContent = svi ? '第一段 · 起始動作' : '正向提示詞';
  promptInput.maxLength = svi ? 2500 : 8000;
  $('precise-mode').classList.toggle('hidden', video);
  $('creation-title').textContent = svi ? '✧ 高耗能模式設定' : video ? '✧ 影片設定' : '✧ 創作設定';
  conversation.setAttribute('aria-label', video ? '影片創作對話' : '圖片創作對話');
  $('welcome').querySelector('h1').textContent = svi ? '讓故事分三段，慢慢展開 ♡' : video ? '讓你的圖片動起來 ♡' : '今天想創作什麼呢？♡';
  $('welcome').querySelector('.welcome-copy').textContent = svi ? '一張首幀，三段連續動作。完成後自動釋放生成資源。' : video ? '最多選擇 4 張首幀，套用相同提示詞與參數，每張各自生成一支影片。' : '說說你的想法，或選張圖片，讓千迷AI陪你一起改造。';
  $('welcome').querySelector('.idea-chips').classList.toggle('hidden', video);
  $('welcome').classList.toggle('hidden', currentFeed().childElementCount > 0);
  promptInput.value = state.drafts[mode].prompt; state.images = [...state.drafts[mode].images];
  promptInput.placeholder = svi ? '描述首幀場景，以及第一段開始的動作…' : video ? '描述影片的畫面、動作與聲音…' : '寫下你的靈感，或先上傳一張圖片…';
  $('send').title = svi ? '生成三段續接影片' : video ? '生成有聲影片' : '開始創作';
  $('send').setAttribute('aria-label', $('send').title);
  resizePrompt(); renderImageTray();
  document.querySelectorAll('[data-studio-mode]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.studioMode === mode)));
  const savedScroll = state.chatScroll[mode];
  setFollowingLatest(savedScroll.following);
  requestAnimationFrame(() => {
    conversation.scrollTop = savedScroll.following ? conversation.scrollHeight : savedScroll.top;
    previousScrollTop = conversation.scrollTop;
  });
  if (h3) loadVideoParameters(state.generation.h3_image || {});
  if (svi) { $('svi-seed').value = state.generation.svi_image?.seed ?? ''; renderSviLoras(); }
}

function sviParameters() {
  const values = { ...state.generation.svi_image };
  if ($('svi-seed').value === '') delete values.seed;
  else values.seed = Number($('svi-seed').value);
  if ($('negative-prompt').value === '') delete values.negative;
  else values.negative = $('negative-prompt').value;
  for (const side of ['high', 'low']) if (values[side + '_lora']) values[side + '_lora'] = {
    ...values[side + '_lora'], strength: Number($('svi-' + side + '-lora-strength').value)
  };
  return values;
}

function renderSviLoras() {
  const values = state.generation.svi_image || {}, busy = state.generating || state.sviImporting;
  for (const side of ['high', 'low']) {
    const selection = values[side + '_lora'];
    const label = $('svi-' + side + '-lora-name');
    label.textContent = selection ? selection.name.split('/').pop() : '未選擇額外 LoRA';
    label.title = selection?.name || '';
    $('svi-' + side + '-lora-pick').disabled = Boolean(busy);
    $('svi-' + side + '-lora-clear').disabled = busy || !selection;
    const strength = $('svi-' + side + '-lora-strength');
    strength.disabled = busy || !selection;
    strength.value = selection?.strength ?? .5;
  }
  $('svi-save-settings').disabled = Boolean(busy);
  $('send').disabled = Boolean(busy);
}

async function chooseSviLora(side) {
  if (state.generating || state.sviImporting) return;
  state.sviImporting = true; renderSviLoras();
  const status = $('svi-lora-status');
  try {
    const path = await open({ multiple: false, directory: false, title: `選擇 ${side.toUpperCase()} 額外 LoRA`, filters: [{ name: 'LoRA', extensions: ['safetensors'] }] });
    if (!path) return;
    status.textContent = '正在匯入本機 LoRA，請稍候…';
    const { name } = await invoke('import_svi_lora', { path });
    const values = { ...state.generation.svi_image };
    values[side + '_lora'] = { name, strength: values[side + '_lora']?.strength ?? .5 };
    state.generation.svi_image = values;
    toast(`${side.toUpperCase()} LoRA 已選擇`);
  } catch (error) { toast(`LoRA 匯入失敗：${error}`); }
  finally {
    state.sviImporting = false; renderSviLoras();
    status.textContent = '權重 0 為停用；建議先用 0.3～0.5，再依作者說明調整。';
  }
}

function setupVideoModes() {
  document.querySelectorAll('[data-studio-mode]').forEach(button => button.onclick = () => setStudioMode(button.dataset.studioMode));
  $('video-profile').onchange = () => {
    const base = $('video-profile').value === 'base';
    $('video-steps').value = base ? 20 : $('video-profile').value === 'turbo4' ? 4 : 8;
    $('video-shift-video').value = $('video-profile').value === 'turbo4' ? 6 : 12;
    $('video-shift-audio').value = 3; $('video-lora').value = 1; $('video-sampler').value = 'euler';
    updateVideoSettings();
  };
  $('video-size').onchange = () => {
    if ($('video-size').value === 'custom') return;
    [$('video-width').value, $('video-height').value] = $('video-size').value.split('x');
    updateVideoSettings();
  };
  for (const id of ['duration', 'width', 'height', 'end-frame', 'crop']) $('video-' + id).addEventListener('input', updateVideoSettings);
  $('video-last-upload').onclick = async () => {
    try {
      const file = await open({ multiple: false, directory: false, title: '選擇影片尾幀', filters: [{ name: '圖片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }] });
      if (!file) return;
      state.videoLastImage = file;
      const preview = $('video-last-preview'); preview.innerHTML = '';
      const img = document.createElement('img'); img.src = convertFileSrc(file); img.alt = '影片尾幀';
      img.style.cssText = 'width:72px;height:72px;object-fit:cover;border-radius:13px'; preview.appendChild(img);
    } catch (error) { toast(`選擇尾幀失敗：${error}`); }
  };
  $('video-example').onclick = () => {
    const duration = $('video-duration').value, end = Number(duration).toFixed(3).padStart(6, '0');
    promptInput.value = `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\nintegrated_multimodal_description: [Shot 1] Realistic footage, warm afternoon sunlight, fixed camera. At 00:00.000 the shot matches <Picture 1>: a small orange cat sits on a wooden table beside a window. During the shot the cat slowly turns its head toward the window, blinks and gently moves its tail. The shot ends at 00:${end}.\n\noverall_soundscape: Quiet room ambience, faint birds outside the window. No dialogue.\n\nnon_diegetic_music: N/A`;
    resizePrompt(); setCreationOpen(false); promptInput.focus();
  };
  $('video-save-settings').onclick = async () => {
    for (const input of $('video-form').querySelectorAll('input, select')) if (!input.reportValidity()) return;
    state.generation[state.studioMode] = videoParameters();
    if (await persistSettings()) toast('影片參數已儲存；尾幀圖片需在每次開啟程式後重新選擇');
  };
  $('video-reset-settings').onclick = () => { loadVideoParameters(); toast('已還原影片配方，儲存後會成為預設'); };
  $('video-form').onsubmit = event => { event.preventDefault(); submitPrompt(); };
  $('svi-form').onsubmit = event => { event.preventDefault(); submitPrompt(); };
  for (const side of ['high', 'low']) {
    $('svi-' + side + '-lora-pick').onclick = () => chooseSviLora(side);
    $('svi-' + side + '-lora-clear').onclick = () => {
      delete state.generation.svi_image[side + '_lora']; renderSviLoras();
    };
    $('svi-' + side + '-lora-strength').oninput = event => {
      if (event.target.checkValidity()) state.generation.svi_image[side + '_lora'].strength = Number(event.target.value);
    };
  }
  $('svi-save-settings').onclick = async () => {
    for (const input of $('svi-form').querySelectorAll('input')) if (!input.reportValidity()) return;
    state.generation.svi_image = sviParameters();
    if (await persistSettings()) toast('高耗能模式預設已儲存');
  };
  $('svi-seed').oninput = () => {
    const values = { ...state.generation.svi_image };
    if ($('svi-seed').value === '') delete values.seed;
    else if ($('svi-seed').checkValidity()) values.seed = Number($('svi-seed').value);
    state.generation.svi_image = values;
  };
  $('svi-example').onclick = () => {
    promptInput.value = 'A small orange cat sits on a wooden table beside a window. The cat slowly turns its head toward the warm sunlight. Fixed camera, natural movement.';
    $('svi-prompt-2').value = 'The same orange cat gently raises one front paw and stretches, staying on the wooden table. Keep the camera and lighting consistent.';
    $('svi-prompt-3').value = 'The cat lowers its paw, settles comfortably on the table and slowly blinks toward the camera. End on a calm, steady frame.';
    resizePrompt(); setCreationOpen(false); promptInput.focus();
  };
}

function artworkMarkup(path) {
  const url = escapeHtml(convertFileSrc(path));
  return /\.mp4$/i.test(path) ? `<video class="result-video" src="${url}" controls playsinline preload="metadata"></video>` : `<a href="${url}" target="_blank" rel="noopener"><img src="${url}" alt="共用任務作品" loading="lazy"></a>`;
}

function jobTime(value) {
  return value ? new Date(value * 1000).toLocaleString('zh-TW', { hour12: false }) : '未記錄';
}

function renderSharedJob(job, cancelling = false) {
  const origin = job.origin || {};
  const { negative = '', segment_prompts, ...parameters } = job.parameters || {};
  const workflows = { quick: '快速生成', reference: '多圖參考', superduper: 'SuperDuper 群組', nsfw_adv: 'NSFW Adv 群組', h3_image: '圖片生影片', svi_image: '高耗能圖片轉影片模式' };
  const endLabel = job.status === 'cancelled' ? '終止' : job.status === 'failed' ? '失敗' : '完成';
  return `<article class="shared-job">
    <div class="shared-job-heading"><b>${escapeHtml(workflows[job.workflow] || job.workflow)}</b>${['queued', 'running', 'cancelling'].includes(job.status) ? `<button type="button" class="cancel-button" data-cancel-job="${escapeHtml(job.id)}"${cancelling || job.status === 'cancelling' ? ' disabled' : ''}>${cancelling || job.status === 'cancelling' ? '終止中…' : '■ 強制終止'}</button>` : ''}</div>
    <div class="shared-task-progress"></div>
    <p class="job-meta">提交：${escapeHtml(jobTime(job.created))}<br>開始：${escapeHtml(job.started ? jobTime(job.started) : '尚未開始／未記錄')} · ${endLabel}：${escapeHtml(job.finished ? jobTime(job.finished) : '尚未結束／未記錄')}${job.billing_status === 'pending' ? '<br>點數確認中，連線恢復後自動重試。' : job.finished && job.billing_status === 'reserved' ? '<br>點數結算待連線，自動重試中。' : ''}</p>
    <dl class="job-origin"><dt>平台</dt><dd>${escapeHtml(origin.platform || '未記錄')}</dd><dt>設備</dt><dd>${escapeHtml(origin.device || '未記錄')}</dd><dt>使用者（來源回報）</dt><dd>${escapeHtml(origin.user || '未記錄')}</dd><dt>設備識別碼</dt><dd>${escapeHtml(origin.device_id || '未記錄')}</dd><dt>任務編號</dt><dd>${escapeHtml(job.id)}</dd></dl>
    <p class="job-meta">參數：${escapeHtml(JSON.stringify(parameters))}</p><details data-job="${escapeHtml(job.id)}"><summary>查看${job.workflow === 'h3_image' ? '完整提示詞' : '正向／負面提示詞'}</summary><b>正向提示詞</b><p class="job-prompt">${escapeHtml(job.prompt || '此舊任務未保留提示詞。')}</p>${job.workflow === 'h3_image' ? '' : `<b>負面提示詞</b><p class="job-prompt">${escapeHtml(negative || '未填寫')}</p>`}</details>
    <button class="secondary-button" data-recipe-job="${escapeHtml(job.id)}">儲存為生成配方</button>
    ${job.results.map(artworkMarkup).join('')}</article>`;
}

function setFollowingLatest(follow) {
  followingLatest = follow;
  $('latest-message').classList.toggle('hidden', follow || !currentFeed().childElementCount);
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
  observer.observe(videoFeed);
  observer.observe($('video-results-svi_image'));
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
  for (const input of [promptInput, $('svi-prompt-2'), $('svi-prompt-3'), $('negative-prompt')]) {
    input.style.height = '0px';
    const maximum = parseFloat(getComputedStyle(input).maxHeight);
    input.style.height = Math.min(input.scrollHeight, maximum) + 'px';
  }
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
  $('image-refmod-help').textContent = `${state.workflow === 'nsfw_adv' ? '此模式使用 Qwen Image FP8' : '此模式使用 Qwen Image 2.1'}；RefMod 僅支援 H3 的參考條件，無法直接套用。`;
  $('workflow-help').textContent = state.workflow === 'reference'
    ? '上傳 2～4 張圖片，由 Qwen Image Turbo 融合參考生成一張作品。'
    : state.workflow === 'superduper'
      ? 'ComfyUI 雙階段工作流；上傳圖片時依提示詞逐張編輯，未上傳時文字生圖。圖片會依設定寬高置中裁切。'
      : state.workflow === 'nsfw_adv'
        ? 'LoKr + Lightning 群組；上傳圖片時逐張重繪，未上傳時文字生圖。圖片會依設定寬高置中裁切。'
      : 'Qwen Image Turbo 文字生圖；有圖片時逐張修改。';
  $('upload-images').disabled = state.generating;
}

function renderPresets() {
  if (!state.presets.length) {
    presetList.innerHTML = '<div class="empty-presets">還沒有魔法按鈕，<br>點下方做一個吧 ♡</div>';
    return;
  }
  presetList.innerHTML = state.presets.map((p, i) => `<button class="preset-card" data-preset="${escapeHtml(p.id)}" style="animation-delay:${Math.min(i * 35, 250)}ms"><span class="preset-emoji">${['🌷','🪻','🧁','🦋','🍓'][i % 5]}</span><span class="preset-copy"><b>${escapeHtml(p.name)}</b><small>${escapeHtml(p.prompt)}</small></span></button>`).join('');
  presetList.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => {
    const preset = state.presets.find(p => p.id === button.dataset.preset);
    if (preset && !state.generating) {
      setSidebarOpen(false); promptInput.value = preset.prompt;
      if (state.studioMode === 'image') state.generation[parameterKey()] = { ...currentParameters(), negative: preset.negative || '' };
      renderParameters();
      if (state.studioMode === 'svi_image') { resizePrompt(); promptInput.focus(); }
      else submitPrompt();
    }
  }));
}

function renderPreciseState() {
  $('precise-state').textContent = state.preciseMode ? '開啟' : '關閉';
  $('precise-state').style.color = state.preciseMode ? '#8b69b5' : '';
  $('precise-mode').setAttribute('aria-pressed', String(state.preciseMode));
}

function parameterKey() { return state.studioMode === 'svi_image' ? 'svi_image' : state.workflow; }
function currentParameters() { return Object.fromEntries(Object.entries(state.generation[parameterKey()] || {}).filter(([, value]) => value !== null)); }

function parameterFields() {
  const superduper = state.workflow === 'superduper';
  const nsfwAdv = state.workflow === 'nsfw_adv';
  const fields = [
    { key: 'width', label: '寬度 Width', min: 256, max: 2048, step: 32, defaultValue: 1024, help: '輸出圖片的水平像素。調高：畫面更寬、細節、耗時與顯存用量增加。調低：更快更省顯存，但細節與可容納內容減少。必須是 32 的倍數。' },
    { key: 'height', label: '高度 Height', min: 256, max: 2048, step: 32, defaultValue: (superduper || nsfwAdv) ? 1536 : 1024, help: '輸出圖片的垂直像素。調高：畫面更高、細節、耗時與顯存用量增加。調低：更快更省顯存，但細節減少。必須是 32 的倍數。' },
    { key: 'steps', label: '步數 Steps', min: 4, max: 60, step: 1, defaultValue: superduper ? 40 : nsfwAdv ? 10 : 8, help: superduper ? '雙階段取樣的總去噪步數，會依原工作流比例切成前後兩段。調高：細化時間更長、可能更穩定但耗時增加；調低：更快，但結構與細節容易不足。' : nsfwAdv ? '作者範例使用 10 步。調高會增加細化時間但可能削弱 Lightning 配方；調低更快，但細節與結構可能不足。' : '模型反覆去除雜訊的次數。8 是 Turbo 官方蒸餾配方。調高：明顯變慢且不保證更清晰；調低：更快，但細節、文字與構圖穩定度通常下降。' },
    { key: 'cfg', label: '提示詞引導 CFG', min: 1, max: 15, step: .1, defaultValue: superduper ? 2 : 1, help: superduper ? '控制第二階段貼近提示詞的強度。調高：提示詞約束與對比更強，過高會僵硬、過曝或出現瑕疵；調低：畫面更自由自然，但可能偏離描述。' : nsfwAdv ? '作者建議 CFG 1。調高會加強提示詞約束，但可能破壞 LoKr 與 Lightning 的原始平衡；最低為 1。' : '控制模型貼近提示詞的強度。1 是 Turbo 原生值。調高：提示詞約束增強，但更慢且過高容易失真；最低為 1。' },
    { key: 'seed', label: '種子 Seed', min: 0, max: 9007199254740991, step: 1, defaultValue: '隨機', help: '決定初始雜訊；相同提示詞、尺寸與其他參數搭配相同種子可重現結果。數字大小沒有強弱之分，換一個數字只是換一種構圖與細節。留白會每次隨機。' }
  ];
  if (superduper) fields.push({ key: 'lora_strength', label: 'LoRA 強度', min: 0, max: 2, step: .05, defaultValue: .8, help: '控制 pussyV2 LoRA 對模型與文字編碼的影響。調高：LoRA 特徵與觸發詞效果更明顯，過高可能扭曲或產生雜訊；調低：更接近基礎模型，設為 0 等同關閉 LoRA。' });
  if (nsfwAdv) fields.push(
    { key: 'denoise', label: '重繪強度 Denoise', min: .05, max: 1, step: .05, defaultValue: .6, help: '只在上傳圖片時生效。調低：保留更多原圖構圖與細節；調高：更依提示詞重新創作，人物與構圖也更容易改變。1 接近完全重畫；未上傳圖片時固定使用 1。' },
    { key: 'lokr_strength', label: 'NSFW Adv LoKr 強度', min: 0, max: 2, step: .05, defaultValue: 1, help: '作者建議 1.0，用於加強人體細節。調高會放大 LoKr 特徵，也更容易產生形體瑕疵；調低會減弱效果，0 等同關閉。' },
    { key: 'lightning_strength', label: 'Lightning 強度', min: 0, max: 2, step: .05, defaultValue: .45, help: '作者建議 0.4～0.5，用來配合低步數加速。調高會加重蒸餾效果，過高可能失去細節；調低會接近原模型，但 10 步可能不足，0 等同關閉。' });
  return fields;
}

function renderParameters() {
  const values = currentParameters();
  $('generation-parameters').innerHTML = parameterFields().map(field => `<div class="parameter-field"><label>${field.label}<input data-parameter="${field.key}" type="number" min="${field.min}" max="${field.max}" step="${field.step}" placeholder="${escapeHtml(field.defaultValue)}" value="${escapeHtml(values[field.key] ?? '')}"></label><p>${escapeHtml(field.help)}</p></div>`).join('');
  $('generation-parameters').querySelectorAll('input').forEach(input => input.oninput = () => {
    if (!input.checkValidity()) return;
    const values = currentParameters();
    if (input.value === '') delete values[input.dataset.parameter];
    else values[input.dataset.parameter] = Number(input.value);
    state.generation[parameterKey()] = values;
  });
  const video = state.studioMode === 'h3_image';
  $('negative-prompt').disabled = video;
  $('negative-prompt').classList.toggle('hidden', video);
  $('negative-label').classList.toggle('hidden', video);
  $('negative-prompt').value = video ? '' : values.negative || '';
  $('negative-prompt').placeholder = state.studioMode === 'svi_image' ? '三段共用；留白沿用作者負面提示詞…' : '描述不希望出現的內容，可留白…';
  resizePrompt();
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
  if (state.studioMode === 'image') for (const input of $('generation-parameters').querySelectorAll('input')) if (!input.reportValidity()) return false;
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
    <label class="form-field"><span>正向提示詞</span><textarea id="preset-prompt" maxlength="8000" placeholder="描述希望生成的內容…">${escapeHtml(preset?.prompt ?? '')}</textarea></label>
    <label class="form-field"><span>負面提示詞</span><textarea id="preset-negative" maxlength="4000" placeholder="描述不希望出現的內容，可留白…">${escapeHtml(preset?.negative ?? '')}</textarea></label>
    <div class="modal-actions"><button class="secondary-button" id="preset-cancel">先不要</button><button class="primary-button" id="preset-save">♡ 儲存按鈕</button></div>`);
  modal.querySelector('#preset-cancel').onclick = () => { modalRoot.innerHTML = ''; };
  modal.querySelector('#preset-save').onclick = async () => {
    const save = modal.querySelector('#preset-save');
    if (save.disabled) return;
    const name = modal.querySelector('#preset-name').value.trim();
    const text = modal.querySelector('#preset-prompt').value.trim();
    const negative = modal.querySelector('#preset-negative').value;
    if (!name || !text) { toast('名稱和提示詞都要填寫喔'); return; }
    const nextPresets = editingId
      ? state.presets.map(p => p.id === editingId ? { ...p, name, prompt: text, negative } : p)
      : [...state.presets, { id: crypto.randomUUID(), name, prompt: text, negative }];
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
  toast(state.preciseMode ? '精準模式已開啟，保留原文並附加生成規範' : '精準模式已關閉');
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

async function openDrive() {
  let timer, busy = false;
  const panel = openModal('Google Drive 自動上傳', `
    <p class="modal-subtitle">所有平台的圖片與影片依「年-月-日」上傳到同一資料夾，電腦需保持開機與連網。</p>
    <p id="drive-status" class="settings-tip" role="status" aria-live="polite">正在讀取…</p>
    <label class="form-field"><span>Google Drive 目標資料夾連結</span><input id="drive-folder" type="url" required placeholder="https://drive.google.com/drive/folders/…"></label>
    <label><input id="drive-enabled" type="checkbox"> 開啟自動上傳</label>
    <p class="mobile-help">首次請匯入 Google OAuth「桌面應用程式」JSON，並在瀏覽器登入授權；之後自動上傳，不需每次登入。授權資料只保存在這台電腦。</p>
    <div class="modal-actions"><button id="drive-connect" class="secondary-button">匯入 JSON 並登入</button><button id="drive-save" class="primary-button">儲存</button></div>`, () => clearInterval(timer));
  const status = panel.querySelector('#drive-status');
  const refresh = async (fill = false) => {
    if (busy) return;
    try {
      const info = await invoke('google_drive', { action: 'status', value: {} });
      status.textContent = info.message + (info.last_success ? ` 上次完成：${new Date(info.last_success * 1000).toLocaleString('zh-TW')}` : '');
      if (fill) {
        panel.querySelector('#drive-folder').value = `https://drive.google.com/drive/folders/${info.folder_id}`;
        panel.querySelector('#drive-enabled').checked = info.enabled;
      }
    } catch (error) { status.textContent = String(error); }
  };
  panel.querySelector('#drive-save').onclick = async () => {
    try {
      const field = panel.querySelector('#drive-folder');
      if (!field.reportValidity()) return;
      const url = new URL(field.value);
      const match = url.pathname.match(/^\/drive\/folders\/([a-zA-Z0-9_-]+)\/?$/);
      if (url.protocol !== 'https:' || url.hostname !== 'drive.google.com' || !match) throw new Error('請填入 Google Drive 資料夾分享連結。');
      await invoke('google_drive', { action: 'save', value: { enabled: panel.querySelector('#drive-enabled').checked, folder_id: match[1] } });
      toast('Google Drive 設定已儲存'); await refresh();
    } catch (error) { status.textContent = String(error); }
  };
  panel.querySelector('#drive-connect').onclick = async event => {
    if (busy) return;
    const path = await open({ multiple: false, filters: [{ name: 'Google OAuth JSON', extensions: ['json'] }] });
    if (!path) return;
    busy = true; event.currentTarget.disabled = true;
    status.textContent = '正在準備連線，請在開啟的瀏覽器登入並授權…';
    try {
      const info = await invoke('google_drive', { action: 'connect', value: { path } });
      status.textContent = info.message;
    } catch (error) { status.textContent = String(error); }
    finally { busy = false; panel.querySelector('#drive-connect').disabled = false; }
  };
  await refresh(true);
  if (modalRoot.contains(panel)) timer = setInterval(() => refresh(), 5000);
}

function appendUserMessage(text, images) {
  const node = document.createElement('article'); node.className = 'message user-message';
  if (!images.length) {
    const prompt = document.createElement('div'); prompt.className = 'reference-prompt'; prompt.textContent = text; node.appendChild(prompt);
  }
  if (images.length) {
    const row = document.createElement('div'); row.style.cssText = 'display:flex;gap:6px;flex-wrap:wrap';
    images.forEach(file => { const im = document.createElement('img'); im.src = convertFileSrc(file); im.style.cssText = 'width:62px;height:62px;object-fit:cover;border-radius:13px'; row.appendChild(im); }); node.appendChild(row);
  }
  currentFeed().appendChild(node);
}

function setBusy(value) {
  state.generating = value; $('send').disabled = value; $('upload-images').disabled = value;
  state.currentJobId = null; state.cancelling = false; state.cancelSent = false;
  $('cancel-generation').classList.toggle('hidden', !value);
  $('cancel-generation').disabled = !value;
  $('cancel-generation').textContent = '■ 強制終止';
  $('video-last-upload').disabled = value;
  $('workflow-mode').disabled = value;
  $('workflow-trigger').disabled = value;
  $('workflow-menu').classList.remove('is-open');
  $('workflow-trigger').classList.remove('is-open');
  $('workflow-trigger').setAttribute('aria-expanded', 'false');
  renderWorkflow();
  $('send').classList.toggle('busy', value);
  $('send').innerHTML = value ? '<span>✧</span>' : '<span>↑</span>';
  renderSviLoras();
}

async function submitPrompt() {
  const svi = state.studioMode === 'svi_image', h3 = state.studioMode === 'h3_image', video = h3 || svi;
  if (!promptInput.reportValidity() || !$('negative-prompt').reportValidity()) return;
  for (const input of $(svi ? 'svi-form' : h3 ? 'video-form' : 'generation-parameters').querySelectorAll('input, select')) if (!input.reportValidity()) return;
  if (state.generating || state.sviImporting || state.checkingCredits) return;
  const segments = svi ? [promptInput.value, $('svi-prompt-2').value, $('svi-prompt-3').value] : [];
  if (svi && segments.some(text => !text.trim())) { toast('請完整填寫三段提示詞'); return; }
  if (svi && ![$('svi-prompt-2'), $('svi-prompt-3')].every(input => input.reportValidity())) return;
  const finalPrompt = svi ? segments.map((text, index) => `第 ${index + 1} 段：\n${text}`).join('\n\n') : promptInput.value;
  if (!finalPrompt.trim()) { toast('先寫下想法吧 ♡'); promptInput.focus(); return; }
  const images = [...state.images];
  const workflow = video ? state.studioMode : state.workflow;
  const parameters = h3 ? videoParameters() : svi ? sviParameters() : currentParameters();
  if (!h3 && (!svi || $('negative-prompt').value)) parameters.negative = $('negative-prompt').value;
  if (svi) parameters.segment_prompts = segments;
  if (svi && images.length !== 1) { toast('請選擇一張首幀圖片'); return; }
  if (h3 && (images.length < 1 || images.length > MAX_REFERENCE_IMAGES)) { toast('請選擇 1 至 4 張首幀圖片'); return; }
  const lastImage = h3 && parameters.end_frame === 'custom' ? state.videoLastImage : null;
  if (h3 && parameters.end_frame === 'custom') {
    if (!lastImage) { toast('請選擇尾幀圖片，或將尾幀約束改為不使用'); return; }
  }
  if (workflow === 'reference' && images.length < 2) { toast('多圖參考生成至少需要 2 張參考圖片'); return; }
  const preciseMode = video ? false : state.preciseMode;
  const signature = JSON.stringify([finalPrompt, images, lastImage, workflow, parameters, preciseMode]);
  const retry = state.pendingGeneration?.signature === signature;
  state.checkingCredits = true;
  try { await window.qianmiMembership.ensureCredit(workflow, images.length, retry); }
  catch (error) { toast(String(error.message || error)); return; }
  finally { state.checkingCredits = false; }
  if (!retry) state.pendingGeneration = { signature, id: crypto.randomUUID().replaceAll('-', '') };
  $('welcome').classList.add('hidden');
  const target = currentFeed();
  appendUserMessage(finalPrompt, lastImage ? [...images, lastImage] : images);
  const progress = document.createElement('div'); progress.className = 'message progress-card'; target.appendChild(progress);
  state.progressJob = { status: 'uploading', message: '正在連線工作室與上傳圖片…', progress: { elapsed_seconds: 0 } };
  window.qianmiProgress.render(progress, state.progressJob);
  state.resultTarget = target; state.currentProgress = progress; promptInput.value = ''; resizePrompt();
  if (svi) { $('svi-prompt-2').value = ''; $('svi-prompt-3').value = ''; resizePrompt(); }
  if (!video) state.images = [];
  renderImageTray(); setBusy(true); scrollFeed(true);
  try { await invoke('generate_images', { prompt: finalPrompt, images, lastImage, workflow, parameters, preciseMode, requestId: state.pendingGeneration.id }); }
  catch (e) {
    progress.removeAttribute('data-task-progress');
    progress.className = 'message error-card'; progress.textContent = `工作連線中斷：${e}。可在共用任務查看，原內容重試沿用同一筆請求。`;
    if (!promptInput.value) promptInput.value = svi ? segments[0] : finalPrompt;
    if (svi) { if (!$('svi-prompt-2').value) $('svi-prompt-2').value = segments[1]; if (!$('svi-prompt-3').value) $('svi-prompt-3').value = segments[2]; }
    if (!video) state.images = images;
    resizePrompt(); renderImageTray(); setBusy(false); toast('工作連線中斷');
  }
  finally { window.qianmiMembership.refresh().catch(() => {}); }
}

function renderImageTray() {
  renderWorkflow();
  const tray = $('image-tray'); tray.innerHTML = '';
  tray.classList.toggle('hidden', !state.images.length);
  state.images.forEach((path, index) => {
    const wrap = document.createElement('div'); wrap.className = 'thumb-wrap';
    wrap.innerHTML = `<img src="${escapeHtml(convertFileSrc(path))}" alt="待處理圖片"><button title="移除圖片">×</button>`;
    wrap.querySelector('button').onclick = () => { state.images.splice(index, 1); renderImageTray(); };
    tray.appendChild(wrap);
  });
  if (!state.images.length) { $('batch-label').textContent = ''; return; }
  $('batch-label').textContent = state.studioMode === 'svi_image' ? '1 張首幀 · 三段續接 · 置中裁切' : state.studioMode === 'h3_image' ? `${state.images.length} 張首幀 · 每張各自生成一支影片 · ${$('video-crop').value === 'center' ? '置中裁切' : '拉伸填滿'}` : state.workflow === 'reference'
    ? `${state.images.length} 張參考圖${state.images.length >= 2 ? ' · 會融合參考' : ''}`
    : `${state.images.length} 張圖片${state.images.length > 1 ? ' · 會依序修改' : ''}`;
}

async function chooseImages() {
  try {
    const mode = state.studioMode, video = mode === 'h3_image', svi = mode === 'svi_image';
    const picked = await open({ multiple: !svi, directory: false, title: svi ? '選擇一張影片首幀' : video ? '選擇影片首幀（最多 4 張）' : '選擇要修改的圖片', filters: [{ name: '圖片', extensions: ['png', 'jpg', 'jpeg', 'webp', 'bmp'] }] });
    if (!picked) return;
    if (mode !== state.studioMode) return;
    const paths = Array.isArray(picked) ? picked : [picked];
    if (svi) state.images = [];
    for (const file of paths) {
      if (state.images.length >= (svi ? 1 : MAX_REFERENCE_IMAGES)) {
        toast(`一次最多 ${svi ? 1 : MAX_REFERENCE_IMAGES} 張圖片`);
        break;
      }
      if (!state.images.includes(file)) state.images.push(file);
    }
    renderImageTray();
  } catch (e) { toast(`選擇圖片失敗：${e}`); }
}

async function cancelGeneration() {
  if (!state.generating || state.cancelSent) return;
  state.cancelling = true; $('cancel-generation').disabled = true; $('cancel-generation').textContent = '終止中…';
  if (!state.currentJobId) return;
  state.cancelSent = true;
  try { await invoke('cancel_generation', { jobId: state.currentJobId }); }
  catch (error) { state.cancelling = false; state.cancelSent = false; $('cancel-generation').disabled = false; $('cancel-generation').textContent = '■ 強制終止'; toast(`無法終止：${error}`); }
}

listen('generation-progress', event => {
  const data = event.payload;
  if (state.generating && data.jobId && !data.done) {
    state.currentJobId = data.jobId;
    if (state.cancelling) cancelGeneration();
  }
  const result = data.video || data.image;
  const target = state.resultTarget || feed;
  if (result) {
    state.jobs.push(result);
    const card = document.createElement('article'); card.className = 'message assistant-result';
    const title = document.createElement('div'); title.className = 'assistant-label'; title.textContent = data.video ? '▷ 影片完成' : '✿ 圖片完成'; card.appendChild(title);
    const img = document.createElement(data.video ? 'video' : 'img'); img.className = data.video ? 'result-video' : 'result-image'; img.src = convertFileSrc(result);
    if (data.video) { img.controls = true; img.playsInline = true; img.preload = 'metadata'; } else img.alt = '生成圖片';
    card.appendChild(img);
    const download = document.createElement('a'); download.href = convertFileSrc(result); download.download = result.split(/[\\/]/).pop(); download.textContent = '下載作品'; card.appendChild(download);
    const path = document.createElement('div'); path.className = 'result-path'; path.textContent = `已儲存至 ${result}`; card.appendChild(path); target.appendChild(card);
  }
  if (data.error) {
    const error = document.createElement('div'); error.className = 'message error-card'; error.textContent = `${data.message}\n${data.error}`; target.appendChild(error);
  }
  if (state.currentProgress) {
    if (data.done) {
      state.pendingGeneration = null;
      state.currentProgress.className = 'message assistant-label task-progress';
      setBusy(false); toast(data.message);
    }
    state.progressJob = { ...state.progressJob, status: data.status || (data.done ? (data.error ? 'failed' : 'completed') : 'running'),
      message: data.message || `已完成 ${data.index}/${data.total} 個輸出…`, billing_status: data.billingStatus,
      progress: data.progress || { ...state.progressJob.progress, completed: data.index, total: data.total } };
    window.qianmiProgress.render(state.currentProgress, state.progressJob);
  }
  if (target === currentFeed()) scrollFeed();
});

async function init() {
  setupVideoModes();
  setupConversationScroll();
  $('welcome').classList.remove('hidden');
  $('manage-presets').onclick = openPresetManager;
  $('generation-recipes').onclick = () => openGenerationRecipes();
  $('studio-maintenance').onclick = openStudioMaintenance;
  $('shared-jobs').onclick = () => {
    let closed = false, refreshTimer;
    const cancelling = new Set();
    let sharedJobs = [];
    openModal('共用任務', '<div id="shared-job-list" role="status">正在讀取主機佇列…</div>', () => { closed = true; clearTimeout(refreshTimer); });
    const refresh = async () => {
      try {
        const { jobs } = await invoke('studio_jobs');
        sharedJobs = jobs;
        const list = $('shared-job-list');
        if (closed || !list) return;
        const expanded = new Set([...list.querySelectorAll('details[open]')].map(node => node.dataset.job));
        list.innerHTML = jobs.length ? [...jobs].reverse().map(job => renderSharedJob(job, cancelling.has(job.id))).join('') : '目前沒有任務。';
        list.querySelectorAll('.shared-task-progress').forEach((element, index) => window.qianmiProgress.render(element, jobs[jobs.length - 1 - index]));
        list.querySelectorAll('details').forEach(node => { node.open = expanded.has(node.dataset.job); });
        clearTimeout(refreshTimer); refreshTimer = setTimeout(refresh, jobs.some(job => ['queued', 'running', 'cancelling'].includes(job.status)) ? 1000 : 5000);
      } catch (error) { const list = $('shared-job-list'); if (list && !closed) { list.textContent = String(error); refreshTimer = setTimeout(refresh, 5000); } }
    };
    $('shared-job-list').onclick = async event => {
      const recipeButton = event.target.closest('[data-recipe-job]');
      if (recipeButton) { closed = true; clearTimeout(refreshTimer); openGenerationRecipes(sharedJobs.find(job => job.id === recipeButton.dataset.recipeJob)); return; }
      const button = event.target.closest('[data-cancel-job]');
      if (!button || button.disabled) return;
      const jobId = button.dataset.cancelJob;
      cancelling.add(jobId); button.disabled = true; button.textContent = '終止中…';
      try { await invoke('cancel_generation', { jobId }); }
      catch (error) { toast(`無法終止：${error}`); }
      finally { cancelling.delete(jobId); }
      if (!closed) await refresh();
    };
    refresh();
  };
  // Do not pass the click event as the optional preset argument. Otherwise the
  // editor mistakes the event object for an existing preset and opens in edit mode.
  $('new-preset-shortcut').onclick = () => openPresetEditor();
  $('precise-mode').onclick = togglePreciseMode;
  $('mobile-connection').onclick = openMobileConnection;
  $('google-drive').onclick = openDrive;
  $('sidebar-collapse').onclick = () => setSidebarCollapsed(true);
  $('sidebar-toggle').onclick = () => {
    if (window.matchMedia('(max-width: 48rem)').matches) setSidebarOpen(!$('app-shell').classList.contains('sidebar-open'));
    else setSidebarCollapsed(!$('app-shell').classList.contains('sidebar-collapsed'));
  };
  $('sidebar-backdrop').onclick = () => setSidebarOpen(false);
  $('open-output').onclick = async () => { try { await invoke('open_output_folder'); } catch (e) { toast(`無法開啟作品集：${e}`); } };
  $('upload-images').onclick = chooseImages;
  $('send').onclick = submitPrompt;
  $('cancel-generation').onclick = cancelGeneration;
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
  for (const id of ['svi-prompt-2', 'svi-prompt-3']) $(id).addEventListener('input', resizePrompt);
  $('negative-prompt').addEventListener('input', () => {
    const values = currentParameters();
    if (state.studioMode === 'svi_image' && !$('negative-prompt').value) delete values.negative;
    else values.negative = $('negative-prompt').value;
    state.generation[parameterKey()] = values;
    resizePrompt();
  });
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
