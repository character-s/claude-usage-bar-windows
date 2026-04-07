/* Claude Usage Bar - Modern UI (JavaScript) */

let usageChart = null;
let currentRange = '6h';
let countdownTimer = null;
let cachedUsage = null;
let gapThresholdMs = 30 * 60 * 1000 * 2.5; // polling_minutes * 2.5
let pollTimer = null;
let needsResize = false;
let prevContentHeight = 0;

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
  if (usage.polling_minutes) {
    gapThresholdMs = usage.polling_minutes * 60 * 1000 * 2.5;
  }

  const signinEl = document.getElementById('signin-section');
  const usageEl = document.getElementById('usage-section');
  const codeEntry = document.getElementById('code-entry');
  const errorMsg = document.getElementById('error-msg');

  // If neither provider is authenticated, show sign-in
  if (!usage.is_authenticated && !usage.codex_authenticated) {
    signinEl.style.display = '';
    usageEl.style.display = 'none';
    codeEntry.style.display = usage.is_awaiting_code ? '' : 'none';
    errorMsg.textContent = usage.last_error || '';
    return;
  }

  signinEl.style.display = 'none';
  usageEl.style.display = '';

  const primary = usage.primary_provider || 'claude';
  const dualMode = usage.dual_mode;
  const claudeAuth = usage.is_authenticated;
  const codexAuth = usage.codex_authenticated;

  // Primary section
  const claudePrimary = document.getElementById('claude-primary');
  const codexPrimary = document.getElementById('codex-primary');
  const chartSection = document.getElementById('chart-section');
  const primaryLabel = document.getElementById('primary-label');

  if (dualMode) {
    // Dual mode: show provider labels when both available
    const bothAvailable = claudeAuth && codexAuth;
    primaryLabel.style.display = bothAvailable ? '' : 'none';
    primaryLabel.textContent = primary === 'claude' ? 'Claude' : 'Codex';

    if (primary === 'claude' && claudeAuth) {
      claudePrimary.style.display = '';
      codexPrimary.style.display = 'none';
      updateClaudeBuckets(usage);
    } else if (primary === 'codex' && codexAuth) {
      claudePrimary.style.display = 'none';
      codexPrimary.style.display = '';
      updateCodexBuckets(usage, false);
    } else if (claudeAuth) {
      claudePrimary.style.display = '';
      codexPrimary.style.display = 'none';
      updateClaudeBuckets(usage);
    } else if (codexAuth) {
      claudePrimary.style.display = 'none';
      codexPrimary.style.display = '';
      updateCodexBuckets(usage, false);
    }
  } else {
    // Single mode: show only the primary provider (or whichever is authenticated)
    primaryLabel.style.display = 'none';
    if (primary === 'codex' && codexAuth) {
      claudePrimary.style.display = 'none';
      codexPrimary.style.display = '';
      updateCodexBuckets(usage, false);
    } else if (claudeAuth) {
      claudePrimary.style.display = '';
      codexPrimary.style.display = 'none';
      updateClaudeBuckets(usage);
    } else if (codexAuth) {
      claudePrimary.style.display = 'none';
      codexPrimary.style.display = '';
      updateCodexBuckets(usage, false);
    }
  }

  // Chart: always show when Claude is authenticated (chart data is always Claude)
  chartSection.style.display = claudeAuth ? '' : 'none';

  // Secondary section (only in dual mode)
  const secondarySection = document.getElementById('secondary-section');
  const secondaryLabel = document.getElementById('secondary-label');
  const claudeSecondary = document.getElementById('claude-secondary');
  const codexSecondaryEl = document.getElementById('codex-secondary-section');
  const secondarySignin = document.getElementById('secondary-signin');

  if (dualMode) {
    const bothAvailable = claudeAuth && codexAuth;
    if (bothAvailable) {
      secondarySection.style.display = '';
      secondarySignin.style.display = 'none';
      if (primary === 'claude') {
        secondaryLabel.textContent = 'Codex';
        claudeSecondary.style.display = 'none';
        codexSecondaryEl.style.display = '';
        updateCodexBuckets(usage, true);
      } else {
        secondaryLabel.textContent = 'Claude';
        claudeSecondary.style.display = '';
        codexSecondaryEl.style.display = 'none';
        updateClaudeCompact(usage);
      }
    } else if (claudeAuth && !codexAuth) {
      secondarySection.style.display = '';
      secondaryLabel.textContent = 'Codex';
      claudeSecondary.style.display = 'none';
      codexSecondaryEl.style.display = 'none';
      secondarySignin.style.display = '';
      const btn = document.getElementById('secondary-signin-btn');
      btn.textContent = 'Sign in with ChatGPT';
      btn.onclick = codexSignIn;
    } else if (codexAuth && !claudeAuth) {
      secondarySection.style.display = '';
      secondaryLabel.textContent = 'Claude';
      claudeSecondary.style.display = 'none';
      codexSecondaryEl.style.display = 'none';
      secondarySignin.style.display = '';
      const btn = document.getElementById('secondary-signin-btn');
      btn.textContent = 'Sign in with Claude';
      btn.onclick = signIn;
    } else {
      secondarySection.style.display = 'none';
    }
  } else {
    secondarySection.style.display = 'none';
  }

  // Updated time (use primary provider's timestamp)
  const updatedIso = primary === 'codex' && codexAuth
    ? usage.codex_last_updated
    : usage.last_updated;
  document.getElementById('updated-text').textContent = formatUpdatedTime(updatedIso);

  // Account email
  if (usage.account_email) {
    document.getElementById('account-email').textContent = usage.account_email;
  }

  // Error
  errorMsg.textContent = usage.last_error || '';

  // Refresh chart and legend
  if (chartSection.style.display !== 'none') {
    await refreshChart();
  }

  // Resize only when content height changes significantly (>10px)
  // Skip when settings view is active (main-view is hidden, scrollHeight unreliable)
  if (!document.getElementById('settings-view').classList.contains('active')) {
    requestAnimationFrame(() => {
      const h = document.getElementById('main-view').scrollHeight;
      if (Math.abs(h - prevContentHeight) > 10) {
        prevContentHeight = h;
        requestResize();
      }
    });
  }
}

function updateClaudeBuckets(usage) {
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
    barOpus.style.width = `${usage.opus_util > 0 ? Math.max(2, usage.opus_util) : 0}%`;
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
    barSonnet.style.width = `${usage.sonnet_util > 0 ? Math.max(2, usage.sonnet_util) : 0}%`;
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
    const extraUtil = usage.extra_util || 0;
    barExtra.style.width = `${extraUtil > 0 ? Math.max(2, extraUtil) : 0}%`;
    barExtra.style.background = pctColor(extraPct);
  } else {
    extraEl.style.display = 'none';
  }
}

function updateCodexBuckets(usage, compact) {
  const prefix = compact ? 'codex-compact' : 'codex';

  // Primary window
  const pPct = usage.codex_primary_pct;
  const pLabel = usage.codex_primary_label || '5h';
  const pReset = usage.codex_primary_reset;
  document.getElementById(`${prefix}-primary-label`).textContent = pLabel + ' Window';
  // Use same updateBucket as Claude for consistent rendering
  const pNorm = pPct !== null && pPct !== undefined ? pPct / 100 : 0;
  updateBucket(`${prefix}-primary`, pNorm, pReset, pPct);

  // Secondary window
  const sPct = usage.codex_secondary_pct;
  const sLabel = usage.codex_secondary_label || '7d';
  const sReset = usage.codex_secondary_reset;
  document.getElementById(`${prefix}-secondary-label`).textContent = sLabel + ' Window';
  const sNorm = sPct !== null && sPct !== undefined ? sPct / 100 : 0;
  updateBucket(`${prefix}-secondary`, sNorm, sReset, sPct);
}

function updateClaudeCompact(usage) {
  updateBucket('5h-sec', usage.pct_5h, usage.reset_5h, usage.util_5h);
  updateBucket('7d-sec', usage.pct_7d, usage.reset_7d, usage.util_7d);
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


// ── Auto-resize ──

function requestResize() {
  // Only resize based on main view, not settings
  if (document.getElementById('settings-view').classList.contains('active')) return;
  requestAnimationFrame(() => {
    setTimeout(() => {
      const el = document.getElementById('main-view');
      const height = el.scrollHeight + 2;
      apiPost('/api/resize', { height });
    }, 50);
  });
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
          spanGaps: true,
          segment: {
            borderDash: ctx => ctx.p1.parsed.x - ctx.p0.parsed.x > gapThresholdMs ? [6, 3] : undefined,
          },
        },
        {
          label: '7d',
          data: [],
          borderColor: '#fb923c',
          borderWidth: 2,
          tension: 0.4,
          pointRadius: 0,
          fill: false,
          spanGaps: true,
          segment: {
            borderDash: ctx => ctx.p1.parsed.x - ctx.p0.parsed.x > gapThresholdMs ? [6, 3] : undefined,
          },
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      scales: {
        x: {
          type: 'linear',
          grid: { color: '#2e2e48', drawBorder: false },
          ticks: {
            color: '#606078',
            font: { size: 10 },
            maxTicksLimit: 4,
            callback: function(value) {
              const d = new Date(value);
              const r = currentRange;
              if (r === '1h' || r === '6h' || r === '1d') {
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              }
              return d.toLocaleDateString([], { month: '2-digit', day: '2-digit' });
            },
          },
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
      events: [],
    },
  });
}

async function refreshChart() {
  const history = await apiGet(`/api/history/${currentRange}`);
  if (!history || !usageChart) return;

  // Fix X-axis to cover the full selected range
  const rangeMs = { '1h': 3600000, '6h': 21600000, '1d': 86400000, '7d': 604800000, '30d': 2592000000 };
  const now = new Date();
  const rangeStart = new Date(now.getTime() - (rangeMs[currentRange] || 21600000));
  const nullPt = { pct_5h: null, pct_7d: null, codex_primary: null, codex_secondary: null };

  const points = [...history];
  if (points.length === 0 || new Date(points[0].timestamp) - rangeStart > 60000) {
    points.unshift({ timestamp: rangeStart.toISOString(), ...nullPt });
  }
  if (points.length === 0 || now - new Date(points[points.length - 1].timestamp) > 60000) {
    points.push({ timestamp: now.toISOString(), ...nullPt });
  }

  // Set X-axis range
  usageChart.options.scales.x.min = rangeStart.getTime();
  usageChart.options.scales.x.max = now.getTime();

  const primary = cachedUsage ? cachedUsage.primary_provider : 'claude';
  const isCodex = primary === 'codex';

  usageChart.data.labels = [];
  if (isCodex) {
    usageChart.data.datasets[0].data = points.map(p => ({
      x: new Date(p.timestamp).getTime(),
      y: p.codex_primary != null ? p.codex_primary * 100 : null,
    }));
    usageChart.data.datasets[1].data = points.map(p => ({
      x: new Date(p.timestamp).getTime(),
      y: p.codex_secondary != null ? p.codex_secondary * 100 : null,
    }));
  } else {
    usageChart.data.datasets[0].data = points.map(p => ({
      x: new Date(p.timestamp).getTime(),
      y: p.pct_5h != null ? p.pct_5h * 100 : null,
    }));
    usageChart.data.datasets[1].data = points.map(p => ({
      x: new Date(p.timestamp).getTime(),
      y: p.pct_7d != null ? p.pct_7d * 100 : null,
    }));
  }
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

// ── Provider selector ──

document.getElementById('provider-selector').addEventListener('click', async (e) => {
  const btn = e.target.closest('.provider-btn');
  if (!btn) return;
  document.querySelectorAll('.provider-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  const provider = btn.dataset.provider;
  await apiPost('/api/settings/primary-provider', { provider });
  needsResize = true;
});

// ── Actions ──

async function signIn() {
  await apiPost('/api/sign-in');
  document.getElementById('code-entry').style.display = '';
  requestResize();
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
  requestResize();
}

async function codexSignIn() {
  await apiPost('/api/codex/sign-in');
}

function toggleSigninCodex() {
  const entry = document.getElementById('signin-codex-entry');
  entry.style.display = entry.style.display === 'none' ? '' : 'none';
  requestResize();
}

async function submitSigninCodexToken() {
  const input = document.getElementById('signin-codex-token-input');
  const token = input.value.trim();
  if (!token) return;
  const result = await apiPost('/api/codex/submit-token', { token });
  if (result && result.success) {
    input.value = '';
    await refreshData();
  } else {
    document.getElementById('signin-codex-error-msg').textContent =
      (result && result.error) || 'Invalid token';
  }
}

async function submitCodexToken() {
  const input = document.getElementById('codex-token-input');
  const token = input.value.trim();
  if (!token) return;
  const result = await apiPost('/api/codex/submit-token', { token });
  if (result && result.success) {
    input.value = '';
    await refreshData();
    loadSettings();
  } else {
    document.getElementById('codex-error-msg').textContent =
      (result && result.error) || 'Invalid token';
  }
}

async function codexSignOut() {
  await apiPost('/api/codex/sign-out');
  await refreshData();
  requestResize();
  loadSettings();
}

async function refresh() {
  await apiPost('/api/refresh');
  setTimeout(refreshData, 1500);
}

async function quit() {
  await apiPost('/api/quit');
}

function closeWindow() {
  if (appMode === 'widget') {
    // Exit widget mode and hide
    fetch('/api/exit-widget', { method: 'POST' }).catch(() => {});
  } else {
    window.close();
  }
}

// ── Startup toggle ──

async function toggleStartup(checked) {
  await apiPost('/api/settings/startup', { enabled: checked });
  document.getElementById('settings-startup-toggle').checked = checked;
}

async function toggleDualMode(checked) {
  await apiPost('/api/settings/dual-mode', { enabled: checked });
  document.getElementById('settings-dual-toggle').checked = checked;
  const primarySetting = document.getElementById('primary-display-setting');
  primarySetting.style.display = checked ? '' : 'none';
  await refreshData();
  needsResize = true;
}

// ── Settings view ──

function showSettings() {
  document.getElementById('main-view').classList.add('hidden');
  document.getElementById('settings-view').classList.add('active');
  loadSettings();
}

async function hideSettings() {
  document.getElementById('main-view').classList.remove('hidden');
  document.getElementById('settings-view').classList.remove('active');
  await refreshData();
  if (needsResize) {
    needsResize = false;
    requestResize();
  }
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

  // Dual mode toggle
  document.getElementById('settings-dual-toggle').checked = settings.dual_mode;
  const primarySetting = document.getElementById('primary-display-setting');
  primarySetting.style.display = settings.dual_mode ? '' : 'none';

  // Provider selector
  document.querySelectorAll('.provider-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.provider === settings.primary_provider);
  });

  // Codex account status
  const codexSignedIn = document.getElementById('codex-signed-in');
  const codexSignedOut = document.getElementById('codex-signed-out');
  if (settings.codex_authenticated) {
    codexSignedIn.style.display = '';
    codexSignedOut.style.display = 'none';
  } else {
    codexSignedIn.style.display = 'none';
    codexSignedOut.style.display = '';
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
  // Claude primary
  if (cachedUsage.reset_5h) {
    const el = document.getElementById('reset-5h');
    if (el) el.textContent = formatRelativeTime(cachedUsage.reset_5h);
  }
  if (cachedUsage.reset_7d) {
    const el = document.getElementById('reset-7d');
    if (el) el.textContent = formatRelativeTime(cachedUsage.reset_7d);
  }
  // Claude compact (secondary)
  if (cachedUsage.reset_5h) {
    const el = document.getElementById('reset-5h-sec');
    if (el) el.textContent = formatRelativeTime(cachedUsage.reset_5h);
  }
  if (cachedUsage.reset_7d) {
    const el = document.getElementById('reset-7d-sec');
    if (el) el.textContent = formatRelativeTime(cachedUsage.reset_7d);
  }
  // Codex primary + compact
  if (cachedUsage.codex_primary_reset) {
    const el = document.getElementById('reset-codex-primary');
    if (el) el.textContent = formatRelativeTime(cachedUsage.codex_primary_reset);
    const elC = document.getElementById('reset-codex-compact-primary');
    if (elC) elC.textContent = formatRelativeTime(cachedUsage.codex_primary_reset);
  }
  if (cachedUsage.codex_secondary_reset) {
    const el = document.getElementById('reset-codex-secondary');
    if (el) el.textContent = formatRelativeTime(cachedUsage.codex_secondary_reset);
    const elC = document.getElementById('reset-codex-compact-secondary');
    if (elC) elC.textContent = formatRelativeTime(cachedUsage.codex_secondary_reset);
  }
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
  } else if (appMode === 'widget') {
    // Widget mode: show title bar, no auto-hide
    const titleBar = document.getElementById('main-title-bar');
    if (titleBar) {
      titleBar.style.display = '';
      // Drag via JS mouse events + Win32 move
      let drag = null;
      titleBar.addEventListener('mousedown', async (e) => {
        if (e.target.closest('.close-btn')) return;
        e.preventDefault();
        const pos = await fetch('/api/window-pos').then(r => r.json());
        drag = { sx: e.screenX, sy: e.screenY, wx: pos.x, wy: pos.y, scale: pos.dpi_scale || 1 };
      });
      document.addEventListener('mousemove', (e) => {
        if (!drag) return;
        const x = drag.wx + Math.round((e.screenX - drag.sx) * drag.scale);
        const y = drag.wy + Math.round((e.screenY - drag.sy) * drag.scale);
        fetch('/api/move-window', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ x, y }),
        });
      });
      document.addEventListener('mouseup', () => { drag = null; });
    }
  }

  initChart();
  await refreshData();
  requestResize();
  countdownTimer = setInterval(updateCountdowns, 1000);
  // Poll for updates every 15 seconds
  pollTimer = setInterval(refreshData, 15000);
});
