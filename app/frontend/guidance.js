/* Plain-language guidance layered over the reviewed mapping workflow. */
(() => {
  const w = window.workspace;
  w.profileLabel = (key, meta = {}) => {
    const sizes = {micro:'Micro company',klein:'Small company',middelgroot:'Medium-sized company',groot:'Large company'};
    const sectors = {bank:'Bank',insurer:'Insurance company',investment:'Investment entity',pension:'Pension institution',cooperative:'Cooperative',foundation:'Foundation',healthcare:'Healthcare institution',nonprofit:'Non-profit organization',fundraising:'Fundraising organization',housing:'Housing institution'};
    let label = sectors[meta.sector] || sizes[meta.company_class] || 'Reporting profile';
    if (key.includes('cv_vof')) label = 'Limited or general partnership';
    if (key.includes('premiepensioen')) label = 'Premium pension institution';
    if (key.includes('pensioenfondsen')) label = 'Pension fund';
    label += ' — ' + (meta.framework === 'nlgaap' ? 'Dutch accounting standards' : meta.framework || 'NL-GAAP');
    if (key.endsWith('_pub')) label += ' — public filing';
    if (key.endsWith('_vert')) label += ' — vertical balance sheet';
    if (key.endsWith('_plus')) label += ' — extended profile';
    return `${label}${meta.company_class ? " (" + meta.company_class + ")" : ""}`;
  };
  w.filterProfiles = function() {
    const size = document.getElementById('profileSize').value;
    const purpose = document.getElementById('profilePurpose').value;
    const select = document.getElementById('entryPointInput');
    [...select.options].forEach(option => {
      const meta = this.state.entryPointMetadata?.[option.value];
      if (!meta) return;
      option.hidden = Boolean((size && meta.company_class !== size) || (purpose && option.value.endsWith('_pub') !== (purpose === 'public')));
    });
    if (select.selectedOptions[0]?.hidden && !this.state.filingId) { select.value = ''; this.handleEntryPointChange(); }
  };
  w.refreshGuide = function() {
    const s = this.state;
    const stage = !s.kvkNumber ? 0 : !s.document || !s.filingId ? 1 : ['frozen','validated'].includes(s.filingState) ? 4 : Object.keys(s.mappings).length ? 3 : 2;
    const labels = ['Set company and financial year','Upload financial statements','Review the suggested tags','Check for issues','View delivery requirements'];
    const help = [
      'Confirm the company, financial-year dates and applicable reporting profile. Ask your accountant if the profile is uncertain.',
      'Upload the DOCX version of your financial statements. Review extracted text and tables; images and complex layouts need separate review.',
      'A tag links a value or disclosure to the reporting rules. Confirm each suggestion, including its year, currency and amount.',
      'Review remaining disclosures, fix blockers and check the rendered report before locking this version. Local checks do not establish filing acceptance.',
      'This version is locked. Delivery is separate: no report has been sent to KVK. Check the supported route and retain the final processing receipt.'
    ];
    document.getElementById('nextStep').textContent = labels[stage];
    document.getElementById('journeyHelp').textContent = help[stage];
    document.querySelectorAll('#journeySteps li').forEach((el,i) => {
      el.classList.toggle('current', i === stage);
      if (i === stage) el.setAttribute('aria-current','step'); else el.removeAttribute('aria-current');
    });
    this._guideStage = stage;
    const saveLabel = document.getElementById('saveStatus');
    if (saveLabel) {
      if (!s.filingId) saveLabel.textContent = 'No filing saved yet';
      else if (saveLabel.textContent === 'No filing saved yet') saveLabel.textContent = 'Confirmed changes are saved automatically';
    }
    const warnEl = document.getElementById('sourceWarnings');
    if (warnEl) warnEl.textContent = (s.document?.warnings || []).join(' ');
  };
  w.nextStep = function() {
    [() => this.openEntityModal(), () => document.getElementById('docUpload').click(),
     () => { document.getElementById('checklistContainer').scrollIntoView({block:'nearest'}); this.autoTagDocument ? this.autoTagDocument() : this.showFilingHelp(); },
     () => this.runDiagnostics(), () => this.showFilingHelp('delivery')][this._guideStage || 0]();
  };
  w.showFilingHelp = function(section) {
    const modal = document.getElementById('helpModal');
    document.getElementById('helpContent').innerHTML = `
      <p><strong>Preparation only — nothing has been submitted to KVK.</strong> This workspace helps you tag and review your statements. Export requires qualified reporting rules and independent filing validation.</p>
      <ol class="help-steps">
        <li><strong>Company & financial year (Boekjaar).</strong> Check the eight-digit KVK number and dates against your statements. A financial year need not be a calendar year.</li>
        <li><strong>Reporting profile.</strong> Small (klein), medium-sized (middelgroot) and large (groot) have different reporting requirements. NL-GAAP means Dutch accounting standards. Use the profile confirmed for your company.</li>
        <li><strong>Upload & review.</strong> Upload a DOCX. Check extraction warnings, images, headers and complex tables against the original; the preview is not a faithful Word conversion.</li>
        <li><strong>Tags.</strong> Review English and Dutch labels, source values and the reporting period. Dutch 1.234,56 and English 1,234.56 both mean 1234.56; select the correct number format. Enter full amounts, even when the source displays thousands.</li>
        <li><strong>Check & lock.</strong> Fix errors and assess warnings. “Adopted” (vastgesteld) means the financial statements have been formally approved; it is separate from your review here. Locking records this version and its review actor, not an independent audit opinion.</li>
        <li><strong>Delivery (Deponeren).</strong> A downloaded package is not a filed report. Confirm the accepted format, attachments and credentials with your filing provider. Submit through that provider, check the final processing result and retain the receipt and exact package. This app has no connected delivery service and cannot verify acceptance.</li>
      </ol>
      <p><a href="https://www.kvk.nl/en/filing/filing-financial-statements/" target="_blank" rel="noopener">Official KVK filing guidance (English)</a> · <a href="https://www.sbr-nl.nl/sbr-domeinen/handelsregister/documentatie-boekjaar-2026" target="_blank" rel="noopener">Official 2026 iXBRL documentation</a></p>
      <p class="help-text">The bundled 2026 NT21 beta is for preparation. The separately published 2026 iXBRL alpha is not automatically enabled for filing. Reporting rules and interface language are separate from the language of your financial statements.</p>`;
    modal.style.display = 'flex';
  };
  w.loadWorkspacePrompt = async function() {
    document.getElementById('savedModal').style.display = 'flex';
    const box = document.getElementById('savedContent');
    box.textContent = 'Loading your saved filings…';
    try {
      const response = await fetch('/api/workspace/list');
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Saved filings could not be loaded.');
      box.innerHTML = data.filings.length ? data.filings.map(f => `<button class="saved-filing" data-filing="${this._esc(f.filing_id)}" data-kvk="${this._esc(f.kvk_number)}"><strong>${this._esc(f.entity_name)}</strong><span>${this._esc(f.kvk_number)} · ${this._esc(f.period_start)} to ${this._esc(f.period_end)} · ${this._esc(f.state)} · Not submitted</span></button>`).join('') : '<p>No saved filings are available to this account.</p>';
      box.querySelectorAll('button').forEach(button => button.addEventListener('click', async () => {
        try {
          const res = await fetch(`/api/workspace/load/${encodeURIComponent(button.dataset.kvk)}?filing_id=${encodeURIComponent(button.dataset.filing)}`);
          const snap = await res.json();
          if (!res.ok) throw new Error(snap.detail || 'Load failed.');
          this._restoreSnapshot(snap); this.renderWorkspace(); await this.fetchRequirements();
          document.getElementById('savedModal').style.display = 'none';
          document.getElementById('saveStatus').textContent = 'Loaded from durable storage';
          this.refreshGuide();
        } catch (error) { this.setNavStatus(error.message, 'error'); }
      }));
    } catch (error) { box.textContent = error.message; }
  };
  const originalLog = w.showLogBook;
  w.showLogBook = async function() {
    originalLog.call(this);
    if (!this.state.filingId) return;
    try {
      const res = await fetch(`/api/snapshot/${encodeURIComponent(this.state.filingId)}/audit`);
      if (!res.ok) throw new Error('Audit history could not be loaded.');
      const data = await res.json();
      const history = data.events.map(e => `<p>${this._esc(e.at)} · ${this._esc(e.actor)} · ${this._esc(e.state)}</p>`).join('');
      document.getElementById('logBookContent').insertAdjacentHTML('afterbegin', `<h3>Recorded changes</h3>${history || '<p>No subsequent changes recorded.</p>'}<h3>Current tags</h3>`);
    } catch(error) { this.setNavStatus(error.message,'error'); }
  };
  const init = w.init;
  w.init = async function() {
    await init.call(this);
    try {
      const res = await fetch('/api/me');
      if (!res.ok) throw new Error('Account could not be verified. Sign in again.');
      const account = await res.json();
      this.currentUser = {id:account.user,name:account.user,role:account.role};
      const signedInUser = document.getElementById('signedInUser');
      if (signedInUser) signedInUser.textContent = account.user;
      const mapRev = document.getElementById('mapReviewer');
      if (mapRev) mapRev.value = account.user;
      const adminLink = document.getElementById('adminLink');
      if (adminLink && account.role === 'admin') {
        adminLink.style.display = 'inline-flex';
      }
    } catch (error) { this.setNavStatus(error.message,'error'); }
    this.refreshGuide();
    // Observe modal visibility to keep keyboard focus inside the active dialog.
    let previousFocus = null, activeModal = null;
    const observer = new MutationObserver(() => {
      const open = [...document.querySelectorAll('.modal-overlay')].filter(el => el.style.display !== 'none');
      const current = open.at(-1);
      if (current && current !== activeModal) {
        previousFocus = document.activeElement; activeModal = current;
        current.setAttribute('role','dialog'); current.setAttribute('aria-modal','true');
        current.setAttribute('aria-label', current.querySelector('.modal-title')?.textContent || 'Review');
        current.querySelector('button,input,select')?.focus();
      } else if (!current && activeModal) { activeModal = null; previousFocus?.focus(); }
    });
    document.querySelectorAll('.modal-overlay').forEach(el => observer.observe(el,{attributes:true,attributeFilter:['style']}));
    document.addEventListener('keydown', event => {
      if (!activeModal) return;
      if (event.key === 'Escape') { activeModal.querySelector('.modal-close')?.click(); return; }
      if (event.key !== 'Tab') return;
      const focusable = [...activeModal.querySelectorAll('button,input,select,a[href],textarea,summary')].filter(el => !el.disabled && el.getClientRects().length);
      const first = focusable[0], last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    });
  };
  for (const method of ['renderWorkspace','updateStatePill','saveEntityModal','handleEntryPointChange']) {
    const original = w[method];
    w[method] = function(...args) {
      const result = original.apply(this,args);
      const after = () => {
        this.refreshGuide();
        const key = this.state.entryPointKey, meta = this.state.entryPointMetadata?.[key];
        const profEl = document.getElementById('profileExplanation');
        if (profEl) {
          profEl.textContent = key ? this.profileLabel(key,meta) + '. Original Dutch profile: ' + (meta?.name || key) : 'Choose a profile deliberately; the app does not infer your legal reporting obligations.';
        }
      };
      if (result?.then) return result.then(value => {after(); return value;});
      after(); return result;
    };
  }
})();
