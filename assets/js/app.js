// 爬取页：账号输入、平台切换、模拟爬取、跳转分析

let currentPlatform = '小红书';
let crawledPosts = [];

function setError(msg) {
  show('crawlLoading', false);
  show('analyzeLoading', false);
  show('resultError', true);
  $('errorText').textContent = msg;
}

// 调用桌面端（Tauri）命令；扫码登录与小红书抓取都依赖内置 WebView，仅桌面端可用
function tauriInvoke(cmd, args) {
  const tauri = window.__TAURI__;
  if (!tauri || !tauri.core) {
    return Promise.reject(new Error('该功能仅支持在桌面客户端中使用'));
  }
  return tauri.core.invoke(cmd, args);
}

function getApiBase() {
  const c = loadConfig();
  return (c.apiBase || 'http://127.0.0.1:8000').replace(/\/$/, '');
}

async function crawlAccount() {
  const account = $('accountInput').value.trim();
  if (!account) {
    show('resultEmpty', false);
    setError('请输入账号昵称或 ID。');
    return;
  }
  const cfg = loadConfig();
  const limit = cfg.limit || 20;
  const apiBase = getApiBase();

  show('resultEmpty', false);
  show('crawlResult', false);
  show('resultError', false);
  show('crawlLoading', true);
  $('crawlLoadingText').textContent = `正在爬取 ${currentPlatform} 账号「${account}」（前 ${limit} 条）…`;

  try {
    let data;
    if (currentPlatform === '小红书') {
      // 小红书在桌面端的内置 WebView 中抓取，复用扫码登录的会话
      try {
        data = await tauriInvoke('xhs_crawl', { account, limit });
      } catch (err) {
        throw new Error(String(err.message || err));
      }
    } else {
      let url = `${apiBase}/api/crawl?platform=${encodeURIComponent(currentPlatform)}&account=${encodeURIComponent(account)}&limit=${limit}`;
      if (cfg.weiboCookie) {
        url += `&cookie=${encodeURIComponent(cfg.weiboCookie)}`;
      }
      const resp = await fetch(url);
      data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    }
    crawledPosts = data.posts.map(p => ({ ...p, platform: data.platform, account: data.account }));
    show('crawlLoading', false);
    renderPosts();
  } catch (e) {
    setError(`爬取失败：${e.message}\n\n如遇 Cookie 过期，请点击右上角「设置」更新 Cookie。`);
  }
}

function renderPosts() {
  const first = crawledPosts[0];
  $('crawlTitle').textContent =
    `爬取结果 · ${first.platform} · @${first.account}（${crawledPosts.length} 条）`;
  $('postList').innerHTML = crawledPosts.map(p => `
    <li class="post-item">
      <div class="post-meta">
        <span class="post-platform">${p.platform}</span>
        <span>@${p.account}</span>
        <span>${p.time}</span>
        <span>赞 ${p.likes}</span>
      </div>
      <div class="post-content">${p.content}</div>
    </li>
  `).join('');
  show('crawlResult', true);
}

async function goAnalyze() {
  const cfg = loadConfig();
  if (!cfg.baseUrl || !cfg.apiKey || !cfg.model) {
    setError('请先在右上角「大模型配置」中填写 API 地址、API Key 与模型名称。');
    openSettings();
    return;
  }
  if (!crawledPosts.length) {
    setError('请先完成模拟爬取。');
    return;
  }
  show('crawlResult', false);
  show('resultError', false);
  show('analyzeLoading', true);

  try {
    let raw;
    try {
      raw = await callLLM(cfg, formatPosts(crawledPosts), true);
    } catch (e) {
      if (String(e.message).includes('400')) {
        raw = await callLLM(cfg, formatPosts(crawledPosts), false);
      } else throw e;
    }
    const result = extractJson(raw);
    localStorage.setItem('sz_payload', JSON.stringify({
      platform: currentPlatform,
      account: $('accountInput').value.trim(),
      crawlTime: new Date().toLocaleString('zh-CN'),
      posts: crawledPosts,
    }));
    localStorage.setItem('sz_result', JSON.stringify(result));
    location.href = 'result.html';
  } catch (e) {
    show('analyzeLoading', false);
    show('crawlResult', true);
    setError(`分析失败：${e.message}\n\n若为跨域（CORS）错误，请更换允许浏览器直连的接口地址。`);
  }
}

document.querySelectorAll('.source-tabs .tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.source-tabs .tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    currentPlatform = btn.dataset.platform;
  });
});

$('btnCrawl').addEventListener('click', crawlAccount);
$('btnAnalyze').addEventListener('click', goAnalyze);
bindSettings();

const btnWeibo = $('btnWeiboLogin');
if (btnWeibo) {
  btnWeibo.addEventListener('click', async () => {
    const statusEl = $('weiboLoginStatus');
    btnWeibo.disabled = true;
    statusEl.textContent = '已弹出微博扫码窗口，请使用微博 App 扫码并在手机上点击确认。登录成功后窗口将自动关闭，请勿手动关闭窗口...';
    statusEl.style.color = '#3b82f6';
    try {
      let data;
      try {
        const cookie = await tauriInvoke('weibo_login');
        data = { ok: true, cookie };
      } catch (err) {
        data = { ok: false, message: String(err.message || err) };
      }
      if (data.ok && data.cookie) {
        statusEl.textContent = '登录成功！已自动提取并保存最新微博 Cookie。';
        statusEl.style.color = '#10b981';
        if ($('cfgWeiboCookie')) $('cfgWeiboCookie').value = data.cookie;
        const currentCfg = loadConfig();
        saveConfig({ ...currentCfg, weiboCookie: data.cookie });
      } else {
        statusEl.textContent = data.message || '未检测到登录成功或登录已超时';
        statusEl.style.color = '#ef4444';
      }
    } catch (e) {
      statusEl.textContent = `启动失败：${e.message}`;
      statusEl.style.color = '#ef4444';
    } finally {
      btnWeibo.disabled = false;
    }
  });
}

const btnXhs = $('btnXhsLogin');
if (btnXhs) {
  btnXhs.addEventListener('click', async () => {
    const statusEl = $('xhsLoginStatus');
    btnXhs.disabled = true;
    statusEl.textContent = '已弹出小红书扫码窗口，请使用小红书 App 扫码并在手机上点击确认。登录成功后窗口将自动关闭，请勿手动关闭窗口...';
    statusEl.style.color = '#3b82f6';
    try {
      let data;
      try {
        const cookie = await tauriInvoke('xhs_login');
        data = { ok: true, cookie };
      } catch (err) {
        data = { ok: false, message: String(err.message || err) };
      }
      if (data.ok) {
        statusEl.textContent = '登录成功！小红书登录态已保存，可直接抓取。';
        statusEl.style.color = '#10b981';
        if (data.cookie) {
          if ($('cfgXhsCookie')) $('cfgXhsCookie').value = data.cookie;
          const currentCfg = loadConfig();
          saveConfig({ ...currentCfg, xhsCookie: data.cookie });
        }
      } else {
        statusEl.textContent = data.message || '登录超时或未完成';
        statusEl.style.color = '#ef4444';
      }
    } catch (e) {
      statusEl.textContent = `扫码启动失败：${e.message}`;
      statusEl.style.color = '#ef4444';
    } finally {
      btnXhs.disabled = false;
    }
  });
}
