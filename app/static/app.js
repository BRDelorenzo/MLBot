/* ============================================
   MLBot SPA — Client
   ============================================ */

const API = '';

// --- State ---
let currentView = 'dashboard';
let products = [];
let batches = [];

// --- API helpers ---
async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Accept': 'application/json', ...(opts.headers || {}) },
    ...opts,
  });
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) {
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
    case 'auth': renderAuth(main); break;
    default: main.innerHTML = '<div class="empty-state"><h3>Página não encontrada</h3></div>';
  }
}

// --- Dashboard ---
async function renderDashboard(el) {
  el.innerHTML = '<div class="view"><div class="spinner"></div></div>';

  try {
    const [prods, batchList, authStatus] = await Promise.all([
      api('/products'),
      api('/batches'),
      api('/auth/ml/status'),
    ]);
    products = prods;
    batches = batchList;

    const total = products.length;
    const published = products.filter(p => p.source_data === 'mock_provider').length; // approximate
    const pending = total - published;

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
            <div class="stat-value">${pending}</div>
            <div class="stat-label">Em Processamento</div>
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
          <div class="flex gap-3" style="flex-wrap:wrap">
            <button class="btn btn-secondary" onclick="actionEnrich(${productId})">Enriquecer (Mock)</button>
            <button class="btn btn-secondary" onclick="showPricingForm(${productId})">Calcular Preço</button>
            <button class="btn btn-secondary" onclick="showImageUpload(${productId})">Upload Imagens</button>
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

function showPricingForm(id) {
  const area = document.getElementById('action-area');
  area.innerHTML = `
    <div class="card section">
      <h2 class="section-header">Calcular Preço</h2>
      <div class="detail-grid">
        <div class="form-group">
          <label class="form-label">Custo (R$)</label>
          <input type="number" step="0.01" id="price-cost" class="form-input" placeholder="0.00" value="50">
        </div>
        <div class="form-group">
          <label class="form-label">Frete Estimado (R$)</label>
          <input type="number" step="0.01" id="price-shipping" class="form-input" placeholder="0.00" value="15">
        </div>
        <div class="form-group">
          <label class="form-label">Comissão ML (%)</label>
          <input type="number" step="0.01" id="price-commission" class="form-input" placeholder="0.16" value="0.16">
        </div>
        <div class="form-group">
          <label class="form-label">Taxa Fixa (R$)</label>
          <input type="number" step="0.01" id="price-fee" class="form-input" placeholder="0.00" value="6">
        </div>
        <div class="form-group">
          <label class="form-label">Margem (%)</label>
          <input type="number" step="0.01" id="price-margin" class="form-input" placeholder="0.20" value="0.20">
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

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => navigate(btn.dataset.view));
  });
  navigate('dashboard');
  updateAuthStatus();
  setInterval(updateAuthStatus, 30000);
});
