// 分析报告页：读取 payload、调用大模型、渲染精美报告

let payload = null;

function postsToText() {
  return formatPosts(payload.posts);
}

function showState(state) {
  show('reportLoading', state === 'loading');
  show('reportError', state === 'error');
  show('reportBody', state === 'report');
}

async function runAnalysis() {
  const cfg = loadConfig();
  if (!cfg.baseUrl || !cfg.apiKey || !cfg.model) {
    showState('error');
    $('errorText').textContent = '尚未配置大模型，请先完成配置。';
    openSettings();
    return;
  }
  showState('loading');
  try {
    let raw;
    try {
      raw = await callLLM(cfg, postsToText(), true);
    } catch (e) {
      if (String(e.message).includes('400')) {
        raw = await callLLM(cfg, postsToText(), false);
      } else throw e;
    }
    const result = extractJson(raw);
    localStorage.setItem('sz_result', JSON.stringify(result));
    renderReport(result);
  } catch (e) {
    showState('error');
    $('errorText').textContent =
      `分析失败：${e.message}\n\n若为跨域（CORS）错误，请更换允许浏览器直连的接口地址。`;
  }
}

function renderDistribution(dims) {
  const total = dims.length || 1;
  const counts = RISK_LEVELS.map(l => ({
    level: l,
    cls: riskClass(l),
    count: dims.filter(d => normalizeRisk(d.risk) === l).length,
  })).filter(c => c.count > 0);

  $('distBar').innerHTML = counts
    .map(c => `<span class="seg ${c.cls}" style="width:${(c.count / total) * 100}%"></span>`)
    .join('');

  $('distLegend').innerHTML = counts
    .map(c => `<span class="legend-item"><i class="dot ${c.cls}"></i>${c.level} ${c.count}</span>`)
    .join('');
}

function renderReport(result) {
  showState('report');
  const overall = normalizeRisk(result.overall_risk);
  const now = new Date().toLocaleString('zh-CN');

  $('metaText').textContent =
    `${payload.platform} · @${payload.account} · 数据 ${payload.posts.length} 条 · 爬取 ${payload.crawlTime} · 生成 ${now}`;

  $('heroRisk').textContent = overall;
  $('heroRisk').className = `big-badge ${riskClass(overall)}`;
  $('heroSummary').textContent = result.summary || '暂无总体评价';

  const dims = Array.isArray(result.dimensions) ? result.dimensions : [];
  renderDistribution(dims);

  const grid = $('dimensionGrid');
  grid.innerHTML = '';
  dims.forEach((d, i) => {
    const risk = normalizeRisk(d.risk);
    const evidences = Array.isArray(d.evidence) ? d.evidence : [];
    const evHTML = evidences.length
      ? `<div class="evidence-box">${evidences.map(ev => `<p>${ev}</p>`).join('')}</div>`
      : '';
    const el = document.createElement('div');
    el.className = `dim-card ${riskClass(risk)}`;
    el.style.animationDelay = `${i * 60}ms`;
    el.innerHTML = `
      <div class="dim-head">
        <div class="dim-title">
          <i class="dot ${riskClass(risk)}"></i>
          <h3>${d.name || ''}</h3>
        </div>
        <span class="badge ${riskClass(risk)}">${risk}</span>
      </div>
      <div class="dim-desc">${DIMENSIONS.find(x => x.name === d.name)?.desc || ''}</div>
      <div class="dim-analysis">${d.analysis || ''}</div>
      ${evHTML}
    `;
    grid.appendChild(el);
  });
}

function init() {
  const rawPayload = localStorage.getItem('sz_payload');
  const rawResult = localStorage.getItem('sz_result');
  if (rawPayload) payload = JSON.parse(rawPayload);
  bindSettings(() => {
    if (!$('reportError').classList.contains('hidden')) runAnalysis();
  });
  if (payload && rawResult) {
    renderReport(JSON.parse(rawResult));
  } else if (payload) {
    runAnalysis();
  } else {
    showState('error');
    $('errorText').textContent = '暂无数据，请返回首页完成模拟爬取后再来查看分析。';
  }
}

$('btnBack').addEventListener('click', () => { location.href = 'index.html'; });
$('btnRetry').addEventListener('click', runAnalysis);
$('btnOpenSettings2').addEventListener('click', openSettings);

init();
