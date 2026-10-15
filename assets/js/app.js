// 爬取页：账号输入、平台切换、模拟爬取、跳转分析

let currentPlatform = '小红书';
let crawledPosts = [];

function setError(msg) {
  show('crawlLoading', false);
  show('analyzeLoading', false);
  show('resultError', true);
  $('errorText').textContent = msg;
}

const API_BASE = 'http://localhost:8000';

async function crawlAccount() {
  const account = $('accountInput').value.trim();
  if (!account) {
    show('resultEmpty', false);
    setError('请输入账号昵称或 ID。');
    return;
  }
  show('resultEmpty', false);
  show('crawlResult', false);
  show('resultError', false);
  show('crawlLoading', true);
  $('crawlLoadingText').textContent = `正在爬取 ${currentPlatform} 账号「${account}」的内容…`;

  try {
    const resp = await fetch(
      `${API_BASE}/api/crawl?platform=${encodeURIComponent(currentPlatform)}&account=${encodeURIComponent(account)}&limit=20`
    );
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    crawledPosts = data.posts.map(p => ({ ...p, platform: data.platform, account: data.account }));
    show('crawlLoading', false);
    renderPosts();
  } catch (e) {
    setError(`爬取失败：${e.message}\n\n请确认爬虫服务已启动：uv run server/main.py`);
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
