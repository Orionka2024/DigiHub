const originalFetch = window.fetch;
window.fetch = async function(...args) {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.includes('/login.html')) {
        window.location.href = '/login.html';
    }
    return response;
};

/**
 * KVK iXBRL v2 – Workspace controller
 *
 * All API calls target the KVK_v2 FastAPI backend (/api/...).
 * The core design decisions:
 *  - Tagging is always deliberate: a Map Fact modal forces the user to specify
 *    qname, kind, context and reviewer before a fact is committed.
 *  - The FilingSnapshot state machine (draft → frozen → validated) is surfaced
 *    in the UI via the state pill.
 *  - Auto-tag suggestions require a reviewer-approved MappingDecision.
 */
'use strict';

window.workspace = {
  BASE_URL: '',

  // ── Mutable state ──────────────────────────────────────────────────────────
  state: {
    // Entity / taxonomy metadata
    kvkNumber: '',
    entityName: '',
    periodStart: '2024-01-01',
    periodEnd: '2024-12-31',
    taxonomyId: 'NT21_KVK_20261209_b',
    entryPointKey: '',

    // Server-assigned filing ID
    filingId: null,
    filingState: 'draft',   // draft | reviewed | frozen | validated

    // Document extraction result (ExtractedDocumentOut)
    document: null,   // { sha256, nodes, headers, footers, warnings }

    // Mapping ledger: nodeId → { factId, qname, kind, value, contextId, reviewer }
    mappings: {},

    // Node currently selected in the inspector
    activeNodeId: null,

    // Taxonomy requirements
    taxonomyRequirements: [],
    _contextMenuNodeId: null,

    // Cache of contexts registered for this filing
    contexts: {
      ctx_current:     { id: 'ctx_current',     type: 'duration' },
      ctx_prior:       { id: 'ctx_prior',        type: 'duration' },
      ctx_instant_prior: { id: 'ctx_instant_prior', type: 'instant' },
      ctx_instant_end: { id: 'ctx_instant_end',  type: 'instant'  },
    },
  },

  // ── User role ──────────────────────────────────────────────────────────────
  currentUser: { id: 'preparer', name: 'Jane (Preparer)', role: 'preparer' },

  // ── Initialisation ─────────────────────────────────────────────────────────
  async init() {
    this.refreshTaxonomyList();
    fetch(`${this.BASE_URL}/health`).then(r=>r.json()).then(health=>{
      const notice = document.getElementById('readinessNotice');
      if (notice) {
        if (!health.export_ready) {
          let text = 'Preparation only: export requires a verified taxonomy and independent filing validation.';
          if (health.errors && health.errors.length > 0) {
            text += ` (${health.errors.length} taxonomy loader error(s) detected)`;
          } else if (health.warning) {
            text += ` (${health.warning})`;
          }
          notice.textContent = text;
          notice.style.display = 'block';
        } else {
          notice.textContent = '';
          notice.style.display = 'none';
        }
      }
    }).catch(()=>{});
    // Open Entity modal on first load if no entity is set
    if (!this.state.kvkNumber) {
      this.openEntityModal();
    }

    // Attach global event listeners for new UX features
    this._attachDocumentEventListeners();
  },

  _attachDocumentEventListeners() {
    const viewer = document.getElementById('documentViewer');
    const ctxMenu = document.getElementById('contextMenu');
    const tooltip = document.getElementById('hoverTooltip');
    
    // Hide context menu on global click
    document.addEventListener('click', (e) => {
      if (!ctxMenu.contains(e.target)) {
        ctxMenu.style.display = 'none';
      }
    });

    // Delegated Context Menu
    viewer.addEventListener('contextmenu', (e) => {
      // Find the closest node element
      const nodeEl = e.target.closest('[id^="node-"]');
      if (nodeEl) {
        e.preventDefault();
        const nodeId = nodeEl.id.replace('node-', '');
        this.state._contextMenuNodeId = nodeId;
        
        ctxMenu.style.display = 'block';
        // Basic bounds checking
        let x = e.clientX;
        let y = e.clientY;
        if (x + ctxMenu.offsetWidth > window.innerWidth) x -= ctxMenu.offsetWidth;
        if (y + ctxMenu.offsetHeight > window.innerHeight) y -= ctxMenu.offsetHeight;
        
        ctxMenu.style.left = x + 'px';
        ctxMenu.style.top = y + 'px';
      }
    });

    // Delegated Hover Tooltip
    viewer.addEventListener('mouseover', (e) => {
      const nodeEl = e.target.closest('.mapped');
      if (nodeEl && nodeEl.id && nodeEl.id.startsWith('node-')) {
        const nodeId = nodeEl.id.replace('node-', '');
        const mapping = this.state.mappings[nodeId];
        if (mapping) {
          tooltip.innerHTML = `
            <div class="tt-row"><strong>QName:</strong> ${this._esc(mapping.qname)}</div>
            <div class="tt-row"><strong>Context:</strong> ${this._esc(mapping.contextId)}</div>
            <div class="tt-row"><strong>Value:</strong> ${mapping.value !== null ? this._esc(String(mapping.value)) : '—'}</div>
            <div class="tt-row"><strong>Reviewer:</strong> ${this._esc(mapping.reviewer)}</div>
          `;
          tooltip.style.display = 'block';
        }
      }
    });

    viewer.addEventListener('mousemove', (e) => {
      if (tooltip.style.display === 'block') {
        tooltip.style.left = (e.clientX + 15) + 'px';
        tooltip.style.top = (e.clientY + 15) + 'px';
      }
    });

    viewer.addEventListener('mouseout', (e) => {
      const nodeEl = e.target.closest('.mapped');
      if (nodeEl) {
        tooltip.style.display = 'none';
      }
    });
  },

  // Populate taxonomy selector from backend
  async refreshTaxonomyList() {
    try {
      const res = await fetch(`${this.BASE_URL}/api/taxonomy/list`);
      if (!res.ok) return;
      const data = await res.json();
      const sel = document.getElementById('taxonomyIdInput');
      if (!sel) return;
      sel.innerHTML = data.taxonomies
        .map(t => `<option value="${this._esc(t)}" ${t === this.state.taxonomyId ? 'selected' : ''}>${this._esc(t)}</option>`)
        .join('');
        
      if (data.taxonomies.length > 0) {
        if (!data.taxonomies.includes(this.state.taxonomyId)) {
          this.state.taxonomyId = data.taxonomies[0];
        }
        await this.handleTaxonomyChange();
      }
    } catch (_) { /* backend may not be running yet */ }
  },
  
  async handleTaxonomyChange() {
    const sel = document.getElementById('taxonomyIdInput');
    if (!sel) return;
    if (this.state.filingId && sel.value !== this.state.taxonomyId) {
      sel.value = this.state.taxonomyId;
      this.setNavStatus('Start a new filing to change its taxonomy.', 'error');
      return;
    }
    this.state.taxonomyId = sel.value;
    
    try {
      const res = await fetch(`${this.BASE_URL}/api/taxonomy/${this.state.taxonomyId}/entry-points`);
      if (!res.ok) return;
      const data = await res.json();
      
      const epSel = document.getElementById('entryPointInput');
      if (!epSel) return;
      
      const eps = data.entry_points || {};
      this.state.entryPointMetadata = data.metadata || {};
      epSel.innerHTML = '<option value="">Choose the applicable reporting profile…</option>' + Object.keys(eps)
        .map(k => `<option value="${this._esc(k)}" ${k === this.state.entryPointKey ? 'selected' : ''}>${this._esc(data.metadata?.[k]?.name || k)}</option>`)
        .join('');
        
      if (Object.keys(eps).length > 0 && !Object.keys(eps).includes(this.state.entryPointKey)) {
        this.state.entryPointKey = '';
        this.state.checklistSections = [];
        this.renderChecklist();
        epSel.value = this.state.entryPointKey;
      }
      await this.fetchRequirements();
    } catch (e) {
      console.warn("Failed to fetch entry points", e);
    }
  },

  async handleEntryPointChange() {
    const epSel = document.getElementById('entryPointInput');
    if (!epSel) return;
    if (this.state.filingId && epSel.value !== this.state.entryPointKey) {
      epSel.value = this.state.entryPointKey;
      this.setNavStatus('Start a new filing to change its entry point.', 'error');
      return;
    }
    this.state.entryPointKey = epSel.value;
    await this.fetchRequirements();
  },

  // ── User role ──────────────────────────────────────────────────────────────
  handleUserChange() {
    const sel = document.getElementById('userSelector');
    this.currentUser = {
      id: sel.value,
      name: sel.options[sel.selectedIndex].text,
      role: sel.value,
    };
    // Pre-fill reviewer field in Map Fact modal
    const rev = document.getElementById('mapReviewer');
    if (rev) rev.value = this.currentUser.name;
    this.renderInspector();
    this.setNavStatus(`Switched to ${this.currentUser.name}`);
  },

  // ── Nav status ─────────────────────────────────────────────────────────────
  setNavStatus(msg, type = 'ready') {
    const el = document.getElementById('navStatus');
    if (!el) return;
    el.innerText = msg;
    el.style.color = type === 'error' ? '#ef4444' : type === 'loading' ? '#d97706' : '#4b5563';
    el.style.background = type === 'error' ? 'rgba(220,38,38,.08)' : type === 'loading' ? 'rgba(217,119,6,.1)' : '#f3f4f6';
  },

  // ── State pill ─────────────────────────────────────────────────────────────
  updateStatePill(state) {
    this.state.filingState = state;
    const pill = document.getElementById('statePill');
    if (!pill) return;
    const labels = { draft: 'Draft', reviewed: 'Reviewed', frozen: 'Frozen', validated: 'Validated' };
    pill.className = `state-pill ${state}`;
    pill.textContent = labels[state] || state;

    // Button availability
    const isFrozen    = state === 'frozen' || state === 'validated';
    const isValidated = state === 'validated';
    const canEdit     = !isFrozen;

    if (document.getElementById('btnFreeze'))
      document.getElementById('btnFreeze').disabled = isFrozen || !this.state.filingId;
    if (document.getElementById('btnExport'))
      document.getElementById('btnExport').disabled = !isFrozen;
    if (document.getElementById('btnReopen')) document.getElementById('btnReopen').disabled = !isFrozen;
  },

  // ── Readiness Modal ────────────────────────────────────────────────────────

  async showReadiness() {
    const modal = document.getElementById('readinessModal');
    const content = document.getElementById('readinessContent');
    if (!modal || !content) return;
    
    modal.style.display = 'flex';
    content.innerHTML = '<div class="loading-pulse" style="text-align: center; color: #6b7280;">Fetching status…</div>';
    
    try {
      const res = await fetch(`${this.BASE_URL}/api/submission/readiness`);
      if (!res.ok) throw new Error('Failed to load readiness status');
      const data = await res.json();
      
      const renderStatus = (val, textTrue='Active', textFalse='Inactive') => {
        const color = val ? 'var(--accent-green)' : 'var(--accent-red)';
        const text = val ? textTrue : textFalse;
        return `<span style="color:${color}; font-weight:600;">${text}</span>`;
      };

      let html = `
        <div style="margin-bottom: 1.5rem;">
          <h3 style="margin: 0 0 0.5rem 0; font-size: 1.05rem;">Production Status</h3>
          <p style="margin:0;">Production Enabled: ${renderStatus(data.production_enabled)}</p>
          <p style="margin:4px 0 0 0; color:#6b7280; font-size:0.85rem;">Policy: ${this._esc(data.release_policy)}</p>
        </div>

        <div style="margin-bottom: 1.5rem;">
          <h3 style="margin: 0 0 0.5rem 0; font-size: 1.05rem;">Provider Handoff</h3>
          <table style="width:100%; border-collapse: collapse; font-size:0.9rem;">
            <tr><td style="padding: 4px 0; width: 40%; color:#4b5563;">Provider Name:</td><td style="padding: 4px 0;"><strong>${this._esc(data.provider.name || 'None')}</strong></td></tr>
            <tr><td style="padding: 4px 0; color:#4b5563;">Mode:</td><td style="padding: 4px 0;">${this._esc(data.provider.mode)}</td></tr>
            <tr><td style="padding: 4px 0; color:#4b5563;">API Connected:</td><td style="padding: 4px 0;">${renderStatus(data.provider.api_connected, 'Connected', 'Disconnected')}</td></tr>
          </table>
        </div>

        <div style="margin-bottom: 1.5rem;">
          <h3 style="margin: 0 0 0.5rem 0; font-size: 1.05rem;">Direct Submission (WUS)</h3>
          <table style="width:100%; border-collapse: collapse; font-size:0.9rem; margin-bottom: 0.5rem;">
            <tr><td style="padding: 4px 0; width: 40%; color:#4b5563;">Protocol:</td><td style="padding: 4px 0;">${this._esc(data.direct.protocol)}</td></tr>
            <tr><td style="padding: 4px 0; color:#4b5563;">Environment:</td><td style="padding: 4px 0;">${this._esc(data.direct.environment)}</td></tr>
            <tr><td style="padding: 4px 0; color:#4b5563;">Connected:</td><td style="padding: 4px 0;">${renderStatus(data.direct.connected, 'Connected', 'Disconnected')}</td></tr>
          </table>
          <div style="font-weight: 600; font-size: 0.85rem; color:#4b5563; margin-top: 0.5rem;">Prerequisites for connection:</div>
          <ul style="margin: 4px 0 0 0; padding-left: 20px; font-size: 0.85rem; color: #374151;">
            ${data.direct.required.map(req => `<li>${this._esc(req)}</li>`).join('')}
          </ul>
        </div>

        <div>
          <h3 style="margin: 0 0 0.5rem 0; font-size: 1.05rem;">Independent Validator</h3>
          <table style="width:100%; border-collapse: collapse; font-size:0.9rem;">
            <tr><td style="padding: 4px 0; width: 40%; color:#4b5563;">Installed:</td><td style="padding: 4px 0;">${renderStatus(data.validator.installed, 'Yes', 'No')}</td></tr>
            ${data.validator.installed ? `
              <tr><td style="padding: 4px 0; color:#4b5563;">Version:</td><td style="padding: 4px 0;">${this._esc(data.validator.version)}</td></tr>
              <tr><td style="padding: 4px 0; color:#4b5563;">Approval Authority:</td><td style="padding: 4px 0;">${renderStatus(data.validator.filing_approval, 'Authorized', 'Diagnostic Only')}</td></tr>
              <tr><td style="padding: 4px 0; color:#4b5563; vertical-align:top;">Supported Profiles:</td><td style="padding: 4px 0;">${data.validator.profiles.map(p=>this._esc(p)).join(', ')}</td></tr>
            ` : ''}
          </table>
        </div>
      `;
      content.innerHTML = html;
    } catch (e) {
      content.innerHTML = `<div style="color:var(--accent-red); padding:1rem;">Error loading readiness data: ${this._esc(e.message)}</div>`;
    }
  },

  // ── Entity modal ───────────────────────────────────────────────────────────
  openEntityModal() {
    document.getElementById('entityModal').style.display = 'flex';
    // Fill current values
    document.getElementById('kvkInput').value       = this.state.kvkNumber;
    document.getElementById('entityNameInput').value = this.state.entityName;
    document.getElementById('periodStartInput').value = this.state.periodStart;
    document.getElementById('periodEndInput').value   = this.state.periodEnd;
    document.getElementById('taxonomyIdInput').value  = this.state.taxonomyId;
    document.getElementById('entryPointInput').value  = this.state.entryPointKey;
  },

  closeEntityModal() {
    document.getElementById('entityModal').style.display = 'none';
  },

  async lookupKvk() {
    const kvk = document.getElementById('kvkInput').value.trim();
    if (!kvk) return;
    this.setNavStatus('Looking up KVK…', 'loading');
    try {
      const res = await fetch(`${this.BASE_URL}/api/kvk-lookup/${kvk}`);
      if (!res.ok) throw new Error('Lookup failed');
      const data = await res.json();
      if (data.found && data.entity_name) {
        document.getElementById('entityNameInput').value = data.entity_name;
        this.setNavStatus(`Found: ${data.entity_name}`);
      } else {
        this.setNavStatus(data.error || 'KVK number not found', 'error');
      }
    } catch (e) {
      this.setNavStatus('Lookup failed', 'error');
    }
  },

  async saveEntityModal() {
    if (!document.getElementById('entryPointInput').value) { alert('Choose the company size and reporting profile first.'); return; }
    if (this.state.filingId) {
      const fields = [['kvkInput','kvkNumber'],['entityNameInput','entityName'],['periodStartInput','periodStart'],['periodEndInput','periodEnd'],['taxonomyIdInput','taxonomyId'],['entryPointInput','entryPointKey']];
      if (fields.some(([id,key]) => document.getElementById(id).value.trim() !== this.state[key])) {
        alert('Entity, period and taxonomy are bound to this filing. Start a new filing to use different settings.');
        return;
      }
    }
    this.state.kvkNumber    = document.getElementById('kvkInput').value.trim();
    this.state.entityName   = document.getElementById('entityNameInput').value.trim();
    this.state.periodStart  = document.getElementById('periodStartInput').value;
    this.state.periodEnd    = document.getElementById('periodEndInput').value;
    this.state.taxonomyId   = document.getElementById('taxonomyIdInput').value;
    this.state.entryPointKey = document.getElementById('entryPointInput').value;

    document.getElementById('entityStatusLabel').innerText =
      `${this.state.kvkNumber} · ${this.state.entityName}`;
    this.closeEntityModal();

    if (this.state.document && !this.state.filingId) {
      await this.createSnapshot();
    }
    
    // Fetch requirements for the checklist
    await this.fetchRequirements();
    
    this.setNavStatus('Entity saved');
  },

  async fetchRequirements() {
    if (!this.state.taxonomyId || !this.state.entryPointKey) {
      this.state.checklistSections = [];
      this.renderChecklist();
      return;
    }
    try {
      let url = `${this.BASE_URL}/api/taxonomy/${this.state.taxonomyId}/checklist?entry_point_key=${this.state.entryPointKey}`;
      if (this.state.filingId) {
        url += `&filing_id=${this.state.filingId}`;
      }
      const res = await fetch(url);
      if (res.status === 503) {
        const key = this.state.taxonomyId + ':' + this.state.entryPointKey;
        clearTimeout(this._checklistRetry);
        this._checklistRetry = setTimeout(() => {
          if (key === this.state.taxonomyId + ':' + this.state.entryPointKey) this.fetchRequirements();
        }, 5000);
        this.setNavStatus('Taxonomy checklist is loading. You can continue reviewing the source.', 'loading');
        return;
      }
      if (!res.ok) throw new Error('Taxonomy checklist is unavailable.');
      this.state.checklistSections = await res.json();
      const options = document.getElementById('tagConceptOptions');
      if (options) options.innerHTML = this.state.checklistSections.flatMap(s => s.items)
        .map(item => `<option value="${this._esc(item.concept_qname)}">${this._esc(item.label_en || item.label_nl)}</option>`).join('');
      this.renderChecklist();
    } catch (e) {
      this.setNavStatus(e.message, 'error');
    }
  },

  // ── Snapshot creation ──────────────────────────────────────────────────────
  async createSnapshot() {
    if (!this.state.kvkNumber || !this.state.document) return;
    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/create`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          entity_name:     this.state.entityName,
          kvk_number:      this.state.kvkNumber,
          period_start:    this.state.periodStart,
          period_end:      this.state.periodEnd,
          taxonomy_id:     this.state.taxonomyId,
          entry_point_key: this.state.entryPointKey,
          document_sha256: this.state.document.sha256,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Snapshot creation failed');
      }
      const snap = await res.json();
      this.state.filingId = snap.filing_id;
      this.updateStatePill(snap.state);
      this.setNavStatus('Snapshot created');
      this._enablePostDocButtons();
      // Register default contexts for this filing
      await this._registerDefaultContexts();
    } catch (e) {
      this.setNavStatus(`Snapshot error: ${e.message}`, 'error');
    }
  },

  // Register the three standard contexts against the new snapshot
  async _registerDefaultContexts() {
    // We register them lazily when a fact is mapped that uses them,
    // but we pre-declare them here in the local state for the selector.
    // The backend creates them on-the-fly via the `context` field in MapFactIn.
    // Nothing to call here – they will be sent with the first fact.
  },

  // ── DOCX upload & extraction ───────────────────────────────────────────────
  async handleFileUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    this.setNavStatus('Extracting DOCX…', 'loading');
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${this.BASE_URL}/api/extract`, { method: 'POST', body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Extraction failed');
      }
      const doc = await res.json();
      if (this.state.filingId) {
        const current = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}`);
        if (!current.ok) throw new Error('Cannot retrieve the active filing.');
        const snap = await current.json();
        if (doc.sha256 !== snap.document_sha256) {
          throw new Error('This source differs from the active filing. Start a separate filing for a different document.');
        }
        this._restoreSnapshot({...snap, document: doc});
        this.renderWorkspace();
        this.setNavStatus('Source reattached to the existing filing.');
        return;
      }
      this.state.document = doc;
      this.state.mappings = {};
      this.state.activeNodeId = null;

      this.renderWorkspace();
      this.setNavStatus(`Document loaded — ${doc.nodes.length} nodes, sha256: ${doc.sha256.substring(0, 12)}…`);

      if (doc.warnings.length) {
        console.warn('[KVK_v2] Extraction warnings:', doc.warnings);
      }

      // Create snapshot if entity is already set
      if (this.state.kvkNumber) {
        await this.createSnapshot();
      } else {
        this.openEntityModal();
      }
    } catch (e) {
      this.setNavStatus(`Extraction failed: ${e.message}`, 'error');
    }
    // Reset file input so the same file can be re-uploaded
    event.target.value = '';
  },

  _enablePostDocButtons() {
    ['btnSaveSession', 'btnLogBook', 'btnDiagnostics']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.disabled = !this.state.filingId;
      });
    this.updateStatePill(this.state.filingState);
  },

  // ── Rendering ──────────────────────────────────────────────────────────────
  renderWorkspace() {
    this.renderDocumentMap();
    this.renderDocumentViewer();
    this.renderInspector();
    this.renderChecklist();
    this._updateTagCount();
  },

  renderDocumentMap() {
    const container = document.getElementById('documentMap');
    if (!this.state.document) { container.innerHTML = '<div class="empty-state">No document loaded.</div>'; return; }

    let html = '';
    for (const node of this.state.document.nodes) {
      const isMapped = !!this.state.mappings[node.id];
      const mappedDot = isMapped ? '🟢 ' : '';
      if (node.kind === 'paragraph') {
        // Only show paragraphs with a style that looks like a heading
        const isHeading = node.style && /heading|titel|kop/i.test(node.style);
        if (isHeading || (node.style && node.style.includes('1'))) {
          html += `<a class="nav-item heading ${isMapped ? 'mapped' : ''}" onclick="workspace.scrollToNode('node-${node.id}')">${mappedDot}${this._esc(node.text.slice(0, 60))}</a>`;
        }
      } else if (node.kind === 'table') {
        html += `<a class="nav-item table ${isMapped ? 'mapped' : ''}" onclick="workspace.scrollToNode('node-${node.id}')">${mappedDot}Table: ${node.location}</a>`;
      }
    }
    container.innerHTML = html || '<div class="empty-state">No navigable headings found.</div>';
  },

  scrollToNode(id) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  },

  renderDocumentViewer() {
    const container = document.getElementById('documentViewer');
    if (!this.state.document) return;

    let html = '';
    for (const node of this.state.document.nodes) {
      const isMapped = !!this.state.mappings[node.id];
      const isActive = this.state.activeNodeId === node.id;
      const clickAttr = `onclick="workspace.selectNode('${node.id}')" id="node-${node.id}"`;

      if (node.kind === 'paragraph') {
        const classes = ['para-node', isMapped ? 'mapped' : '', isActive ? 'active' : ''].filter(Boolean).join(' ');
        const badge = isMapped ? `<span class="chip green" style="font-size:0.62rem; float:right;">✓ ${this._esc(this.state.mappings[node.id].qname.split(':')[1] || this.state.mappings[node.id].qname)}</span>` : '';
        const style = node.style ? node.style.toLowerCase() : '';
        let tag = 'p';
        if (/heading 1|kop 1/.test(style)) tag = 'h2';
        else if (/heading 2|kop 2/.test(style)) tag = 'h3';
        else if (/heading 3|kop 3/.test(style)) tag = 'h4';

        html += `<${tag} class="${classes}" ${clickAttr}>${badge}${this._esc(node.text)}</${tag}>`;

      } else if (node.kind === 'table') {
        html += `<div id="node-${node.id}" style="margin-bottom:1.5rem; border: 1px solid var(--border-color); border-radius: 4px; overflow:hidden;">`;
        html += `<div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:0.5rem 1rem; border-bottom:1px solid var(--border-color);">
                   <strong style="font-size:0.85rem; color:#475569;">${node.location}</strong>
                   <button class="btn-secondary" style="font-size:0.75rem; padding:0.2rem 0.5rem;" onclick="workspace.autoTagTable('${node.id}')">Auto-Tag Table ⚡</button>
                 </div>`;
        html += '<table style="width:100%; border-collapse:collapse; font-size:0.85rem;">';
        for (let rIdx = 0; rIdx < node.rows.length; rIdx++) {
          const row = node.rows[rIdx];
          html += '<tr>';
          for (let cIdx = 0; cIdx < row.length; cIdx++) {
            const cell = row[cIdx];
            const isNum = /^-?[\d,.\s]+$/.test(cell.trim()) && cell.trim().length > 0;
            const align = isNum ? 'right' : 'left';
            
            // Sub-node ID for this specific cell
            const cellId = `${node.id}-r${rIdx}c${cIdx}`;
            const isCellActive = this.state.activeNodeId === cellId;
            const cellMapped = this.state.mappings[cellId];
            
            let bg = 'transparent';
            if (isCellActive) bg = 'rgba(37, 99, 235, 0.1)';
            else if (cellMapped) bg = 'rgba(22, 163, 74, 0.1)';

            const cellStyle = `padding:0.4rem; border:1px solid #e2e8f0; text-align:${align}; background:${bg}; cursor:pointer;`;
            html += `<td id="node-${cellId}" style="${cellStyle}" onclick="workspace.selectNode('${cellId}')" oncontextmenu="workspace.showContextMenu(event, '${cellId}')">`;
            
            if (cellMapped) {
              html += `<div style="color:var(--accent-green); font-weight:700; font-size:0.7rem; margin-bottom:0.2rem;">✓ ${this._esc(cellMapped.qname)}</div>`;
            }
            html += `${this._esc(cell)}</td>`;
          }
          html += '</tr>';
        }
        html += '</table></div>';
      }
    }
    container.innerHTML = html;
  },

  selectNode(nodeId) {
    if (this.state.activeNodeId === nodeId) {
      this.state.activeNodeId = null;
    } else {
      this.state.activeNodeId = nodeId;
    }
    this.renderDocumentViewer();
    this.renderInspector();
  },

  renderInspector() {
    const container = document.getElementById('inspectorPanel');
    if (!this.state.activeNodeId) {
      container.innerHTML = '<div class="empty-state">Select a node in the document to inspect and tag it.</div>';
      return;
    }

    const node = this.state.document
      ? this.state.document.nodes.find(n => n.id === this.state.activeNodeId)
      : null;
    if (!node) { container.innerHTML = '<div class="empty-state">Node not found.</div>'; return; }

    const mapping = this.state.mappings[node.id];
    const isFrozen = this.state.filingState === 'frozen' || this.state.filingState === 'validated';
    const canTag = !isFrozen && this.state.filingId;

    const preview = node.kind === 'paragraph'
      ? this._esc(node.text.slice(0, 200))
      : `Table (${node.rows.length} rows × ${node.rows[0] ? node.rows[0].length : 0} cols)`;

    let html = `
      <div class="inspector-section slide-in">
        <span class="inspector-label">Node</span>
        <div style="font-size:0.75rem; color: var(--text-muted); font-family: var(--font-mono); margin-bottom: 0.5rem;">${node.id} · ${node.location}</div>
        <div style="background:#f8fafc; border:1px solid var(--border-color); border-radius:6px; padding: 0.5rem 0.75rem; font-size: 0.85rem; max-height: 100px; overflow-y:auto; word-break: break-word;">${preview}</div>
      </div>
    `;

    if (mapping) {
      html += `
        <div class="fact-status-card mapped slide-in">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.5rem;">
            <strong style="color: var(--accent-green);">✓ Mapped</strong>
          </div>
          <div style="font-family:var(--font-mono); font-size:0.78rem; color: #166534; margin-bottom:0.4rem;">${this._esc(mapping.qname)}</div>
          <div style="font-size:0.75rem; color:#4b5563; border-top:1px solid rgba(0,0,0,.08); padding-top:0.4rem;">
            <div><strong>Kind:</strong> ${mapping.kind}</div>
            <div><strong>Value:</strong> ${mapping.value !== null && mapping.value !== undefined ? this._esc(String(mapping.value)) : '—'}</div>
            <div><strong>Context:</strong> ${this._esc(mapping.contextId)}</div>
            <div><strong>Reviewer:</strong> ${this._esc(mapping.reviewer || '—')}</div>
            <div><strong>Fact ID:</strong> <span style="font-family:var(--font-mono); font-size:0.7rem;">${this._esc(mapping.factId)}</span></div>
          </div>
          ${canTag ? `<button class="btn-danger btn-block" style="margin-top:0.75rem;" onclick="workspace.removeMapping('${node.id}')">Remove Tag</button>` : ''}
        </div>
      `;
    } else {
      html += `
        <div class="fact-status-card unmapped slide-in">
          <div style="color: var(--text-muted); font-size: 0.8rem; margin-bottom: 0.75rem;">No XBRL tag assigned to this node.</div>
          ${canTag
            ? `<button class="btn-primary btn-block" onclick="workspace.openMapFactModal('${node.id}')">Tag this Node…</button>`
            : isFrozen
              ? `<div style="color: var(--accent-amber); font-size:0.78rem;">Snapshot is frozen — tagging disabled.</div>`
              : `<div style="color: var(--text-muted); font-size:0.78rem;">Load a document and set entity info first.</div>`
          }
        </div>
      `;
    }

    container.innerHTML = html;
  },

  _updateTagCount() {
    const count = Object.keys(this.state.mappings).length;
    const chip = document.getElementById('tagCount');
    if (chip) chip.textContent = `${count} tag${count !== 1 ? 's' : ''}`;
  },

  renderChecklist() {
    const container = document.getElementById('checklistContainer');
    if (!container) return;
    if (!this.state.checklistSections || this.state.checklistSections.length === 0) {
      container.innerHTML = '<div class="empty-state">Set entity and taxonomy to see required tags.</div>';
      return;
    }

    const mappedQnames = new Set(Object.values(this.state.mappings).map(m => m.qname));
    const filter = document.getElementById('checklistFilter')?.value || 'outstanding';
    const query = (document.getElementById('checklistSearch')?.value || '').trim().toLowerCase();
    const profile = document.getElementById('taggingProfile');
    if (profile) profile.textContent = `Selected profile: ${this.state.entryPointMetadata?.[this.state.entryPointKey]?.name || this.state.entryPointKey}. ${this.state.taxonomyId}`;
    const matches = item => {
      const reviewed = item.is_satisfied || mappedQnames.has(item.concept_qname);
      const visible = filter === 'all' || (filter === 'mapped' ? reviewed :
        filter === 'outstanding' ? !reviewed && ['mandatory', 'conditional'].includes(item.status) : item.status === filter);
      return visible && (!query || `${item.label_nl} ${item.label_en} ${item.concept_qname}`.toLowerCase().includes(query));
    };
    const count = this.state.checklistSections.flatMap(section => section.items).filter(matches).length;
    const summary = document.getElementById('checklistSummary');
    if (summary) summary.textContent = `${count} matching items. ${count > 100 ? 'Showing the first 100; narrow your search. ' : ''}Parsed rules are preparation guidance, not filing approval.`;
    let shown = 0;
    let html = '';

    for (const section of this.state.checklistSections) {
      const items = section.items.filter(matches).slice(0, Math.max(0, 100 - shown));
      shown += items.length;
      if (!items.length) continue;
      
      const isComplete = section.satisfied >= section.total && section.total > 0;
      const progressClass = isComplete ? 'complete' : '';

      html += `
        <div class="checklist-section-header">
          <span>${this._esc(section.title_nl)}</span>
          <span class="checklist-progress-pill">${items.length} shown</span>
        </div>`;
      
      for (const item of items) {
        const isMapped = item.is_satisfied || mappedQnames.has(item.concept_qname);
        const statusClass = isMapped ? 'done' : (item.status === 'conditional' ? 'conditional' : 'pending');
        const icon = isMapped 
          ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
          : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle></svg>';

        let extraAction = '';
        if (item.status === 'conditional' && !isMapped && ['draft','reviewed'].includes(this.state.filingState)) {
            extraAction = `<button class="btn-secondary" style="font-size:0.7rem; padding: 2px 4px; margin-top:4px;" data-rule-ids="${this._esc(JSON.stringify(item.rule_ids))}" onclick="event.stopPropagation(); workspace.markReviewedGroup(this.dataset.ruleIds)">Mark N/A</button>`;
        }

        const clickToTag = !isMapped && ['draft','reviewed'].includes(this.state.filingState)
          ? `data-qname="${this._esc(item.concept_qname)}" data-label="${this._esc(item.label_nl)}" data-label-en="${this._esc(item.label_en || '')}" onclick="workspace.quickTagFromChecklist(this.dataset.qname, this.dataset.label, this.dataset.labelEn)" style="cursor:pointer;"`
          : '';

        html += `
          <div class="checklist-item ${statusClass}" title="${this._esc(item.condition_nl)}" ${clickToTag}>
            <div class="status-icon">${icon}</div>
            <div style="flex: 1;">
              <div class="req-name">${this._esc(item.label_en || item.label_nl || item.concept_qname)}</div>
              <div class="req-desc">${this._esc(item.concept_qname)} · ${item.status}</div>
              ${extraAction}
            </div>
          </div>
        `;
      }
    }
    
    container.innerHTML = html || '<div class="empty-state">No items match this view. Use All available tags to browse the selected profile.</div>';
  },

  quickTagFromChecklist(qname, label_nl, label_en) {
    if (this.state.activeNodeId) {
      if (!confirm(`You currently have a node selected.\n\nClick OK to tag the selected node.\nClick Cancel to clear the selection and auto-search the document for this concept.`)) {
        this.state.activeNodeId = null;
        this.renderDocumentViewer();
        this.renderInspector();
      }
    }

    if (!this.state.activeNodeId && (label_nl || label_en)) {
      const bestNode = this._findBestNodeForLabel(label_nl, label_en);
      if (bestNode) {
        this.selectNode(bestNode.id);
        this.scrollToNode('node-' + bestNode.id);
      } else {
        const label = label_nl || label_en;
        alert(`Could not find a matching text or table row in the document for "${label}". Select a node manually first.`);
        return;
      }
    } else if (!this.state.activeNodeId) {
      alert('Select a node in the document viewer first, then click a checklist concept to tag it.');
      return;
    }
    this.openMapFactModal(this.state.activeNodeId);
    const qnameInput = document.getElementById('mapQname');
    if (qnameInput) qnameInput.value = qname;
  },

  _findBestNodeForLabel(label_nl, label_en) {
    if (!this.state.document || !this.state.document.nodes) return null;
    const targetWordsNL = label_nl ? label_nl.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/).filter(w => w.length > 2) : [];
    const targetWordsEN = label_en ? label_en.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/).filter(w => w.length > 2) : [];
    if (targetWordsNL.length === 0 && targetWordsEN.length === 0) return null;

    let bestScore = 0;
    let bestMatch = null;

    const calcScore = (words) => {
      let score = 0;
      if (targetWordsNL.length > 0) {
        let matchCount = 0;
        targetWordsNL.forEach(tw => { if (words.includes(tw)) matchCount++; });
        score = Math.max(score, matchCount / targetWordsNL.length);
      }
      if (targetWordsEN.length > 0) {
        let matchCount = 0;
        targetWordsEN.forEach(tw => { if (words.includes(tw)) matchCount++; });
        score = Math.max(score, matchCount / targetWordsEN.length);
      }
      return score;
    };

    for (const node of this.state.document.nodes) {
      if (node.kind === 'paragraph') {
        const words = node.text.toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/);
        const score = calcScore(words);
        if (score > bestScore && score >= 0.5) {
          bestScore = score;
          bestMatch = { id: node.id };
        }
      } else if (node.kind === 'table') {
        for (let rIdx = 0; rIdx < node.rows.length; rIdx++) {
          const row = node.rows[rIdx];
          if (!row || row.length === 0) continue;
          const words = (row[0] || '').toLowerCase().replace(/[^\w\s]/g, '').split(/\s+/);
          const score = calcScore(words);
          if (score > bestScore && score >= 0.5) {
            bestScore = score;
            let cIdx = 1;
            for (let i = 1; i < row.length; i++) {
              if (row[i] && row[i].trim().match(/^[\d,.-]+$/)) { cIdx = i; break; }
            }
            bestMatch = { id: `${node.id}-r${rIdx}c${cIdx}` };
          }
        }
      }
    }
    return bestMatch;
  },

  async markReviewedGroup(serializedIds) {
    if (!this.state.filingId) return;
    try {
      for (const ruleId of JSON.parse(serializedIds)) {
        const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/review-requirement`, {
          method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({requirement_id:ruleId})
        });
        if (!res.ok) throw new Error('Could not save requirement review.');
      }
      await this.fetchRequirements();
    } catch (e) { this.setNavStatus(e.message, 'error'); }
  },

  // ── Context Menu & Tooltip ────────────────────────────────────────────────
  handleContextMenuTag() {
    document.getElementById('contextMenu').style.display = 'none';
    if (this.state._contextMenuNodeId) {
      this.openMapFactModal(this.state._contextMenuNodeId);
      this.state._contextMenuNodeId = null;
    }
  },

  // ── Map Fact modal ─────────────────────────────────────────────────────────
  openMapFactModal(nodeId) {
    let parentNodeId = nodeId;
    let subLoc = '';
    let cellText = '';
    let isCell = false;

    if (nodeId.includes('-r')) {
      parentNodeId = nodeId.split('-r')[0];
      const match = nodeId.match(/-r(\d+)c(\d+)/);
      if (match) {
        subLoc = `, Row ${parseInt(match[1]) + 1}, Col ${parseInt(match[2]) + 1}`;
        isCell = true;
      }
    }

    const node = this.state.document.nodes.find(n => n.id === parentNodeId);
    if (!node) return;
    this.state._pendingNodeId = nodeId;

    if (isCell) {
      const match = nodeId.match(/-r(\d+)c(\d+)/);
      cellText = node.rows[parseInt(match[1])][parseInt(match[2])];
    }

    // Pre-fill source text
    let srcText = node.kind === 'paragraph' ? node.text : `Table: ${node.location}${subLoc}`;
    if (isCell) srcText += `\nValue: ${cellText}`;
    document.getElementById('mapSourceText').textContent = srcText.slice(0, 300);

    // Pre-fill value
    let prefillVal = '';
    if (node.kind === 'paragraph') prefillVal = node.text;
    if (isCell) prefillVal = cellText;
    document.getElementById('mapValue').value = prefillVal;

    // Pre-fill reviewer
    document.getElementById('mapReviewer').value = this.currentUser.name;

    this.state._reviewingSuggestion = false;
    if (document.getElementById('skipSuggestion')) document.getElementById('skipSuggestion').style.display = 'none';
    // Reset kind
    document.getElementById('mapKind').value = 'text';
    document.getElementById('numericLocale').value = 'nl';
    this.updateMapKind();

    document.getElementById('mapQname').value = '';

    document.getElementById('mapFactModal').style.display = 'flex';
  },

  updateMapKind() {
    const kind = document.getElementById('mapKind').value;
    const numExtras = document.getElementById('numericExtras');
    if (numExtras) numExtras.style.display = kind === 'numeric' ? 'grid' : 'none';
  },

  async submitMapFact() {
    const nodeId = this.state._pendingNodeId;
    if (!nodeId) return;

    const parentNodeId = nodeId.split('-r')[0];
    const node = this.state.document.nodes.find(n => n.id === parentNodeId);
    const qname    = document.getElementById('mapQname').value.trim();
    const kind     = document.getElementById('mapKind').value;
    const rawValue = document.getElementById('mapValue').value.trim();
    const contextId = document.getElementById('mapContextId').value;
    const reviewer = document.getElementById('mapReviewer').value.trim();

    if (!qname) { alert('Please enter a QName for the taxonomy concept.'); return; }
    if (!contextId) { alert('Please select a reporting period (Context ID).'); return; }
    if (!reviewer) { alert('A reviewer name is required for every mapping decision.'); return; }

    let value = rawValue;
    if (kind === 'numeric') {
      try { value = this._parseAmount(rawValue, document.getElementById('numericLocale').value); }
      catch (e) { alert(e.message); return; }
    } else if (kind === 'boolean') {
      if (!['true', 'false'].includes(rawValue.toLowerCase())) { alert('Enter true or false.'); return; }
      value = rawValue.toLowerCase() === 'true';
    }

    const unitMeasure = kind === 'numeric' ? document.getElementById('mapUnit').value.trim() : null;
    const unitId = unitMeasure ? 'u-' + unitMeasure.replaceAll(':', '-') : null;
    const decimals = kind === 'numeric' ? parseInt(document.getElementById('mapDecimals').value, 10) : null;

    // Build the context payload (the backend will auto-register it)
    const ctx = this._buildContext(contextId);

    // Build the unit payload if numeric
    let unitPayload = null;
    if (kind === 'numeric' && unitId) {
      unitPayload = { id: unitId, measure: unitMeasure };
    }

    // If it's a table cell, reconstruct precise source location
    let finalSourceLocation = node ? node.location : nodeId;
    if (nodeId.includes('-r')) {
      const match = nodeId.match(/-r(\d+)c(\d+)/);
      if (match) {
        finalSourceLocation += `, Row ${parseInt(match[1]) + 1}, Col ${parseInt(match[2]) + 1}`;
      }
    }

    const payload = {
      replaces_fact_id: this.state.mappings[nodeId]?.factId || null,
      decision: {
        source_node_id: parentNodeId, // backend expects parent table ID for node checking
        source_location: finalSourceLocation,
        qname,
        context_id: contextId,
        kind,
        value,
        unit_id: kind === 'numeric' ? unitId : null,
        decimals,
        reviewer,
      },
      context: ctx,
      unit: unitPayload,
    };

    this.setNavStatus('Saving tag…', 'loading');
    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/map`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Map failed');
      }
      const result = await res.json();

      // Store locally
      this.state.mappings[nodeId] = {
        factId: result.fact_id,
        qname: result.qname,
        kind,
        value,
        contextId,
        reviewer,
      };

      document.getElementById('mapFactModal').style.display = 'none';
      this.setNavStatus(`Tagged: ${qname}`);
      this.renderWorkspace();
      await this.fetchRequirements();
      if (this.state._reviewingSuggestion && this.state.pendingRecommendations?.length) {
        this.state.pendingRecommendations.shift();
        this._openNextRecommendation();
      }
    } catch (e) {
      this.setNavStatus(`Tag failed: ${e.message}`, 'error');
      alert(`Mapping failed: ${e.message}`);
    }
  },

  _parseAmount(raw, locale = 'nl') {
    let value = raw.trim();
    const negative = value.startsWith('(') && value.endsWith(')');
    if (negative) value = value.slice(1, -1);
    const pattern = locale === 'nl' ? /^[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?$/ : /^[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?$/;
    if (!pattern.test(value)) throw new Error('Amount does not match the selected number format.');
    value = locale === 'nl' ? value.replaceAll('.', '').replace(',', '.') : value.replaceAll(',', '');
    return negative ? (value.startsWith('-') ? value.slice(1) : '-' + value.replace(/^\+/, '')) : value;
  },

  _restoreSnapshot(snap) {
    Object.assign(this.state, {filingId: snap.filing_id, kvkNumber: snap.kvk_number,
      entityName: snap.entity_name, periodStart: snap.period_start, periodEnd: snap.period_end,
      taxonomyId: snap.taxonomy_id, entryPointKey: snap.entry_point_key,
      document: snap.document, mappings: {}, activeNodeId: null});
    for (const fact of snap.facts || []) {
      const location = fact.source.location;
      const node = snap.document?.nodes.find(n => location === n.location || location.startsWith(n.location + ', Row '));
      if (!node) continue;
      const cell = location.match(/, Row (\d+), Col (\d+)$/);
      const key = cell ? `${node.id}-r${Number(cell[1])-1}c${Number(cell[2])-1}` : node.id;
      this.state.mappings[key] = {factId: fact.id, qname: fact.qname, kind: fact.kind,
        value: fact.value, contextId: fact.context_id, reviewer: fact.source.reviewer};
    }
    document.getElementById('entityStatusLabel').innerText = `${snap.kvk_number} · ${snap.entity_name}`;
    this.updateStatePill(snap.state);
    this._enablePostDocButtons();
  },

  _openNextRecommendation() {
    const rec = this.state.pendingRecommendations?.[0];
    if (!rec) { this.state._reviewingSuggestion = false; this.setNavStatus('Suggestion review complete. Check remaining items in Tagging review.'); return; }
    this.openMapFactModal(`${rec.source_node_id}-r${rec.row_index}c${rec.col_index}`);
    this.state._reviewingSuggestion = true;
    document.getElementById('skipSuggestion').style.display = '';
    document.getElementById('mapSourceText').textContent = `${rec.source_label || ''} — ${rec.source_text || rec.value}\nSuggested: ${rec.label || rec.qname}\nLabel match: ${Math.round((rec.match_score || 0) * 100)}% (not certainty). ${rec.alternatives?.length ? 'Other possible tags: ' + rec.alternatives.join(', ') : ''}\nCheck period, currency and scale against the source.`;
    const year = Number(this.state.periodEnd.slice(0, 4));
    const prior = rec.year_hint === year - 1;
    const knownYear = rec.year_hint === year || prior;
    document.getElementById('mapContextId').value = knownYear ?
      (rec.period_type === 'instant' ? (prior ? 'ctx_instant_prior' : 'ctx_instant_end') : (prior ? 'ctx_prior' : 'ctx_current')) : '';
    document.getElementById('mapQname').value = rec.qname;
    document.getElementById('mapKind').value = rec.kind;
    document.getElementById('mapValue').value = rec.value;
    document.getElementById('numericLocale').value = 'en';
    document.getElementById('mapDecimals').value = rec.value.includes('.') ? rec.value.split('.')[1].length : 0;
    this.updateMapKind();
    this.setNavStatus(`Review the amount, period and unit (${this.state.pendingRecommendations.length} recommendations remaining).`);
  },

  _buildContext(contextId) {
    const start = this.state.periodStart;
    const end   = this.state.periodEnd;

    // Compute a prior year start/end
    const priorDate = value => {
      const [year, month, day] = value.split('-').map(Number);
      const lastDay = new Date(Date.UTC(year - 1, month, 0)).getUTCDate();
      return `${year - 1}-${String(month).padStart(2, '0')}-${String(Math.min(day, lastDay)).padStart(2, '0')}`;
    };
    const priorStart = priorDate(start);
    const priorEnd = priorDate(end);

    const scheme = 'http://www.kvk.nl/kvk-id';
    const identifier = this.state.kvkNumber;

    const defs = {
      ctx_current: {
        id: 'ctx_current', entity_scheme: scheme, entity_identifier: identifier,
        start_date: start, end_date: end, dimensions: [],
      },
      ctx_prior: {
        id: 'ctx_prior', entity_scheme: scheme, entity_identifier: identifier,
        start_date: priorStart, end_date: priorEnd, dimensions: [],
      },
      ctx_instant_prior: { id: 'ctx_instant_prior', entity_scheme: scheme, entity_identifier: identifier, instant: priorEnd, dimensions: [] },
      ctx_instant_end: {
        id: 'ctx_instant_end', entity_scheme: scheme, entity_identifier: identifier,
        instant: end, dimensions: [],
      },
    };
    if (!defs[contextId]) throw new Error('Unknown context ID.');
    return defs[contextId];
  },

  // ── Remove a mapping ───────────────────────────────────────────────────────
  async removeMapping(nodeId) {
    const mapping = this.state.mappings[nodeId];
    if (!mapping) return;
    if (!confirm(`Remove tag "${mapping.qname}" from this node?`)) return;

    try {
      const res = await fetch(
        `${this.BASE_URL}/api/snapshot/${this.state.filingId}/facts/${encodeURIComponent(mapping.factId)}`,
        { method: 'DELETE' }
      );
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Delete failed');
      }
      delete this.state.mappings[nodeId];
      this.setNavStatus('Tag removed');
      this.renderWorkspace();
    } catch (e) {
      this.setNavStatus(`Remove failed: ${e.message}`, 'error');
    }
  },

  // ── Diagnostics ────────────────────────────────────────────────────────────
  async runDiagnostics() {
    if (!this.state.filingId) { alert('No active filing snapshot. Please set entity info and upload a document first.'); return; }
    document.getElementById('diagnosticsModal').style.display = 'flex';
    const container = document.getElementById('diagnosticsContent');
    container.innerHTML = '<div class="loading-pulse" style="padding: 2rem; text-align: center; color:#6b7280;">Running validation…</div>';

    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/validate`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Validation API failed');
      }
      const result = await res.json();
      this.state.diagnosticIssues = result.issues || [];
      this.filterDiagnostics('all');
    } catch (e) {
      container.innerHTML = `<div style="padding:2rem; color: var(--accent-red);">Diagnostics failed: ${this._esc(e.message)}</div>`;
    }
  },

  filterDiagnostics(severityFilter = 'all') {
    document.querySelectorAll('.diag-filter-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.filter === severityFilter);
    });
    this.renderDiagnostics(severityFilter);
  },

  renderDiagnostics(filter = 'all') {
    const container = document.getElementById('diagnosticsContent');
    const issues = this.state.diagnosticIssues || [];
    
    const errCount = issues.filter(i => ['error', 'critical'].includes(i.severity)).length;
    const warnCount = issues.filter(i => i.severity === 'warning').length;
    
    const errEl = document.getElementById('diagErrCount');
    const warnEl = document.getElementById('diagWarnCount');
    if (errEl) errEl.textContent = errCount;
    if (warnEl) warnEl.textContent = warnCount;

    const filtered = filter === 'all' 
      ? issues 
      : issues.filter(i => filter === 'error' ? ['error', 'critical'].includes(i.severity) : i.severity === filter);

    if (issues.length === 0) {
      container.innerHTML = `
        <div style="padding: 2rem; text-align: center; color: var(--accent-green);">
          <div style="font-size:2rem; margin-bottom:0.5rem;">✓</div>
          <strong>No issues found — validation passed!</strong>
          <p style="color:#6b7280; margin-top:0.5rem; font-size:0.85rem;">Local checks passed. Export also requires verified taxonomy and independent filing validation.</p>
        </div>`;
      return;
    }

    if (filtered.length === 0) {
      container.innerHTML = `<div style="padding: 2rem; text-align: center; color: #6b7280;">No ${filter} issues found.</div>`;
      return;
    }

    let html = `<ul style="list-style:none; padding:0; margin:0;">`;
    for (const issue of filtered) {
      const isCritical = ['error', 'critical'].includes(issue.severity);
      const isWarning = issue.severity === 'warning';
      const icon = isCritical ? '🔴' : isWarning ? '🟡' : 'ℹ️';
      
      const conceptBadge = issue.concept ? `<span class="diag-concept-badge">${this._esc(issue.concept)}</span>` : '';
      const ruleRefBadge = issue.rule_ref ? `<span class="diag-rule-ref">Rule: ${this._esc(issue.rule_ref)}</span>` : '';

      html += `
        <li class="diag-item" style="display: flex; gap: 0.75rem; align-items: flex-start; padding: 0.85rem 1rem; border-bottom: 1px solid var(--border-color);">
          <div style="font-size: 1.1rem; line-height: 1;">${icon}</div>
          <div style="flex: 1;">
            <div style="font-weight:600; font-size:0.85rem; margin-bottom:0.25rem; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;">
              <span>${this._esc(issue.code)}</span>
              ${conceptBadge}
              ${ruleRefBadge}
            </div>
            <div style="color:#4b5563; font-size:0.82rem; line-height: 1.4;">${this._esc(issue.message)}</div>
          </div>
        </li>`;
    }
    html += '</ul>';
    container.innerHTML = html;
  },

  // ── Sign-Off / Freeze ──────────────────────────────────────────────────────
  openSignOffWizard() {
    if (!this.state.filingId) return;
    document.getElementById('signoffDate').value = new Date().toISOString().split('T')[0];
    document.getElementById('signoffName').value = this.currentUser.name;
    document.getElementById('completionModal').style.display = 'flex';
  },

  async submitSignOff() {
    if (!this.state.filingId) return;
    
    const isFinal = document.querySelector('input[name="signoffFinal"]:checked').value === 'true';
    const signatoryName = document.getElementById('signoffName').value;
    const approvalDate = document.getElementById('signoffDate').value;

    this.setNavStatus('Freezing…', 'loading');
    document.getElementById('completionModal').style.display = 'none';

    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/freeze`, { 
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          is_final: isFinal,
          signatory_name: signatoryName,
          approval_date: approvalDate || null
        })
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Freeze failed');
      }
      const snap = await res.json();
      this.updateStatePill(snap.state);
      document.getElementById('btnExport').disabled = false;
      this.setNavStatus('Snapshot frozen — package generation is now available');
      this.renderInspector();
    } catch (e) {
      this.setNavStatus(`Freeze failed: ${e.message}`, 'error');
    }
  },

  async reopenFiling() {
    if (!this.state.filingId) return;
    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/reopen`, {method:'POST'});
      if (!res.ok) throw new Error('Could not reopen filing.');
      this._restoreSnapshot(await res.json());
      this.renderWorkspace();
      this.setNavStatus('Filing reopened. Review and sign off again after editing.');
    } catch (e) { this.setNavStatus(e.message, 'error'); }
  },

  // ── Export (validate-and-package) ─────────────────────────────────────────
  async independentValidation() {
    if (!this.state.filingId) { alert('Open a filing first.'); return; }
    this.setNavStatus('Running independent technical checks…', 'loading');
    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/independent-validation`, { method: 'POST' });
      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || 'Validation failed');
      const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url; a.download = 'arelle-diagnostics.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      this.setNavStatus(result.technical_valid ? 'Technical checks passed; filing approval is still pending.' : 'Technical checks found issues. See the downloaded diagnostics.', 'warning');
    } catch (e) { this.setNavStatus(e.message, 'error'); }
  },

  async exportPackage(handoff = false) {
    if (!this.state.filingId) return;
    this.setNavStatus('Generating & validating package…', 'loading');
    try {
      const action = handoff ? 'provider-handoff' : 'validate-and-package';
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/${action}`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Export failed');
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = handoff ? 'provider-handoff.zip' : `report_${this.state.kvkNumber}_${this.state.periodEnd.split('-')[0]}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      this.setNavStatus('Package exported ✓');
      // Refresh state pill (now validated)
      try {
        const snapRes = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}`);
        if (snapRes.ok) { const snap = await snapRes.json(); this.updateStatePill(snap.state); }
      } catch (_) {}
    } catch (e) {
      this.setNavStatus(`Export failed: ${e.message}`, 'error');
      alert(`Export failed: ${e.message}`);
    }
  },

  // ── Save / Load workspace ──────────────────────────────────────────────────
  async saveWorkspace() {
    if (!this.state.filingId || !this.state.kvkNumber) {
      alert('Nothing to save. Set entity info and upload a document first.');
      return;
    }
    this.setNavStatus('Saving…', 'loading');
    try {
      const res = await fetch(`${this.BASE_URL}/api/workspace/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kvk_number: this.state.kvkNumber, filing_id: this.state.filingId }),
      });
      if (!res.ok) throw new Error('Save failed');
      this.setNavStatus('Workspace saved ✓');
      setTimeout(() => this.setNavStatus('Ready'), 2500);
    } catch (e) {
      this.setNavStatus('Save failed', 'error');
    }
  },

  async newFiling() {
    try {
      if (this.state.filingId) {
        const saved = await fetch(`${this.BASE_URL}/api/workspace/save`, {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({kvk_number:this.state.kvkNumber, filing_id:this.state.filingId})
        });
        if (!saved.ok) throw new Error('The current filing could not be saved. It remains open.');
      }
      clearTimeout(this._checklistRetry);
      Object.assign(this.state, {filingId:null, filingState:'draft', document:null, mappings:{},
        activeNodeId:null, checklistSections:[], pendingRecommendations:[]});
      this._enablePostDocButtons();
      this.renderWorkspace();
      this.openEntityModal();
      this.setNavStatus('Set the entity and period, then upload the new source document.');
    } catch (e) { this.setNavStatus(e.message, 'error'); }
  },

  async loadWorkspacePrompt() {
    const kvk = prompt('Enter the KVK number of the saved workspace:');
    if (!kvk) return;
    this.setNavStatus('Loading…', 'loading');
    try {
      const res = await fetch(`${this.BASE_URL}/api/workspace/load/${kvk.trim()}`);
      if (!res.ok) {
        if (res.status === 404) alert(`No saved workspace found for KVK ${kvk}.`);
        else throw new Error('Load failed');
        this.setNavStatus('Ready');
        return;
      }
      const snap = await res.json();
      this._restoreSnapshot(snap);
      this.renderWorkspace();
      await this.fetchRequirements();
      this.setNavStatus(`Loaded workspace ${snap.filing_id} (${snap.fact_count} facts). ${snap.document ? '' : 'Re-upload the same DOCX to reattach its source.'}`);

    } catch (e) {
      this.setNavStatus('Load failed', 'error');
    }
  },

  // ── Log Book ───────────────────────────────────────────────────────────────
  showLogBook() {
    const modal = document.getElementById('logBookModal');
    const content = document.getElementById('logBookContent');
    const entries = Object.entries(this.state.mappings);

    if (!entries.length) {
      content.innerHTML = '<div class="empty-state" style="padding: 2rem;">No tags have been made yet.</div>';
    } else {
      let html = '';
      for (const [nodeId, m] of entries) {
        html += `
          <div class="log-entry">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 0.3rem;">
              <span style="font-family:var(--font-mono); font-size:0.82rem; font-weight:700; color:var(--accent-blue);">${this._esc(m.qname)}</span>
              <span class="log-badge manual">manual</span>
            </div>
            <div style="font-size:0.77rem; color:#374151; display:grid; grid-template-columns: 1fr 1fr; gap: 0.3rem; margin-bottom: 0.3rem;">
              <div><strong>Value:</strong> ${m.value !== null && m.value !== undefined ? this._esc(String(m.value)) : '—'}</div>
              <div><strong>Kind:</strong> ${this._esc(m.kind)}</div>
              <div><strong>Context:</strong> ${this._esc(m.contextId)}</div>
              <div><strong>Reviewer:</strong> ${this._esc(m.reviewer || '—')}</div>
            </div>
            <div style="font-size:0.7rem; color:#6b7280; font-family:var(--font-mono); border-top:1px solid #f1f5f9; padding-top:0.25rem;">
              Node: ${this._esc(nodeId)} · Fact ID: ${this._esc(m.factId || '—')}
            </div>
          </div>`;
      }
      content.innerHTML = html;
    }
    modal.style.display = 'flex';
  },

  cancelTagReview() {
    this.state.pendingRecommendations = [];
    this.state._reviewingSuggestion = false;
    document.getElementById('mapFactModal').style.display = 'none';
  },

  skipSuggestion() {
    this.state.pendingRecommendations?.shift();
    document.getElementById('mapFactModal').style.display = 'none';
    this._openNextRecommendation();
  },

  async autoTagDocument() {
    if (!this.state.filingId || !this.state.document) { alert('Open a filing and upload its document first.'); return; }
    if (!['draft', 'reviewed'].includes(this.state.filingState)) { alert('Reopen the filing before reviewing new tags.'); return; }
    if (this._suggesting) return;
    this._suggesting = true;
    const filingId = this.state.filingId;
    try {
      const suggestions = [];
      for (const node of this.state.document.nodes.filter(n => n.kind === 'table')) {
        this.setNavStatus(`Finding suggestions… ${suggestions.length} found`, 'loading');
        const res = await fetch(`${this.BASE_URL}/api/snapshot/${filingId}/auto-tag-table`, {
          method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source_node_id: node.id})});
        if (!res.ok) throw new Error('Suggestions unavailable. Check that the selected taxonomy has loaded.');
        suggestions.push(...(await res.json()).recommendations);
      }
      if (this.state.filingId !== filingId) return;
      this.state.pendingRecommendations = suggestions;
      if (suggestions.length) this._openNextRecommendation();
      else this.setNavStatus('No new matches found. Browse tags or select a source cell to tag it manually.', 'warning');
    } catch (e) { this.setNavStatus(e.message, 'error'); }
    finally { this._suggesting = false; }
  },

  // ── Auto-Tagging ───────────────────────────────────────────────────────────
  async autoTagTable(tableNodeId) {
    if (!this.state.filingId || !['draft','reviewed'].includes(this.state.filingState)) return;
    this.setNavStatus('Analyzing table...', 'loading');
    
    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/auto-tag-table`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source_node_id: tableNodeId })
      });
      if (!res.ok) throw new Error('Auto-tagging failed');
      const data = await res.json();
      
      const recs = data.recommendations;
      if (recs.length === 0) {
        this.setNavStatus('No recommendations found for this table.', 'warning');
        alert("No matching amount labels were found. You can tag cells manually.");
        return;
      }
      
      this.state.pendingRecommendations = recs;
      this._openNextRecommendation();

    } catch (e) {
      this.setNavStatus(`Auto-tag error: ${e.message}`, 'error');
    }
  },

  // ── Utilities ──────────────────────────────────────────────────────────────
  _esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  },
};

window.onload = () => workspace.init();
