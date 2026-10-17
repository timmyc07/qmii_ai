'use strict';

const studioTools = (action, value = {}) => invoke('studio_tools', { action, value });
const storageSize = value => value === null ? '讀取失敗' : `${(value / 1024 ** 3).toFixed(2)} GiB`;

function openStudioMaintenance() {
  const panel = openModal('健檢與儲存管理', `
    <button id="refresh-health" class="secondary-button">重新健檢</button><div id="workflow-health" role="status">正在檢查…</div>
    <hr><h3>儲存用量</h3><button id="storage-scan" class="secondary-button">掃描用量</button><div id="storage-usage" role="status"></div>
    <h3>過期作品清理</h3><p class="settings-tip">只處理已結束任務的日期資料夾作品。先預覽，再確認刪除；模型、設定、雲端檔案與進行中的任務不在清理範圍。</p>
    <label class="form-field"><span>清理多久以前的作品（天）</span><input id="cleanup-days" type="number" min="1" max="3650" step="1" value="30" required></label>
    <button id="cleanup-preview" class="secondary-button">預覽清理清單</button><div id="cleanup-summary" role="status"></div>
    <button id="cleanup-confirm" class="danger-button hidden">確認刪除預覽中的作品</button>`);
  let preview = null;
  const refreshHealth = async () => {
    const button = panel.querySelector('#refresh-health'); button.disabled = true;
    try {
      const report = await studioTools('health');
      if (!panel.isConnected) return;
      panel.querySelector('#workflow-health').innerHTML = `<p class="settings-tip">${escapeHtml(report.note)}</p>` + report.workflows.map(item => `<details class="maintenance-item"><summary>${escapeHtml(item.name)} · ${item.ready ? item.runtime_checked || ['quick', 'reference'].includes(item.workflow) ? '已就緒' : '檔案齊全，服務節點待確認' : '需要處理'}</summary>
        ${[...item.missing, ...item.missing_nodes.map(name => '缺少節點：' + name)].map(name => `<p>${escapeHtml(name)}</p>`).join('')}
        <p>安裝／修復方式：<code>${escapeHtml(item.repair)}</code></p></details>`).join('') +
        Object.values(report.runtimes).map(runtime => `<p class="settings-tip">ComfyUI ${escapeHtml(runtime.system?.comfyui_version || '未知版本')} · RAM 可用 ${storageSize(runtime.system?.ram_free ?? null)}${(runtime.devices || []).map(device => `<br>${escapeHtml(device.name)} · 顯存可用 ${storageSize(device.vram_free)}`).join('')}</p>`).join('');
    } catch (error) { panel.querySelector('#workflow-health').textContent = String(error); }
    finally { button.disabled = false; }
  };
  panel.querySelector('#refresh-health').onclick = refreshHealth;
  panel.querySelector('#storage-scan').onclick = async event => {
    const button = event.currentTarget; button.disabled = true;
    panel.querySelector('#storage-usage').textContent = '正在掃描檔案大小…';
    try {
      const value = await studioTools('storage');
      panel.querySelector('#storage-usage').innerHTML = `<p>作品磁碟可用：${storageSize(value.free_bytes)}</p><ul>${value.items.map(item => `<li>${escapeHtml(item.name)}：${item.available ? storageSize(item.bytes) : item.bytes === null ? '讀取失敗' : '尚未建立'}</li>`).join('')}</ul><p class="settings-tip">${escapeHtml(value.note)}</p>`;
    } catch (error) { panel.querySelector('#storage-usage').textContent = String(error); }
    finally { button.disabled = false; }
  };
  panel.querySelector('#cleanup-days').oninput = () => { preview = null; panel.querySelector('#cleanup-confirm').classList.add('hidden'); panel.querySelector('#cleanup-summary').textContent = '天數已變更，請重新預覽。'; };
  panel.querySelector('#cleanup-preview').onclick = async event => {
    const input = panel.querySelector('#cleanup-days'); if (!input.reportValidity()) return;
    const button = event.currentTarget; button.disabled = true; preview = null;
    panel.querySelector('#cleanup-confirm').classList.add('hidden');
    try {
      preview = await studioTools('preview', { days: Number(input.value) });
      panel.querySelector('#cleanup-summary').innerHTML = `<p>${preview.count} 個作品，共 ${storageSize(preview.bytes)}。刪除後無法從本機復原。</p><details><summary>完整檔案清單</summary><ul>${preview.files.map(name => `<li>${escapeHtml(name)}</li>`).join('')}</ul></details>`;
      panel.querySelector('#cleanup-confirm').classList.toggle('hidden', !preview.count);
    } catch (error) { panel.querySelector('#cleanup-summary').textContent = String(error); }
    finally { button.disabled = false; }
  };
  panel.querySelector('#cleanup-confirm').onclick = async event => {
    if (!preview) return;
    const button = event.currentTarget; button.disabled = true;
    try {
      const result = await studioTools('cleanup', { token: preview.token }); preview = null;
      panel.querySelector('#cleanup-summary').textContent = `已刪除 ${result.count} 個作品，釋放 ${storageSize(result.bytes)}；${result.failed.length} 個檔案無法刪除。已變動的檔案會略過。`;
      button.classList.add('hidden');
    } catch (error) { panel.querySelector('#cleanup-summary').textContent = String(error); }
    finally { button.disabled = false; }
  };
  refreshHealth();
}

function captureRecipe() {
  const h3 = state.studioMode === 'h3_image', svi = state.studioMode === 'svi_image';
  const parameters = h3 ? videoParameters() : svi ? sviParameters() : { ...currentParameters(), negative: $('negative-prompt').value };
  if (svi) parameters.segment_prompts = [promptInput.value, $('svi-prompt-2').value, $('svi-prompt-3').value];
  return { workflow: h3 || svi ? state.studioMode : state.workflow,
    prompt: svi ? parameters.segment_prompts.map((text, i) => `第 ${i + 1} 段：\n${text}`).join('\n\n') : promptInput.value,
    parameters, precise_mode: !h3 && !svi && state.preciseMode };
}

function applyRecipe(recipe) {
  const mode = ['h3_image', 'svi_image'].includes(recipe.workflow) ? recipe.workflow : 'image';
  setStudioMode(mode);
  state.generation[recipe.workflow] = structuredClone(recipe.parameters);
  state.images = []; state.videoLastImage = null;
  $('video-last-preview').replaceChildren();
  if (mode === 'image') { state.workflow = recipe.workflow; state.preciseMode = recipe.precise_mode; renderParameters(); renderPreciseState(); }
  if (mode === 'h3_image') loadVideoParameters(recipe.parameters);
  if (mode === 'svi_image') {
    $('svi-seed').value = recipe.parameters.seed ?? ''; renderSviLoras();
    $('svi-prompt-2').value = recipe.parameters.segment_prompts[1]; $('svi-prompt-3').value = recipe.parameters.segment_prompts[2];
  }
  promptInput.value = mode === 'svi_image' ? recipe.parameters.segment_prompts[0] : recipe.prompt;
  $('negative-prompt').value = recipe.parameters.negative || '';
  renderImageTray(); resizePrompt();
  modalRoot.querySelector('.modal-close')?.click();
  toast('已套用配方，請重新選擇圖片與尾幀後送出');
}

async function openGenerationRecipes(source = null) {
  if (state.generating) { toast('請等待目前任務結束後再套用配方'); return; }
  const value = source ? { workflow: source.workflow, prompt: source.prompt, parameters: source.parameters, precise_mode: source.precise_mode } : captureRecipe();
  const panel = openModal('生成配方', `<p class="settings-tip">保存提示詞、模式、參數與 LoRA 選擇。套用後可調整再送出；附件需要重新選擇。</p>
    <label class="form-field"><span>配方名稱</span><input id="recipe-name" required maxlength="100" placeholder="替這組設定命名"></label>
    <button id="recipe-save" class="primary-button">${source ? '儲存此任務設定' : '儲存目前設定'}</button><div id="generation-recipe-list" role="status">正在讀取…</div>`);
  const render = items => {
    panel.querySelector('#generation-recipe-list').innerHTML = items.length ? items.map(item => `<div class="recipe-row"><button class="secondary-button" data-recipe-apply="${item.id}">${escapeHtml(item.name)}</button><button class="danger-button" data-recipe-delete="${item.id}">刪除</button></div>`).join('') : '<p class="settings-tip">還沒有生成配方。</p>';
    panel.querySelectorAll('[data-recipe-apply]').forEach(button => button.onclick = () => applyRecipe(items.find(item => item.id === button.dataset.recipeApply)));
    panel.querySelectorAll('[data-recipe-delete]').forEach(button => button.onclick = async () => {
      button.disabled = true;
      try { render((await studioTools('delete_recipe', { id: button.dataset.recipeDelete })).recipes); }
      catch (error) { button.disabled = false; toast(String(error)); }
    });
  };
  panel.querySelector('#recipe-save').onclick = async event => {
    const input = panel.querySelector('#recipe-name'); if (!input.reportValidity()) return;
    const button = event.currentTarget; button.disabled = true;
    try { render((await studioTools('save_recipe', { ...value, name: input.value.trim() })).recipes); toast('已儲存生成配方'); }
    catch (error) { toast(String(error)); }
    finally { button.disabled = false; }
  };
  try { render((await studioTools('recipes')).recipes); }
  catch (error) { panel.querySelector('#generation-recipe-list').textContent = String(error); }
}
