/* ============================================
   MLBot SPA — Client
   ============================================ */

const API = '';

// --- XSS Protection ---
function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// --- State ---
let currentView = 'dashboard';
let products = [];
let batches = [];
let currentUser = null;

// --- Auth ---
function getToken() { return localStorage.getItem('mlbot_token'); }
function setToken(token) { localStorage.setItem('mlbot_token', token); }
function clearToken() { localStorage.removeItem('mlbot_token'); currentUser = null; }

function authHeaders() {
  const token = getToken();
  return token ? { 'Authorization': `Bearer ${token}` } : {};
}

// --- API helpers ---
async function api(path, opts = {}) {
  const headers = { 'Accept': 'application/json', ...authHeaders(), ...(opts.headers || {}) };
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith('/auth/')) {
      clearToken();
      renderAuth();
      throw new Error('Sessão expirada');
    }
    const msg = data?.detail || `Erro ${res.status}`;
    throw new Error(msg);
  }
  return data;
}

async function apiPost(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

async function apiPatch(path, body) {
  return api(path, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// --- Toast ---
function toast(message, type = 'info') {
  const container = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// --- Status helpers ---
function statusBadge(status) {
  const map = {
    imported: ['Importado', 'neutral'],
    normalized: ['Normalizado', 'info'],
    enriching: ['Enriquecendo', 'info'],
    enriched: ['Enriquecido', 'info'],
    awaiting_review: ['Aguardando Revisão', 'warning'],
    awaiting_photos: ['Aguardando Fotos', 'warning'],
    photos_received: ['Fotos Recebidas', 'info'],
    processing_images: ['Processando', 'info'],
    processed: ['Processado', 'info'],
    validating: ['Validando', 'info'],
    validation_error: ['Erro Validação', 'error'],
    ready_to_publish: ['Pronto p/ Publicar', 'accent'],
    publishing: ['Publicando', 'info'],
    published: ['Publicado', 'success'],
    publish_error: ['Erro Publicação', 'error'],
    draft: ['Rascunho', 'neutral'],
    valid: ['Validado', 'success'],
  };
  const [label, variant] = map[status] || [status, 'neutral'];
  return `<span class="badge badge-${variant}">${label}</span>`;
}

// --- Sidebar (mobile) ---
function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  const isOpen = sidebar.classList.contains('open');
  if (isOpen) {
    closeSidebar();
  } else {
    sidebar.classList.add('open');
    overlay.classList.add('active');
    requestAnimationFrame(() => overlay.classList.add('visible'));
  }
}

function closeSidebar() {
  const sidebar = document.getElementById('sidebar');
  const overlay = document.getElementById('sidebar-overlay');
  sidebar.classList.remove('open');
  overlay.classList.remove('visible');
  setTimeout(() => overlay.classList.remove('active'), 250);
}

// --- Navigation ---
function navigate(view, data) {
  currentView = view;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === view);
  });
  closeSidebar();
  renderView(view, data);
}

// --- Render Router ---
function renderView(view, data) {
  const main = document.getElementById('main-content');
  switch (view) {
    case 'dashboard': renderDashboard(main); break;
    case 'import': renderImport(main); break;
    case 'products': renderProducts(main); break;
    case 'product-detail': navigate('products'); break;
    case 'kb': renderKnowledgeBase(main); break;
    case 'auth': renderAuth(main); break;
    default: main.innerHTML = '<div class="empty-state"><h3>Página não encontrada</h3></div>';
  }
}

// --- Dashboard ---
async function renderDashboard(el) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    const [prods, batchList, authStatus, kbStats] = await Promise.all([
      api('/products'),
      api('/batches'),
      api('/auth/ml/status'),
      api('/kb/stats'),
    ]);
    products = prods;
    batches = batchList;

    const total = products.length;
    const enriched = products.filter(p => p.part_name && p.brand && p.category).length;
    const pending = total - enriched;

    el.innerHTML = `
      <div class="view">
        <div class="page-header">
          <div>
            <h1>Dashboard</h1>
            <p>Visão geral do pipeline de produtos</p>
          </div>
          <div class="flex gap-3">
            <button class="btn btn-secondary" onclick="navigate('import')">Importar OEMs</button>
            <button class="btn btn-primary" onclick="navigate('products')">Ver Produtos</button>
          </div>
        </div>

        <div class="stats-grid section">
          <div class="stat-card">
            <div class="stat-value">${total}</div>
            <div class="stat-label">Produtos Total</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${batches.length}</div>
            <div class="stat-label">Lotes Importados</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${enriched}</div>
            <div class="stat-label">Enriquecidos</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${pending}</div>
            <div class="stat-label">Pendentes</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${kbStats.total_entries}</div>
            <div class="stat-label">OEMs na KB (${kbStats.coverage_pct}% cobertura)</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">
              <span class="status-dot ${authStatus.authenticated ? 'connected' : 'disconnected'}" style="display:inline-block;vertical-align:middle;margin-right:8px"></span>
              ${authStatus.authenticated ? 'Conectado' : 'Desconectado'}
            </div>
            <div class="stat-label">Mercado Livre</div>
          </div>
        </div>

        ${batches.length > 0 ? `
        <div class="section">
          <h2 class="section-header">Últimos Lotes</h2>
          <div class="table-wrap">
            <table>
              <thead><tr>
                <th>ID</th><th>Arquivo</th><th>Itens</th><th>Válidos</th><th>Data</th>
              </tr></thead>
              <tbody>
                ${batches.slice(0, 5).map(b => `
                  <tr onclick="loadBatchItems(${b.id})">
                    <td class="mono">#${b.id}</td>
                    <td>${escapeHtml(b.filename)}</td>
                    <td>${b.total_items}</td>
                    <td>${b.total_valid}</td>
                    <td>${new Date(b.created_at).toLocaleDateString('pt-BR')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>` : `
        <div class="empty-state">
          <h3>Nenhum lote importado ainda</h3>
          <p>Importe seu primeiro arquivo de OEMs para começar</p>
          <button class="btn btn-primary mt-4" onclick="navigate('import')">Importar OEMs</button>
        </div>`}
      </div>
    `;
  } catch (err) {
    el.innerHTML = `<div class="empty-state"><h3>Erro ao carregar</h3><p>${escapeHtml(err.message)}</p></div>`;
  }
}

// --- Import ---
function renderImport(el) {
  el.innerHTML = `
    <div class="view">
      <div class="page-header">
        <div>
          <h1>Importar OEMs</h1>
          <p>Faça upload de um arquivo .txt com códigos OEM (um por linha)</p>
        </div>
      </div>

      <div class="card" style="max-width: 560px;">
        <div class="upload-zone" id="upload-zone" onclick="document.getElementById('file-input').click()">
          <div class="upload-icon">&#8593;</div>
          <p><strong>Clique para selecionar</strong> ou arraste o arquivo aqui</p>
          <p style="font-size:11px;margin-top:4px">Formato: .txt — UTF-8</p>
        </div>
        <input type="file" id="file-input" accept=".txt" style="display:none" onchange="handleFileUpload(this)">
        <div id="upload-result" class="mt-4"></div>
      </div>
    </div>
  `;

  const zone = document.getElementById('upload-zone');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files[0]) {
      document.getElementById('file-input').files = e.dataTransfer.files;
      handleFileUpload(document.getElementById('file-input'));
    }
  });
}

async function handleFileUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const result = document.getElementById('upload-result');
  result.innerHTML = '<div class="flex items-center gap-2"><div class="spinner"></div> Importando...</div>';

  try {
    const form = new FormData();
    form.append('file', file);
    const data = await api('/batches/import', { method: 'POST', body: form, headers: {} });
    result.innerHTML = `
      <div class="card" style="background:var(--success-subtle);border-color:var(--success)">
        <strong>${data.total_items} OEMs importados</strong> do arquivo ${escapeHtml(data.filename)}<br>
        <span style="color:var(--text-secondary)">${data.total_valid} válidos · ${data.total_invalid} inválidos</span>
        <div class="mt-4">
          <button class="btn btn-primary btn-sm" onclick="navigate('products')">Ver Produtos</button>
        </div>
      </div>
    `;
    toast(`${data.total_items} OEMs importados com sucesso`, 'success');
  } catch (err) {
    result.innerHTML = `<div class="card" style="border-color:var(--error);color:var(--error)">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
  }
}

// --- Pipeline Steps Definition ---
const PIPELINE_STEPS = [
  { id: 0, label: 'Enriquecer IA', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M18 18l.5 1.5L20 20l-1.5.5L18 22l-.5-1.5L16 20l1.5-.5z"/></svg>' },
  { id: 1, label: 'Preço', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>' },
  { id: 2, label: 'Upload', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>' },
  { id: 3, label: 'Fundo', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 4V2"/><path d="M15 16v-2"/><path d="M8 9h2"/><path d="M20 9h2"/><path d="M17.8 11.8L19 13"/><path d="M15 9h0"/><path d="M17.8 6.2L19 5"/><path d="M3 21l9-9"/><path d="M12.2 6.2L11 5"/></svg>' },
  { id: 4, label: 'Anúncio', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>' },
  { id: 5, label: 'Validar', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>' },
  { id: 6, label: 'Publicar ML', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>' },
];

function statusToProgress(product) {
  const s = product.status || '';

  // Statuses terminais / avançados
  if (s === 'published') return 7;
  if (s === 'publishing' || s === 'ready_to_publish' || s === 'publish_error') return 6;
  if (s === 'validating' || s === 'validation_error') return 5;
  if (s === 'processed') {
    // processed but might already have listing generated
    return product.has_listing ? 5 : 4;
  }
  if (s === 'processing_images') return 3;
  if (s === 'photos_received') return 3;
  if (s === 'awaiting_photos') return 2;
  if (s === 'enriched' || s === 'awaiting_review') {
    return product.has_pricing ? 2 : 1;
  }
  if (s === 'enriching' || s === 'normalized' || s === 'imported') return 0;

  // Fallback: infer from data when status is empty
  const hasImages = (product.images || []).some(i => i.image_type === 'original');
  const hasProcessed = (product.images || []).some(i => i.image_type === 'processed');
  if (product.ml_item_id) return 7;
  if (product.has_listing) return 5;
  if (hasProcessed) return 4;
  if (hasImages) return 3;
  if (product.has_pricing) return 2;
  if (product.part_name && product.brand && product.category) return 1;
  return 0;
}

function confidenceClass(val) {
  if (val == null || val === 0) return 'low';
  if (val >= 80) return 'high';
  if (val >= 50) return 'medium';
  return 'low';
}

function renderProductCard(p) {
  const progress = statusToProgress(p);
  const isPublished = progress >= 7;
  const confVal = p.confidence_level != null ? `${p.confidence_level}%` : '—';
  const confClass = confidenceClass(p.confidence_level);

  const stepsHtml = PIPELINE_STEPS.map((step, index) => {
    const isCompleted = progress > step.id;
    const isCurrent = progress === step.id;
    const isPending = progress < step.id;

    let btnClass = 'pipeline-btn';
    if (isCompleted) btnClass += ' completed';
    else if (isCurrent) btnClass += ' current';
    else btnClass += ' pending';

    const dotHtml = isCompleted ? '<span class="pipeline-done-dot"></span>' : '';
    const onclick = (isCurrent || isCompleted) && !isPending
      ? `onclick="event.stopPropagation();cardAction(${p.id}, ${step.id})"`
      : '';
    const disabled = isPending ? 'disabled' : '';
    const btn = `<button class="${btnClass}" ${onclick} ${disabled} title="${step.label}">${step.icon}<span>${step.label}</span>${dotHtml}</button>`;

    const connector = index < PIPELINE_STEPS.length - 1
      ? `<span class="pipeline-connector ${isCompleted ? 'done' : 'pending'}"></span>`
      : '';

    return btn + connector;
  }).join('');

  return `
    <div class="product-card ${isPublished ? 'published' : ''}" id="pcard-${p.id}">
      <div class="product-card-info">
        <div>
          <div class="product-card-field-label">OEM</div>
          <span class="product-card-oem">${escapeHtml(p.oem)}</span>
        </div>
        <div>
          <div class="product-card-field-label">Peça</div>
          <div class="product-card-field-value">${escapeHtml(p.part_name) || '—'}</div>
        </div>
        <div>
          <div class="product-card-field-label">Marca</div>
          <div class="product-card-field-value">${escapeHtml(p.brand) || '—'}</div>
        </div>
        <div>
          <div class="product-card-field-label">Categoria</div>
          <div class="product-card-field-value" style="color:var(--text-tertiary)">${escapeHtml(p.category) || '—'}</div>
        </div>
        <div>
          <div class="product-card-field-label">Confiança</div>
          <div class="product-card-field-value product-card-confidence ${confClass}">${confVal}</div>
        </div>
      </div>
      <div class="product-card-divider"></div>
      <div class="product-pipeline-bar">
        ${stepsHtml}
      </div>
      <div id="pcard-action-${p.id}"></div>
    </div>
  `;
}

// --- Inline Card Actions ---

function cardActionClose(productId) {
  const area = document.getElementById(`pcard-action-${productId}`);
  if (area) area.innerHTML = '';
}

function cardActionArea(productId, html) {
  const area = document.getElementById(`pcard-action-${productId}`);
  if (area) area.innerHTML = `
    <div class="product-card-action">
      <button class="action-close" onclick="cardActionClose(${productId})">&times;</button>
      ${html}
    </div>
  `;
}

async function refreshCard(productId) {
  try {
    const p = await api(`/products/${productId}`);
    // Update local cache
    const idx = products.findIndex(x => x.id === productId);
    if (idx >= 0) products[idx] = p;
    // Re-render card in place
    const cardEl = document.getElementById(`pcard-${productId}`);
    if (cardEl) {
      const newHtml = renderProductCard(p);
      cardEl.outerHTML = newHtml;
    }
  } catch (err) {
    console.error('refreshCard error:', err);
  }
}

function cardAction(productId, stepId) {
  switch (stepId) {
    case 0: cardActionEnrich(productId); break;
    case 1: cardActionPricing(productId); break;
    case 2: cardActionImageUpload(productId); break;
    case 3: cardActionBackground(productId); break;
    case 4: cardActionGenerate(productId); break;
    case 5: cardActionValidate(productId); break;
    case 6: cardActionPublish(productId); break;
  }
}

// Step 0 — Enriquecer com IA
async function cardActionEnrich(productId) {
  cardActionArea(productId, `
    <div class="flex items-center gap-2"><div class="spinner"></div> <span>Enriquecendo com IA...</span></div>
  `);
  try {
    const result = await api(`/products/${productId}/ai-enrich`, { method: 'POST' });
    cardActionArea(productId, `
      <div class="action-result success">
        <strong>${result.common_name}</strong> — ${result.provider} [${result.model}]<br>
        Confiança: ${result.confidence}%
      </div>
    `);
    toast(`Enriquecido: ${result.common_name} (${result.confidence}%)`, 'success');
    await refreshCard(productId);
  } catch (err) {
    cardActionArea(productId, `<div class="action-result error">${escapeHtml(err.message)}</div>`);
    toast(err.message, 'error');
  }
}

// Step 1 — Preço
async function cardActionPricing(productId) {
  cardActionArea(productId, `<div class="flex items-center gap-2"><div class="spinner"></div> Carregando...</div>`);

  let info = { cost: 0, estimated_shipping: 0, commission_percent: 0.16, fixed_fee: 0, margin_percent: 0.20, honda_price: null };
  try { info = await api(`/products/${productId}/pricing/info`); } catch { /* defaults */ }

  const costValue = info.honda_price || info.cost || 0;
  const hondaBadge = info.honda_price
    ? `<div style="background:var(--info-subtle);padding:var(--space-3);border-radius:var(--radius-sm);margin-bottom:var(--space-3);font-size:12px">
        <strong>Preço Honda:</strong> R$ ${parseFloat(info.honda_price).toFixed(2)}
      </div>` : '';
  const existingPrice = info.suggested_price
    ? `<div style="background:var(--success-subtle);padding:var(--space-3);border-radius:var(--radius-sm);margin-bottom:var(--space-3);font-size:12px">
        <strong>Preço atual:</strong> R$ ${parseFloat(info.suggested_price).toFixed(2)}
        ${info.final_price ? ` | Final: R$ ${parseFloat(info.final_price).toFixed(2)}` : ''}
      </div>` : '';

  cardActionArea(productId, `
    <h3 style="margin-bottom:var(--space-3)">Calcular Preço</h3>
    ${hondaBadge}${existingPrice}
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Custo (R$)</label>
        <input type="number" step="0.01" id="pc-cost-${productId}" class="form-input" value="${costValue}">
      </div>
      <div class="form-group">
        <label class="form-label">Frete (R$)</label>
        <input type="number" step="0.01" id="pc-ship-${productId}" class="form-input" value="${info.estimated_shipping}">
      </div>
      <div class="form-group">
        <label class="form-label">Comissão ML (%)</label>
        <input type="number" step="0.01" id="pc-comm-${productId}" class="form-input" value="${info.commission_percent}">
      </div>
      <div class="form-group">
        <label class="form-label">Taxa Fixa (R$)</label>
        <input type="number" step="0.01" id="pc-fee-${productId}" class="form-input" value="${info.fixed_fee}">
      </div>
      <div class="form-group">
        <label class="form-label">Margem (%)</label>
        <input type="number" step="0.01" id="pc-margin-${productId}" class="form-input" value="${info.margin_percent}">
      </div>
    </div>
    <div style="margin-top:var(--space-3)">
      <button class="btn btn-primary btn-sm" onclick="submitCardPricing(${productId})">Calcular</button>
    </div>
    <div id="pc-result-${productId}"></div>
  `);
}

async function submitCardPricing(productId) {
  const body = {
    cost: parseFloat(document.getElementById(`pc-cost-${productId}`).value),
    estimated_shipping: parseFloat(document.getElementById(`pc-ship-${productId}`).value),
    commission_percent: parseFloat(document.getElementById(`pc-comm-${productId}`).value),
    fixed_fee: parseFloat(document.getElementById(`pc-fee-${productId}`).value),
    margin_percent: parseFloat(document.getElementById(`pc-margin-${productId}`).value),
  };
  const resultEl = document.getElementById(`pc-result-${productId}`);
  resultEl.innerHTML = '<div class="flex items-center gap-2" style="margin-top:var(--space-3)"><div class="spinner"></div> Calculando...</div>';
  try {
    const result = await apiPost(`/products/${productId}/pricing/calculate`, body);
    toast(`Preço calculado: R$ ${parseFloat(result.suggested_price).toFixed(2)}`, 'success');
    // Refresh card to advance pipeline — the toast shows the result
    await refreshCard(productId);
  } catch (err) {
    resultEl.innerHTML = `<div class="action-result error" style="margin-top:var(--space-3)">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
  }
}

// --- Image preview helper ---
function renderExistingImages(product, type) {
  const imgs = (product.images || []).filter(i => i.image_type === type);
  if (!imgs.length) return '';
  return `
    <div style="margin-bottom:var(--space-3)">
      <span style="font-size:12px;color:var(--text-secondary)"><strong>${imgs.length}</strong> imagem(ns) ${type === 'processed' ? 'processada(s)' : 'original(is)'}</span>
      <div class="image-grid" style="margin-top:var(--space-2)">
        ${imgs.map(img => `
          <div class="image-thumb">
            <img src="/uploads/${encodeURIComponent(product.oem)}/${encodeURIComponent(img.filename)}" alt="${escapeHtml(img.filename)}">
          </div>
        `).join('')}
      </div>
    </div>
  `;
}

function getLocalProduct(productId) {
  return products.find(p => p.id === productId);
}

// Step 2 — Upload de Imagens
function cardActionImageUpload(productId) {
  const product = getLocalProduct(productId);
  const existingHtml = product ? renderExistingImages(product, 'original') : '';

  cardActionArea(productId, `
    <h3 style="margin-bottom:var(--space-3)">Upload de Imagens</h3>
    ${existingHtml}
    <div class="upload-zone" id="img-zone-${productId}" onclick="document.getElementById('img-input-${productId}').click()" style="padding:var(--space-6)">
      <div class="upload-icon">&#128247;</div>
      <p><strong>Selecione imagens</strong> do produto</p>
      <p style="font-size:11px;margin-top:4px">JPG, PNG — max 10MB — até 10 imagens</p>
    </div>
    <input type="file" id="img-input-${productId}" accept="image/*" multiple style="display:none" onchange="previewCardImages(${productId}, this)">
    <div id="img-preview-${productId}" style="margin-top:var(--space-3)"></div>
    <div id="img-result-${productId}"></div>
  `);

  const zone = document.getElementById(`img-zone-${productId}`);
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      document.getElementById(`img-input-${productId}`).files = e.dataTransfer.files;
      previewCardImages(productId, document.getElementById(`img-input-${productId}`));
    }
  });
}

function previewCardImages(productId, input) {
  const files = input.files;
  if (!files.length) return;
  const preview = document.getElementById(`img-preview-${productId}`);
  preview.innerHTML = `
    <div style="font-size:12px;color:var(--text-secondary);margin-bottom:var(--space-2)"><strong>${files.length}</strong> imagem(ns)</div>
    <div class="image-grid">
      ${Array.from(files).map((f, i) => `<div class="image-thumb" id="cthumb-${productId}-${i}"><span style="font-size:10px">${f.name.substring(0, 10)}</span></div>`).join('')}
    </div>
    <button class="btn btn-primary btn-sm" style="margin-top:var(--space-3)" onclick="submitCardImages(${productId})">Enviar ${files.length} imagem(ns)</button>
  `;
  Array.from(files).forEach((f, i) => {
    const reader = new FileReader();
    reader.onload = e => {
      const t = document.getElementById(`cthumb-${productId}-${i}`);
      if (t) t.innerHTML = `<img src="${e.target.result}">`;
    };
    reader.readAsDataURL(f);
  });
}

async function submitCardImages(productId) {
  const input = document.getElementById(`img-input-${productId}`);
  const files = input.files;
  if (!files.length) return;

  const resultEl = document.getElementById(`img-result-${productId}`);
  resultEl.innerHTML = '<div class="flex items-center gap-2" style="margin-top:var(--space-3)"><div class="spinner"></div> Enviando...</div>';

  const form = new FormData();
  for (const f of files) form.append('files', f);

  try {
    const result = await api(`/products/${productId}/images/upload`, { method: 'POST', body: form, headers: {} });
    resultEl.innerHTML = `<div class="action-result success" style="margin-top:var(--space-3)"><strong>${result.files.length} imagem(ns) salva(s)</strong></div>`;
    toast(`${result.files.length} imagens enviadas`, 'success');
    await refreshCard(productId);
  } catch (err) {
    resultEl.innerHTML = `<div class="action-result error" style="margin-top:var(--space-3)">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
  }
}

// Step 3 — Tratar Fundo
async function cardActionBackground(productId) {
  const product = getLocalProduct(productId);
  const processedHtml = product ? renderExistingImages(product, 'processed') : '';
  const originalHtml = product ? renderExistingImages(product, 'original') : '';
  const hasProcessed = product && (product.images || []).some(i => i.image_type === 'processed');

  cardActionArea(productId, `
    <h3 style="margin-bottom:var(--space-3)">Tratamento de Fundo</h3>
    ${processedHtml || originalHtml}
    <button class="btn btn-primary btn-sm" id="btn-bg-${productId}" onclick="execBackground(${productId})">
      ${hasProcessed ? 'Reprocessar Fundo' : 'Remover Fundo'}
    </button>
    <div id="bg-result-${productId}" style="margin-top:var(--space-3)"></div>
  `);
}

async function execBackground(productId) {
  const btn = document.getElementById(`btn-bg-${productId}`);
  const resultEl = document.getElementById(`bg-result-${productId}`);
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner" style="width:14px;height:14px;display:inline-block;vertical-align:middle"></span> Processando...'; }
  resultEl.innerHTML = '';

  try {
    const result = await api(`/products/${productId}/images/process-background`, { method: 'POST' });
    resultEl.innerHTML = `
      <div class="action-result success">
        <strong>${result.message}</strong>
        ${result.errors && result.errors.length ? `<div style="color:var(--error);margin-top:4px">Erros: ${result.errors.map(e => e.file).join(', ')}</div>` : ''}
      </div>
    `;
    toast(result.message, 'success');
    await refreshCard(productId);
    // Re-open fundo panel to show new processed images
    cardActionBackground(productId);
  } catch (err) {
    resultEl.innerHTML = `<div class="action-result error">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Remover Fundo'; }
  }
}

// Step 4 — Gerar Anúncio
async function cardActionGenerate(productId) {
  cardActionArea(productId, `
    <div class="flex items-center gap-2"><div class="spinner"></div> <span>Gerando anúncio...</span></div>
  `);
  try {
    const listing = await api(`/products/${productId}/listing/generate`, { method: 'POST' });
    cardActionArea(productId, `
      <div class="action-result success">
        <strong>Anúncio gerado</strong> — Categoria: ${listing.ml_category || 'não definida'}
      </div>
    `);
    toast('Anúncio gerado', 'success');
    await refreshCard(productId);
  } catch (err) {
    cardActionArea(productId, `<div class="action-result error">${escapeHtml(err.message)}</div>`);
    toast(err.message, 'error');
  }
}

// Step 5 — Validar
async function cardActionValidate(productId) {
  cardActionArea(productId, `
    <div class="flex items-center gap-2"><div class="spinner"></div> <span>Validando anúncio...</span></div>
  `);
  try {
    const result = await api(`/products/${productId}/listing/validate`, { method: 'POST' });
    if (result.valid) {
      cardActionArea(productId, `<div class="action-result success"><strong>Anúncio validado</strong> — pronto para publicar</div>`);
      toast('Validado com sucesso', 'success');
    } else {
      cardActionArea(productId, `<div class="action-result error"><strong>Falha na validação:</strong> ${result.errors.join(', ')}</div>`);
      toast('Validação falhou', 'error');
    }
    await refreshCard(productId);
  } catch (err) {
    cardActionArea(productId, `<div class="action-result error">${escapeHtml(err.message)}</div>`);
    toast(err.message, 'error');
  }
}

// Step 6 — Publicar no ML
async function cardActionPublish(productId) {
  cardActionArea(productId, `
    <div class="flex items-center gap-2"><div class="spinner"></div> <span>Publicando no Mercado Livre...</span></div>
  `);
  try {
    const result = await api(`/products/${productId}/listing/publish`, { method: 'POST' });
    toast(`Publicado! ID: ${result.ml_item_id}`, 'success');

    // Refresh card first to update pipeline to "published"
    await refreshCard(productId);

    // Then show the result with the permalink inside the refreshed card
    cardActionArea(productId, `
      <div class="action-result success">
        <strong>Publicado!</strong> ML ID: <span class="mono">${result.ml_item_id}</span>
        ${result.permalink ? `<div style="margin-top:var(--space-2)"><a href="${result.permalink}" target="_blank" class="btn btn-primary btn-sm">Ver no Mercado Livre &rarr;</a></div>` : ''}
      </div>
    `);
  } catch (err) {
    cardActionArea(productId, `<div class="action-result error">${escapeHtml(err.message)}</div>`);
    toast(err.message, 'error');
  }
}

// --- Products List ---
let productsFilter = 'all';

function filterProducts(filter) {
  productsFilter = filter;
  applyProductsFilter();
}

function applyProductsFilter() {
  // Update active button
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === productsFilter);
  });

  const filtered = productsFilter === 'all'
    ? products
    : productsFilter === 'published'
      ? products.filter(p => statusToProgress(p) >= 7)
      : products.filter(p => statusToProgress(p) < 7);

  const listEl = document.getElementById('products-list');
  const countEl = document.getElementById('products-count');

  if (!listEl) return;

  countEl.textContent = `${filtered.length} de ${products.length} produto${products.length !== 1 ? 's' : ''}`;

  if (filtered.length > 0) {
    listEl.innerHTML = filtered.map(p => renderProductCard(p)).join('');
  } else {
    const msg = productsFilter === 'published'
      ? 'Nenhum produto publicado ainda'
      : productsFilter === 'in_progress'
        ? 'Nenhum produto em andamento'
        : 'Nenhum produto';
    listEl.innerHTML = `<div class="empty-state"><h3>${msg}</h3></div>`;
  }
}

async function renderProducts(el) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    products = await api('/products');

    const publishedCount = products.filter(p => statusToProgress(p) >= 7).length;
    const inProgressCount = products.length - publishedCount;

    el.innerHTML = `
      <div class="view">
        <div class="page-header">
          <div>
            <h1>Produtos</h1>
            <p id="products-count">${products.length} produto${products.length !== 1 ? 's' : ''} no sistema</p>
          </div>
          <button class="btn btn-secondary" onclick="navigate('import')">Importar OEMs</button>
        </div>

        <div class="products-filter-bar">
          <button class="filter-btn ${productsFilter === 'all' ? 'active' : ''}" data-filter="all" onclick="filterProducts('all')">
            Todos <span class="filter-count">${products.length}</span>
          </button>
          <button class="filter-btn ${productsFilter === 'in_progress' ? 'active' : ''}" data-filter="in_progress" onclick="filterProducts('in_progress')">
            Em andamento <span class="filter-count">${inProgressCount}</span>
          </button>
          <button class="filter-btn ${productsFilter === 'published' ? 'active' : ''}" data-filter="published" onclick="filterProducts('published')">
            Publicados <span class="filter-count">${publishedCount}</span>
          </button>
        </div>

        <div class="product-cards-list" id="products-list"></div>
      </div>
    `;

    applyProductsFilter();

  } catch (err) {
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${escapeHtml(err.message)}</p></div>`;
  }
}

// --- Product Detail ---

// --- Knowledge Base ---
async function renderKnowledgeBase(el) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    const [docs, stats, providers] = await Promise.all([
      api('/kb/documents'),
      api('/kb/stats'),
      api('/kb/ai-providers'),
    ]);

    const anyConfigured = providers.some(p => p.configured);

    el.innerHTML = `
      <div class="view">
        <div class="page-header">
          <div>
            <h1>Base de Conhecimento</h1>
            <p>Catálogos Honda para enriquecimento inteligente</p>
          </div>
        </div>

        <!-- AI Providers -->
        <div class="section">
          <h2 class="section-header">Provedores de IA</h2>
          <p style="color:var(--text-tertiary);font-size:12px;margin-bottom:var(--space-4)">
            Configure pelo menos um provedor. O primeiro configurado será usado por padrão.
          </p>
          <div class="provider-grid">
            ${providers.map(p => `
              <div class="card provider-card" id="provider-card-${p.id}">
                <div class="flex items-center gap-3" style="margin-bottom:var(--space-4)">
                  <span class="status-dot ${p.configured ? 'connected' : 'disconnected'}"></span>
                  <span style="font-weight:600;font-size:14px">${escapeHtml(p.name)}</span>
                </div>
                ${p.configured ? `
                  <div style="margin-bottom:var(--space-3)">
                    <span class="badge badge-success">Ativa</span>
                    <span class="mono" style="color:var(--text-tertiary);font-size:11px;margin-left:var(--space-2)">${p.masked_key}</span>
                  </div>
                  <div style="margin-bottom:var(--space-3)">
                    <span class="detail-label">Modelo</span>
                    <span class="mono" style="font-size:12px">${p.selected_model}</span>
                  </div>
                  <div class="flex gap-2">
                    <button class="btn btn-ghost btn-sm" onclick="toggleProviderForm('${p.id}')">Alterar</button>
                    <button class="btn btn-danger btn-sm" onclick="removeProvider('${p.id}')">Remover</button>
                  </div>
                ` : `
                  <p style="color:var(--text-tertiary);font-size:12px;margin-bottom:var(--space-3)">Nenhuma chave configurada</p>
                `}
                <div id="provider-form-${p.id}" style="${p.configured ? 'display:none;' : ''}margin-top:var(--space-3)">
                  <div class="form-group" style="margin-bottom:var(--space-3)">
                    <label class="form-label">API Key</label>
                    <input type="password" id="key-${p.id}" class="form-input" placeholder="${p.id === 'anthropic' ? 'sk-ant-api03-...' : p.id === 'openai' ? 'sk-...' : 'AI...'}">
                  </div>
                  <div class="form-group" style="margin-bottom:var(--space-3)">
                    <label class="form-label">Modelo</label>
                    <select id="model-${p.id}" class="form-select">
                      ${p.models.map(m => `<option value="${m}" ${m === p.selected_model ? 'selected' : ''}>${m}</option>`).join('')}
                    </select>
                  </div>
                  <button class="btn btn-primary btn-sm" onclick="saveProvider('${p.id}')">Salvar</button>
                  <div id="provider-result-${p.id}" class="mt-4"></div>
                </div>
              </div>
            `).join('')}
          </div>
        </div>

        <div class="stats-grid section">
          <div class="stat-card">
            <div class="stat-value">${stats.total_documents}</div>
            <div class="stat-label">Documentos</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.total_entries}</div>
            <div class="stat-label">OEMs Extraídos</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.unique_oems}</div>
            <div class="stat-label">OEMs Únicos</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.coverage_pct}%</div>
            <div class="stat-label">Cobertura (${stats.products_matched}/${stats.products_total})</div>
          </div>
        </div>

        <!-- Upload -->
        <div class="section">
          <h2 class="section-header">Upload de Catálogo</h2>
          <div class="card" style="max-width:560px">
            <div class="upload-zone" id="kb-upload-zone" onclick="document.getElementById('kb-file-input').click()">
              <div class="upload-icon">&#128214;</div>
              <p><strong>Clique para selecionar</strong> ou arraste o catálogo PDF</p>
              <p style="font-size:11px;margin-top:4px">Formato: .pdf — Catálogo de peças Honda</p>
            </div>
            <input type="file" id="kb-file-input" accept=".pdf" style="display:none" onchange="handleKBUpload(this)">
            <div id="kb-upload-result" class="mt-4"></div>
          </div>
        </div>

        <!-- Search -->
        <div class="section">
          <h2 class="section-header">Buscar OEM na Base</h2>
          <div class="flex gap-3" style="max-width:560px">
            <input type="text" id="kb-search-input" class="form-input" style="flex:1" placeholder="Ex: 53170-MEL-006">
            <button class="btn btn-primary" onclick="searchKB()">Buscar</button>
          </div>
          <div id="kb-search-result" class="mt-4"></div>
        </div>

        <!-- Documents -->
        ${docs.length > 0 ? `
        <div class="section">
          <h2 class="section-header">Documentos</h2>
          <div class="table-wrap">
            <table>
              <thead><tr>
                <th>ID</th><th>Arquivo</th><th>Marca</th><th>Páginas</th><th>OEMs</th><th>Status</th><th>Ações</th>
              </tr></thead>
              <tbody>
                ${docs.map(d => `
                  <tr style="cursor:default">
                    <td class="mono">#${d.id}</td>
                    <td>${escapeHtml(d.filename)}</td>
                    <td>${escapeHtml(d.brand)}</td>
                    <td>${d.page_count || '—'}</td>
                    <td>${d.entry_count}</td>
                    <td>${kbStatusBadge(d.status)}</td>
                    <td><button class="btn btn-danger btn-sm" onclick="event.stopPropagation();deleteKBDoc(${d.id})">Remover</button></td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>` : ''}
      </div>
    `;

    // Drag & drop
    const zone = document.getElementById('kb-upload-zone');
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
    zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
    zone.addEventListener('drop', e => {
      e.preventDefault();
      zone.classList.remove('dragover');
      if (e.dataTransfer.files[0]) {
        document.getElementById('kb-file-input').files = e.dataTransfer.files;
        handleKBUpload(document.getElementById('kb-file-input'));
      }
    });

    // Enter to search
    const searchInput = document.getElementById('kb-search-input');
    searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') searchKB(); });

  } catch (err) {
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${escapeHtml(err.message)}</p></div>`;
  }
}

function kbStatusBadge(status) {
  const map = {
    pending: ['Pendente', 'neutral'],
    processing: ['Processando', 'info'],
    processed: ['Processado', 'success'],
    error: ['Erro', 'error'],
  };
  const [label, variant] = map[status] || [status, 'neutral'];
  return `<span class="badge badge-${variant}">${label}</span>`;
}

async function handleKBUpload(input) {
  const file = input.files[0];
  if (!file) return;

  const result = document.getElementById('kb-upload-result');
  result.innerHTML = '<div class="flex items-center gap-2"><div class="spinner"></div> Enviando e processando PDF...</div>';

  try {
    const form = new FormData();
    form.append('file', file);
    const data = await api('/kb/upload', { method: 'POST', body: form, headers: {} });
    result.innerHTML = `
      <div class="card" style="background:var(--success-subtle);border-color:var(--success)">
        <strong>${escapeHtml(data.filename)}</strong> enviado com sucesso<br>
        <span style="color:var(--text-secondary)">Status: ${data.status} — O processamento está sendo feito em background.</span>
        <div class="mt-4">
          <button class="btn btn-secondary btn-sm" onclick="navigate('kb')">Atualizar</button>
        </div>
      </div>
    `;
    toast('Catálogo enviado! Processamento em background.', 'success');
  } catch (err) {
    result.innerHTML = `<div class="card" style="border-color:var(--error);color:var(--error)">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
  }
}

async function searchKB() {
  const input = document.getElementById('kb-search-input');
  const oem = input.value.trim();
  if (!oem) { toast('Digite um código OEM', 'error'); return; }

  const resultEl = document.getElementById('kb-search-result');
  resultEl.innerHTML = '<div class="flex items-center gap-2"><div class="spinner"></div> Buscando...</div>';

  try {
    const result = await api(`/kb/search?oem=${encodeURIComponent(oem)}`);
    if (!result.found_in_kb) {
      resultEl.innerHTML = `
        <div class="card" style="border-color:var(--warning)">
          <strong>OEM ${escapeHtml(result.oem_code)}</strong> não encontrado na base de conhecimento.
          <p style="color:var(--text-tertiary);font-size:12px;margin-top:var(--space-2)">A IA ainda pode enriquecer este produto usando conhecimento geral.</p>
        </div>
      `;
    } else {
      resultEl.innerHTML = `
        <div class="card" style="border-color:var(--success)">
          <strong>${result.entries.length} entrada(s)</strong> encontrada(s) para <span class="mono">${escapeHtml(result.oem_code)}</span>
          ${result.entries.map(e => `
            <div style="margin-top:var(--space-3);padding:var(--space-3);background:var(--bg-elevated);border-radius:var(--radius-sm)">
              <div><strong>Descrição Honda:</strong> ${escapeHtml(e.honda_part_name) || '—'}</div>
              <div><strong>Preço Honda:</strong> ${e.honda_price ? 'R$ ' + parseFloat(e.honda_price).toFixed(2) : '—'}</div>
              <div><strong>Página:</strong> ${e.page_number || '—'}</div>
            </div>
          `).join('')}
        </div>
      `;
    }
  } catch (err) {
    resultEl.innerHTML = `<div style="color:var(--error)">${escapeHtml(err.message)}</div>`;
  }
}

function toggleProviderForm(id) {
  const form = document.getElementById(`provider-form-${id}`);
  form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function saveProvider(id) {
  const key = document.getElementById(`key-${id}`).value.trim();
  const model = document.getElementById(`model-${id}`).value;
  if (!key) { toast('Cole a API Key', 'error'); return; }

  const resultEl = document.getElementById(`provider-result-${id}`);
  resultEl.innerHTML = '<div class="flex items-center gap-2"><div class="spinner"></div> Salvando...</div>';

  try {
    await apiPost(`/kb/ai-providers/${id}`, { api_key: key, model });
    toast(`${id} configurado com sucesso`, 'success');
    navigate('kb');
  } catch (err) {
    resultEl.innerHTML = `<div style="color:var(--error)">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
  }
}

async function removeProvider(id) {
  try {
    await api(`/kb/ai-providers/${id}`, { method: 'DELETE' });
    toast(`${id} removido`, 'success');
    navigate('kb');
  } catch (err) { toast(err.message, 'error'); }
}

async function deleteKBDoc(id) {
  try {
    await api(`/kb/documents/${id}`, { method: 'DELETE' });
    toast('Documento removido', 'success');
    navigate('kb');
  } catch (err) { toast(err.message, 'error'); }
}

// --- Auth ---
async function renderAuth(el) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    const status = await api('/auth/ml/status');

    el.innerHTML = `
      <div class="view">
        <div class="page-header">
          <div>
            <h1>Mercado Livre</h1>
            <p>Autenticação OAuth 2.0</p>
          </div>
        </div>

        <div class="card" style="max-width:520px">
          <div class="flex items-center gap-3" style="margin-bottom:var(--space-5)">
            <span class="status-dot ${status.authenticated ? 'connected' : 'disconnected'}"></span>
            <span style="font-weight:600">${status.authenticated ? 'Conectado' : 'Desconectado'}</span>
          </div>

          ${status.authenticated ? `
            <div class="detail-grid">
              <div class="detail-field">
                <span class="detail-label">User ID</span>
                <span class="detail-value mono">${status.ml_user_id}</span>
              </div>
              <div class="detail-field">
                <span class="detail-label">Token</span>
                <span class="detail-value">${status.expired ? '<span class="badge badge-error">Expirado</span>' : '<span class="badge badge-success">Válido</span>'}</span>
              </div>
              <div class="detail-field" style="grid-column:1/-1">
                <span class="detail-label">Expira em</span>
                <span class="detail-value">${new Date(status.expires_at).toLocaleString('pt-BR')}</span>
              </div>
            </div>
            <button class="btn btn-secondary mt-6" onclick="startAuth()">Reconectar</button>
          ` : `
            <p style="color:var(--text-tertiary);margin-bottom:var(--space-5)">
              Conecte sua conta do Mercado Livre para publicar produtos.
            </p>
            <button class="btn btn-primary" onclick="startAuth()">1. Abrir Autenticação ML</button>
          `}
        </div>

        <!-- Code input area (shown after clicking auth) -->
        <div id="auth-code-area" style="margin-top:var(--space-6)"></div>
      </div>
    `;
  } catch (err) {
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${escapeHtml(err.message)}</p></div>`;
  }
}

async function startAuth() {
  try {
    const data = await api('/auth/ml/login');
    window.open(data.auth_url, '_blank');

    const area = document.getElementById('auth-code-area');
    area.innerHTML = `
      <div class="card" style="max-width:520px">
        <h2 class="section-header">2. Cole o código de autorização</h2>
        <p style="color:var(--text-tertiary);font-size:13px;margin-bottom:var(--space-4)">
          Após autorizar no Mercado Livre, você será redirecionado. Copie o <strong>code</strong> da URL
          (o valor após <span class="mono">?code=</span>) e cole abaixo.
        </p>
        <div class="flex gap-3">
          <input type="text" id="auth-code-input" class="form-input" style="flex:1"
            placeholder="TG-xxxxxxxxxxxx-xxxxxxxxx">
          <button class="btn btn-primary" onclick="submitAuthCode()">Conectar</button>
        </div>
        <p style="color:var(--text-tertiary);font-size:11px;margin-top:var(--space-3)">
          Dica: se a URL de redirect foi <span class="mono">https://...?code=TG-abc123</span>, cole apenas <span class="mono">TG-abc123</span>
        </p>
        <div id="auth-code-result" class="mt-4"></div>
      </div>
    `;

    document.getElementById('auth-code-input').focus();
  } catch (err) { toast(err.message, 'error'); }
}

async function submitAuthCode() {
  const input = document.getElementById('auth-code-input');
  let code = input.value.trim();
  if (!code) { toast('Cole o código de autorização', 'error'); return; }

  // Se o usuário colou a URL inteira, extrai o code
  if (code.includes('?code=')) {
    code = new URL(code).searchParams.get('code') || code;
  } else if (code.includes('code=')) {
    code = code.split('code=')[1].split('&')[0];
  }

  const result = document.getElementById('auth-code-result');
  result.innerHTML = '<div class="flex items-center gap-2"><div class="spinner"></div> Trocando code por token...</div>';

  try {
    await api(`/auth/ml/callback?code=${encodeURIComponent(code)}`);
    toast('Mercado Livre conectado com sucesso!', 'success');
    updateAuthStatus();
    navigate('auth');
  } catch (err) {
    result.innerHTML = `<div style="color:var(--error);font-size:13px;margin-top:var(--space-2)">${escapeHtml(err.message)}</div>`;
    toast(err.message, 'error');
  }
}

// --- Auth status check ---
async function updateAuthStatus() {
  try {
    const status = await api('/auth/ml/status');
    const dot = document.getElementById('global-status-dot');
    const text = document.getElementById('global-status-text');
    if (dot && text) {
      dot.className = `status-dot ${status.authenticated ? 'connected' : 'disconnected'}`;
      text.textContent = status.authenticated ? 'ML Conectado' : 'ML Desconectado';
    }
  } catch { /* silent */ }
}

// --- Auth UI ---
function renderAuthScreen() {
  const appEl = document.querySelector('.app');
  const sidebar = document.querySelector('.sidebar');
  const main = document.getElementById('main-content');

  // Esconde sidebar e faz o main ocupar tudo
  sidebar.style.display = 'none';
  appEl.style.gridTemplateColumns = '1fr';

  main.style.display = 'flex';
  main.style.alignItems = 'center';
  main.style.justifyContent = 'center';
  main.style.maxHeight = '100vh';
  main.style.padding = '0';

  main.innerHTML = `
    <div class="view" style="width:100%;max-width:400px;padding:var(--space-6)">
      <div style="text-align:center;margin-bottom:var(--space-10)">
        <div style="display:inline-flex;align-items:center;gap:var(--space-3);margin-bottom:var(--space-4)">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
          </svg>
          <span style="font-size:32px;font-weight:800;letter-spacing:-0.04em"><span style="color:var(--accent)">ML</span>Bot</span>
        </div>
        <p style="color:var(--text-tertiary);font-size:14px">Automatize seus anuncios no Mercado Livre</p>
      </div>

      <div class="card" style="padding:var(--space-8)">
        <div id="auth-tabs" style="display:flex;gap:0;margin-bottom:var(--space-8);border-radius:var(--radius-sm);overflow:hidden;border:1px solid var(--border-default)">
          <button id="tab-login" style="flex:1;padding:10px;border:none;cursor:pointer;font-weight:600;font-size:13px;font-family:var(--font-sans);background:var(--accent);color:white;transition:all 150ms" onclick="showLoginForm()">Entrar</button>
          <button id="tab-register" style="flex:1;padding:10px;border:none;cursor:pointer;font-weight:600;font-size:13px;font-family:var(--font-sans);background:var(--bg-elevated);color:var(--text-secondary);transition:all 150ms" onclick="showRegisterForm()">Criar Conta</button>
        </div>
        <div id="auth-form"></div>
      </div>
    </div>
  `;
  showLoginForm();
}

function _setActiveTab(tab) {
  const login = document.getElementById('tab-login');
  const register = document.getElementById('tab-register');
  if (!login || !register) return;
  if (tab === 'login') {
    login.style.background = 'var(--accent)'; login.style.color = 'white';
    register.style.background = 'var(--bg-elevated)'; register.style.color = 'var(--text-secondary)';
  } else {
    register.style.background = 'var(--accent)'; register.style.color = 'white';
    login.style.background = 'var(--bg-elevated)'; login.style.color = 'var(--text-secondary)';
  }
}

function showLoginForm() {
  _setActiveTab('login');
  document.getElementById('auth-form').innerHTML = `
    <div class="form-group" style="margin-bottom:var(--space-5)">
      <label class="form-label">Email</label>
      <input type="email" id="auth-email" class="form-input" placeholder="seu@email.com" onkeydown="if(event.key==='Enter')doLogin()">
    </div>
    <div class="form-group" style="margin-bottom:var(--space-8)">
      <label class="form-label">Senha</label>
      <input type="password" id="auth-password" class="form-input" placeholder="••••••" onkeydown="if(event.key==='Enter')doLogin()">
    </div>
    <button class="btn btn-primary w-full" style="padding:12px;font-size:14px" onclick="doLogin()">Entrar</button>
    <div id="auth-error" class="mt-4"></div>
  `;
  const emailInput = document.getElementById('auth-email');
  if (emailInput) emailInput.focus();
}

function showRegisterForm() {
  _setActiveTab('register');
  document.getElementById('auth-form').innerHTML = `
    <div class="form-group" style="margin-bottom:var(--space-5)">
      <label class="form-label">Nome</label>
      <input type="text" id="auth-name" class="form-input" placeholder="Seu nome" onkeydown="if(event.key==='Enter')document.getElementById('auth-email').focus()">
    </div>
    <div class="form-group" style="margin-bottom:var(--space-5)">
      <label class="form-label">Email</label>
      <input type="email" id="auth-email" class="form-input" placeholder="seu@email.com" onkeydown="if(event.key==='Enter')document.getElementById('auth-password').focus()">
    </div>
    <div class="form-group" style="margin-bottom:var(--space-8)">
      <label class="form-label">Senha</label>
      <input type="password" id="auth-password" class="form-input" placeholder="Min. 6 caracteres" onkeydown="if(event.key==='Enter')doRegister()">
    </div>
    <button class="btn btn-primary w-full" style="padding:12px;font-size:14px" onclick="doRegister()">Criar Conta</button>
    <div id="auth-error" class="mt-4"></div>
  `;
  const nameInput = document.getElementById('auth-name');
  if (nameInput) nameInput.focus();
}

async function doLogin() {
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  if (!email || !password) { toast('Preencha email e senha', 'error'); return; }
  try {
    const result = await apiPost('/auth/login', { email, password });
    setToken(result.token);
    currentUser = result.user;
    initApp();
  } catch (err) {
    document.getElementById('auth-error').innerHTML = `<div style="color:var(--error)">${escapeHtml(err.message)}</div>`;
  }
}

async function doRegister() {
  const name = document.getElementById('auth-name').value.trim();
  const email = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;
  if (!name || !email || !password) { toast('Preencha todos os campos', 'error'); return; }
  try {
    const result = await apiPost('/auth/register', { name, email, password });
    setToken(result.token);
    currentUser = result.user;
    initApp();
  } catch (err) {
    document.getElementById('auth-error').innerHTML = `<div style="color:var(--error)">${escapeHtml(err.message)}</div>`;
  }
}

function doLogout() {
  clearToken();
  renderAuthScreen();
}

function initApp() {
  const appEl = document.querySelector('.app');
  const sidebar = document.querySelector('.sidebar');
  const main = document.getElementById('main-content');

  // Restaura layout do app após login
  sidebar.style.display = '';
  appEl.style.gridTemplateColumns = '';
  main.style.display = '';
  main.style.alignItems = '';
  main.style.justifyContent = '';
  main.style.maxHeight = '';
  main.style.padding = '';

  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => navigate(btn.dataset.view));
  });
  navigate('dashboard');
  updateAuthStatus();
}

// --- Init ---
document.addEventListener('DOMContentLoaded', async () => {
  const token = getToken();
  if (token) {
    try {
      const user = await api('/auth/me');
      currentUser = user;
      initApp();
    } catch {
      clearToken();
      renderAuthScreen();
    }
  } else {
    renderAuthScreen();
  }
  setInterval(updateAuthStatus, 30000);
});
