const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const nodes = new Map();
const el = id => {
  if (!nodes.has(id)) nodes.set(id, {value:'', style:{}, innerText:'', textContent:'', disabled:false});
  return nodes.get(id);
};
let requests = [];
const sandbox = {setTimeout,clearTimeout,window:{}, document:{getElementById:el}, console, alert:message=>{throw new Error(message);},
  fetch:async (url, options)=>{
    requests.push({url, options});
    return {ok:true,json:async()=>({fact_id:'server-id',qname:'t:Flag'})};
  }};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('app/frontend/workspace.js','utf8'),sandbox);
const w = sandbox.window.workspace;
w.renderWorkspace=()=>{}; w.fetchRequirements=async()=>{}; w.setNavStatus=()=>{};w._enablePostDocButtons=()=>{};
assert.equal(w._parseAmount('1.234,56','nl'),'1234.56');
assert.equal(w._parseAmount('(1,234.56)','en'),'-1234.56');
assert.throws(()=>w._parseAmount('1,234.56','nl'));
Object.assign(w.state,{filingId:'filing',kvkNumber:'12345678',periodStart:'2026-04-01',periodEnd:'2027-03-31',
  document:{sha256:'a'.repeat(64),nodes:[{id:'t1',kind:'table',location:'body table 1',rows:[['Flag','true']]}]},_pendingNodeId:'t1-r0c1'});
el('mapQname').value='t:Flag';el('mapKind').value='boolean';el('mapValue').value='true';el('mapContextId').value='ctx_current';el('mapReviewer').value='Reviewer';
(async()=>{
  await w.submitMapFact();
  const payload=JSON.parse(requests[0].options.body);
  assert.equal(payload.decision.source_node_id,'t1');
  assert.equal(payload.decision.source_location,'body table 1, Row 1, Col 2');
  assert.equal(payload.decision.value,true);
  assert.equal(w._buildContext('ctx_prior').start_date,'2025-04-01');
  assert.equal(w._buildContext('ctx_prior').end_date,'2026-03-31');
  assert.throws(()=>w._buildContext('unknown'));
  const snap={filing_id:'saved',kvk_number:'12345678',entity_name:'Test',period_start:'2026-01-01',period_end:'2026-12-31',
    taxonomy_id:'test',entry_point_key:'ep',state:'draft',document:w.state.document,
    facts:[{id:'saved-fact',qname:'t:Flag',kind:'boolean',value:true,context_id:'ctx_current',source:{location:'body table 1, Row 1, Col 2',reviewer:'Reviewer'}}]};
  w._restoreSnapshot(snap);
  assert.equal(w.state.filingId,'saved');
  assert.equal(w.state.mappings['t1-r0c1'].factId,'saved-fact');
  // Reattaching an identical source must not create another snapshot.
  sandbox.FormData = class {append(){}};
  let created=false;w.createSnapshot=async()=>{created=true};
  sandbox.fetch=async url=>({ok:true,json:async()=>url.includes('/extract')?snap.document:{...snap,document_sha256:snap.document.sha256}});
  await w.handleFileUpload({target:{files:[{}],value:'source'}});
  assert.equal(created,false);assert.equal(w.state.filingId,'saved');
  sandbox.fetch=async()=>({ok:true,json:async()=>({})});
  w.openEntityModal=()=>{};
  await w.newFiling();
  assert.equal(w.state.filingId,null);
  assert.equal(w.state.document,null);
  // Checklist defaults exclude optional concepts, while catalogue search retains them.
  w.state.checklistSections = [{title_nl:'Balance sheet', total:2, satisfied:0, items:[
    {concept_qname:'t:Assets',label_nl:'Activa',label_en:'Assets',status:'mandatory',rule_ids:[]},
    {concept_qname:'t:Other',label_nl:'Overige',label_en:'Other',status:'optional',rule_ids:[]}]}];
  el('checklistFilter').value='outstanding'; w.renderChecklist();
  assert(el('checklistContainer').innerHTML.includes('t:Assets'));
  assert(!el('checklistContainer').innerHTML.includes('t:Other'));
  el('checklistFilter').value='all'; w.renderChecklist();
  assert(el('checklistContainer').innerHTML.includes('t:Other'));
  // Suggestions with no explicit year require a period choice; skipping never maps.
  w.openMapFactModal=()=>{};
  w.state.periodEnd='2026-12-31';
  w.state.pendingRecommendations=[{source_node_id:'t',row_index:1,col_index:1,qname:'t:Assets',value:'1234',kind:'numeric',period_type:'instant',year_hint:null}];
  w._openNextRecommendation();
  assert.equal(el('mapContextId').value,'');
  const beforeSkip=requests.length;
  w.skipSuggestion();
  assert.equal(requests.length,beforeSkip);
  assert.equal(w.state.pendingRecommendations.length,0);
  w.cancelTagReview();
  assert.equal(w.state._reviewingSuggestion,false);
  console.log('Workspace regression checks passed: numbers, manual boolean/cell mapping, periods, restore, source reattachment.');
})().catch(e=>{console.error(e);process.exitCode=1;});
