import re

with open("app/frontend/workspace.js", "r") as f:
    content = f.read()

# Replace fetchRequirements
old_fetch = """  async fetchRequirements() {
    if (!this.state.taxonomyId || !this.state.entryPointKey) return;
    try {
      const res = await fetch(`${this.BASE_URL}/api/taxonomy/${this.state.taxonomyId}/requirements/${this.state.entryPointKey}`);
      if (res.ok) {
        const data = await res.json();
        this.state.taxonomyRequirements = data.requirements || [];
        this.renderChecklist();
      }
    } catch (e) {
      console.warn("Failed to fetch taxonomy requirements", e);
    }
  },"""

new_fetch = """  async fetchRequirements() {
    if (!this.state.taxonomyId || !this.state.entryPointKey) return;
    try {
      let url = `${this.BASE_URL}/api/taxonomy/${this.state.taxonomyId}/checklist?entry_point_key=${this.state.entryPointKey}`;
      if (this.state.filingId) {
        url += `&filing_id=${this.state.filingId}`;
      }
      const res = await fetch(url);
      if (res.ok) {
        this.state.checklistSections = await res.json();
        this.renderChecklist();
      }
    } catch (e) {
      console.warn("Failed to fetch taxonomy checklist", e);
    }
  },"""

content = content.replace(old_fetch, new_fetch)

# Replace renderChecklist
old_render = """  renderChecklist() {
    const container = document.getElementById('checklistContainer');
    if (!container) return;
    if (!this.state.taxonomyRequirements || this.state.taxonomyRequirements.length === 0) {
      container.innerHTML = '<div class="empty-state">Set entity and taxonomy to see required tags.</div>';
      return;
    }

    const mappedQnames = new Set(Object.values(this.state.mappings).map(m => m.qname));
    let html = '';

    for (const req of this.state.taxonomyRequirements) {
      if (!req.qname) continue; // Skip section-only requirements for the checklist
      
      const isMapped = mappedQnames.has(req.qname);
      const statusClass = isMapped ? 'done' : (req.conditional ? 'conditional' : 'pending');
      const icon = isMapped 
        ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
        : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle></svg>';

      html += `
        <div class="checklist-item ${statusClass}">
          <div class="status-icon">${icon}</div>
          <div>
            <div class="req-name">${this._esc(req.qname)}</div>
            <div class="req-desc">${req.conditional ? 'Conditional' : 'Mandatory'}</div>
          </div>
        </div>
      `;
    }
    
    container.innerHTML = html || '<div class="empty-state">No required tags found for this taxonomy.</div>';
  },"""

new_render = """  renderChecklist() {
    const container = document.getElementById('checklistContainer');
    if (!container) return;
    if (!this.state.checklistSections || this.state.checklistSections.length === 0) {
      container.innerHTML = '<div class="empty-state">Set entity and taxonomy to see required tags.</div>';
      return;
    }

    const mappedQnames = new Set(Object.values(this.state.mappings).map(m => m.qname));
    let html = '';

    for (const section of this.state.checklistSections) {
      if (section.items.length === 0) continue;
      
      html += `<div style="font-weight:600; padding:8px 12px; background:#f8fafc; border-bottom:1px solid #e2e8f0; font-size:0.85rem;">${this._esc(section.title_nl)}</div>`;
      
      for (const item of section.items) {
        const isMapped = mappedQnames.has(item.concept_qname);
        const statusClass = isMapped ? 'done' : (item.status === 'conditional' ? 'conditional' : 'pending');
        const icon = isMapped 
          ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"></polyline></svg>'
          : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"></circle></svg>';

        let extraAction = '';
        if (item.status === 'conditional' && !isMapped) {
            extraAction = `<button class="btn-secondary" style="font-size:0.7rem; padding: 2px 4px; margin-top:4px;" onclick="workspace.markReviewed('${item.rule_ids[0]}')">Mark N/A</button>`;
        }

        html += `
          <div class="checklist-item ${statusClass}" title="${this._esc(item.condition_nl)}">
            <div class="status-icon">${icon}</div>
            <div>
              <div class="req-name">${this._esc(item.concept_qname)}</div>
              <div class="req-desc">${this._esc(item.label_nl)} (${item.status})</div>
              ${extraAction}
            </div>
          </div>
        `;
      }
    }
    
    container.innerHTML = html || '<div class="empty-state">No required tags found for this taxonomy.</div>';
  },

  async markReviewed(ruleId) {
    if (!this.state.filingId || !ruleId) return;
    try {
      const res = await fetch(`${this.BASE_URL}/api/snapshot/${this.state.filingId}/review-requirement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ requirement_id: ruleId })
      });
      if (res.ok) {
        this.fetchRequirements();
      }
    } catch (e) {
      console.warn("Failed to mark reviewed", e);
    }
  },"""

content = content.replace(old_render, new_render)

with open("app/frontend/workspace.js", "w") as f:
    f.write(content)

print("Updated workspace.js")
