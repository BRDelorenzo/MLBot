/* ============================================
   MLBot SPA — Client
   ============================================ */

const API = '';

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

// --- Navigation ---
function navigate(view, data) {
  currentView = view;
  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('active', el.dataset.view === view);
  });
  renderView(view, data);
}

// --- Render Router ---
function renderView(view, data) {
  const main = document.getElementById('main-content');
  switch (view) {
    case 'dashboard': renderDashboard(main); break;
    case 'import': renderImport(main); break;
    case 'products': renderProducts(main); break;
    case 'product-detail': renderProductDetail(main, data); break;
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
                    <td>${b.filename}</td>
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
    el.innerHTML = `<div class="empty-state"><h3>Erro ao carregar</h3><p>${err.message}</p></div>`;
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
        <strong>${data.total_items} OEMs importados</strong> do arquivo ${data.filename}<br>
        <span style="color:var(--text-secondary)">${data.total_valid} válidos · ${data.total_invalid} inválidos</span>
        <div class="mt-4">
          <button class="btn btn-primary btn-sm" onclick="navigate('products')">Ver Produtos</button>
        </div>
      </div>
    `;
    toast(`${data.total_items} OEMs importados com sucesso`, 'success');
  } catch (err) {
    result.innerHTML = `<div class="card" style="border-color:var(--error);color:var(--error)">${err.message}</div>`;
    toast(err.message, 'error');
  }
}

// --- Products List ---
async function renderProducts(el) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    products = await api('/products');

    el.innerHTML = `
      <div class="view">
        <div class="page-header">
          <div>
            <h1>Produtos</h1>
            <p>${products.length} produto${products.length !== 1 ? 's' : ''} no sistema</p>
          </div>
          <button class="btn btn-secondary" onclick="navigate('import')">Importar OEMs</button>
        </div>

        ${products.length > 0 ? `
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>OEM</th><th>Peça</th><th>Marca</th><th>Categoria</th><th>Confiança</th><th>Ações</th>
            </tr></thead>
            <tbody>
              ${products.map(p => `
                <tr onclick="navigate('product-detail', ${p.id})">
                  <td><span class="mono">${p.oem}</span></td>
                  <td>${p.part_name || '<span style="color:var(--text-tertiary)">—</span>'}</td>
                  <td>${p.brand || '—'}</td>
                  <td>${p.category || '—'}</td>
                  <td>${p.confidence_level != null ? `${p.confidence_level}%` : '—'}</td>
                  <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();navigate('product-detail', ${p.id})">Abrir</button></td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>` : `
        <div class="empty-state">
          <h3>Nenhum produto</h3>
          <p>Importe OEMs para criar produtos automaticamente</p>
          <button class="btn btn-primary mt-4" onclick="navigate('import')">Importar</button>
        </div>`}
      </div>
    `;
  } catch (err) {
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${err.message}</p></div>`;
  }
}

// --- Product Detail ---
async function renderProductDetail(el, productId) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    const product = await api(`/products/${productId}`);

    el.innerHTML = `
      <div class="view">
        <div class="page-header">
          <div>
            <div class="flex items-center gap-3">
              <button class="btn btn-ghost btn-sm" onclick="navigate('products')">&larr; Voltar</button>
              <h1><span class="mono" style="color:var(--accent)">${product.oem}</span></h1>
            </div>
            <p>${product.part_name || 'Produto não enriquecido'} ${product.brand ? '· ' + product.brand : ''}</p>
          </div>
        </div>

        <!-- Pipeline -->
        <div class="section">
          <div id="product-pipeline"></div>
        </div>

        <!-- Actions -->
        <div class="section">
          <h2 class="section-header">Ações Rápidas</h2>
          <div class="action-bar">
            <button class="btn btn-primary" onclick="actionAIEnrich(${productId})" id="btn-ai-enrich">Enriquecer com IA</button>
            <button class="btn btn-secondary" onclick="showPricingForm(${productId})">Calcular Preço</button>
            <button class="btn btn-secondary" onclick="showImageUpload(${productId})">Upload Imagens</button>
            <button class="btn btn-secondary" onclick="processBackground(${productId})" id="btn-process-bg">Tratar Fundo</button>
            <button class="btn btn-secondary" onclick="actionGenerate(${productId})">Gerar Anúncio</button>
            <button class="btn btn-secondary" onclick="actionValidate(${productId})">Validar</button>
            <button class="btn btn-primary" onclick="actionPublish(${productId})">Publicar no ML</button>
          </div>
        </div>

        <!-- Info -->
        <div class="section">
          <div class="card">
            <h2 class="section-header">Dados do Produto</h2>
            <div class="detail-grid">
              <div class="detail-field">
                <span class="detail-label">Nome da Peça</span>
                <span class="detail-value">${product.part_name || '—'}</span>
              </div>
              <div class="detail-field">
                <span class="detail-label">Marca</span>
                <span class="detail-value">${product.brand || '—'}</span>
              </div>
              <div class="detail-field">
                <span class="detail-label">Categoria</span>
                <span class="detail-value">${product.category || '—'}</span>
              </div>
              <div class="detail-field">
                <span class="detail-label">Confiança</span>
                <span class="detail-value">${product.confidence_level != null ? product.confidence_level + '%' : '—'}</span>
              </div>
              <div class="detail-field">
                <span class="detail-label">Fonte</span>
                <span class="detail-value">${product.source_data === 'kb+ai' ? '<span class="badge badge-success">KB + IA</span>' : product.source_data === 'ai_only' ? '<span class="badge badge-info">IA</span>' : product.source_data === 'mock_provider' ? '<span class="badge badge-neutral">Mock</span>' : '—'}</span>
              </div>
              <div class="detail-field" style="grid-column:1/-1">
                <span class="detail-label">Descrição Técnica</span>
                <span class="detail-value">${product.technical_description || '—'}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Compatibilities -->
        ${product.compatibilities.length > 0 ? `
        <div class="section">
          <div class="card">
            <h2 class="section-header">Compatibilidades</h2>
            <div class="table-wrap" style="border:none">
              <table>
                <thead><tr><th>Marca</th><th>Modelo</th><th>Anos</th><th>Notas</th></tr></thead>
                <tbody>
                  ${product.compatibilities.map(c => `
                    <tr style="cursor:default">
                      <td>${c.motorcycle_brand}</td>
                      <td>${c.motorcycle_model}</td>
                      <td>${c.year_start}–${c.year_end}</td>
                      <td>${c.notes || '—'}</td>
                    </tr>
                  `).join('')}
                </tbody>
              </table>
            </div>
          </div>
        </div>` : ''}

        <!-- Attributes -->
        ${product.attributes.length > 0 ? `
        <div class="section">
          <div class="card">
            <h2 class="section-header">Atributos</h2>
            <div class="detail-grid">
              ${product.attributes.map(a => `
                <div class="detail-field">
                  <span class="detail-label">${a.name}</span>
                  <span class="detail-value">${a.value}</span>
                </div>
              `).join('')}
            </div>
          </div>
        </div>` : ''}

        <!-- Action Results Area -->
        <div id="action-area"></div>
      </div>
    `;
  } catch (err) {
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${err.message}</p></div>`;
  }
}

// --- Product Actions ---
async function actionAIEnrich(id) {
  const btn = document.getElementById('btn-ai-enrich');
  if (btn) { btn.disabled = true; btn.textContent = 'Enriquecendo...'; }

  try {
    const result = await api(`/products/${id}/ai-enrich`, { method: 'POST' });
    toast(`${result.provider} [${result.model}]: ${result.common_name} (${result.confidence}% confiança)`, 'success');
    navigate('product-detail', id);
  } catch (err) {
    toast(err.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = 'Enriquecer com IA'; }
  }
}

async function actionEnrich(id) {
  try {
    await api(`/products/${id}/mock-enrich`, { method: 'POST' });
    toast('Produto enriquecido com sucesso', 'success');
    navigate('product-detail', id);
  } catch (err) { toast(err.message, 'error'); }
}

async function actionGenerate(id) {
  try {
    const listing = await api(`/products/${id}/listing/generate`, { method: 'POST' });
    toast(`Anúncio gerado — Categoria: ${listing.ml_category || 'não definida'}`, 'success');
    navigate('product-detail', id);
  } catch (err) { toast(err.message, 'error'); }
}

async function actionValidate(id) {
  try {
    const result = await api(`/products/${id}/listing/validate`, { method: 'POST' });
    if (result.valid) {
      toast('Anúncio validado — pronto para publicar', 'success');
    } else {
      toast(`Validação falhou: ${result.errors.join(', ')}`, 'error');
    }
  } catch (err) { toast(err.message, 'error'); }
}

async function actionPublish(id) {
  try {
    const result = await api(`/products/${id}/listing/publish`, { method: 'POST' });
    toast(`Publicado no ML! ID: ${result.ml_item_id}`, 'success');
    if (result.permalink) {
      const area = document.getElementById('action-area');
      area.innerHTML = `
        <div class="card" style="border-color:var(--success)">
          <h2 class="section-header">Publicado com Sucesso</h2>
          <p>ML Item ID: <span class="mono">${result.ml_item_id}</span></p>
          ${result.permalink ? `<a href="${result.permalink}" target="_blank" class="btn btn-primary mt-4">Ver no Mercado Livre &rarr;</a>` : ''}
        </div>
      `;
    }
  } catch (err) { toast(err.message, 'error'); }
}

async function showPricingForm(id) {
  const area = document.getElementById('action-area');
  area.innerHTML = `<div class="card section"><p>Carregando dados de preço...</p></div>`;

  let info = { cost: 0, estimated_shipping: 0, commission_percent: 0.16, fixed_fee: 0, margin_percent: 0.20, honda_price: null };
  try {
    info = await api(`/products/${id}/pricing/info`);
  } catch (e) { /* usa defaults */ }

  const costValue = info.honda_price || info.cost || 0;
  const hondaBadge = info.honda_price
    ? `<div style="background:var(--info-subtle);padding:var(--space-3);border-radius:var(--radius-md);margin-bottom:var(--space-4)">
        <strong>Preço Honda (catálogo):</strong> R$ ${parseFloat(info.honda_price).toFixed(2)}
        <span style="color:var(--text-tertiary);margin-left:8px">— preenchido automaticamente no custo</span>
      </div>`
    : '';

  const existingPrice = info.suggested_price
    ? `<div style="background:var(--success-subtle);padding:var(--space-3);border-radius:var(--radius-md);margin-bottom:var(--space-4)">
        <strong>Preço atual:</strong> R$ ${parseFloat(info.suggested_price).toFixed(2)}
        ${info.final_price ? ` | <strong>Final:</strong> R$ ${parseFloat(info.final_price).toFixed(2)}` : ''}
      </div>`
    : '';

  area.innerHTML = `
    <div class="card section">
      <h2 class="section-header">Calcular Preço</h2>
      ${hondaBadge}${existingPrice}
      <div class="detail-grid">
        <div class="form-group">
          <label class="form-label">Custo (R$)</label>
          <input type="number" step="0.01" id="price-cost" class="form-input" placeholder="0.00" value="${costValue}">
        </div>
        <div class="form-group">
          <label class="form-label">Frete Estimado (R$)</label>
          <input type="number" step="0.01" id="price-shipping" class="form-input" placeholder="0.00" value="${info.estimated_shipping}">
        </div>
        <div class="form-group">
          <label class="form-label">Comissão ML (%)</label>
          <input type="number" step="0.01" id="price-commission" class="form-input" placeholder="0.16" value="${info.commission_percent}">
        </div>
        <div class="form-group">
          <label class="form-label">Taxa Fixa (R$)</label>
          <input type="number" step="0.01" id="price-fee" class="form-input" placeholder="0.00" value="${info.fixed_fee}">
        </div>
        <div class="form-group">
          <label class="form-label">Margem (%)</label>
          <input type="number" step="0.01" id="price-margin" class="form-input" placeholder="0.20" value="${info.margin_percent}">
        </div>
      </div>
      <div class="mt-4">
        <button class="btn btn-primary" onclick="submitPricing(${id})">Calcular</button>
      </div>
      <div id="pricing-result" class="mt-4"></div>
    </div>
  `;
}

async function submitPricing(id) {
  const body = {
    cost: parseFloat(document.getElementById('price-cost').value),
    estimated_shipping: parseFloat(document.getElementById('price-shipping').value),
    commission_percent: parseFloat(document.getElementById('price-commission').value),
    fixed_fee: parseFloat(document.getElementById('price-fee').value),
    margin_percent: parseFloat(document.getElementById('price-margin').value),
  };
  try {
    const result = await apiPost(`/products/${id}/pricing/calculate`, body);
    document.getElementById('pricing-result').innerHTML = `
      <div style="background:var(--success-subtle);padding:var(--space-4);border-radius:var(--radius-md)">
        <strong style="font-size:20px">R$ ${parseFloat(result.suggested_price).toFixed(2)}</strong>
        <span style="color:var(--text-tertiary);margin-left:8px">preço sugerido</span>
      </div>
    `;
    toast('Preço calculado com sucesso', 'success');
  } catch (err) { toast(err.message, 'error'); }
}

function showImageUpload(id) {
  const area = document.getElementById('action-area');
  area.innerHTML = `
    <div class="card section">
      <h2 class="section-header">Upload de Imagens</h2>
      <div class="upload-zone" id="img-zone" onclick="document.getElementById('img-input').click()">
        <div class="upload-icon">&#128247;</div>
        <p><strong>Selecione várias imagens</strong> do produto</p>
        <p style="font-size:11px;margin-top:4px">JPG, PNG — max 10MB cada — até 10 imagens por vez</p>
      </div>
      <input type="file" id="img-input" accept="image/*" multiple style="display:none" onchange="previewImages(${id}, this)">
      <div id="img-preview" class="mt-4"></div>
      <div id="img-result" class="mt-4"></div>
    </div>
  `;

  // Drag & drop
  const zone = document.getElementById('img-zone');
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragover'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
      document.getElementById('img-input').files = e.dataTransfer.files;
      previewImages(id, document.getElementById('img-input'));
    }
  });
}

function previewImages(id, input) {
  const files = input.files;
  if (!files.length) return;

  const preview = document.getElementById('img-preview');
  preview.innerHTML = `
    <div style="margin-bottom:var(--space-3);color:var(--text-secondary);font-size:13px">
      <strong>${files.length} imagem(ns)</strong> selecionada(s)
    </div>
    <div class="image-grid">
      ${Array.from(files).map((f, i) => `
        <div class="image-thumb" id="thumb-${i}">
          <span>${f.name.substring(0, 12)}...</span>
        </div>
      `).join('')}
    </div>
    <button class="btn btn-primary mt-4" onclick="submitImages(${id})">Enviar ${files.length} imagem(ns)</button>
  `;

  // Render thumbnails
  Array.from(files).forEach((f, i) => {
    const reader = new FileReader();
    reader.onload = e => {
      const thumb = document.getElementById(`thumb-${i}`);
      if (thumb) thumb.innerHTML = `<img src="${e.target.result}" alt="${f.name}">`;
    };
    reader.readAsDataURL(f);
  });
}

async function submitImages(id) {
  const input = document.getElementById('img-input');
  const files = input.files;
  if (!files.length) return;

  document.getElementById('img-result').innerHTML = '<div class="flex items-center gap-2"><div class="spinner"></div> Enviando ' + files.length + ' imagem(ns)...</div>';

  const form = new FormData();
  for (const f of files) form.append('files', f);

  try {
    const result = await api(`/products/${id}/images/upload`, { method: 'POST', body: form, headers: {} });
    document.getElementById('img-preview').innerHTML = '';
    document.getElementById('img-result').innerHTML = `
      <div style="background:var(--success-subtle);padding:var(--space-4);border-radius:var(--radius-md)">
        <strong>${result.files.length} imagem(ns) salva(s) com sucesso</strong>
      </div>
    `;
    toast(`${result.files.length} imagens enviadas`, 'success');
  } catch (err) {
    document.getElementById('img-result').innerHTML = `<div style="color:var(--error)">${err.message}</div>`;
    toast(err.message, 'error');
  }
}

async function processBackground(id) {
  const btn = document.getElementById('btn-process-bg');
  const oldText = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="width:14px;height:14px"></span> Processando...';

  const area = document.getElementById('action-area');
  area.innerHTML = `
    <div class="card section">
      <h2 class="section-header">Tratamento de Fundo</h2>
      <div class="flex items-center gap-2">
        <div class="spinner"></div>
        <span>Removendo fundo e aplicando fundo branco nas imagens... Isso pode levar alguns segundos.</span>
      </div>
    </div>
  `;

  try {
    const result = await api(`/products/${id}/images/process-background`, { method: 'POST' });
    area.innerHTML = `
      <div class="card section">
        <h2 class="section-header">Tratamento de Fundo</h2>
        <div style="background:var(--success-subtle);padding:var(--space-4);border-radius:var(--radius-md)">
          <strong>${result.message}</strong>
          ${result.errors.length ? `<div style="color:var(--error);margin-top:8px">Erros: ${result.errors.map(e => e.file).join(', ')}</div>` : ''}
        </div>
        <div style="margin-top:var(--space-4);font-size:13px;color:var(--text-secondary)">
          As imagens processadas serao usadas automaticamente na publicacao do anuncio.
        </div>
      </div>
    `;
    toast(result.message, 'success');
  } catch (err) {
    area.innerHTML = `
      <div class="card section">
        <h2 class="section-header">Tratamento de Fundo</h2>
        <div style="color:var(--error)">${err.message}</div>
      </div>
    `;
    toast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
}

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
                  <span style="font-weight:600;font-size:14px">${p.name}</span>
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
                    <td>${d.filename}</td>
                    <td>${d.brand}</td>
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
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${err.message}</p></div>`;
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
        <strong>${data.filename}</strong> enviado com sucesso<br>
        <span style="color:var(--text-secondary)">Status: ${data.status} — O processamento está sendo feito em background.</span>
        <div class="mt-4">
          <button class="btn btn-secondary btn-sm" onclick="navigate('kb')">Atualizar</button>
        </div>
      </div>
    `;
    toast('Catálogo enviado! Processamento em background.', 'success');
  } catch (err) {
    result.innerHTML = `<div class="card" style="border-color:var(--error);color:var(--error)">${err.message}</div>`;
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
          <strong>OEM ${result.oem_code}</strong> não encontrado na base de conhecimento.
          <p style="color:var(--text-tertiary);font-size:12px;margin-top:var(--space-2)">A IA ainda pode enriquecer este produto usando conhecimento geral.</p>
        </div>
      `;
    } else {
      resultEl.innerHTML = `
        <div class="card" style="border-color:var(--success)">
          <strong>${result.entries.length} entrada(s)</strong> encontrada(s) para <span class="mono">${result.oem_code}</span>
          ${result.entries.map(e => `
            <div style="margin-top:var(--space-3);padding:var(--space-3);background:var(--bg-elevated);border-radius:var(--radius-sm)">
              <div><strong>Descrição Honda:</strong> ${e.honda_part_name || '—'}</div>
              <div><strong>Preço Honda:</strong> ${e.honda_price ? 'R$ ' + parseFloat(e.honda_price).toFixed(2) : '—'}</div>
              <div><strong>Página:</strong> ${e.page_number || '—'}</div>
            </div>
          `).join('')}
        </div>
      `;
    }
  } catch (err) {
    resultEl.innerHTML = `<div style="color:var(--error)">${err.message}</div>`;
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
    resultEl.innerHTML = `<div style="color:var(--error)">${err.message}</div>`;
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
    el.innerHTML = `<div class="empty-state"><h3>Erro</h3><p>${err.message}</p></div>`;
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
    result.innerHTML = `<div style="color:var(--error);font-size:13px;margin-top:var(--space-2)">${err.message}</div>`;
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
    document.getElementById('auth-error').innerHTML = `<div style="color:var(--error)">${err.message}</div>`;
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
    document.getElementById('auth-error').innerHTML = `<div style="color:var(--error)">${err.message}</div>`;
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
