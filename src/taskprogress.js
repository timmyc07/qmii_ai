'use strict';

window.qianmiProgress = (() => {
  const active = status => ['uploading', 'queued', 'running', 'cancelling'].includes(status);
  const duration = value => {
    const seconds = Math.max(0, Math.ceil(value));
    if (seconds < 60) return `${seconds} 秒`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
    return `${Math.floor(seconds / 3600)} 小時 ${Math.floor(seconds % 3600 / 60)} 分`;
  };
  function tick(element) {
    const { job, received } = element.taskProgress;
    const progress = job.progress || {}, live = active(job.status), sampling = job.status === 'running' ? progress.sampling : null;
    const since = (performance.now() - received) / 1000;
    const delta = live ? since : 0;
    const elapsed = (progress.elapsed_seconds || 0) + delta;
    const details = [progress.elapsed_seconds == null ? '耗時尚未記錄' : `${job.status === 'queued' ? '已等待' : '已耗時'} ${duration(elapsed)}`];
    if (progress.total) details.push(`已完成 ${progress.completed}/${progress.total} 個輸出`);
    const sampleText = element.querySelector('.task-sampling'), meter = element.querySelector('.task-meter');
    const sampleTitle = sampling?.total ? `${sampling.label}：第 ${sampling.step} / ${sampling.total} 步` : '';
    if (sampleText.textContent !== sampleTitle) sampleText.textContent = sampleTitle;
    sampleText.hidden = meter.hidden = !sampleTitle;
    if (sampleTitle) { meter.max = sampling.total; meter.value = sampling.step; meter.setAttribute('aria-label', sampleTitle); }
    let hint = '';
    if (live && since >= 15) {
      hint = `已 ${duration(since)}未收到主機更新，正在等待回應；請勿重複提交，可在共用任務確認狀態。`;
    } else if (job.status === 'queued') {
      if (progress.queue_position) details.push(`排隊第 ${progress.queue_position} 位（前方 ${progress.queue_position - 1} 個任務）`);
      hint = job.billing_status === 'pending' ? '正在確認點數，連線恢復後會自動繼續。' : '開始執行後顯示剩餘時間，等待時間取決於前方任務。';
    } else if (job.status === 'cancelling') {
      hint = '正在等待模型確認停止，已完成的作品會保留。';
    } else if (job.status === 'running') {
      if (sampling) {
        const age = (sampling.age_seconds || 0) + delta;
        if (sampling.state === 'disconnected') {
          hint = '即時採樣連線中斷，正在重新連線；生成任務仍由主機管理。';
        } else if (sampling.state === 'complete' || sampling.state === 'paused') {
          details.push(sampling.state === 'complete' ? '本輪採樣完成，任務仍在進行' : '採樣階段已切換');
        } else if (age > Math.max(60, (sampling.seconds_per_step || 0) * 3)) {
          hint = '尚未收到新的採樣步數，正在等待引擎回報。';
        } else if (sampling.seconds_per_step != null) {
          details.push(`每步約 ${sampling.seconds_per_step.toFixed(2)} 秒`);
        } else {
          details.push('採樣速度估算中…');
        }
      }
      if (!hint && progress.remaining_seconds != null) {
        const remaining = progress.remaining_seconds - delta;
        details.push(remaining > 0 ? `整個任務預計剩餘約 ${duration(remaining)}` : '已超過整體估時，任務仍在處理');
        hint = progress.estimate_basis === 'speed'
          ? '已包含所有後續採樣、解碼、存檔與資源釋放，依本次實測速度與完整任務紀錄持續校正。'
          : `依本機最近 ${progress.sample_count} 次完整任務估算，包含後續採樣、解碼與存檔；正在累積各階段速度紀錄。`;
      } else if (!hint) {
        details.push('整體估時校準中');
        hint = '尚缺相同設定的完整階段紀錄，完成本次任務後可估算所有採樣、解碼與存檔的剩餘時間。';
      }
    } else if (job.status === 'uploading') {
      hint = '正在連線工作室並傳送資料，接著會顯示排隊位置與生成階段。';
    } else if (job.billing_status === 'reserved') {
      hint = '點數結算待連線，自動重試中。';
    }
    element.querySelector('.task-timing').textContent = details.join(' · ');
    element.querySelector('.task-hint').textContent = hint;
    element.querySelector('.task-hint').hidden = !hint;
  }
  function render(element, job) {
    if (!element.hasAttribute('data-task-progress')) {
      element.setAttribute('data-task-progress', '');
      element.classList.add('task-progress');
      element.innerHTML = '<div class="task-heading"><span class="task-spinner" aria-hidden="true"></span><span class="task-stage" role="status"></span></div><p class="task-sampling" role="status" hidden></p><progress class="task-meter" hidden></progress><p class="task-timing" aria-live="off"></p><p class="task-hint" aria-live="off"></p>';
    }
    element.taskProgress = { job, received: performance.now() };
    const title = `${active(job.status) ? '目前階段：' : ''}${job.message}`;
    const stage = element.querySelector('.task-stage');
    if (stage.textContent !== title) stage.textContent = title;
    element.querySelector('.task-spinner').hidden = !active(job.status);
    tick(element);
  }
  setInterval(() => document.querySelectorAll('[data-task-progress]').forEach(element => {
    if (element.taskProgress && active(element.taskProgress.job.status)) tick(element);
  }), 1000);
  return { render };
})();
