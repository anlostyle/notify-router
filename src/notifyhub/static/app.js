const $ = (selector, root = document) => root.querySelector(selector)
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)]
const PAGES = {
  dashboard: ['运行概览', '系统看板', '查看通知服务的运行状态与近期投递表现'],
  channels: ['通知管理', '通知渠道', '管理企业微信、Telegram、Webhook 等消息出口'],
  routes: ['通知管理', '通知通道', '将推送入口、通知模板与发送渠道连接起来'],
  templates: ['通知管理', '通知模板', '统一管理不同服务的消息格式并实时预览'],
  monitors: ['服务中心', '监控中心', '集中查看服务、主机、容器与备份的当前状态和事件'],
  tasks: ['服务中心', '任务中心', '查看定时任务、系统任务及每次执行结果'],
  plugins: ['应用与插件', '插件管理', '管理插件商店、运行能力和第三方服务集成'],
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
      ['corpsecret', '应用 Secret', 'password', '', '以明文保存和显示'],
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

const DEFAULT_TEMPLATE_TYPE = 'default'
const TEMPLATE_EVENT_GROUPS = [
  {
    label: '默认',
    values: [[DEFAULT_TEMPLATE_TYPE, '默认']],
  },
  {
    label: 'Emby',
    values: [
      ['Emby.PlaybackStart', '播放开始'],
      ['Emby.PlaybackEnd', '播放停止'],
      ['Emby.LibraryNewMovie', '电影入库'],
      ['Emby.LibraryNewSeries', '剧集入库'],
      ['Emby.PlaybackPause', '暂停播放'],
      ['Emby.PlaybackUnpause', '恢复播放'],
      ['Emby.LibraryNewAudio', '音乐入库'],
      ['Emby.LibraryDeleted', '删除媒体'],
      ['Emby.UserAuthenticated', '登录成功'],
      ['Emby.UserAuthenticationFailed', '登录失败'],
      ['Emby.PluginInstalled', '插件安装'],
      ['Emby.PluginUninstalled', '插件卸载'],
      ['Emby.IntroskipUpdate', '片头标记更新'],
      ['Emby.ItemMarkedPlayed', '标记已播放'],
      ['Emby.ItemMarkedUnplayed', '标记未播放'],
      ['Emby.ItemRated', '评分/收藏'],
      ['Emby.SystemStartup', '服务启动'],
      ['Emby.SystemUpdateAvailable', '新版本可用'],
    ],
  },
  {
    label: 'PVE',
    values: [
      ['PVE.Backup', '备份任务'],
      ['PVE.Pruning', '精简任务'],
      ['PVE.Garbage', '垃圾回收'],
    ],
  },
  {
    label: 'Watchtower',
    values: [
      ['Watchtower.Update', '镜像更新'],
      ['Watchtower.Start', '启动事件'],
      ['Watchtower.Error', '错误事件'],
    ],
  },
]

const state = {
  session: null,
  status: null,
  config: null,
  templates: [],
  eventTypes: [],
  plugins: [],
  pluginStore: { sources: [], plugins: [] },
  pluginStoreLoading: false,
  pluginStoreError: '',
  pluginStoreRequest: 0,
  monitors: { items: [], events: [], summary: {} },
  tasks: { items: [], runs: [], summary: {} },
  deliveries: [],
  logs: [],
  query: '',
  deliveryStatus: '',
  deliveryFilters: { route_id: '', channel_name: '', error: '', date_from: '', date_to: '' },
  lastPage: '',
  modalSubmit: null,
  logTimer: null,
  pluginLogTimer: null,
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

function templateEventOptions(selectedType) {
  const registered = new Map((state.eventTypes || []).map(item => [String(item.value), item]))
  const groups = TEMPLATE_EVENT_GROUPS.map(group => ({ label: group.label, values: group.values.slice() }))
  const assigned = new Set()

  for (const group of groups) {
    group.values = group.values.filter(([value]) => value === DEFAULT_TEMPLATE_TYPE || registered.has(value))
    group.values.forEach(([value]) => assigned.add(value))
  }

  // Keep newly registered plugin/native events available without flattening the built-in groups.
  for (const item of registered.values()) {
    const value = String(item.value || '')
    if (!value || assigned.has(value)) continue
    const groupName = value.split('.', 1)[0]
    let group = groups.find(entry => entry.label === groupName)
    const rawLabel = String(item.label || value)
    const label = rawLabel.startsWith(`${groupName} · `) ? rawLabel.slice(groupName.length + 3) : rawLabel.startsWith(`${groupName}:`) ? rawLabel.slice(groupName.length + 1).trim() : rawLabel
    if (!group) {
      group = { label: groupName || '其他', values: [] }
      groups.push(group)
    }
    group.values.push([value, label])
    assigned.add(value)
  }

  const options = groups.map(group => {
    const values = group.values.map(([value, label]) => `<option value="${escapeHtml(value)}" ${selectedType === value ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')
    return values ? `<optgroup label="${escapeHtml(group.label)}">${values}</optgroup>` : ''
  }).join('')
  return options
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

async function copyText(value) {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(value)
  const field = document.createElement('textarea')
  field.value = value
  field.style.position = 'fixed'
  field.style.opacity = '0'
  document.body.append(field)
  field.select()
  const copied = document.execCommand('copy')
  field.remove()
  if (!copied) throw new Error('当前浏览器不支持自动复制，请手动复制接口地址')
}

function setTheme(theme) {
  document.documentElement.dataset.theme = theme
  localStorage.setItem('notify-theme', theme)
  const icon = theme === 'dark' ? '#i-sun' : '#i-moon'
  $('#theme-icon')?.setAttribute('href', icon)
  $('#login-theme-icon')?.setAttribute('href', icon)
}

const PALETTES = [
  ['靛蓝', '#4f46e5', '#3730a3'], ['海蓝', '#2563eb', '#1d4ed8'],
  ['青色', '#0891b2', '#0e7490'], ['翡翠', '#059669', '#047857'],
  ['琥珀', '#d97706', '#b45309'], ['珊瑚', '#ea580c', '#c2410c'],
  ['玫红', '#e11d48', '#be123c'], ['紫罗兰', '#7c3aed', '#6d28d9'],
  ['洋红', '#c026d3', '#a21caf'], ['蓝灰', '#64748b', '#475569'],
]

function setPalette(index) {
  index = PALETTES[index] ? index : 7
  const item = PALETTES[index]
  document.documentElement.style.setProperty('--primary', item[1])
  document.documentElement.style.setProperty('--primary-strong', item[2])
  document.documentElement.style.setProperty('--primary-soft', `${item[1]}26`)
  document.documentElement.style.setProperty('--primary-grad', `linear-gradient(180deg, ${item[1]}, ${item[2]})`)
  document.documentElement.style.setProperty('--nav-active-bg', `${item[1]}26`)
  document.documentElement.style.setProperty('--nav-active-text', item[1])
  document.documentElement.style.setProperty('--nav-badge-bg', `${item[1]}20`)
  document.documentElement.style.setProperty('--nav-badge-text', item[1])
  document.querySelectorAll('.brand-mark').forEach(node => { node.style.background = `linear-gradient(145deg, ${item[1]}, ${item[2]})` })
  localStorage.setItem('notify-palette', String(index))
}

function togglePaletteMenu(button) {
  const existing = $('#palette-menu')
  if (existing) return existing.remove()
  const selected = Number(localStorage.getItem('notify-palette') || 7)
  const menu = document.createElement('div')
  menu.id = 'palette-menu'
  menu.className = 'palette-menu'
  menu.innerHTML = PALETTES.map((item, index) => `<button class="palette-item ${index === selected ? 'active' : ''}" data-palette="${index}"><i class="palette-dot" style="background:${item[1]}"></i>${item[0]}</button>`).join('')
  document.body.append(menu)
  const rect = button.getBoundingClientRect()
  menu.style.top = `${Math.min(rect.bottom + 8, window.innerHeight - menu.offsetHeight - 12)}px`
  menu.style.right = `${Math.max(12, window.innerWidth - rect.right)}px`
}

function currentPage() {
  const page = location.hash.slice(1).split('?')[0]
  return PAGES[page] ? page : 'dashboard'
}

function showLogin() {
  clearInterval(state.logTimer)
  $('#app').hidden = true
  $('#login-view').hidden = false
  document.body.classList.remove('auth-pending')
  setTimeout(() => $('#login-form input[name="username"]')?.focus(), 40)
}

async function showApp(session) {
  state.session = session
  $('#login-view').hidden = true
  $('#app').hidden = false
  document.body.classList.remove('auth-pending')
  $('#username').textContent = session.username || 'admin'
  $('#user-avatar').textContent = (session.username || 'A').slice(0, 1).toUpperCase()
  await loadCore()
  await renderPage()
  if (session.password_change_required || state.status.password_change_required) {
    setTimeout(() => openPasswordForm(true), 120)
  }
}

async function loadCore() {
  const [status, config, templatePayload, eventTypePayload, plugins, monitors, tasks] = await Promise.all([
    api('/api/admin/status'), api('/api/admin/config'), api('/api/admin/templates'), api('/api/admin/event-types'), api('/api/admin/plugins'),
    api('/api/admin/monitors'), api('/api/admin/tasks'),
  ])
  state.status = status
  state.config = config
  state.templates = templatePayload.template || []
  state.eventTypes = eventTypePayload.event_types || []
  state.plugins = plugins || []
  state.monitors = monitors || { items: [], events: [], summary: {} }
  state.tasks = tasks || { items: [], runs: [], summary: {} }
  $('#nav-channels').textContent = status.channels
  $('#nav-routes').textContent = status.routes
  $('#nav-plugins').textContent = status.plugins
  $('#nav-monitors').textContent = state.monitors.summary?.total || 0
  $('#nav-tasks').textContent = state.tasks.summary?.total || 0
  $('#sidebar-version').textContent = `v${status.version}`
}

function setPageActions(page) {
  const actions = {
    dashboard: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    channels: `<button class="button primary" data-action="add-channel" aria-label="新增渠道">${icon('plus')}<span>新增渠道</span></button>`,
    routes: `<button class="button primary" data-action="add-route" aria-label="新增通道">${icon('plus')}<span>新增通道</span></button>`,
    templates: `<button class="button primary" data-action="add-template" aria-label="新增模板">${icon('plus')}<span>新增模板</span></button>`,
    monitors: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    tasks: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    deliveries: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    logs: `<button class="button secondary" data-action="refresh" aria-label="刷新">${icon('refresh')}<span>刷新</span></button>`,
    plugins: `<button class="button secondary" data-action="manage-plugin-sources" aria-label="管理插件源">${icon('settings')}<span>插件源</span></button>`,
    settings: `<button class="button secondary" data-action="export-config" aria-label="导出配置">${icon('download')}<span>导出</span></button><button class="button secondary" data-action="import-config" aria-label="导入配置">${icon('upload')}<span>导入</span></button><button class="button primary" data-action="edit-settings" aria-label="编辑设置">${icon('edit')}<span>编辑设置</span></button>`,
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
    const filters = { ...state.deliveryFilters, status: state.deliveryStatus }
    const suffix = Object.entries(filters).filter(([, value]) => value).map(([key, value]) => `&${key}=${encodeURIComponent(value)}`).join('')
    state.deliveries = await api(`/api/admin/deliveries?limit=300${suffix}`)
  }
  if (page === 'logs') {
    state.logs = await api('/api/admin/logs?limit=300')
    state.logTimer = setInterval(async () => {
      if (currentPage() !== 'logs') return
      try { state.logs = await api('/api/admin/logs?limit=300'); renderCurrent() } catch { /* next poll retries */ }
    }, 5000)
  }
  if (page === 'plugins') {
    state.pluginStoreLoading = true
    state.pluginStoreError = ''
    loadPluginStore()
  }
  if (page === 'monitors') {
    $('#page-content').innerHTML = '<div class="skeleton"></div>'
    state.monitors = await api('/api/admin/monitors')
    $('#nav-monitors').textContent = state.monitors.summary?.total || 0
  }
  if (page === 'tasks') {
    $('#page-content').innerHTML = '<div class="skeleton"></div>'
    state.tasks = await api('/api/admin/tasks')
    $('#nav-tasks').textContent = state.tasks.summary?.total || 0
  }
  renderCurrent()
}

function renderCurrent() {
  const renderers = {
    dashboard: renderDashboard,
    channels: renderChannels,
    routes: renderRoutes,
    templates: renderTemplates,
    monitors: renderMonitors,
    tasks: renderTasks,
    plugins: renderPlugins,
    deliveries: renderDeliveries,
    logs: renderLogs,
    settings: renderSettings,
  }
  $('#page-content').innerHTML = renderers[currentPage()]()
}

function renderMonitors() {
  const summary = state.monitors.summary || {}
  const items = (state.monitors.items || []).filter(item => matches(item.name, item.provider, item.category, item.status, item.summary))
  const events = state.monitors.events || []
  const cards = items.length ? `<div class="entity-grid">${items.map(item => {
    const healthy = ['up', 'healthy', 'ok'].includes(item.status)
    return `<article class="entity-card"><div class="entity-head"><span class="entity-icon">${icon('monitor')}</span><div class="entity-title"><h3>${escapeHtml(item.name)}</h3><p>${escapeHtml(item.provider)} · ${escapeHtml(item.category)}</p></div><span class="status-badge ${healthy ? 'active' : 'failed'}">${healthy ? '正常' : '需关注'}</span></div><div class="entity-body"><p>${escapeHtml(item.summary || '暂无状态说明')}</p></div><div class="entity-actions"><small>检查：${escapeHtml(formatDate(item.last_checked_at))}</small><span class="spacer"></span><span class="tag">${escapeHtml(item.status)}</span></div></article>`
  }).join('')}</div>` : emptyState('monitor', '还没有监控数据', 'NDU、Watchtower、哪吒或 PVE 产生状态后会显示在这里')
  const history = events.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>事件</th><th>来源</th><th>状态</th><th>时间</th></tr></thead><tbody>${events.slice(0,50).map(item => `<tr><td><div class="cell-title"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.summary)}</small></div></td><td>${escapeHtml(item.source)}</td><td><span class="status-badge ${item.status === 'resolved' ? 'active' : 'pending'}">${item.status === 'resolved' ? '已恢复' : '事件'}</span></td><td>${escapeHtml(formatDate(item.created_at))}</td></tr>`).join('')}</tbody></table></div>` : ''
  return `<div class="stats-grid">${statCard('监控项', summary.total || 0, '统一状态入口', 'monitor', 'purple')}${statCard('运行正常', summary.healthy || 0, '最近检查健康', 'check', 'green')}${statCard('需要关注', summary.attention || 0, '异常或警告', 'alert', 'orange')}</div>${cards}<section class="panel" style="margin-top:18px"><header class="panel-header"><div><h2>状态事件</h2><p>异常与恢复历史</p></div></header><div class="panel-body">${history || '暂无状态变化'}</div></section>`
}

function renderTasks() {
  const summary = state.tasks.summary || {}
  const items = (state.tasks.items || []).filter(item => matches(item.name, item.plugin_id, item.schedule, item.last_status))
  const rows = items.length ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>任务</th><th>来源</th><th>计划</th><th>最近状态</th><th>最近完成</th></tr></thead><tbody>${items.map(item => `<tr><td><strong>${escapeHtml(item.name)}</strong></td><td><span class="tag purple">${escapeHtml(item.plugin_id)}</span></td><td><code class="code">${escapeHtml(item.schedule)}</code></td><td><span class="status-badge ${item.last_status === 'success' ? 'active' : item.last_status === 'failed' ? 'failed' : 'pending'}">${escapeHtml(item.last_status)}</span></td><td>${escapeHtml(formatDate(item.last_finished_at))}</td></tr>`).join('')}</tbody></table></div>` : emptyState('task', '还没有已注册任务', 'Reminder、NSRSS 等插件注册定时任务后会显示在这里')
  return `<div class="stats-grid">${statCard('全部任务', summary.total || 0, '插件与系统任务', 'task', 'purple')}${statCard('已启用', summary.enabled || 0, '由调度器管理', 'check', 'green')}${statCard('执行失败', summary.failed || 0, `运行中 ${summary.running || 0}`, 'alert', 'orange')}</div>${rows}`
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
  const catalog = (state.pluginStore.plugins || []).filter(item => matches(item.name, item.id, item.description, item.version, item.author))
  const sources = state.pluginStore.sources || []
  const sourceSummary = sources.length
    ? sources.map(source => `<span class="tag ${source.status === 'error' ? 'danger' : ''}" title="${escapeHtml(source.error || source.url)}">${escapeHtml(source.name)} · ${source.status === 'ok' ? '正常' : '异常'}</span>`).join(' ')
    : state.pluginStoreLoading ? '<span class="form-note">正在加载插件源…</span>' : '<span class="form-note">还没有插件源，点击右上角“插件源”添加地址。</span>'
  const installedCards = plugins.length ? `<div class="entity-grid">${plugins.map(plugin => {
    const canTest = (plugin.capabilities || []).includes('notify.test')
    return `<article class="entity-card"><div class="entity-head"><span class="entity-icon">${icon('plug')}</span><div class="entity-title"><h3>${escapeHtml(plugin.name || plugin.id)}</h3><p>${escapeHtml(plugin.id)} · v${escapeHtml(plugin.version || '—')}</p></div><span class="status-badge active">已加载</span></div><div class="entity-body"><p>${escapeHtml(plugin.description || '暂无插件说明')}</p><div>${(plugin.capabilities || []).map(value => `<span class="tag purple">${escapeHtml(value)}</span>`).join(' ')}</div></div><div class="entity-actions">${plugin.has_frontend ? `<button class="button secondary small" data-action="open-plugin" data-id="${escapeHtml(plugin.id)}">打开页面</button>` : ''}<button class="button secondary small" data-action="plugin-docs" data-id="${escapeHtml(plugin.id)}">使用说明</button><button class="button secondary small" data-action="plugin-logs" data-id="${escapeHtml(plugin.id)}">日志</button>${canTest ? `<button class="button secondary small" data-action="test-plugin" data-id="${escapeHtml(plugin.id)}">${icon('send')}测试通知</button>` : ''}<span class="spacer"></span><button class="button secondary small" data-action="edit-plugin" data-id="${escapeHtml(plugin.id)}">${icon('settings')}配置</button></div></article>`
  }).join('')}</div>`
    : '<div class="empty-state"><p>当前没有已加载的可选插件</p></div>'
  const storeCards = catalog.length ? `<div class="entity-grid">${catalog.map(plugin => {
    const action = plugin.update_available ? 'update-plugin' : plugin.installed ? '' : 'install-plugin'
    const label = plugin.update_available ? `更新到 v${plugin.version}` : plugin.installed ? '已是最新版' : '安装'
    return `<article class="entity-card"><div class="entity-head"><span class="entity-icon">${icon('plug')}</span><div class="entity-title"><h3>${escapeHtml(plugin.name || plugin.id)}</h3><p>${escapeHtml(plugin.author || '第三方开发者')} · v${escapeHtml(plugin.version)}</p></div><span class="status-badge ${plugin.installed ? 'active' : 'pending'}">${plugin.update_available ? '可更新' : plugin.installed ? '已安装' : '未安装'}</span></div><div class="entity-body"><p>${escapeHtml(plugin.description || '暂无插件说明')}</p>${plugin.installed_version ? `<small>本地版本 v${escapeHtml(plugin.installed_version)}</small>` : ''}</div><div class="entity-actions">${action ? `<button class="button primary small" data-action="${action}" data-id="${escapeHtml(plugin.id)}" data-source="${escapeHtml(plugin.source_url)}">${label}</button>` : `<button class="button secondary small" disabled>${label}</button>`}<span class="spacer"></span>${plugin.installed ? `<button class="button danger small" data-action="uninstall-plugin" data-id="${escapeHtml(plugin.id)}">卸载</button>` : ''}</div></article>`
  }).join('')}</div>` : state.pluginStoreLoading ? emptyState('plug', '正在加载插件商店', '已加载插件会先显示，插件库稍后自动刷新') : state.pluginStoreError ? emptyState('plug', '插件商店加载失败', state.pluginStoreError) : emptyState('plug', sources.length ? '插件源中没有匹配的插件' : '添加插件源后浏览插件库', sources.length ? '请检查插件源或尝试其他关键词' : '插件源是一个公开的 JSON 索引地址')
  const storeStatus = state.pluginStoreLoading ? '<span class="tag">正在刷新</span>' : state.pluginStoreError ? '<span class="tag danger">加载失败</span>' : `<span class="tag purple">${catalog.length} 个插件</span>`
  return `<div class="toolbar">${sourceSummary}</div><section class="panel"><header class="panel-header"><div><h2>插件商店</h2><p>在线安装和更新插件；单插件热切换，失败自动回滚</p></div>${storeStatus}</header><div class="panel-body">${storeCards}</div></section><section class="panel" style="margin-top:18px"><header class="panel-header"><div><h2>已加载插件</h2><p>由独立 Worker 运行的插件</p></div><span class="tag">${plugins.length} 个</span></header><div class="panel-body">${installedCards}</div></section>`
}

function loadPluginStore() {
  const request = ++state.pluginStoreRequest
  api('/api/admin/plugin-store').then(payload => {
    if (request !== state.pluginStoreRequest || currentPage() !== 'plugins') return
    state.pluginStore = payload || { sources: [], plugins: [] }
    state.pluginStoreLoading = false
    renderCurrent()
  }).catch(error => {
    if (request !== state.pluginStoreRequest || currentPage() !== 'plugins') return
    state.pluginStoreLoading = false
    state.pluginStoreError = error.message || '无法加载插件商店'
    renderCurrent()
  })
}

function renderDeliveries() {
  const deliveries = state.deliveries.filter(item => matches(item.title, item.content, item.route_name, item.channel_name, item.last_error))
  const filter = (key, placeholder) => `<input class="filter-input delivery-filter" data-filter="${key}" value="${escapeHtml(state.deliveryFilters[key])}" placeholder="${placeholder}">`
  const toolbar = `<div class="toolbar"><select id="delivery-status" class="filter-select"><option value="">全部状态</option>${['sent', 'failed', 'retry', 'pending', 'processing'].map(status => `<option value="${status}" ${state.deliveryStatus === status ? 'selected' : ''}>${statusText(status)}</option>`).join('')}</select>${filter('route_id', '路由 ID')}${filter('channel_name', '渠道名称')}${filter('error', '失败原因')}<input type="date" class="filter-input delivery-filter" data-filter="date_from" value="${state.deliveryFilters.date_from}"><input type="date" class="filter-input delivery-filter" data-filter="date_to" value="${state.deliveryFilters.date_to}"><span class="tag">共 ${deliveries.length} 条</span></div>`
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
  return `<div class="settings-grid"><section class="panel"><header class="panel-header"><div><h2>站点设置</h2><p>管理后台的基础信息</p></div><button class="button secondary small" data-action="edit-settings">${icon('edit')}编辑</button></header><div class="panel-body settings-list"><div class="info-row"><span>应用名称</span><strong>${escapeHtml(app.app_name || 'Notify')}</strong></div><div class="info-row"><span>站点地址</span><strong>${escapeHtml(app.site_url || location.origin)}</strong></div><div class="info-row"><span>记录保留</span><strong>${escapeHtml(app.record_retention_days || 90)} 天</strong></div><div class="info-row"><span>GitHub Token</span><code class="code">${escapeHtml(app.github_token || '未配置')}</code></div></div></section><section class="panel"><header class="panel-header"><div><h2>管理员安全</h2><p>修改管理后台登录密码</p></div><button class="button secondary small" data-action="change-password">${icon('settings')}修改密码</button></header><div class="panel-body settings-list"><div class="info-row"><span>当前账户</span><strong>${escapeHtml(state.session?.username || 'admin')}</strong></div><div class="info-row"><span>密码状态</span><span class="status-badge ${state.status.password_change_required ? 'pending' : 'active'}">${state.status.password_change_required ? '需要修改' : '已设置'}</span></div><p class="form-note">密码会保存到数据目录，修改后立即生效，并使其他登录会话失效。</p></div></section><section class="panel"><header class="panel-header"><div><h2>运行信息</h2><p>当前实例状态</p></div><span class="status-badge active">正常</span></header><div class="panel-body settings-list"><div class="info-row"><span>系统版本</span><code class="code">v${escapeHtml(state.status.version)}</code></div><div class="info-row"><span>通知渠道</span><strong>${state.status.channels}</strong></div><div class="info-row"><span>通知通道</span><strong>${state.status.routes}</strong></div><div class="info-row"><span>插件任务</span><span class="status-badge ${state.status.plugin_tasks ? 'active' : 'inactive'}">${state.status.plugin_tasks ? '运行中' : '已暂停'}</span></div><div class="info-row"><span>API 文档</span><a class="code" href="/docs" target="_blank" rel="noopener">/docs</a></div></div></section></div>`
}

function emptyState(iconName, title, description) {
  return `<div class="empty-state">${icon(iconName)}<div><h3>${escapeHtml(title)}</h3><p>${escapeHtml(description)}</p></div></div>`
}

function formField(name, label, type = 'text', value = '', placeholder = '', hint = '', options = []) {
  const safeValue = value ?? ''
  const note = hint
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
    const inputType = type === 'password' ? 'text' : type
    control = `<input name="${escapeHtml(name)}" type="${escapeHtml(inputType)}" value="${escapeHtml(safeValue)}" placeholder="${escapeHtml(placeholder)}" autocomplete="off">`
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
  if (state.pluginLogTimer) {
    clearInterval(state.pluginLogTimer)
    state.pluginLogTimer = null
  }
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
  const selectedType = original.type || DEFAULT_TEMPLATE_TYPE
  const knownType = selectedType === DEFAULT_TEMPLATE_TYPE || state.eventTypes.some(item => item.value === selectedType)
  const typeOptions = templateEventOptions(selectedType)
  const embyBaseVariables = ['notification_title', 'content', 'event_code', 'event_label', 'event', 'username', 'user', 'user_data', 'item', 'item_data', 'item_type', 'session', 'session_data', 'server', 'server_data', 'payload', 'server_name', 'server_id', 'server_version', 'server_info', 'server_url', 'date', 'date_text', 'remote_ip', 'location', 'address_info', 'client', 'client_version', 'device', 'device_name', 'device_info', 'device_play_info', 'item_url', 'image_url', 'emby_url', 'created_at']
  const embyItemVariables = ['item_type_name', 'item_name', 'title', 'year', 'year_label', 'premiere_date', 'premiere_text', 'score_origin', 'official_rating', 'score_text', 'genres', 'genres_text', 'people', 'people_text', 'overview', 'overview_text', 'container', 'size', 'media_info', 'film_info', 'album_info']
  const embyPlaybackVariables = ['playback', 'playback_data', 'play_state', 'play_method', 'volume', 'position_seconds', 'runtime_seconds', 'position', 'runtime', 'progress_bar', 'progress_text', 'video_stream_title', 'transcoding_info', 'bitrate', 'current_cpu']
  const embyVariables = [...embyBaseVariables, ...embyItemVariables]
  const variableGroups = {
    'Emby.PlaybackStart': [...embyVariables, ...embyPlaybackVariables],
    'Emby.PlaybackPause': [...embyVariables, ...embyPlaybackVariables],
    'Emby.PlaybackUnpause': [...embyVariables, ...embyPlaybackVariables],
    'Emby.PlaybackEnd': [...embyVariables, ...embyPlaybackVariables],
    'Emby.LibraryNewMovie': [...embyVariables, 'episode_count'],
    'Emby.LibraryNewSeries': [...embyVariables, 'episode_count'],
    'Emby.LibraryNewAudio': [...embyVariables],
    'Emby.LibraryDeleted': [...embyVariables, 'item_path', 'path_text'],
    'Emby.UserAuthenticated': [...embyBaseVariables],
    'Emby.UserAuthenticationFailed': [...embyBaseVariables],
    'Emby.PluginInstalled': [...embyBaseVariables, 'plugin_name', 'plugin_version', 'plugin_info', 'plugin_version_text'],
    'Emby.PluginUninstalled': [...embyBaseVariables, 'plugin_name', 'plugin_version', 'plugin_info', 'plugin_version_text'],
    'Emby.IntroskipUpdate': [...embyVariables],
    'Emby.ItemMarkedPlayed': [...embyVariables, 'is_favorite'],
    'Emby.ItemMarkedUnplayed': [...embyVariables, 'is_favorite'],
    'Emby.ItemRated': [...embyVariables, 'is_favorite'],
    'Emby.SystemStartup': [...embyBaseVariables],
    'Emby.SystemUpdateAvailable': [...embyBaseVariables, 'new_version', 'current_version_text', 'new_version_text'],
  }
  const examples = { notification_title: '用户开始播放：示例电影', content: '媒体库：电影 · 设备：手机', event_code: 'playback.start', event_label: '开始播放', event: '开始播放', username: '用户', user: '用户', title: '示例电影', item_name: '示例电影', item_type_name: '电影', item_type: 'Movie', year: '2025', year_label: '(2025)', genres: '剧情、科幻', genres_text: '剧情·科幻', overview: '这是一段示例简介。', server_name: '家庭影院', server_version: '4.8.0', device: '手机客户端', device_name: '手机客户端', client: 'Emby', size: '2 GB', container: 'H264', bitrate: '8', progress_text: '进度：50%', position: '00:30:00', runtime: '01:00:00', play_method: '直接播放', media_info: '媒体：H264', machine_name: 'PVE节点', task_type: '备份', task_status: '成功', datastore_name: 'local', total_time: '3秒', total_size: '1 GB', job_id: 'daily', removed_garbage: '200 MB', update_title: 'Watchtower 更新', update_content: '发现 1 个镜像更新', updated_image_count: '1', updated_image_list: 'example/app:latest' }
  const variablesForType = type => {
    if (variableGroups[type]) return variableGroups[type]
    if (String(type).startsWith('PVE.')) return ['machine_name', 'task_type', 'task_status', 'datastore_name', 'total_time', 'total_size', 'job_id', 'details', 'index_file_count', 'removed_garbage', 'original_data_usage', 'on_disk_usage', 'deduplication_factor']
    if (String(type).startsWith('Watchtower.')) return ['update_title', 'update_content', 'server_name', 'updated_image_count', 'updated_image_list']
    return ['notification_title', 'content', 'event_code', 'event_label', 'event', 'payload']
  }
  openModal({
    eyebrow: template ? '编辑通知模板' : '新增通知模板', title: template ? original.name : '创建通知模板', wide: true,
    body: `<div class="dialog-grid"><div><div class="field-row">${formField('name', '模板名称', 'text', original.name, '例如：短信通知')}<label class="field"><span>事件类型</span><select name="type_choice">${typeOptions}<option value="__custom__" ${knownType ? '' : 'selected'}>自定义事件类型</option></select><input name="type_custom" type="text" value="${escapeHtml(knownType ? '' : original.type)}" placeholder="例如：MyService.Alert" autocomplete="off" ${knownType ? 'hidden' : ''}><small>内置事件按模块分组显示；也可以选择“自定义事件类型”手动输入。</small></label></div>${formField('description', '模板说明', 'text', original.description || '', '说明这个模板的使用场景')}${formField('title', '通知标题', 'textarea', original.title || '')}${formField('content', '通知内容', 'textarea', original.content || '')}<p class="form-note">保持现有 Jinja 模板变量不变，例如 <code>{{ device_name }}</code>。变量由实际推送来源填充。</p></div><aside class="preview-pane"><p class="eyebrow">News 实时预览</p><div class="news-preview"><div class="news-image">${icon('bell')}</div><div class="news-copy"><h3 id="preview-title">${escapeHtml(original.title || '通知标题')}</h3><p id="preview-content">${escapeHtml(original.content || '通知内容')}</p></div></div><p class="preview-note">这是企业微信 News 卡片的内容结构预览；图片和链接来自通道或推送请求。</p></aside></div>`,
    onSubmit: async form => {
      const data = new FormData(form)
      const name = String(data.get('name') || '').trim()
      const typeChoice = String(data.get('type_choice') || '')
      const type = typeChoice === '__custom__' ? String(data.get('type_custom') || '').trim() : typeChoice
      if (!name) throw new Error('请输入模板名称')
      if (!type) throw new Error('请选择已注册事件类型，或选择自定义后输入类型')
      if (state.templates.some(item => item.name === name && item.name !== template?.name)) throw new Error('模板名称已存在')
      const next = { ...original, name, type, description: String(data.get('description') || '').trim(), title: String(data.get('title') || ''), content: String(data.get('content') || '') }
      const templates = [...state.templates]
      const index = templates.findIndex(item => item.name === template?.name)
      if (index >= 0) templates[index] = next
      else templates.push(next)
      const routes = (state.config.routes || []).map(route => template && template.name !== name ? { ...route, bind_template: (route.bind_template || []).map(item => item === template.name ? name : item) } : route)
      if (template && template.name !== name) await api('/api/admin/config', { method: 'PUT', body: JSON.stringify({ ...state.config, routes }) })
      await saveTemplates(templates, template ? '模板已更新' : '模板已创建')
    },
  })
  const typeChoice = $('#modal-body select[name="type_choice"]')
  const customType = $('#modal-body input[name="type_custom"]')
  const variableHost = Object.assign(document.createElement('div'), { className: 'template-variable-host' })
  $('#modal-body .field-row').after(variableHost)
  let activeEditor = $('#modal-body textarea[name="content"]')
  let activeSelection = { start: activeEditor.selectionStart || 0, end: activeEditor.selectionEnd || 0 }
  const refreshVariableHelper = type => {
    const variableNames = variablesForType(type)
    variableHost.innerHTML = `<div class="variable-helper"><div class="helper-heading"><strong>可用变量</strong><small>点击插入到当前编辑框 · ${escapeHtml(type || '自定义事件')}</small></div><div class="variable-list">${variableNames.map(name => `<button type="button" class="variable-chip" data-variable="${escapeHtml(name)}">{{ ${escapeHtml(name)} }}</button>`).join('')}</div></div>`
    variableHost.querySelectorAll('[data-variable]').forEach(button => button.addEventListener('click', () => {
      const field = activeEditor || $('#modal-body textarea[name="content"]')
      const value = `{{ ${button.dataset.variable} }}`
      const start = activeEditor === field ? activeSelection.start : field.value.length
      const end = activeEditor === field ? activeSelection.end : start
      field.value = field.value.slice(0, start) + value + field.value.slice(end)
      field.focus(); field.selectionStart = field.selectionEnd = start + value.length
      activeSelection = { start: start + value.length, end: start + value.length }
      field.dispatchEvent(new Event('input'))
    }))
  }
  const trackEditor = event => {
    activeEditor = event.currentTarget
    activeSelection = { start: activeEditor.selectionStart || 0, end: activeEditor.selectionEnd || 0 }
  }
  $('#modal-body').querySelectorAll('textarea[name="title"], textarea[name="content"]').forEach(field => {
    field.addEventListener('focus', trackEditor)
    field.addEventListener('select', trackEditor)
    field.addEventListener('click', trackEditor)
    field.addEventListener('input', trackEditor)
    field.addEventListener('keyup', trackEditor)
  })
  refreshVariableHelper(typeChoice.value === '__custom__' ? customType.value : typeChoice.value)
  typeChoice.addEventListener('change', () => {
    const custom = typeChoice.value === '__custom__'
    customType.hidden = !custom
    if (!custom && typeChoice.value) customType.value = typeChoice.value
    refreshVariableHelper(custom ? customType.value : typeChoice.value)
  })
  customType.addEventListener('input', () => refreshVariableHelper(customType.value))
  const renderExample = value => String(value || '').replace(/{{\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*}}/g, (_, name) => examples[name] ?? `{{ ${name} }}`).replace(/{%[^%]*%}/g, '')
  const updatePreview = () => {
    $('#preview-title').textContent = renderExample($('#modal-body [name="title"]').value) || '通知标题'
    $('#preview-content').textContent = renderExample($('#modal-body [name="content"]').value) || '通知内容'
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
  return formField(`plugin_${name}`, field.label || name, type, Array.isArray(value) ? value.join(',') : value ?? field.defaultValue ?? '', '', field.helpText || '')
}

function pluginHelp(plugin) {
  const fields = plugin.helpTextField || []
  if (!fields.length) return ''
  const siteUrl = String(state.config?.app?.site_url || location.origin).replace(/\/+$/, '')
  return `<div class="form-section">${fields.map(field => {
    const value = String(field.value || '').replaceAll('{site_url}', siteUrl)
    if (field.fieldType === 'title') return `<h3 class="form-section-title">${escapeHtml(value)}</h3>`
    if (field.fieldType === 'code') return `<div class="form-note"><strong>企业微信回调 URL</strong><code class="code" style="display:block;margin-top:8px;overflow-wrap:anywhere">${escapeHtml(value)}</code></div>`
    return `<p class="form-note">${escapeHtml(value)}</p>`
  }).join('')}</div>`
}

function pluginDocs(plugin) {
  const docs = plugin.documentation && typeof plugin.documentation === 'object' ? plugin.documentation : {}
  const sections = []
  if (typeof plugin.documentation === 'string' && plugin.documentation.trim()) sections.push(`<div class="form-note">${escapeHtml(plugin.documentation)}</div>`)
  if (docs.summary) sections.push(`<div class="form-note">${escapeHtml(docs.summary)}</div>`)
  const listSection = (title, values) => {
    if (!Array.isArray(values) || !values.length) return
    sections.push(`<div class="form-section"><h3 class="form-section-title">${escapeHtml(title)}</h3><ol class="plugin-doc-list">${values.map(value => `<li>${escapeHtml(value)}</li>`).join('')}</ol></div>`)
  }
  listSection('配置步骤', docs.setup)
  listSection('使用方式', docs.usage)
  if (Array.isArray(docs.callbacks) && docs.callbacks.length) sections.push(`<div class="form-section"><h3 class="form-section-title">回调地址</h3>${docs.callbacks.map(item => `<div class="form-note"><strong>${escapeHtml(item.name || '回调地址')}</strong>${item.method ? `<span class="tag purple" style="margin-left:8px">${escapeHtml(item.method)}</span>` : ''}<code class="code plugin-doc-code">${escapeHtml(String(item.url || '').replaceAll('{site_url}', String(state.config?.app?.site_url || location.origin).replace(/\/+$/, '')))}</code></div>`).join('')}</div>`)
  if (Array.isArray(docs.examples) && docs.examples.length) sections.push(`<div class="form-section"><h3 class="form-section-title">示例</h3>${docs.examples.map(item => `<div class="form-note"><strong>${escapeHtml(item.title || '示例')}</strong><code class="code plugin-doc-code">${escapeHtml(item.code || '')}</code></div>`).join('')}</div>`)
  listSection('注意事项', docs.notes)
  if (!sections.length) return pluginHelp(plugin) || '<p class="form-note">这个插件暂时没有补充使用说明。</p>'
  return sections.join('')
}

function openPluginDocs(plugin) {
  openModal({ eyebrow: '插件说明', title: plugin.name || plugin.id, body: pluginDocs(plugin), wide: true, noSubmit: true })
}

async function openPluginLogs(plugin) {
  if (state.pluginLogTimer) clearInterval(state.pluginLogTimer)
  const render = logs => {
    const status = plugin.running ? '<span class="status-badge active">运行中</span>' : '<span class="status-badge failed">已停止</span>'
    const body = logs.length ? `<div class="plugin-log-meta"><span>${status}</span><span class="form-note">最近 ${logs.length} 条</span></div><div class="log-view">${logs.slice().reverse().map(item => `<div class="log-line"><span class="log-time">${escapeHtml(item.time)}</span><span class="log-level ${escapeHtml(item.level)}">${escapeHtml(item.level)}</span><span class="log-name">${escapeHtml(item.logger)}</span><span>${escapeHtml(item.message)}</span></div>`).join('')}</div>` : `<div class="plugin-log-meta"><span>${status}</span></div><p class="form-note">暂无插件日志。Worker 启动、任务执行和异常会显示在这里。</p>`
    $('#modal-body').innerHTML = body
  }
  openModal({ eyebrow: '插件日志', title: plugin.name || plugin.id, body: '<p class="form-note">正在加载日志…</p>', wide: true, noSubmit: true })
  const refresh = async () => {
    try { render(await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/logs?limit=300`)) } catch (error) { render([{ time: '', level: 'ERROR', logger: 'notify', message: error.message }]) }
  }
  await refresh()
  state.pluginLogTimer = setInterval(refresh, 4000)
}

async function openPluginTest(plugin) {
  const routes = state.config.routes || []
  const routeOptions = routes.map(item => [item.route_id, item.route_name || item.route_id])
  let config = {}
  try { config = await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/config`) || {} } catch { /* route can still be selected manually */ }
  const selected = config.route_id || config.notify_route || config.notify_route_id || (routes.length === 1 ? routes[0].route_id : '')
  openModal({
    eyebrow: '插件通知测试', title: `测试 · ${plugin.name || plugin.id}`,
    body: `${formField('route_id', '通知通道', 'select', selected, '', '模拟插件事件并通过真实通知通道发送。', routeOptions)}${formField('title', '通知标题', 'text', `[测试] ${plugin.name || plugin.id}`)}${formField('content', '通知内容', 'textarea', '这是一条来自插件的测试通知，用于验证插件配置的通知通道。')}`,
    submitText: '发送测试通知',
    onSubmit: async form => {
      const data = new FormData(form)
      const routeId = String(data.get('route_id') || '').trim()
      if (!routeId) throw new Error('请选择通知通道')
      const result = await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/test`, { method: 'POST', body: JSON.stringify({ route_id: routeId, title: data.get('title'), content: data.get('content') }) })
      closeModal()
      toast('测试通知已加入队列', `通道：${result.route_id}`)
      setTimeout(async () => { await loadCore(); if (currentPage() === 'deliveries') renderCurrent() }, 800)
    },
  })
}

function openPluginSources() {
  const sources = (state.config.app?.plugin_sources || []).join('\n')
  openModal({
    eyebrow: '插件商店', title: '管理插件源', wide: true,
    body: `${formField('sources', '插件源地址', 'textarea', sources, 'https://raw.githubusercontent.com/example/plugins/main/plugin-store.json', '每行一个公开 HTTPS JSON 索引地址，最多 10 个。安装第三方插件等同于允许其代码在容器内运行。')}`,
    onSubmit: async form => {
      const values = String(new FormData(form).get('sources') || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean)
      await api('/api/admin/plugin-store/sources', { method: 'PUT', body: JSON.stringify({ sources: values }) })
      closeModal()
      await loadCore()
      state.pluginStore = await api('/api/admin/plugin-store')
      renderCurrent()
      toast('插件源已保存')
    },
  })
}

async function openPluginForm(plugin) {
  const config = await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/config`)
  const fields = plugin.configField || []
  const body = `${fields.length ? fields.map(field => pluginField(field, config[field.fieldName])).join('') : '<p class="form-note">这个插件没有通用配置项，请使用插件自己的页面完成操作。</p>'}`
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
        next[name] = value
      }
      await api(`/api/admin/plugins/${encodeURIComponent(plugin.id)}/config`, { method: 'PUT', body: JSON.stringify(next) })
      toast('插件配置已保存', '重启服务后加载新的插件设置')
      closeModal()
    } : null,
  })
}

function passwordField(name, label, autocomplete) {
  return `<label class="field"><span>${escapeHtml(label)}</span><input name="${escapeHtml(name)}" type="password" autocomplete="${escapeHtml(autocomplete)}" required></label>`
}

function openPasswordForm(firstLogin = false) {
  openModal({
    eyebrow: '管理员安全',
    title: firstLogin ? '请先修改默认密码' : '修改管理员密码',
    submitText: '更新密码',
    body: `${firstLogin ? '<div class="form-note">当前使用的是默认密码。为保护你的通知配置，请先设置一个新的管理员密码。</div>' : ''}${passwordField('current_password', '当前密码', 'current-password')}${passwordField('new_password', '新密码', 'new-password')}${passwordField('confirm_password', '确认新密码', 'new-password')}<p class="form-note">新密码至少需要 8 个字符。更新后当前及其他登录会话都会失效。</p>`,
    onSubmit: async form => {
      const data = new FormData(form)
      const currentPassword = String(data.get('current_password') || '')
      const newPassword = String(data.get('new_password') || '')
      const confirmPassword = String(data.get('confirm_password') || '')
      if (!currentPassword || !newPassword || !confirmPassword) throw new Error('请完整填写密码')
      if (newPassword !== confirmPassword) throw new Error('两次输入的新密码不一致')
      await api('/api/admin/password', { method: 'POST', body: JSON.stringify({ current_password: currentPassword, new_password: newPassword, confirm_password: confirmPassword }) })
      closeModal()
      await api('/api/admin/logout', { method: 'POST' })
      $('#login-error').textContent = '密码已更新，请使用新密码登录'
      showLogin()
    },
  })
}

function openSettingsForm() {
  const app = state.config.app || {}
  openModal({
    eyebrow: '系统管理', title: '编辑站点设置',
    body: `${formField('app_name', '应用名称', 'text', app.app_name || 'Notify')}${formField('site_url', '站点公网地址', 'url', app.site_url || '', 'https://notify.example.com', '用于生成对外接口地址')}${formField('record_retention_days', '记录保留天数', 'number', app.record_retention_days || 90)}${formField('github_token', 'GitHub Token', 'password', app.github_token || '', '', '以明文保存和显示')}`,
    onSubmit: async form => {
      const data = new FormData(form)
      const githubToken = String(data.get('github_token') || '').trim()
      const nextApp = {
        ...app,
        app_name: String(data.get('app_name') || '').trim() || 'Notify',
        site_url: String(data.get('site_url') || '').trim(),
        record_retention_days: Math.max(1, Number(data.get('record_retention_days') || 90)),
        github_token: githubToken,
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
      const result = await api(`/api/admin/channels/${encodeURIComponent(channel.name)}/test`, { method: 'POST', body: JSON.stringify({ title: data.get('title'), content: data.get('content'), push_img_url: data.get('push_img_url') || null, push_link_url: data.get('push_link_url') || null, probe: true }) })
      toast(`连接成功 · ${result.elapsed_ms} ms`)
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

function delay(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds))
}

async function finishPluginChange(message, result = {}) {
  if (result.hot_applied && !result.restart_required) {
    await loadCore()
    renderCurrent()
    return toast(message, '新版插件已热应用，Notify Router 无需重启')
  }
  if (!state.status.admin_restart) {
    state.pluginStore = await api('/api/admin/plugin-store')
    renderCurrent()
    return toast(message, '请重启 Notify Router 容器使变更生效')
  }
  toast(message, 'Notify Router 正在重启，页面会自动恢复')
  await api('/api/admin/restart', { method: 'POST' })
  await delay(1500)
  let sawOffline = false
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch('/healthz', { cache: 'no-store' })
      if (response.ok && (sawOffline || attempt >= 2)) return location.reload()
    } catch {
      sawOffline = true
    }
    await delay(1000)
  }
  location.reload()
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
  if (action === 'toggle-palette') return togglePaletteMenu(target)
  if (action === 'restart-service') return confirmModal('重启 Notify Router', '确定要重启服务吗？当前通知会在服务恢复后继续处理。', async () => {
    await api('/api/admin/restart', { method: 'POST' })
    toast('服务正在重启', '页面将在服务恢复后自动刷新')
    await delay(1200)
    for (let attempt = 0; attempt < 30; attempt += 1) {
      try { if ((await fetch('/healthz', { cache: 'no-store' })).ok) return location.reload() } catch {}
      await delay(1000)
    }
    location.reload()
  })
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
    const base = (state.config.app?.site_url || location.origin).replace(/\/$/, '')
    const endpoint = `${base}/api/service/notify/${encodeURIComponent(route.route_id)}/{title}/{content}`
    return confirmModal('删除通知通道', `确定删除“${route.route_name}”吗？现有调用地址将立即失效。\n\n调用地址：${endpoint}`, async () => saveConfig({ ...state.config, routes: state.config.routes.filter(item => item.route_id !== route.route_id) }, '通道已删除'), true)
  }
  if (action === 'copy-route') {
    const base = (state.config.app?.site_url || location.origin).replace(/\/$/, '')
    await copyText(`${base}/api/service/notify?route_id=${encodeURIComponent(target.dataset.id)}&title={title}&content={content}`)
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
  if (action === 'manage-plugin-sources') return openPluginSources()
  if (action === 'install-plugin' || action === 'update-plugin') {
    const verb = action === 'update-plugin' ? '更新' : '安装'
    return confirmModal(`${verb}插件`, `确定${verb}“${target.dataset.id}”吗？系统会只热切换这个插件，失败时自动回滚。`, async () => {
      const result = await api('/api/admin/plugin-store/install', { method: 'POST', body: JSON.stringify({ source_url: target.dataset.source, plugin_id: target.dataset.id }) })
      closeModal()
      await finishPluginChange(`插件已${verb}`, result)
    })
  }
  if (action === 'uninstall-plugin') {
    return confirmModal('卸载插件', `确定卸载“${target.dataset.id}”吗？只会停止这个插件，代码移入备份目录，配置和历史数据不会删除。`, async () => {
      const result = await api(`/api/admin/plugin-store/plugins/${encodeURIComponent(target.dataset.id)}`, { method: 'DELETE' })
      closeModal()
      await finishPluginChange('插件已卸载', result)
    }, true)
  }
  if (action === 'edit-plugin') return openPluginForm(state.plugins.find(item => item.id === target.dataset.id))
  if (action === 'plugin-docs') return openPluginDocs(state.plugins.find(item => item.id === target.dataset.id))
  if (action === 'plugin-logs') return openPluginLogs(state.plugins.find(item => item.id === target.dataset.id))
  if (action === 'test-plugin') return openPluginTest(state.plugins.find(item => item.id === target.dataset.id))
  if (action === 'open-plugin') return window.open(`/api/plugins/${encodeURIComponent(target.dataset.id)}/frontend/`, '_blank', 'noopener')
  if (action === 'change-password') return openPasswordForm()
  if (action === 'retry-delivery') {
    await api(`/api/admin/deliveries/${target.dataset.id}/retry`, { method: 'POST' })
    toast('已重新加入发送队列')
    return renderPage()
  }
  if (action === 'delivery-detail') return openDeliveryDetail(state.deliveries.find(item => String(item.id) === String(target.dataset.id)))
  if (action === 'edit-settings') return openSettingsForm()
  if (action === 'export-config') { const data = await api('/api/admin/export'); const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'notify-router-config.json'; link.click(); URL.revokeObjectURL(link.href); return toast('配置已导出') }
  if (action === 'import-config') { const input = Object.assign(document.createElement('input'), { type: 'file', accept: '.json,application/json' }); input.onchange = async () => { try { const data = JSON.parse(await input.files[0].text()); await api('/api/admin/import', { method: 'PUT', body: JSON.stringify(data) }); toast('配置已导入，请刷新页面') } catch (error) { toast('配置导入失败', error.message, 'error') } }; input.click(); return }
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
  const palette = event.target.closest('[data-palette]')
  if (palette) {
    setPalette(Number(palette.dataset.palette))
    $('#palette-menu')?.remove()
    return
  }
  const target = event.target.closest('[data-action]')
  if (!target) {
    if (!event.target.closest('#palette-menu')) $('#palette-menu')?.remove()
    return
  }
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
  if (event.target.matches('.delivery-filter')) { state.deliveryFilters[event.target.dataset.filter] = event.target.value; renderPage().catch(reason => toast('加载失败', reason.message, 'error')) }
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
  setPalette(Number(localStorage.getItem('notify-palette') || 7))
  try {
    const session = await api('/api/admin/session')
    if (session.authenticated) await showApp(session)
    else showLogin()
  } catch {
    showLogin()
  }
}

boot()
