// 公共常量与工具：配置、风险等级、大模型调用、设置弹窗

const DEFAULT_CONFIG = {
  baseUrl: 'https://api.deepseek.com/v1',
  apiKey: '',
  model: 'deepseek-chat',
  apiBase: 'http://127.0.0.1:8000',
  weiboCookie: '',
};

const RISK_LEVELS = ['无风险', '轻微', '需说明', '高风险', '一票否决'];

const DIMENSIONS = [
  { name: '政治立场倾向', desc: '对党的领导、社会主义制度、路线方针政策的态度' },
  { name: '意识形态倾向', desc: '西方自由主义、历史虚无主义、极端思潮等倾向' },
  { name: '敏感话题立场倾向', desc: '涉港涉疆涉藏涉台、重大政策、热点事件立场' },
  { name: '法治与违纪倾向', desc: '造谣传谣、网暴、涉黄涉赌、泄密等违法违纪行为' },
  { name: '道德品行倾向', desc: '侮辱他人、低俗恶俗、诚信记录、失德行为' },
  { name: '网络行为倾向', desc: '转发关注画像、群组参与、匿名小号等隐性立场' },
  { name: '稳定风险与组织倾向', desc: '煽动聚集、组党结社、动员线下行动等风险' },
];

const SYSTEM_PROMPT = `你是一名专业的政治审查分析师。请对指定社交账号发布的文字内容进行七维度政审分析，评估其在政治素质、意识形态、遵纪守法、道德品行和现实表现方面的倾向性风险，并以严格 JSON 返回。

## 七维度说明
${DIMENSIONS.map((d, i) => `${i + 1}. ${d.name}：${d.desc}`).join('\n')}

## 输出 JSON 结构
{
  "overall_risk": "总体风险等级，可选：${RISK_LEVELS.join(' / ')}",
  "summary": "总体评价（50-100字）",
  "dimensions": [
    {
      "name": "维度名称（必须与上述七个维度一致）",
      "risk": "该维度风险等级",
      "analysis": "分析说明（40-80字）",
      "evidence": ["直接引用原文作为证据，最多3条，无证据则为空数组"]
    }
  ]
}

只输出 JSON 本身，不要 markdown 代码块或额外解释。`;

function $(id) {
  return document.getElementById(id);
}

function show(id, visible) {
  $(id).classList.toggle('hidden', !visible);
}

function loadConfig() {
  const raw = localStorage.getItem('sz_cfg');
  return raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_CONFIG };
}

function saveConfig(cfg) {
  localStorage.setItem('sz_cfg', JSON.stringify(cfg));
}

function riskClass(risk) {
  return {
    无风险: 'ok',
    轻微: 'low',
    需说明: 'mid',
    高风险: 'high',
    一票否决: 'fatal',
  }[risk] || 'mid';
}

function normalizeRisk(raw) {
  const r = String(raw || '');
  return RISK_LEVELS.find(l => r.includes(l)) || '需说明';
}

function extractJson(raw) {
  try { return JSON.parse(raw); } catch {}
  const m = raw.match(/\{[\s\S]*\}/);
  if (m) { try { return JSON.parse(m[0]); } catch {} }
  throw new Error('模型返回的内容不是有效 JSON，请重试或检查模型配置。');
}

async function callLLM(cfg, text, withFormat) {
  const body = {
    model: cfg.model,
    messages: [
      { role: 'system', content: SYSTEM_PROMPT },
      { role: 'user', content: `以下是待分析账号发布的内容：\n\n${text}` },
    ],
    temperature: 0.2,
  };
  if (withFormat) body.response_format = { type: 'json_object' };

  const resp = await fetch(`${cfg.baseUrl.replace(/\/$/, '')}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${cfg.apiKey}`,
    },
    body: JSON.stringify(body),
  });

  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`HTTP ${resp.status}：${txt.slice(0, 300)}`);
  }
  const data = await resp.json();
  if (!data.choices || !data.choices[0]) throw new Error('模型返回格式异常');
  return data.choices[0].message.content;
}

function formatPosts(posts) {
  return posts
    .map((p, i) => `${i + 1}. [${p.platform} @${p.account} ${p.time}] ${p.content}`)
    .join('\n');
}

function openSettings() {
  const c = loadConfig();
  $('cfgBaseUrl').value = c.baseUrl || '';
  $('cfgApiKey').value = c.apiKey || '';
  $('cfgModel').value = c.model || '';
  if ($('cfgApiBase')) $('cfgApiBase').value = c.apiBase || 'http://127.0.0.1:8000';
  if ($('cfgWeiboCookie')) $('cfgWeiboCookie').value = c.weiboCookie || '';
  show('settingsModal', true);
}

function bindSettings(onSaved) {
  $('btnSettings').addEventListener('click', openSettings);
  $('btnCloseSettings').addEventListener('click', () => show('settingsModal', false));
  $('modalMask').addEventListener('click', () => show('settingsModal', false));
  $('btnSaveSettings').addEventListener('click', () => {
    saveConfig({
      baseUrl: $('cfgBaseUrl').value.trim(),
      apiKey: $('cfgApiKey').value.trim(),
      model: $('cfgModel').value.trim(),
      apiBase: $('cfgApiBase') ? $('cfgApiBase').value.trim() : 'http://127.0.0.1:8000',
      weiboCookie: $('cfgWeiboCookie') ? $('cfgWeiboCookie').value.trim() : '',
    });
    show('settingsModal', false);
    if (onSaved) onSaved();
  });
}
