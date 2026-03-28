/* Claude Usage Bar - Modern UI (JavaScript) */

let usageChart = null;
let currentRange = '6h';
let countdownTimer = null;
let cachedUsage = null;
let pollTimer = null;

// Determine mode from URL params
const urlParams = new URLSearchParams(window.location.search);
const appMode = urlParams.get('mode') || 'popup';  // 'popup' or 'widget'

// ── Color helpers ──

function pctColor(pct) {
  if (pct < 0.50) return '#34d399';
  if (pct < 0.75) return '#fbbf24';
  if (pct < 0.90) return '#fb923c';
  return '#f43f5e';
}

function formatRelativeTime(isoStr) {
  if (!isoStr) return '';
  const target = new Date(isoStr);
  const now = new Date();
  let diff = Math.floor((target - now) / 1000);
  if (diff < 0) return 'Expired';
  const days = Math.floor(diff / 86400); diff %= 86400;
  const hours = Math.floor(diff / 3600); diff %= 3600;
  const mins = Math.floor(diff / 60);
  const parts = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  if (mins > 0 && days === 0) parts.push(`${mins}m`);
  return parts.length ? 'Resets ' + parts.join(' ') : 'Resets < 1m';
}

function formatUpdatedTime(isoStr) {
  if (!isoStr) return 'Updated --';
  const d = new Date(isoStr);
  const now = new Date();
  const diffSec = Math.floor((now - d) / 1000);
  if (diffSec < 60) return 'Updated just now';
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `Updated ${mins}m ago`;
  const hours = Math.floor(mins / 60);
  return `Updated ${hours}h ago`;
}

// ── API calls (REST) ──

async function apiGet(path) {
  try {
    const res = await fetch(path);
    return await res.json();
  } catch (e) {
    console.error(`GET ${path} failed:`, e);
    return null;
  }
}

async function apiPost(path, body = {}) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return await res.json();
  } catch (e) {
    console.error(`POST ${path} failed:`, e);
    return null;
  }
}

// ── Data refresh ──

async function refreshData() {
  const usage = await apiGet('/api/usage');
  if (!usage) return;
  cachedUsage = usage;

  const signinEl = document.getElementById('signin-section');
  const usageEl = document.getElementById('usage-section');
  const codeEntry = document.getElementById('code-entry');
  const errorMsg = document.getElementById('error-msg');

  if (!usage.is_authenticated) {
    signinEl.style.display = '';
    usageEl.style.display = 'none';
    codeEntry.style.display = usage.is_awaiting_code ? '' : 'none';
    errorMsg.textContent = usage.last_error || '';
    return;
  }

  signinEl.style.display = 'none';
  usageEl.style.display = '';

  // 5-Hour
  updateBucket('5h', usage.pct_5h, usage.reset_5h, usage.util_5h);
  // 7-Day
  updateBucket('7d', usage.pct_7d, usage.reset_7d, usage.util_7d);

  // Model breakdown
  const modelSection = document.getElementById('model-breakdown');
  const hasModels = usage.opus_util !== null || usage.sonnet_util !== null;
  modelSection.style.display = hasModels ? '' : 'none';

  if (usage.opus_util !== null) {
    document.getElementById('bucket-opus').style.display = '';
    const opusPct = usage.opus_util / 100;
    document.getElementById('pct-opus').textContent = `${Math.round(usage.opus_util)}%`;
    document.getElementById('pct-opus').style.color = pctColor(opusPct);
    const barOpus = document.getElementById('bar-opus');
    barOpus.style.width = `${Math.max(1, usage.opus_util)}%`;
    barOpus.style.background = pctColor(opusPct);
  } else {
    document.getElementById('bucket-opus').style.display = 'none';
  }

  if (usage.sonnet_util !== null) {
    document.getElementById('bucket-sonnet').style.display = '';
    const sonnetPct = usage.sonnet_util / 100;
    document.getElementById('pct-sonnet').textContent = `${Math.round(usage.sonnet_util)}%`;
    document.getElementById('pct-sonnet').style.color = pctColor(sonnetPct);
    const barSonnet = document.getElementById('bar-sonnet');
    barSonnet.style.width = `${Math.max(1, usage.sonnet_util)}%`;
    barSonnet.style.background = pctColor(sonnetPct);
  } else {
    document.getElementById('bucket-sonnet').style.display = 'none';
  }

  // Extra usage
  const extraEl = document.getElementById('extra-section');
  if (usage.extra_enabled) {
    extraEl.style.display = '';
    document.getElementById('extra-amount').textContent =
      `${usage.extra_used_str} / ${usage.extra_limit_str}`;
    const extraPct = (usage.extra_util || 0) / 100;
    const barExtra = document.getElementById('bar-extra');
    barExtra.style.width = `${Math.max(1, usage.extra_util || 0)}%`;
    barExtra.style.background = pctColor(extraPct);
  } else {
    extraEl.style.display = 'none';
  }

  // Updated time
  document.getElementById('updated-text').textContent = formatUpdatedTime(usage.last_updated);

  // Account email
  if (usage.account_email) {
    document.getElementById('account-email').textContent = usage.account_email;
  }

  // Error
  errorMsg.textContent = usage.last_error || '';

  // Refresh chart
  await refreshChart();
}

function updateBucket(key, pct, resetIso, util) {
  const pctEl = document.getElementById(`pct-${key}`);
  const barEl = document.getElementById(`bar-${key}`);
  const resetEl = document.getElementById(`reset-${key}`);

  const utilVal = util !== null && util !== undefined ? Math.round(util) : '--';
  pctEl.textContent = `${utilVal}%`;
  const color = pct > 0 ? pctColor(pct) : '#606078';
  pctEl.style.color = color;

  const widthPct = Math.max(0, Math.min(100, pct * 100));
  barEl.style.width = `${Math.max(widthPct > 0 ? 3 : 0, widthPct)}%`;
  barEl.style.background = pct > 0 ? pctColor(pct) : '#2a2a42';

  resetEl.textContent = formatRelativeTime(resetIso);
  resetEl.style.color = pct > 0 ? pctColor(pct) : '#606078';
}

// ── Chart ──

function initChart() {
  const ctx = document.getElementById('usage-chart').getContext('2d');
  usageChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: '5h',
          data: [],
          borderColor: '#60a5fa',
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0,
          fill: false,
        },
        {
          label: '7d',
          data: [],
          borderColor: '#fb923c',
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          backgroundColor: '#1e1e2e',
          titleColor: '#e8e8f0',
          bodyColor: '#b0b0c8',
          borderColor: '#2e2e48',
          borderWidth: 1,
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${(ctx.parsed.y).toFixed(1)}%`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: '#2e2e48', drawBorder: false },
          ticks: { color: '#606078', font: { size: 10 }, maxTicksLimit: 4 },
        },
        y: {
          min: 0,
          max: 100,
          grid: {
            color: '#2e2e48',
            drawBorder: false,
            borderDash: [2, 4],
          },
          ticks: {
            color: '#606078',
            font: { size: 10 },
            stepSize: 25,
            callback: (v) => `${v}%`,
          },
        },
      },
      interaction: { mode: 'nearest', axis: 'x', intersect: false },
    },
  });
}

async function refreshChart() {
  const history = await apiGet(`/api/history/${currentRange}`);
  if (!history || !usageChart) return;

  const labels = history.map(p => {
    const d = new Date(p.timestamp);
    if (currentRange === '1h' || currentRange === '6h') {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: '2-digit', day: '2-digit' });
  });

  usageChart.data.labels = labels;
  usageChart.data.datasets[0].data = history.map(p => p.pct_5h * 100);
  usageChart.data.datasets[1].data = history.map(p => p.pct_7d * 100);
  usageChart.update('none');
}

// ── Range selector ──

document.getElementById('range-selector').addEventListener('click', (e) => {
  const btn = e.target.closest('.range-btn');
  if (!btn) return;
  document.querySelectorAll('.range-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  currentRange = btn.dataset.range;
  refreshChart();
});

// ── Polling selector ──

document.getElementById('poll-selector').addEventListener('click', (e) => {
  const btn = e.target.closest('.poll-btn');
  if (!btn) return;
  document.querySelectorAll('.poll-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const minutes = parseInt(btn.dataset.minutes);
  apiPost('/api/settings/polling', { minutes });
});

// ── Actions ──

async function signIn() {
  await apiPost('/api/sign-in');
  document.getElementById('code-entry').style.display = '';
}

async function submitCode() {
  const input = document.getElementById('code-input');
  const code = input.value.trim();
  if (!code) return;
  const result = await apiPost('/api/submit-code', { code });
  if (result && result.success) {
    input.value = '';
    await refreshData();
  } else {
    document.getElementById('error-msg').textContent =
      (result && result.error) || 'Failed to submit code';
  }
}

async function signOut() {
  await apiPost('/api/sign-out');
  hideSettings();
  await refreshData();
}

async function refresh() {
  await apiPost('/api/refresh');
  setTimeout(refreshData, 1500);
}

async function quit() {
  await apiPost('/api/quit');
}

function closeWindow() {
  window.close();
}

// ── Startup toggle ──

async function toggleStartup(checked) {
  await apiPost('/api/settings/startup', { enabled: checked });
  document.getElementById('settings-startup-toggle').checked = checked;
}

// ── Settings view ──

function showSettings() {
  document.getElementById('main-view').classList.add('hidden');
  document.getElementById('settings-view').classList.add('active');
  loadSettings();
}

function hideSettings() {
  document.getElementById('main-view').classList.remove('hidden');
  document.getElementById('settings-view').classList.remove('active');
}

async function loadSettings() {
  const settings = await apiGet('/api/settings');
  if (!settings) return;

  document.getElementById('settings-startup-toggle').checked = settings.startup_enabled;

  document.querySelectorAll('.poll-btn').forEach(btn => {
    btn.classList.toggle('active', parseInt(btn.dataset.minutes) === settings.polling_minutes);
  });

  setSlider('5h', settings.threshold_5h);
  setSlider('7d', settings.threshold_7d);
  setSlider('extra', settings.threshold_extra);

  if (settings.account_email) {
    document.getElementById('account-email').textContent = settings.account_email;
  }
}

function styleSliderTrack(slider) {
  const pct = (slider.value - slider.min) / (slider.max - slider.min) * 100;
  slider.style.background = `linear-gradient(to right, #7c3aed ${pct}%, #2a2a42 ${pct}%)`;
}

function setSlider(key, value) {
  const slider = document.getElementById(`slider-${key}`);
  slider.value = value;
  styleSliderTrack(slider);
  document.getElementById(`val-${key}`).textContent = value > 0 ? `${value}%` : 'Off';
}

function updateSlider(key, value) {
  const v = parseInt(value);
  const slider = document.getElementById(`slider-${key}`);
  styleSliderTrack(slider);
  document.getElementById(`val-${key}`).textContent = v > 0 ? `${v}%` : 'Off';
  apiPost('/api/settings/threshold', { key, value: v });
}

// ── Countdown timer ──

function updateCountdowns() {
  if (!cachedUsage) return;
  if (cachedUsage.reset_5h)
    document.getElementById('reset-5h').textContent = formatRelativeTime(cachedUsage.reset_5h);
  if (cachedUsage.reset_7d)
    document.getElementById('reset-7d').textContent = formatRelativeTime(cachedUsage.reset_7d);
  document.getElementById('updated-text').textContent =
    formatUpdatedTime(cachedUsage.last_updated);
}

// ── Init ──

document.addEventListener('DOMContentLoaded', async () => {
  // Apply mode-specific behavior
  if (appMode === 'popup') {
    // Hide title bar in popup mode
    const titleBar = document.getElementById('main-title-bar');
    if (titleBar) titleBar.style.display = 'none';
    // Add top padding to content
    document.querySelector('.content').style.paddingTop = '12px';

    // Auto-hide when losing focus (popover behavior)
    window.addEventListener('blur', () => {
      setTimeout(() => {
        if (!document.hasFocus()) {
          fetch('/api/hide', { method: 'POST' }).catch(() => {});
        }
      }, 200);
    });
  }

  initChart();
  await refreshData();
  countdownTimer = setInterval(updateCountdowns, 1000);
  // Poll for updates every 15 seconds
  pollTimer = setInterval(refreshData, 15000);
});
