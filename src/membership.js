(() => {
  'use strict';
  const desktop = Boolean(window.__TAURI__);
  const button = document.getElementById('account-button');
  let csrf = '', account = null, config = {}, ledgerOffset = 0, memberOffset = 0, auditOffset = 0;
  let busy = false;
  const dialog = document.createElement('dialog'); dialog.className = 'membership-dialog';
  dialog.innerHTML = `<div class="membership-heading"><h2>會員與點數</h2><button type="button" data-close aria-label="關閉會員中心">✕</button></div><p data-prices></p><p data-message role="status"></p><div data-content></div>`;
  document.body.append(dialog);
  const content = dialog.querySelector('[data-content]'), message = dialog.querySelector('[data-message]');
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const field = (name, title, type = 'text', extra = '') => `<label>${title}<input name="${name}" type="${type}" required ${extra}></label>`;
  const password = (name = 'password', title = '密碼（至少 10 個字元）', autocomplete = 'new-password') => field(name, title, 'password', `minlength="10" maxlength="128" autocomplete="${autocomplete}"`);
  const credentials = () => field('email', '電子郵件', 'email', 'maxlength="254" autocomplete="username"') + password('password', '密碼（至少 10 個字元）', 'current-password');
  const time = value => new Date(value * 1000).toLocaleString('zh-TW', { hour12: false });

  async function call(action, value = {}) {
    if (desktop) return window.__TAURI__.core.invoke('membership', { action, value });
    const routes = { config: ['GET', '/api/membership'], me: ['GET', '/api/membership/me'],
      login: ['POST', '/api/membership/login'], register: ['POST', '/api/membership/register'],
      logout: ['POST', '/api/logout'], password: ['POST', '/api/membership/password'], reset: ['POST', '/api/membership/reset'],
      ledger: ['GET', '/api/membership/ledger'], members: ['GET', '/api/admin/members'], audit: ['GET', '/api/admin/audit'],
      settings: ['PUT', '/api/admin/membership'] };
    let route = routes[action];
    value = { ...value };
    if (['update', 'credits', 'issue_reset'].includes(action)) {
      const id = encodeURIComponent(value.id); delete value.id;
      route = [action === 'update' ? 'PUT' : 'POST', `/api/admin/members/${id}${{ update: '', credits: '/credits', issue_reset: '/reset' }[action]}`];
    }
    const [method, path] = route;
    if (!csrf && !['config', 'login', 'register', 'reset'].includes(action)) {
      const session = await fetch('/api/session').then(r => r.json()); csrf = session.csrf || '';
    }
    const response = await fetch(path + (method === 'GET' && Object.keys(value).length ? '?' + new URLSearchParams(value) : ''), {
      method, headers: { 'Content-Type': 'application/json', 'X-Qianmi-CSRF': csrf },
      ...(method === 'GET' ? {} : { body: JSON.stringify(value) })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || '會員操作失敗。');
    if (result.csrf) csrf = result.csrf;
    return result;
  }

  function pricing() {
    dialog.querySelector('[data-prices]').textContent = `照片每張 ${config.image_points ?? 3} 點 · 影片每部 ${config.video_points ?? 10} 點。批次按輸出數量預扣，未完成輸出自動退點。`;
    button.textContent = account?.member ? `${account.member.name} · ${account.member.balance} 點` : '會員登入';
    const note = document.getElementById('member-price-note');
    if (note) note.textContent = `照片每張 ${config.image_points ?? 3} 點、影片每部 ${config.video_points ?? 10} 點。請先登入會員。`;
  }

  async function refresh() {
    config = await call('config');
    try { account = await call('me'); } catch { account = null; }
    pricing();
  }

  async function run(action) {
    if (busy) return;
    busy = true;
    message.textContent = '';
    dialog.setAttribute('aria-busy', 'true');
    try { await action(); } catch (error) { message.textContent = String(error.message || error); }
    finally { busy = false; dialog.removeAttribute('aria-busy'); }
  }

  async function sessionChanged() {
    await refresh();
    if (!desktop) {
      const response = await fetch('/api/session');
      window.dispatchEvent(new CustomEvent('membership-session', { detail: response.ok ? await response.json() : null }));
    }
  }

  function formHandler(selector, handler) {
    content.querySelector(selector).onsubmit = event => {
      event.preventDefault(); const form = event.currentTarget;
      run(() => handler(Object.fromEntries(new FormData(form)), form));
    };
  }

  function loginView() {
    content.innerHTML = `<form data-login>${credentials()}<button type="submit">登入會員</button></form>
      <div class="membership-actions"><button data-register type="button" ${!config.registration_open ? 'disabled' : ''}>註冊會員</button><button data-reset type="button">忘記密碼</button></div>
      ${desktop && !config.initialized ? `<details><summary>第一次使用：建立管理員</summary><form data-bootstrap>${field('name', '管理員名稱', 'text', 'maxlength="80" autocomplete="name"')}${credentials()}<button type="submit">建立管理員</button></form></details>` : ''}`;
    formHandler('[data-login]', async value => {
      await call('login', value); await sessionChanged(); await memberView();
    });
    content.querySelector('[data-register]').onclick = () => {
      content.innerHTML = `<p>註冊後點數為 0，請聯絡管理員儲值。</p><form data-register-form>${field('name', '會員名稱', 'text', 'maxlength="80" autocomplete="name"')}${field('email', '電子郵件', 'email', 'maxlength="254" autocomplete="username"')}${password()}<button type="submit">建立會員</button></form><button data-back type="button">返回登入</button>`;
      content.querySelector('[data-back]').onclick = loginView;
      formHandler('[data-register-form]', async value => { await call('register', value); await sessionChanged(); await memberView(); });
    };
    content.querySelector('[data-reset]').onclick = () => {
      content.innerHTML = `<p>請聯絡管理員取得單次重設碼，30 分鐘內有效。</p><form data-reset-form>${field('token', '重設碼', 'password', 'maxlength="128" autocomplete="off"')}${password()}<button type="submit">重設密碼</button></form><button data-back type="button">返回登入</button>`;
      content.querySelector('[data-back]').onclick = loginView;
      formHandler('[data-reset-form]', async value => { await call('reset', value); await sessionChanged(); loginView(); message.textContent = '密碼已重設，請重新登入。'; });
    };
    if (content.querySelector('[data-bootstrap]')) formHandler('[data-bootstrap]', async value => {
      await call('bootstrap', value); await refresh(); loginView(); message.textContent = '管理員已建立，請使用剛才的帳號登入。';
    });
  }

  async function memberView() {
    if (!account?.member && !account?.owner) { loginView(); return; }
    const member = account.member, admin = account.owner || member?.role === 'admin';
    content.innerHTML = `<p>${member ? `<strong>${escape(member.name)}</strong> · ${escape(member.email)}<br>可用點數：<strong>${member.balance}</strong> 點 · ${member.role === 'admin' ? '管理員' : '一般會員'}` : '私人主機管理連線（免點數），可管理會員。'}</p>
      <div class="membership-actions"><button data-refresh type="button">更新餘額</button>${admin ? '<button data-admin type="button">會員管理</button>' : ''}<button data-logout type="button">登出</button></div>
      ${member ? `<h3>點數紀錄</h3><div data-ledger></div><div class="membership-actions"><button data-prev type="button">上一頁</button><button data-next type="button">下一頁</button></div>
      <details><summary>修改密碼</summary><p>修改後全部設備登出，請重新登入。</p><form data-password>${password('current_password', '目前密碼', 'current-password')}${password()}<button type="submit">更新密碼並登出</button></form></details>` : ''}`;
    content.querySelector('[data-refresh]').onclick = () => run(async () => { await refresh(); await memberView(); });
    content.querySelector('[data-logout]').onclick = () => run(async () => { await call('logout'); csrf = ''; await sessionChanged(); loginView(); });
    if (admin) content.querySelector('[data-admin]').onclick = () => run(adminView);
    if (!member) return;
    const loadLedger = async () => {
      const result = await call('ledger', { offset: ledgerOffset });
      content.querySelector('[data-ledger]').innerHTML = result.items.length ? `<ul class="membership-ledger">${result.items.map(row => `<li><span>${escape(row.reason)}<small>${time(row.created)}</small></span><strong>${row.amount > 0 ? '+' : ''}${row.amount}<small>餘額 ${row.balance}</small></strong></li>`).join('')}</ul>` : '<p>尚無點數紀錄。</p>';
      content.querySelector('[data-prev]').disabled = ledgerOffset === 0;
      content.querySelector('[data-next]').disabled = result.items.length < 50;
    };
    content.querySelector('[data-prev]').onclick = () => run(async () => { ledgerOffset = Math.max(0, ledgerOffset - 50); await loadLedger(); });
    content.querySelector('[data-next]').onclick = () => run(async () => { ledgerOffset += 50; await loadLedger(); });
    formHandler('[data-password]', async value => { await call('password', value); csrf = ''; await sessionChanged(); loginView(); message.textContent = '密碼已更新，請重新登入。'; });
    await loadLedger();
  }

  async function adminView() {
    content.innerHTML = `<button data-back type="button">返回會員中心</button><h3>會員管理</h3>
      <form data-search>${field('search', '搜尋會員', 'search', 'maxlength="100"')}<button type="submit">搜尋</button></form><div data-members></div>
      <div class="membership-actions"><button data-prev type="button">上一頁</button><button data-next type="button">下一頁</button></div>
      <h3>使用規則</h3><form data-config><label class="membership-check"><input type="checkbox" name="registration_open" ${config.registration_open ? 'checked' : ''}>開放會員註冊</label>
      ${field('image_points', '照片每張點數', 'number', `min="1" max="10000" step="1" value="${config.image_points}"`)}${field('video_points', '影片每部點數', 'number', `min="1" max="10000" step="1" value="${config.video_points}"`)}<button type="submit">儲存使用規則</button></form>
      <h3>管理與點數稽核紀錄</h3><button data-audit type="button">載入最新紀錄</button><div data-audit-list></div><div class="membership-actions"><button data-audit-prev type="button">上一頁</button><button data-audit-next type="button">下一頁</button></div>`;
    content.querySelector('[data-back]').onclick = () => run(async () => { await refresh(); await memberView(); });
    const load = async (search = content.querySelector('[name=search]').value) => {
      const result = await call('members', { search, offset: memberOffset });
      content.querySelector('[data-members]').innerHTML = result.items.map(member => `<article class="membership-member"><p><strong>${escape(member.name)}</strong> · ${escape(member.email)}<br>${member.balance} 點 · ${member.role === 'admin' ? '管理員' : '會員'} · ${member.active ? '啟用' : '停用'}</p><div class="membership-actions"><button type="button" data-edit="${member.id}">管理帳號</button></div></article>`).join('') || '<p>沒有符合的會員。</p>';
      content.querySelectorAll('[data-edit]').forEach(b => b.onclick = () => run(() => editMember(result.items.find(m => m.id === b.dataset.edit))));
      content.querySelector('[data-prev]').disabled = memberOffset === 0; content.querySelector('[data-next]').disabled = result.items.length < 100;
    };
    content.querySelector('[name=search]').required = false;
    formHandler('[data-search]', async value => { memberOffset = 0; await load(value.search); });
    content.querySelector('[data-prev]').onclick = () => run(async () => { memberOffset = Math.max(0, memberOffset - 100); await load(); });
    content.querySelector('[data-next]').onclick = () => run(async () => { memberOffset += 100; await load(); });
    formHandler('[data-config]', async value => {
      await call('settings', { registration_open: value.registration_open === 'on', image_points: Number(value.image_points), video_points: Number(value.video_points) });
      await refresh(); message.textContent = '使用規則已儲存，已預扣的任務維持提交時價格。';
    });
    const audit = async () => {
      const value = await call('audit', { offset: auditOffset });
      content.querySelector('[data-audit-list]').innerHTML = `<details open><summary>帳號與設定操作</summary>${value.items.map(row => `<p>${time(row.created)} · ${escape(row.action)}<small>會員 ${escape(row.member_id || '—')} · 操作者 ${escape(row.actor || '主機')}</small></p>`).join('') || '<p>無紀錄</p>'}</details><details><summary>點數流水</summary>${value.ledger.map(row => `<p>${time(row.created)} · ${row.amount > 0 ? '+' : ''}${row.amount} · ${escape(row.reason)}<small>會員 ${escape(row.member_id)} · 餘額 ${row.balance} · 任務 ${escape(row.job_id || '—')}</small></p>`).join('') || '<p>無紀錄</p>'}</details>`;
      content.querySelector('[data-audit-prev]').disabled = auditOffset === 0;
      content.querySelector('[data-audit-next]').disabled = Math.max(value.items.length, value.ledger.length) < 100;
    };
    content.querySelector('[data-audit]').onclick = () => run(async () => { auditOffset = 0; await audit(); });
    content.querySelector('[data-audit-prev]').onclick = () => run(async () => { auditOffset = Math.max(0, auditOffset - 100); await audit(); });
    content.querySelector('[data-audit-next]').onclick = () => run(async () => { auditOffset += 100; await audit(); });
    await load();
  }

  async function editMember(member) {
    content.innerHTML = `<button data-back type="button">返回管理列表</button><h3>${escape(member.name)}</h3><p>${escape(member.email)} · 可用 ${member.balance} 點</p>
      <form data-credits>${field('amount', '加扣點數（扣點填負數）', 'number', 'min="-1000000" max="1000000" step="1"')}${field('reason', '調整原因／儲值單號', 'text', 'maxlength="200"')}<button type="submit">確認調整點數</button></form>
      <hr><form data-status><label>會員角色<select name="role"><option value="member" ${member.role === 'member' ? 'selected' : ''}>一般會員</option><option value="admin" ${member.role === 'admin' ? 'selected' : ''}>管理員</option></select></label><label class="membership-check"><input type="checkbox" name="active" ${member.active ? 'checked' : ''}>帳號啟用</label><p>變更角色或啟用狀態會登出該會員全部設備。</p><button type="submit">儲存帳號權限</button></form>
      <hr><p>請自行驗證會員身分後，私下交付重設碼。</p><button data-issue-reset type="button">產生單次密碼重設碼</button><p data-reset-token role="status"></p>`;
    content.querySelector('[data-back]').onclick = () => run(adminView);
    let adjustmentId = crypto.randomUUID().replaceAll('-', '');
    const renewAdjustment = () => { adjustmentId = crypto.randomUUID().replaceAll('-', ''); };
    content.querySelector('[data-credits]').oninput = renewAdjustment;
    formHandler('[data-credits]', async (value, form) => {
      const updated = await call('credits', { id: member.id, amount: Number(value.amount), reason: value.reason, request_id: adjustmentId });
      await refresh(); await editMember(updated); message.textContent = '點數已調整。';
    });
    formHandler('[data-status]', async value => { await call('update', { id: member.id, role: value.role, active: value.active === 'on' }); await refresh(); if (account) await adminView(); else loginView(); message.textContent = '帳號權限已更新。'; });
    content.querySelector('[data-issue-reset]').onclick = () => run(async () => {
      const result = await call('issue_reset', { id: member.id });
      content.querySelector('[data-reset-token]').textContent = `重設碼（30 分鐘內單次有效，離開後不再顯示）：${result.token}`;
    });
  }

  button.onclick = () => { if (!dialog.open) dialog.showModal(); run(async () => { await refresh(); await memberView(); }); };
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { content.replaceChildren(); message.textContent = ''; });
  window.qianmiMembership = {
    async ensureCredit(workflow, count) {
      await refresh();
      if (account?.owner && !desktop) return 0;
      if (!account?.member) throw new Error('請先開啟「會員登入」並登入會員帳號。');
      const amount = (['h3_image', 'svi_image'].includes(workflow) ? config.video_points : config.image_points) * (['reference', 'svi_image'].includes(workflow) ? 1 : Math.max(1, count));
      if (account.member.balance < amount) throw new Error(`本次需要 ${amount} 點，目前餘額 ${account.member.balance} 點，請聯絡管理員儲值。`);
      return amount;
    },
    refresh
  };
  refresh().catch(() => {});
})();
