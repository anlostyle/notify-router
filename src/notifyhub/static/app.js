const $ = (selector, root = document) => root.querySelector(selector)
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)]
const MASK = '••••••'

const PAGES = {
  dashboard: ['运行概览', '系统看板', '查看通知服务的运行状态与近期投递表现'],
  channels: ['通知管理', '通知渠道', '管理企业微信、Telegram、Webhook 等消息出口'],
  routes: ['通知管理', '通知通道', '将推送入口、通知模板与发送渠道连接起来'],
  templates: ['通知管理', '通知模板', '统一管理不同服务的消息格式并实时预览'],
  plugins: ['扩展能力', '插件管理', '配置现有插件和第三方服务集成'],
  deliveries: ['运行状态', '投递历史', '追踪每一次发送、失败原因与重试状态'],
  logs: ['运行状态', '系统日志', '查看当前进程最近的运行日志'],
  settings: ['系统管理', '系统设置', '管理站点信息、安全参数与运行环境'],
}

const CHANNEL_TYPES = {
  qywx: {
    label: '企业微信', short: '企',
    fields: [
      ['server_url', 'API 服务器地址', 'url', 'https://qyapi.weixin.qq.com', '支持填写自建可信 IP 代理地址'],
      ['corpid', '企业 ID', 'text', '', '企业微信管理后台的 CorpID'],
      ['agentid', '应用 AgentID', 'text', '', '企业微信自建应用的 AgentID'],
      ['corpsecret', '应用 Secret', 'password', '', '留空表示保持现有密钥'],
      ['touser', '接收成员', 'text', '@all', '多个成员使用 | 分隔，@all 表示全部成员'],
      ['is_news', '优先使用 News 消息', 'checkbox', true, '包含图片或链接时发送 News 卡片'],
    ],
  },
  bark: { label: 'Bark', short: 'B', fields: [['push_url', '推送地址', 'url', '', '包含设备 Key 的完整 Bark 地址']] },
  telegram: { label: 'Telegram', short: 'TG', fields: [['bot_token', 'Bot Token', 'password'], ['chat_id', 'Chat ID', 'text']] },
  discord: { label: 'Discord', short: 'D', fields: [['webhook_url', 'Webhook 地址', 'password']] },
  dingtalk: { label: '钉钉', short: '钉', fields: [['access_token', 'Access Token', 'password'], ['webhook_url', 'Webhook 地址（可选）', 'password']] },
  pushdeer: { label: 'PushDeer', short: 'PD', fields: [['server_url', '服务器地址', 'url', 'https://api2.pushdeer.com/message/push'], ['push_key', 'Push Key', 'password']] },
  feishu: { label: '飞书', short: '飞', fields: [['app_id', 'App ID', 'text'], ['app_secret', 'App Secret', 'password'], ['receive_id', '接收目标 ID', 'text'], ['receive_id_type', '目标类型', 'select', 'open_id', '', [['open_id', 'Open ID'], ['user_id', 'User ID'], ['chat_id', 'Chat ID']]]] },
  serverchan3: { label: 'Server酱', short: 'S', fields: [['send_key', 'SendKey', 'password'], ['server_url', '服务器地址（可选）', 'url']] },
  email: { label: '邮件', short: '邮', fields: [['smtp_host', 'SMTP 服务器', 'text'], ['smtp_port', 'SMTP 端口', 'number', 465], ['username', '用户名', 'text'], ['password', '密码', 'password'], ['from_email', '发件地址', 'email'], ['to_email', '收件地址', 'email']] },
  webhook: { label: 'Webhook', short: 'W', fields: [['url', 'Webhook 地址', 'url']] },
}

const state = {
  session: null,
  status: null,
  config: null,
  templates: [],
  plugins: [],
  deliveries: [],
  logs: [],
  query: '',
  deliveryStatus: '',
  lastPage: '',
  modalSubmit: null,
  logTimer: null,
}

function icon(name) {
  return `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char])
}

function matches(...values) {
  const query = state.query.trim().toLowerCase()
  return !query || values.some(value => String(value ?? '').toLowerCase().includes(query))
}

function typeInfo(type) {
  return CHANNEL_TYPES[type] || { label: type || '未知类型', short: String(type || '?').slice(0, 2).toUpperCase(), fields: [] }
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(String(value).replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function statusText(status) {
  return ({ sent: '已送达', failed: '失败', retry: '等待重试', pending: '排队中', processing: '发送中' })[status] || status || '未知'
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
  })
  const text = await response.text()
  let data = null
  try { data = text ? JSON.parse(text) : null } catch { data = text }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/admin/login') showLogin()
    throw new Error(data?.detail || data?.message || text || `HTTP ${response.status}`)
  }
  return data
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme
  localStorage.setItem('notify-theme', theme)
  $('#theme-icon')?.setAttribute('href', theme === 'dark' ? '#i-sun' : '#i-moon')
}

function currentPage() {
  const page = location.hash.slice(1).split('?')[0]
  return PAGES[page] ? page : 'dashboard'
}

function showLogin() {
  clearInterval(state.logTimer)
  $('#app').hidden = true
  $('#login-view').hidden = false
  setTimeout(() => $('#login-form input[name="password"]')?.focus(), 40)
}

async function showApp(session) {
  state.session = session
  $('#login-view').hidden = true
  $('#app').hidden = false
  $('#username').textContent = session.username || 'admin'
  $('#user-avatar').textContent = (session.username || 'A').slice(0, 1).toUpperCase()
  await loadCore()
  await renderPage()
}

async function loadCore() {
  const [status, config, templatePayload, plugins] = await Promise.all([
    api('/api/admin/status'), api('/api/admin/config'), api('/api/admin/templates'), api('/api/admin/plugins'),
  ])
  state.status = status
  state.config = config
  state.templates = templatePayload.template || []
  state.plugins = plugins || []
  $('#nav-channels').textContent = status.channels
  $('#nav-routes').textContent = status.routes
  $('#nav-plugins').textContent = status.plugins
  $('#sidebar-version').textContent = `v${status.version}`
}

function setPageActions(page) {
  const actions = {
    dashboard: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    channels: `<button class="button primary" data-action="add-channel" aria-label="新增渠道">${icon('plus')}<span>新增渠道</span></button>`,
    routes: `<button class="button primary" data-action="add-route" aria-label="新增通道">${icon('plus')}<span>新增通道</span></button>`,
    templates: `<button class="button primary" data-action="add-template" aria-label="新增模板">${icon('plus')}<span>新增模板</span></button>`,
    deliveries: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    logs: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    settings: `<button class="button primary" data-action="edit-settings" aria-label="编辑设置">${icon('edit')}<span>编辑设置</span></button>`,
  }
  $('#page-actions').innerHTML = actions[page] || ''
}

async function renderPage() {
  const page = currentPage()
  if (state.lastPage && state.lastPage !== page) {
    state.query = ''
    $('#global-search').value = ''
  }
  state.lastPage = page
  clearInterval(state.logTimer)
  state.logTimer = null
  const [eyebrow, title, description] = PAGES[page]
  $('#page-eyebrow').textContent = eyebrow
  $('#page-title').textContent = title
  $('#page-description').textContent = description
  setPageActions(page)
  $$('#nav a').forEach(link => link.classList.toggle('active', link.dataset.page === page))
  closeMobileMenu()

  if (page === 'deliveries') {
    $('#page-content').innerHTML = '<div class="skeleton"></div>'
    const suffix = state.deliveryStatus ? `&status=${encodeURIComponent(state.deliveryStatus)}` : ''
    state.deliveries = await api(`/api/admin/deliveries?limit=300${suffix}`)
  }
  if (page === 'logs') {
    state.logs = await api('/api/admin/logs?limit=300')
    state.logTimer = setInterval(async () => {
      if (currentPage() !== 'logs') return
      try { state.logs = await api('/api/admin/logs?limit=300'); renderCurrent() } catch { /* next poll retries */ }
    }, 5000)
  }
  renderCurrent()
}

function renderCurrent() {
  const renderers = {
    dashboard: renderDashboard,
    channels: renderChannels,
    routes: renderRoutes,
    templates: renderTemplates,
    plugins: renderPlugins,
    deliveries: renderDeliveries,
    logs: renderLogs,
    settings: renderSettings,
  }
  $('#page-content').innerHTML = renderers[currentPage()]()
}

function renderDashboard() {
  const stats = state.status.stats || {}
  const queue = stats.queue || {}
  const trend = stats.trend || []
  const deliveries = state.status.deliveries || []
  const maxValue = Math.max(1, ...trend.map(row => Number(row.success || 0) + Number(row.failed || 0)))
  const chart = trend.length ? `<div class="chart">${trend.map(row => {
    const success = Math.max(2, Number(row.success || 0) / maxValue * 100)
    const failed = Number(row.failed || 0) ? Math.max(3, Number(row.failed) / maxValue * 100) : 0
    return `<div class="bar-group" title="${escapeHtml(row.date)} · 成功 ${row.success} · 失败 ${row.failed}"><i class="bar" style="height:${success}%"></i>${failed ? `<i class="bar failed" style="height:${failed}%"></i>` : ''}<span class="bar-label">${escapeHtml(String(row.date).slice(5))}</span></div>`
  }).join('')}</div>` : '<div class="chart-empty">暂无趋势数据</div>'
  const activity = deliveries.slice(0, 7).map(item => `
    <div class="activity-item">
      <span class="activity-icon ${escapeHtml(item.status)}">${icon(item.status === 'sent' ? 'check' : item.status === 'failed' ? 'alert' : 'refresh')}</span>
      <div class="activity-main"><strong>${escapeHtml(item.title || '无标题通知')}</strong><small>${escapeHtml(item.route_name)} → ${escapeHtml(item.channel_name)}</small></div>
      <span class="activity-time">${escapeHtml(formatDate(item.updated_at || item.outbox_created_at))}</span>
    </div>`).join('') || '<div class="empty-state"><p>还没有投递记录</p></div>'
  return `
    <div class="stats-grid">
      ${statCard('累计投递', stats.total || 0, '历史成功与失败总数', 'send', 'purple')}
      ${statCard('成功率', `${stats.success_rate ?? 100}%`, `${stats.success || 0} 条已成功送达`, 'check', 'green')}
      ${statCard('今日消息', (stats.today?.success || 0) + (stats.today?.failed || 0), `失败 ${stats.today?.failed || 0} 条`, 'bell', 'blue')}
      ${statCard('等待处理', (queue.pending || 0) + (queue.retry || 0) + (queue.processing || 0), `重试 ${queue.retry || 0} · 发送中 ${queue.processing || 0}`, 'refresh', 'orange')}
    </div>
    <div class="dashboard-grid">
      <section class="panel"><header class="panel-header"><div><h2>投递趋势</h2><p>最近 ${trend.length || 0} 个有记录的日期</p></div><span class="tag purple">成功 / 失败</span></header><div class="panel-body">${chart}</div></section>
      <section class="panel"><header class="panel-header"><div><h2>最近活动</h2><p>最新的发送状态</p></div><a href="#deliveries" class="tag">查看全部</a></header><div class="panel-body activity-list">${activity}</div></section>
    </div>`
}

function statCard(label, value, foot, iconName, accent) {
  return `<article class="stat-card accent-${accent}"><div class="stat-top"><span>${label}</span><span class="stat-icon">${icon(iconName)}</span></div><div class="stat-value">${escapeHtml(value)}</div><div class="stat-foot">${escapeHtml(foot)}</div></article>`
}

function renderChannels() {
  const latest = new Map((state.status.stats?.channel_states || []).map(item => [item.channel_name, item]))
  const channels = (state.config.channels || []).filter(item => matches(item.name, item.type, item.config?.server_url, item.config?.touser))
  if (!channels.length) return emptyState('bell', state.query ? '没有匹配的通知渠道' : '还没有通知渠道', state.query ? '请尝试其他关键词' : '创建第一个渠道开始发送消息')
  return `<div class="entity-grid">${channels.map(channel => {
    const type = typeInfo(channel.type)
    const status = latest.get(channel.name)
    const endpoint = channel.config?.server_url || channel.config?.push_url || channel.config?.url || '使用官方服务地址'
    return `<article class="entity-card">
      <div class="entity-head"><span class="entity-icon">${escapeHtml(type.short)}</span><div class="entity-title"><h3>${escapeHtml(channel.name)}</h3><p>${escapeHtml(type.label)}</p></div><span class="status-badge ${escapeHtml(status?.status || 'active')}">${escapeHtml(status ? statusText(status.status) : '已配置')}</span></div>
      <div class="entity-body"><div class="entity-meta"><span class="tag">API</span><span title="${escapeHtml(endpoint)}">${escapeHtml(endpoint)}</span></div><div class="entity-meta"><span class="tag purple">${channel.config?.is_news ? 'News' : 'Text'}</span><span>${escapeHtml(channel.config?.touser || '默认接收目标')}</span></div></div>
      <div class="entity-actions"><button class="button secondary small" data-action="test-channel" data-name="${escapeHtml(channel.name)}">${icon('send')}测试</button><span class="spacer"></span><div class="inline-actions"><button class="icon-button" data-action="edit-channel" data-name="${escapeHtml(channel.name)}" aria-label="编辑">${icon('edit')}</button><button class="icon-button danger" data-action="delete-channel" data-name="${escapeHtml(channel.name)}" aria-label="删除">${icon('trash')}</button></div></div>
    </article>`
  }).join('')}</div>`
}

function renderRoutes() {
  const routes = (state.config.routes || []).filter(item => matches(item.route_name, item.route_id, ...(item.channel_name || []), ...(item.bind_template || [])))
  if (!routes.length) return emptyState('route', state.query ? '没有匹配的通知通道' : '还没有通知通道', state.query ? '请尝试其他关键词' : '创建通道连接推送来源与通知渠道')
  return `<div class="table-wrap"><table class="data-table"><thead><tr><th>通道</th><th>发送渠道</th><th>绑定模板</th><th>状态</th><th>操作</th></tr></thead><tbody>${routes.map(route => `
    <tr><td data-label="通道"><div class="cell-title"><strong>${escapeHtml(route.route_name)}</strong><small>${escapeHtml(route.route_id)}</small></div></td><td data-label="发送渠道">${(route.channel_name || []).map(name => `<span class="tag purple">${escapeHtml(name)}</span>`).join(' ') || '—'}</td><td data-label="绑定模板"><span class="truncate">${escapeHtml((route.bind_template || []).join('、') || '直接透传消息')}</span></td><td data-label="状态"><span class="status-badge ${route.active === false ? 'inactive' : 'active'}">${route.active === false ? '已停用' : '运行中'}</span></td><td data-label="操作"><div class="inline-actions"><button class="icon-button" data-action="copy-route" data-id="${escapeHtml(route.route_id)}" aria-label="复制接口">${icon('copy')}</button><button class="icon-button" data-action="edit-route" data-id="${escapeHtml(route.route_id)}" aria-label="编辑">${icon('edit')}</button><button class="icon-button danger" data-action="delete-route" data-id="${escapeHtml(route.route_id)}" aria-label="删除">${icon('trash')}</button></div></td></tr>`).join('')}</tbody></table></div>`
}

function renderTemplates() {
  const templates = state.templates.filter(item => matches(item.name, item.type, item.description, item.title, item.content))
  if (!templates.length) return emptyState('file', state.query ? '没有匹配的通知模板' : '还没有通知模板', state.query ? '请尝试其他关键词' : '创建模板统一管理消息格式')
  return `<div class="entity-grid">${templates.map(template => `
    <article class="entity-card"><div class="entity-head"><span class="entity-icon">${icon('file')}</span><div class="entity-title"><h3>${escapeHtml(template.name)}</h3><p>${escapeHtml(template.type || '通用模板')}</p></div></div><div class="entity-body"><strong class="truncate">${escapeHtml(template.title || '无标题')}</strong><p class="truncate">${escapeHtml(template.description || template.content || '暂无说明')}</p></div><div class="entity-actions"><span class="tag purple">Jinja</span><span class="spacer"></span><div class="inline-actions"><button class="icon-button" data-action="edit-template" data-name="${escapeHtml(template.name)}" aria-label="编辑">${icon('edit')}</button><button class="icon-button danger" data-action="delete-template" data-name="${escapeHtml(template.name)}" aria-label="删除">${icon('trash')}</button></div></div></article>`).join('')}</div>`
}

function renderPlugins() {
  const plugins = state.plugins.filter(item => matches(item.name, item.id, item.description, item.version))
  if (!plugins.length) return emptyState('plug', '没有匹配的插件', '请尝试其他关键词')
  return `<div class="entity-grid">${plugins.map(plugin => `
    <article class="entity-card"><div class="entity-head"><span class="entity-icon">${icon('plug')}</span><div class="entity-title"><h3>${escapeHtml(plugin.name || plugin.id)}</h3><p>${escapeHtml(plugin.id)} · v${escapeHtml(plugin.version || '—')}</p></div><span class="status-badge active">已加载</span></div><div class="entity-body"><p>${escapeHtml(plugin.description || '暂无插件说明')}</p></div><div class="entity-actions">${plugin.has_frontend ? `<button class="button secondary small" data-action="open-plugin" data-id="${escapeHtml(plugin.id)}">打开页面</button>` : ''}<span class="spacer"></span><button class="button secondary small" data-action="edit-plugin" data-id="${escapeHtml(plugin.id)}">${icon('settings')}配置</button></div></article>`).join('')}</div>`
}

function renderDeliveries() {
  const deliveries = state.deliveries.filter(item => matches(item.title, item.content, item.route_name, item.channel_name, item.last_error))
  const toolbar = `<div class="toolbar"><select id="delivery-status" class="filter-select"><option value="">全部状态</option>${['sent', 'failed', 'retry', 'pending', 'processing'].map(status => `<option value="${status}" ${state.deliveryStatus === status ? 'selected' : ''}>${statusText(status)}</option>`).join('')}</select><span class="tag">共 ${deliveries.length} 条</span></div>`
  if (!deliveries.length) return toolbar + emptyState('history', state.query ? '没有匹配的投递记录' : '暂无投递记录', '新通知进入队列后会显示在这里')
  return `${toolbar}<div class="table-wrap"><table class="data-table"><thead><tr><th>消息</th><th>通道 → 渠道</th><th>状态</th><th>尝试</th><th>时间</th><th>操作</th></tr></thead><tbody>${deliveries.map(item => `
    <tr><td data-label="消息"><div class="cell-title"><strong class="truncate">${escapeHtml(item.title || '无标题')}</strong><small class="truncate">${escapeHtml(item.content || '')}</small></div></td><td data-label="投递链路">${escapeHtml(item.route_name)} → ${escapeHtml(item.channel_name)}</td><td data-label="状态"><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(statusText(item.status))}</span></td><td data-label="尝试">${escapeHtml(item.attempts || 0)}</td><td data-label="时间">${escapeHtml(formatDate(item.updated_at || item.outbox_created_at))}</td><td data-label="操作"><div class="inline-actions"><button class="icon-button" data-action="delivery-detail" data-id="${item.id}" aria-label="查看详情">${icon('more')}</button>${item.status === 'failed' ? `<button class="icon-button" data-action="retry-delivery" data-id="${item.id}" aria-label="重试">${icon('refresh')}</button>` : ''}</div></td></tr>`).join('')}</tbody></table></div>`
}

function renderLogs() {
  const logs = state.logs.filter(item => matches(item.level, item.logger, item.message, item.time))
  if (!logs.length) return emptyState('terminal', state.query ? '没有匹配的日志' : '当前还没有运行日志', '页面每 5 秒自动刷新')
  return `<div class="log-view">${logs.slice().reverse().map(item => `<div class="log-line"><span class="log-time">${escapeHtml(item.time)}</span><span class="log-level ${escapeHtml(item.level)}">${escapeHtml(item.level)}</span><span class="log-name">${escapeHtml(item.logger)}</span><span>${escapeHtml(item.message)}</span></div>`).join('')}</div>`
}

function renderSettings() {
  const app = state.config.app || {}
  return `<div class="settings-grid"><section class="panel"><header class="panel-header"><div><h2>站点设置</h2><p>管理后台的基础信息</p></div><button class="button secondary small" data-action="edit-settings">${icon('edit')}编辑</button></header><div class="panel-body settings-list"><div class="info-row"><span>应用名称</span><strong>${escapeHtml(app.app_name || 'Notify')}</strong></div><div class="info-row"><span>站点地址</span><strong>${escapeHtml(app.site_url || location.origin)}</strong></div><div class="info-row"><span>记录保留</span><strong>${escapeHtml(app.record_retention_days || 90)} 天</strong></div><div class="info-row"><span>GitHub Token</span><strong>${app.github_token ? '已配置' : '未配置'}</strong></div></div></section><section class="panel"><header class="panel-header"><div><h2>运行信息</h2><p>当前实例状态</p></div><span class="status-badge active">正常</span></header><div class="panel-body settings-list"><div class="info-row"><span>系统版本</span><code class="code">v${escapeHtml(state.status.version)}</code></div><div class="info-row"><span>通知渠道</span><strong>${state.status.channels}</strong></div><div class="info-row"><span>通知通道</span><strong>${state.status.routes}</strong></div><div class="info-row"><span>插件任务</span><span class="status-badge ${state.status.plugin_tasks ? 'active' : 'inactive'}">${state.status.plugin_tasks ? '运行中' : '已暂停'}</span></div><div class="info-row"><span>API 文档</span><a class="code" href="/docs" target="_blank" rel="noopener">/docs</a></div></div></section></div>`
}

function emptyState(iconName, title, description) {
  return `<div class="empty-state">${icon(iconName)}<div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div></div>`
}

function formField(name, label, type = 'text', value = '', placeholder = '', hint = '', options = []) {
  const safeValue = value === MASK && type === 'password' ? '' : value ?? ''
  const note = hint || (type === 'password' && value === MASK ? '已安全保存，留空保持原值' : '')
  let control
  if (type === 'checkbox') {
    control = `<label class="check-field"><input name="${escapeHtml(name)}" type="checkbox" ${value ? 'checked' : ''}><span>${escapeHtml(note || label)}</span></label>`
    return `<div class="field"><span>${escapeHtml(label)}</span>${control}</div>`
  }
  if (type === 'textarea') {
    control = `<textarea name="${escapeHtml(name)}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(safeValue)}</textarea>`
  } else if (type === 'select') {
    control = `<select name="${escapeHtml(name)}">${options.map(([optionValue, optionLabel]) => `<option value="${escapeHtml(optionValue)}" ${String(safeValue) === String(optionValue) ? 'selected' : ''}>${escapeHtml(optionLabel)}</option>`).join('')}</select>`
  } else {
    control = `<input name="${escapeHtml(name)}" type="${escapeHtml(type)}" value="${escapeHtml(safeValue)}" placeholder="${escapeHtml(placeholder || (value === MASK ? '留空保持现有值' : ''))}">`
  }
  return `<label class="field"><span>${escapeHtml(label)}</span>${control}${note ? `<small>${escapeHtml(note)}</small>` : ''}</label>`
}

function openModal({ eyebrow = '通知管理', title, body, submitText = '保存', wide = false, noSubmit = false, onSubmit = null }) {
  const modal = $('#modal')
  modal.classList.toggle('wide', wide)
  $('#modal-eyebrow').textContent = eyebrow
  $('#modal-title').textContent = title
  $('#modal-body').innerHTML = body
  $('#modal-submit').textContent = submitText
  $('#modal-submit').classList.add('primary')
  $('#modal-submit').classList.remove('danger')
  $('#modal-submit').hidden = noSubmit
  state.modalSubmit = onSubmit
  if (!modal.open) modal.showModal()
}

function closeModal() {
  const modal = $('#modal')
  if (modal.open) modal.close()
  state.modalSubmit = null
}

function confirmModal(title, message, action, danger = false) {
  openModal({
    eyebrow: danger ? '危险操作' : '请确认',
    title,
    body: `<div class="form-note">${escapeHtml(message)}</div>`,
    submitText: danger ? '确认删除' : '确认',
    onSubmit: action,
  })
  $('#modal-submit').classList.toggle('danger', danger)
  $('#modal-submit').classList.toggle('primary', !danger)
}

async function saveConfig(nextConfig, message = '配置已保存') {
  await api('/api/admin/config', { method: 'PUT', body: JSON.stringify(nextConfig) })
  toast(message)
  closeModal()
  await loadCore()
  renderCurrent()
}

async function saveTemplates(templates, message = '模板已保存') {
  await api('/api/admin/templates', { method: 'PUT', body: JSON.stringify({ template: templates }) })
  toast(message)
  closeModal()
  await loadCore()
  renderCurrent()
}

function openChannelForm(channel = null) {
  const original = channel ? structuredClone(channel) : { name: '', type: 'qywx', config: {} }
  const type = typeInfo(original.type)
  const typeOptions = Object.entries(CHANNEL_TYPES).map(([value, item]) => [value, item.label])
  if (!CHANNEL_TYPES[original.type]) typeOptions.unshift([original.type, original.type])
  const configFields = type.fields.map(([key, label, fieldType = 'text', defaultValue = '', hint = '', options = []]) =>
    formField(`cfg_${key}`, label, fieldType, original.config?.[key] ?? defaultValue, '', hint, options)
  ).join('')
  openModal({
    eyebrow: channel ? '编辑通知渠道' : '新增通知渠道',
    title: channel ? original.name : '创建通知渠道',
    body: `<div class="form-section"><h3 class="form-section-title">基础信息</h3><div class="field-row">${formField('name', '渠道名称', 'text', original.name, '例如：短信转发器')}${formField('type', '渠道类型', 'select', original.type, '', '', typeOptions)}</div></div><div class="form-section"><h3 class="form-section-title">${escapeHtml(type.label)}配置</h3>${configFields || '<p class="form-note">该渠道类型没有预设字段，现有扩展配置会原样保留。</p>'}</div>`,
    onSubmit: async form => {
      const data = new FormData(form)
      const name = String(data.get('name') || '').trim()
      const nextType = String(data.get('type') || '')
      if (!name) throw new Error('请输入渠道名称')
      if ((state.config.channels || []).some(item => item.name === name && item.name !== channel?.name)) throw new Error('渠道名称已存在')
      const config = { ...(original.config || {}) }
      for (const [key, , fieldType = 'text', defaultValue = ''] of (CHANNEL_TYPES[nextType]?.fields || [])) {
        if (fieldType === 'checkbox') {
          config[key] = data.has(`cfg_${key}`)
          continue
        }
        let value = String(data.get(`cfg_${key}`) ?? '').trim()
        if (fieldType === 'number' && value !== '') value = Number(value)
        if (fieldType === 'password' && !value && original.config?.[key] === MASK) value = MASK
        config[key] = value === '' && defaultValue !== '' ? defaultValue : value
      }
      const channels = [...(state.config.channels || [])]
      const index = channels.findIndex(item => item.name === channel?.name)
      const next = { ...original, name, type: nextType, config }
      if (index >= 0) channels[index] = next
      else channels.push(next)
      const routes = (state.config.routes || []).map(route => channel && channel.name !== name ? { ...route, channel_name: (route.channel_name || []).map(item => item === channel.name ? name : item) } : route)
      await saveConfig({ ...state.config, channels, routes }, channel ? '渠道已更新' : '渠道已创建')
    },
  })
  const typeSelect = $('#modal-body select[name="type"]')
  typeSelect.onchange = () => {
    const draft = { ...original, name: $('#modal-body input[name="name"]').value, type: typeSelect.value, config: {} }
    openChannelForm(draft)
  }
}

function openRouteForm(route = null) {
  const original = route ? structuredClone(route) : { route_id: `route_${Math.random().toString(36).slice(2, 7)}`, route_name: '', channel_name: [], bind_template: [], push_img: '', active: true }
  const channels = (state.config.channels || []).map(channel => `<label class="choice"><input type="checkbox" name="channel_name" value="${escapeHtml(channel.name)}" ${(original.channel_name || []).includes(channel.name) ? 'checked' : ''}>${escapeHtml(channel.name)}</label>`).join('')
  const templates = state.templates.map(template => `<label class="choice"><input type="checkbox" name="template_name" value="${escapeHtml(template.name)}" ${(original.bind_template || []).includes(template.name) ? 'checked' : ''}>${escapeHtml(template.name)}</label>`).join('')
  openModal({
    eyebrow: route ? '编辑通知通道' : '新增通知通道', title: route ? original.route_name : '创建通知通道', wide: true,
    body: `<div class="field-row">${formField('route_name', '通道名称', 'text', original.route_name, '例如：VoHive 短信')}${formField('route_id', '通道 ID', 'text', original.route_id, 'route_xxxx', '接口调用使用的唯一 ID')}</div>${formField('push_img', '默认通知图片', 'url', original.push_img || '', 'https://...', '发送方未提供图片时使用此地址')}${formField('active', '启用通道', 'checkbox', original.active !== false, '', '关闭后该通道将拒绝新的推送请求')}<div class="form-section"><h3 class="form-section-title">发送渠道</h3><div class="multi-select">${channels || '请先创建通知渠道'}</div></div><div class="form-section"><h3 class="form-section-title">绑定模板</h3><div class="multi-select">${templates || '暂无模板；不绑定时直接透传标题和内容'}</div><p class="preview-note">PVE、Emby 和 Watchtower 事件会根据事件类型选择绑定模板，普通推送可不绑定。</p></div>`,
    onSubmit: async form => {
      const data = new FormData(form)
      const routeName = String(data.get('route_name') || '').trim()
      const routeId = String(data.get('route_id') || '').trim()
      const channelNames = data.getAll('channel_name').map(String)
      if (!routeName || !routeId) throw new Error('通道名称和 ID 不能为空')
      if (!channelNames.length) throw new Error('至少选择一个发送渠道')
      if ((state.config.routes || []).some(item => item.route_id === routeId && item.route_id !== route?.route_id)) throw new Error('通道 ID 已存在')
      const next = { ...original, route_name: routeName, route_id: routeId, channel_name: channelNames, bind_template: data.getAll('template_name').map(String), push_img: String(data.get('push_img') || '').trim(), active: data.has('active') }
      const routes = [...(state.config.routes || [])]
      const index = routes.findIndex(item => item.route_id === route?.route_id)
      if (index >= 0) routes[index] = next
      else routes.push(next)
      await saveConfig({ ...state.config, routes }, route ? '通道已更新' : '通道已创建')
    },
  })
}

function openTemplateForm(template = null) {
  const original = template ? structuredClone(template) : { name: '', type: '', description: '', title: '{{ title }}', content: '{{ content }}' }
  openModal({
    eyebrow: template ? '编辑通知模板' : '新增通知模板', title: template ? original.name : '创建通知模板', wide: true,
    body: `<div class="dialog-grid"><div><div class="field-row">${formField('name', '模板名称', 'text', original.name, '例如：短信通知')}${formField('type', '事件类型', 'text', original.type, '例如：PVE.Backup')}</div>${formField('description', '模板说明', 'text', original.description || '', '说明这个模板的使用场景')}${formField('title', '通知标题', 'textarea', original.title || '')}${formField('content', '通知内容', 'textarea', original.content || '')}<p class="form-note">保持现有 Jinja 模板变量不变，例如 <code>{{ device_name }}</code>。变量由实际推送来源填充。</p></div><aside class="preview-pane"><p class="eyebrow">News 实时预览</p><div class="news-preview"><div class="news-image">${icon('bell')}</div><div class="news-copy"><h3 id="preview-title">${escapeHtml(original.title || '通知标题')}</h3><p id="preview-content">${escapeHtml(original.content || '通知内容')}</p></div></div><p class="preview-note">这是企业微信 News 卡片的内容结构预览；图片和链接来自通道或推送请求。</p></aside></div>`,
    onSubmit: async form => {
      const data = new FormData(form)
      const name = String(data.get('name') || '').trim()
      if (!name) throw new Error('请输入模板名称')
      if (state.templates.some(item => item.name === name && item.name !== template?.name)) throw new Error('模板名称已存在')
      const next = { ...original, name, type: String(data.get('type') || '').trim(), description: String(data.get('description') || '').trim(), title: String(data.get('title') || ''), content: String(data.get('content') || '') }
      const templates = [...state.templates]
      const index = templates.findIndex(item => item.name === template?.name)
      if (index >= 0) templates[index] = next
      else templates.push(next)
      const routes = (state.config.routes || []).map(route => template && template.name !== name ? { ...route, bind_template: (route.bind_template || []).map(item => item === template.name ? name : item) } : route)
      if (template && template.name !== name) await api('/api/admin/config', { method: 'PUT', body: JSON.stringify({ ...state.config, routes }) })
      await saveTemplates(templates, template ? '模板已更新' : '模板已创建')
    },
  })
  const updatePreview = () => {
    $('#preview-title').textContent = $('#modal-body [name="title"]').value || '通知标题'
    $('#preview-content').textContent = $('#modal-body [name="content"]').value || '通知内容'
  }
  $('#modal-body [name="title"]').addEventListener('input', updatePreview)
  $('#modal-body [name="content"]').addEventListener('input', updatePreview)
}

function isSecretField(name) {
  const key = String(name).toLowerCase().replaceAll('-', '_')
  return ['key', 'webhook_url'].includes(key) || ['secret', 'token', 'password', 'api_key', 'apikey', 'aeskey'].some(part => key.includes(part))
}

function pluginOptions(field) {
  if (Array.isArray(field.options)) return field.options.map(item => [item.value, item.label || item.value])
  if (field.enumValuesRef === 'RouterList') return (state.config.routes || []).map(item => [item.route_id, item.route_name])
  if (field.enumValuesRef === 'ChannelList') return (state.config.channels || []).map(item => [item.name, item.name])
  if (field.enumValuesRef === 'TemplateList') return state.templates.map(item => [item.name, item.name])
  return []
}

function pluginField(field, value) {
  const name = field.fieldName
  const options = pluginOptions(field)
  const multiple = field.fieldType === 'multi_select' || field.multiValue === true
  if (multiple && options.length) {
    const selected = Array.isArray(value) ? value.map(String) : String(value || '').split(',').filter(Boolean)
    return `<div class="field"><span>${escapeHtml(field.label || name)}</span><div class="multi-select">${options.map(([optionValue, optionLabel]) => `<label class="choice"><input type="checkbox" name="plugin_${escapeHtml(name)}" value="${escapeHtml(optionValue)}" ${selected.includes(String(optionValue)) ? 'checked' : ''}>${escapeHtml(optionLabel)}</label>`).join('')}</div>${field.helpText ? `<small>${escapeHtml(field.helpText)}</small>` : ''}</div>`
  }
  if (field.fieldType === 'enum' && options.length) return formField(`plugin_${name}`, field.label || name, 'select', value ?? field.defaultValue ?? '', '', field.helpText || '', options)
  const type = field.fieldType === 'number' ? 'number' : field.fieldType === 'text' ? 'textarea' : isSecretField(name) ? 'password' : 'text'
  const hint = isSecretField(name) && value === MASK ? '已安全保存，留空保持原值' : field.helpText || ''
  return formField(`plugin_${name}`, field.label || name, type, Array.isArray(value) ? value.join(',') : value ?? field.defaultValue ?? '', '', hint)
}

async function openPluginForm(plugin) {
  const config = await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/config`)
  const fields = plugin.configField || []
  const body = fields.length ? fields.map(field => pluginField(field, config[field.fieldName])).join('') : '<p class="form-note">这个插件没有通用配置项，请使用插件自己的页面完成操作。</p>'
  openModal({
    eyebrow: '插件设置', title: plugin.name || plugin.id, body,
    noSubmit: !fields.length,
    onSubmit: fields.length ? async form => {
      const data = new FormData(form)
      const next = { ...config }
      for (const field of fields) {
        const name = field.fieldName
        const multiple = field.fieldType === 'multi_select' || field.multiValue === true
        if (multiple && pluginOptions(field).length) {
          next[name] = data.getAll(`plugin_${name}`).map(String)
          continue
        }
        let value = String(data.get(`plugin_${name}`) ?? '').trim()
        if (field.fieldType === 'number' && value !== '') value = Number(value)
        if (isSecretField(name) && !value && config[name] === MASK) value = MASK
        next[name] = value
      }
      await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/config`, { method: 'PUT', body: JSON.stringify(next) })
      toast('插件配置已保存', '重启服务后加载新的插件设置')
      closeModal()
    } : null,
  })
}

function openSettingsForm() {
  const app = state.config.app || {}
  openModal({
    eyebrow: '系统管理', title: '编辑站点设置',
    body: `${formField('app_name', '应用名称', 'text', app.app_name || 'Notify')}${formField('site_url', '站点公网地址', 'url', app.site_url || '', 'https://notify.example.com', '用于生成对外接口地址')}${formField('record_retention_days', '记录保留天数', 'number', app.record_retention_days || 90)}${formField('github_token', 'GitHub Token', 'password', app.github_token || '', '', '可选；留空保持现有 Token')}`,
    onSubmit: async form => {
      const data = new FormData(form)
      const githubToken = String(data.get('github_token') || '').trim()
      const nextApp = {
        ...app,
        app_name: String(data.get('app_name') || '').trim() || 'Notify',
        site_url: String(data.get('site_url') || '').trim(),
        record_retention_days: Math.max(1, Number(data.get('record_retention_days') || 90)),
        github_token: !githubToken && app.github_token === MASK ? MASK : githubToken,
      }
      await saveConfig({ ...state.config, app: nextApp }, '系统设置已更新')
    },
  })
}

function openTestChannel(channel) {
  openModal({
    eyebrow: '连接测试', title: `测试 · ${channel.name}`,
    body: `${formField('title', '通知标题', 'text', 'Notify 测试通知')}${formField('content', '通知内容', 'textarea', '渠道连接正常，这是一条来自 Notify 管理中心的测试消息。')}${formField('push_img_url', '通知图片（可选）', 'url', channel.config?.test_image || '')}${formField('push_link_url', '跳转链接（可选）', 'url', state.config.app?.site_url || '')}`,
    submitText: '发送测试',
    onSubmit: async form => {
      const data = new FormData(form)
      await api(`/api/admin/channels/${encodeURIComponent(channel.name)}/test`, { method: 'POST', body: JSON.stringify({ title: data.get('title'), content: data.get('content'), push_img_url: data.get('push_img_url') || null, push_link_url: data.get('push_link_url') || null }) })
      toast('测试通知已进入发送队列')
      closeModal()
      setTimeout(async () => { await loadCore(); if (currentPage() === 'channels') renderCurrent() }, 1200)
    },
  })
}

function openDeliveryDetail(item) {
  openModal({
    eyebrow: `投递 #${item.id}`, title: item.title || '无标题通知', noSubmit: true, wide: true,
    body: `<div class="field-row three"><div class="info-row"><span>状态</span><span class="status-badge ${escapeHtml(item.status)}">${escapeHtml(statusText(item.status))}</span></div><div class="info-row"><span>尝试次数</span><strong>${escapeHtml(item.attempts || 0)}</strong></div><div class="info-row"><span>更新时间</span><strong>${escapeHtml(formatDate(item.updated_at))}</strong></div></div><div class="form-section"><h3 class="form-section-title">投递链路</h3><p>${escapeHtml(item.route_name)} <span class="code">${escapeHtml(item.route_id)}</span> → ${escapeHtml(item.channel_name)}</p></div><div class="form-section"><h3 class="form-section-title">消息内容</h3><div class="form-note" style="white-space:pre-wrap">${escapeHtml(item.content || '')}</div></div>${item.last_error ? `<div class="form-section"><h3 class="form-section-title">失败原因</h3><div class="form-note" style="color:var(--red);white-space:pre-wrap">${escapeHtml(item.last_error)}</div></div>` : ''}${item.push_img_url || item.push_link_url ? `<div class="form-section"><h3 class="form-section-title">附加内容</h3><p>${item.push_img_url ? `图片：${escapeHtml(item.push_img_url)}<br>` : ''}${item.push_link_url ? `链接：${escapeHtml(item.push_link_url)}` : ''}</p></div>` : ''}`,
  })
}

function toast(title, description = '', type = 'success') {
  const node = document.createElement('div')
  node.className = `toast ${type}`
  node.innerHTML = `<span class="activity-icon ${type === 'error' ? 'failed' : 'sent'}">${icon(type === 'error' ? 'alert' : 'check')}</span><div><strong>${escapeHtml(title)}</strong>${description ? `<small>${escapeHtml(description)}</small>` : ''}</div>`
  $('#toasts').append(node)
  setTimeout(() => node.remove(), 4200)
}

function openMobileMenu() {
  $('#sidebar').classList.add('open')
  $('#mobile-backdrop').classList.add('open')
}

function closeMobileMenu() {
  $('#sidebar').classList.remove('open')
  $('#mobile-backdrop').classList.remove('open')
}

async function handleAction(action, target) {
  if (action === 'open-menu') return openMobileMenu()
  if (action === 'close-menu') return closeMobileMenu()
  if (action === 'close-modal') return closeModal()
  if (action === 'toggle-theme') return setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark')
  if (action === 'user-menu') { $('#user-menu').hidden = !$('#user-menu').hidden; return }
  if (action === 'logout') {
    await api('/api/admin/logout', { method: 'POST' })
    $('#user-menu').hidden = true
    return showLogin()
  }
  if (action === 'refresh') {
    await loadCore()
    await renderPage()
    return toast('数据已刷新')
  }
  if (action === 'add-channel') return openChannelForm()
  if (action === 'edit-channel') return openChannelForm((state.config.channels || []).find(item => item.name === target.dataset.name))
  if (action === 'test-channel') return openTestChannel((state.config.channels || []).find(item => item.name === target.dataset.name))
  if (action === 'delete-channel') {
    const name = target.dataset.name
    const routes = (state.config.routes || []).filter(route => (route.channel_name || []).includes(name))
    if (routes.length) return toast('无法删除正在使用的渠道', `仍被 ${routes.map(item => item.route_name).join('、')} 使用`, 'error')
    return confirmModal('删除通知渠道', `确定删除“${name}”吗？此操作不会删除历史投递记录。`, async () => saveConfig({ ...state.config, channels: state.config.channels.filter(item => item.name !== name) }, '渠道已删除'), true)
  }
  if (action === 'add-route') return openRouteForm()
  if (action === 'edit-route') return openRouteForm((state.config.routes || []).find(item => item.route_id === target.dataset.id))
  if (action === 'delete-route') {
    const route = state.config.routes.find(item => item.route_id === target.dataset.id)
    return confirmModal('删除通知通道', `确定删除“${route.route_name}”吗？现有调用地址将立即失效。`, async () => saveConfig({ ...state.config, routes: state.config.routes.filter(item => item.route_id !== route.route_id) }, '通道已删除'), true)
  }
  if (action === 'copy-route') {
    const base = (state.config.app?.site_url || location.origin).replace(/\/$/, '')
    await navigator.clipboard.writeText(`${base}/api/service/notify/${target.dataset.id}/{title}/{content}`)
    return toast('调用地址已复制')
  }
  if (action === 'add-template') return openTemplateForm()
  if (action === 'edit-template') return openTemplateForm(state.templates.find(item => item.name === target.dataset.name))
  if (action === 'delete-template') {
    const name = target.dataset.name
    const routes = (state.config.routes || []).filter(route => (route.bind_template || []).includes(name))
    if (routes.length) return toast('无法删除正在使用的模板', `仍被 ${routes.map(item => item.route_name).join('、')} 使用`, 'error')
    return confirmModal('删除通知模板', `确定删除“${name}”吗？`, async () => saveTemplates(state.templates.filter(item => item.name !== name), '模板已删除'), true)
  }
  if (action === 'edit-plugin') return openPluginForm(state.plugins.find(item => item.id === target.dataset.id))
  if (action === 'open-plugin') return window.open(`/api/plugins/${encodeURIComponent(target.dataset.id)}/frontend/`, '_blank', 'noopener')
  if (action === 'retry-delivery') {
    await api(`/api/admin/deliveries/${target.dataset.id}/retry`, { method: 'POST' })
    toast('已重新加入发送队列')
    return renderPage()
  }
  if (action === 'delivery-detail') return openDeliveryDetail(state.deliveries.find(item => String(item.id) === String(target.dataset.id)))
  if (action === 'edit-settings') return openSettingsForm()
}

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault()
  const form = event.currentTarget
  const submit = form.querySelector('button[type="submit"]')
  const error = $('#login-error')
  submit.disabled = true
  error.textContent = ''
  try {
    const data = new FormData(form)
    const session = await api('/api/admin/login', { method: 'POST', body: JSON.stringify({ username: data.get('username'), password: data.get('password') }) })
    form.reset()
    form.elements.username.value = session.username || 'admin'
    await showApp(session)
  } catch (reason) {
    error.textContent = reason.message
  } finally {
    submit.disabled = false
  }
})

$('#modal-form').addEventListener('submit', async event => {
  event.preventDefault()
  if (!state.modalSubmit) return closeModal()
  const submit = $('#modal-submit')
  submit.disabled = true
  try {
    await state.modalSubmit(event.currentTarget)
  } catch (reason) {
    toast('操作失败', reason.message, 'error')
  } finally {
    submit.disabled = false
  }
})

document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]')
  if (!target) return
  try { await handleAction(target.dataset.action, target) } catch (reason) { toast('操作失败', reason.message, 'error') }
})

$('#mobile-backdrop').addEventListener('click', closeMobileMenu)

$('#global-search').addEventListener('input', event => {
  state.query = event.target.value
  renderCurrent()
})

document.addEventListener('change', event => {
  if (event.target.id === 'delivery-status') {
    state.deliveryStatus = event.target.value
    renderPage().catch(reason => toast('加载失败', reason.message, 'error'))
  }
})

document.addEventListener('keydown', event => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    $('#global-search')?.focus()
  }
  if (event.key === 'Escape') closeMobileMenu()
})

window.addEventListener('hashchange', () => renderPage().catch(reason => toast('加载失败', reason.message, 'error')))

async function boot() {
  const preferred = localStorage.getItem('notify-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  setTheme(preferred)
  try {
    const session = await api('/api/admin/session')
    if (session.authenticated) await showApp(session)
    else showLogin()
  } catch {
    showLogin()
  }
}

boot()
