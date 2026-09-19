const originalFetch = window.fetch;
window.fetch = async function(...args) {
    const response = await originalFetch(...args);
    if (response.status === 401 && !window.location.pathname.includes('/login.html')) {
        window.location.href = '/login.html';
    }
    return response;
};

const API_BASE = '/api';
const esc = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');

let taxonomies = [];
let currentTaxonomyId = null;
let currentConcepts = [];

async function loadTaxonomies() {
    const tableBody = document.querySelector('#taxonomies-table tbody');
    try {
        const response = await fetch(`${API_BASE}/admin/taxonomies`);
        const data = await response.json();
        taxonomies = data.taxonomies;
        
        tableBody.innerHTML = '';
        
        if (taxonomies.length === 0) {
            tableBody.innerHTML = '<tr><td colspan="5">No taxonomies installed.</td></tr>';
            return;
        }
        
        taxonomies.forEach(t => {
            const tr = document.createElement('tr');
            tr.style.cursor = 'pointer';
            tr.onclick = () => loadExplorer(t.id);
            
            const activeBadge = !t.package_verified ? '<span style="color:#8a5b00">Preparation only</span>' : t.is_active ? '<span style="color:green">Active</span>' : 'Inactive';
            const shaPreview = t.sha256 ? `<br><small style="color:#64748b; font-family:monospace;">SHA-256: ${esc(t.sha256.substring(0, 12))}…</small>` : '';
            
            tr.innerHTML = `
                <td><strong>${esc(t.name)}</strong><br><small>${esc(t.id)}</small>${shaPreview}</td>
                <td>${esc(t.version)}</td>
                <td>${t.concept_count}</td>
                <td>${t.entry_point_count}</td>
                <td>${activeBadge}</td>
            `;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        tableBody.innerHTML = `<tr><td colspan="5" style="color:red">Error loading taxonomies: ${esc(err.message)}</td></tr>`;
    }
}

async function loadExplorer(taxId) {
    currentTaxonomyId = taxId;
    document.getElementById('explorer-status').style.display = 'none';
    document.getElementById('explorer-content').style.display = 'block';
    
    // Load entry points
    try {
        const res = await fetch(`${API_BASE}/taxonomy/${taxId}/entry-points`);
        const data = await res.json();
        const epSelect = document.getElementById('ep-select');
        epSelect.innerHTML = '<option value="">All Entry Points</option>';
        Object.keys(data.entry_points).forEach(ep => {
            const opt = document.createElement('option');
            opt.value = ep;
            opt.textContent = ep;
            epSelect.appendChild(opt);
        });
    } catch(err) {
        console.error("Error loading entry points", err);
    }
    
    loadConcepts(taxId, '');
}

async function loadConcepts(taxId, epKey) {
    const tbody = document.querySelector('#concepts-table tbody');
    tbody.innerHTML = '<tr><td colspan="5">Loading concepts...</td></tr>';
    
    let url = `${API_BASE}/taxonomy/${taxId}/concepts`;
    if (epKey) {
        url += `?entry_point_key=${encodeURIComponent(epKey)}`;
    }
    
    try {
        const res = await fetch(url);
        const data = await res.json();
        currentConcepts = data.concepts;
        renderConcepts();
    } catch(err) {
        tbody.innerHTML = `<tr><td colspan="5" style="color:red">Error loading concepts: ${esc(err.message)}</td></tr>`;
    }
}

function renderConcepts() {
    const tbody = document.querySelector('#concepts-table tbody');
    tbody.innerHTML = '';
    
    const query = document.getElementById('concept-search').value.toLowerCase();
    
    const filtered = currentConcepts.filter(c => {
        return c.qname.toLowerCase().includes(query) || 
               c.local_name.toLowerCase().includes(query) ||
               (c.label_nl && c.label_nl.toLowerCase().includes(query));
    });
    
    if (filtered.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5">No matching concepts found.</td></tr>';
        return;
    }
    
    // Only render first 200 for performance
    filtered.slice(0, 200).forEach(c => {
        const tr = document.createElement('tr');
        const prefix = c.qname.split(':')[0];
        
        let statusHtml = '';
        if (c.mandatory_status === 'mandatory') statusHtml = '<span class="status-badge status-mandatory">Mandatory</span>';
        else if (c.mandatory_status === 'conditional') statusHtml = '<span class="status-badge status-conditional">Conditional</span>';
        else statusHtml = '<span class="status-badge status-optional">Optional</span>';
        
        tr.innerHTML = `
            <td><span style="background:#eee;padding:2px 4px;border-radius:3px;font-size:11px">${esc(prefix)}</span></td>
            <td style="word-break:break-all">${esc(c.local_name)}</td>
            <td>${esc(c.label_nl || '-')}</td>
            <td>${statusHtml}</td>
            <td><small style="color:#666">${esc(c.condition_nl || (c.rule_ids.length > 0 ? 'See rules' : '-'))}</small></td>
        `;
        tbody.appendChild(tr);
    });
    
    if (filtered.length > 200) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="5" style="text-align:center;color:#666">... and ${filtered.length - 200} more. Use search to refine.</td>`;
        tbody.appendChild(tr);
    }
}

document.getElementById('concept-search').addEventListener('input', renderConcepts);
document.getElementById('ep-select').addEventListener('change', (e) => {
    if (currentTaxonomyId) {
        loadConcepts(currentTaxonomyId, e.target.value);
    }
});

// Init
window.onload = loadTaxonomies;
