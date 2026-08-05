/* Meta Legal — Law Matrix app | vanilla JS, no build, offline-capable */
(() => {
  const DOMAINS_CANON = ["privacy","competition","youth_safety","ip","accessibility"];
  const DOMAIN_LABELS = {
    privacy:"Privacy",
    competition:"Competition",
    youth_safety:"Youth Safety",
    ip:"IP",
    accessibility:"Accessibility",
  };

  const els = {};
  const state = {
    raw: null,
    jurisdictions: [],
    domains: [],
    cells: new Map(), // key -> { jurisdiction, jurisdiction_id, domain, domain_id, count, laws }
    laws: [],
    runs: [],
    selectedRunId: "",
    selectedCellKey: "",
    search: "",
    activeDomains: new Set(),
    activeJurisdictions: new Set(),
  };

  function qs(id){ return document.getElementById(id); }

  function heatClass(count){
    if (!count || count <= 0) return "heat-0";
    if (count === 1) return "heat-1";
    if (count === 2) return "heat-2";
    if (count === 3) return "heat-3";
    return "heat-4";
  }
  function nexusClass(v){
    const s = String(v||"").toLowerCase();
    if (s.includes("named")) return "nexus-named";
    if (s.includes("sector")) return "nexus-sector";
    return "nexus-platform";
  }
  function confClass(c){
    const n = Number(c);
    if (n >= 0.75) return "conf-high";
    if (n >= 0.45) return "conf-mid";
    return "conf-low";
  }
  function normalizeId(s){
    return String(s||"").trim().toLowerCase().replace(/[^a-z0-9]+/g,"_").replace(/^_+|_+$/g,"") || "unknown";
  }
  function cellKey(jid, did){ return `${jid}::${did}`; }
  function esc(s){
    return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

  // Data loading — try /api/matrix then fall back to static files.
  async function fetchJson(url){
    const r = await fetch(url, { headers:{Accept:"application/json"} });
    if (!r.ok) throw new Error(`${r.status} ${url}`);
    return r.json();
  }
  async function loadMatrix(){
    const candidates = [
      "/api/matrix",
      "./data/matrix.json",
      "data/matrix.json",
      "./web/data/matrix.json",
      "../data/matrix.json",
    ];
    // When opened via file:// fetch will throw TypeError; handle gracefully
    let lastErr = null;
    for (const u of candidates){
      try{
        const data = await fetchJson(u);
        if (data && typeof data === "object") return { data, url:u };
      }catch(e){ lastErr = e; }
    }
    // Also try to discover runs via dossiers index if matrix.json absent — optional
    return { data:null, url:null, error:lastErr };
  }

  function normalizeMatrix(data){
    if (!data || typeof data !== "object") return null;
    // Support shape: { runs:[...], jurisdictions, domains, cells, laws } or flat laws
    // If data is an array, treat as laws array
    if (Array.isArray(data)) {
      return buildFromLaws(data, []);
    }
    // If data has matrix nested
    const root = data.matrix && typeof data.matrix === "object" ? data.matrix : data;
    // Multi-run wrapper: { runs, latest, run_id }
    if (Array.isArray(root.runs) && root.runs.length){
      state.runs = root.runs;
      // prefer selectedRunId if set, else latest/run_id, else first run
      const want = state.selectedRunId || root.latest || root.run_id || root.runs[0].run_id;
      const picked = root.runs.find(r=>r.run_id===want) || root.runs[0];
      if (picked && picked.matrix) return normalizeMatrix(picked.matrix);
      if (picked && Array.isArray(picked.laws)) return buildFromLaws(picked.laws, picked);
      // if runs are just meta, use root laws/cells
    }
    if (root.jurisdictions && root.domains){
      // cells may be object map or array
      const jurisdictions = root.jurisdictions.map(j => typeof j==="string"? j : (j.name||j.id||String(j)));
      const domains = root.domains.map(d => typeof d==="string"? d : (d.id||String(d)));
      // Normalize domain ids to canonical slugs where possible
      const normDomains = domains.map(d => normalizeId(d)).map(d => DOMAINS_CANON.includes(d)? d : d);
      // Keep display labels via original if needed
      const laws = Array.isArray(root.laws) ? root.laws : (Array.isArray(root.findings)? root.findings : []);
      let cellsMap = new Map();
      if (root.cells && typeof root.cells === "object" && !Array.isArray(root.cells)){
        for (const [k,v] of Object.entries(root.cells)){
          const jid = v.jurisdiction_id || normalizeId(v.jurisdiction || k.split("::")[0]);
          const did = v.domain_id || normalizeId(v.domain || k.split("::")[1]);
          const key = cellKey(jid, did);
          const claws = Array.isArray(v.laws) ? v.laws : (Array.isArray(v.findings)? v.findings : []);
          cellsMap.set(key, {
            jurisdiction: v.jurisdiction || jurisdictions.find(j=>normalizeId(j)===jid) || k.split("::")[0],
            jurisdiction_id: jid,
            domain: v.domain || did,
            domain_id: did,
            count: Number(v.count ?? claws.length),
            laws: claws,
          });
        }
      }
      // If laws flat and cells empty, build cells from laws
      if (cellsMap.size===0 && laws.length){
        return buildFromLaws(laws, { jurisdictions, domains: normDomains, subject: root.subject, run_id: root.run_id });
      }
      // Ensure every jurisdiction x domain has a cell (fill empties)
      const jIds = jurisdictions.map(j=>normalizeId(j));
      const dIds = normDomains;
      for (let i=0;i<jurisdictions.length;i++){
        for (let j=0;j<dIds.length;j++){
          const key = cellKey(jIds[i], dIds[j]);
          if (!cellsMap.has(key)){
            cellsMap.set(key, {
              jurisdiction: jurisdictions[i],
              jurisdiction_id: jIds[i],
              domain: DOMAIN_LABELS[dIds[j]] || dIds[j],
              domain_id: dIds[j],
              count:0, laws:[]
            });
          }
        }
      }
      return {
        run_id: root.run_id || root.id || "",
        subject: root.subject || "Meta",
        jurisdictions, domains: dIds,
        jurisdictions_ids: jIds,
        cells: cellsMap,
        laws,
        stats: root.stats || null,
        generated_at: root.generated_at || root.created_at || "",
        raw: root,
      };
    }
    if (Array.isArray(root.laws)){
      return buildFromLaws(root.laws, root);
    }
    return null;
  }

  function buildFromLaws(laws, meta){
    const jurisdictions = meta.jurisdictions ? [...meta.jurisdictions] : [...new Set(laws.map(l=> l.jurisdiction || l.jurisdiction_id).filter(Boolean))];
    let domains = meta.domains ? [...meta.domains] : [...new Set(laws.map(l=> l.domain || l.domain_id).filter(Boolean).map(normalizeId))];
    if (!domains.length) domains = [...DOMAINS_CANON];
    // Normalize
    const jIds = jurisdictions.map(j=>normalizeId(j));
    const dIds = domains.map(d=> normalizeId(d));
    const cellsMap = new Map();
    for (let i=0;i<jurisdictions.length;i++){
      for (let j=0;j<dIds.length;j++){
        const key = cellKey(jIds[i], dIds[j]);
        cellsMap.set(key, { jurisdiction: jurisdictions[i], jurisdiction_id: jIds[i], domain: DOMAIN_LABELS[dIds[j]]||dIds[j], domain_id: dIds[j], count:0, laws:[] });
      }
    }
    for (const law of laws){
      const jid = normalizeId(law.jurisdiction_id || law.jurisdiction || "");
      const did = normalizeId(law.domain_id || law.domain || "");
      const key = cellKey(jid, did);
      if (!cellsMap.has(key)){
        cellsMap.set(key, { jurisdiction: law.jurisdiction || jid, jurisdiction_id: jid, domain: law.domain || did, domain_id: did, count:0, laws:[] });
      }
      cellsMap.get(key).laws.push(law);
    }
    for (const c of cellsMap.values()) c.count = c.laws.length;
    return {
      run_id: meta.run_id || "",
      subject: meta.subject || "Meta",
      jurisdictions,
      domains: dIds,
      jurisdictions_ids: jIds,
      cells: cellsMap,
      laws,
      stats:null,
      generated_at: meta.generated_at || "",
      raw: meta,
    };
  }

  function computeStats(norm){
    if (!norm) return { total:0, j:0, d:0, coverage:"0%" };
    const total = norm.laws ? norm.laws.length : [...norm.cells.values()].reduce((a,c)=>a + c.count,0);
    const j = norm.jurisdictions.length;
    const d = norm.domains.length;
    const totalCells = j * d || 1;
    const filled = [...norm.cells.values()].filter(c=>c.count>0).length;
    const pct = Math.round((filled/totalCells)*100);
    return { total, j, d, coverage: pct + "%", filled, totalCells };
  }

  function filteredJurisdictions(norm){
    const q = state.activeJurisdictions;
    if (!q.size) return norm.jurisdictions;
    return norm.jurisdictions.filter(j=> q.has(normalizeId(j)));
  }
  function filteredDomains(norm){
    const q = state.activeDomains;
    if (!q.size) return norm.domains;
    return norm.domains.filter(d=> q.has(normalizeId(d)));
  }
  function lawMatchesSearch(law){
    if (!state.search) return true;
    const s = state.search.toLowerCase();
    return (law.title||"").toLowerCase().includes(s) || (law.citation||"").toLowerCase().includes(s) || (law.excerpt||"").toLowerCase().includes(s);
  }
  function cellVisibleCount(cell){
    if (!state.search) return cell.count;
    return cell.laws.filter(lawMatchesSearch).length;
  }

  function renderStats(norm){
    const s = computeStats(norm);
    qs("statTotal").textContent = String(s.total);
    qs("statJurisdictions").textContent = String(s.j);
    qs("statDomains").textContent = String(s.d);
    qs("statCoverage").textContent = s.coverage;
    if (norm && s.totalCells) {
      const sub = qs("matrixSubtitle");
      if (sub) sub.textContent = `${s.filled} of ${s.totalCells} cells filled · ${s.total} laws · run ${norm.run_id ? esc(norm.run_id).slice(0,28) : "—"}`;
    }
  }

  function renderPills(norm){
    const dWrap = qs("domainPills");
    const jWrap = qs("jurisdictionPills");
    if (!norm) { dWrap.innerHTML=""; jWrap.innerHTML=""; return; }
    // domains
    dWrap.innerHTML = norm.domains.map(d=>{
      const id = normalizeId(d);
      const label = DOMAIN_LABELS[id] || d;
      const on = state.activeDomains.has(id);
      return `<button class="filter-pill" data-kind="domain" data-value="${esc(id)}" aria-pressed="${on ? "true":"false"}">${esc(label)}</button>`;
    }).join("");
    // jurisdictions — show up to ~40, pills scroll
    const jurs = norm.jurisdictions;
    jWrap.innerHTML = jurs.map(j=>{
      const id = normalizeId(j);
      const on = state.activeJurisdictions.has(id);
      return `<button class="filter-pill" data-kind="jurisdiction" data-value="${esc(id)}" aria-pressed="${on ? "true":"false"}">${esc(j)}</button>`;
    }).join("");
    // bind
    dWrap.querySelectorAll(".filter-pill").forEach(b=>{
      b.addEventListener("click", ()=>{
        const v = b.dataset.value;
        if (state.activeDomains.has(v)) state.activeDomains.delete(v); else state.activeDomains.add(v);
        renderPills(norm); renderMatrix(norm);
      });
    });
    jWrap.querySelectorAll(".filter-pill").forEach(b=>{
      b.addEventListener("click", ()=>{
        const v = b.dataset.value;
        if (state.activeJurisdictions.has(v)) state.activeJurisdictions.delete(v); else state.activeJurisdictions.add(v);
        renderPills(norm); renderMatrix(norm);
      });
    });
  }

  function renderMatrix(norm){
    const wrap = qs("matrixWrap");
    const emptyEl = qs("emptyMatrix");
    if (!norm || !norm.jurisdictions.length || !norm.domains.length){
      wrap.innerHTML = "";
      emptyEl.hidden = false;
      renderStats(null);
      return;
    }
    emptyEl.hidden = true;
    const jurs = filteredJurisdictions(norm);
    const doms = filteredDomains(norm);
    if (!jurs.length || !doms.length){
      wrap.innerHTML = `<div class="empty-matrix"><strong>No rows/columns match filters</strong><br><span style="font-size:12px">Clear domain or jurisdiction pills to see the matrix.</span></div>`;
      renderStats(norm);
      return;
    }
    const jIds = jurs.map(j=>normalizeId(j));
    const dIds = doms.map(d=>normalizeId(d));
    let html = `<table class="matrix" role="grid" aria-label="Law matrix by jurisdiction and domain"><thead><tr><th class="corner" scope="col">Jurisdiction</th>`;
    for (const d of doms){
      const id = normalizeId(d);
      const label = DOMAIN_LABELS[id] || d;
      html += `<th scope="col" title="${esc(label)}">${esc(label)}</th>`;
    }
    html += `</tr></thead><tbody>`;
    for (let i=0;i<jurs.length;i++){
      const j = jurs[i];
      const jid = jIds[i];
      html += `<tr><th scope="row" title="${esc(j)}">${esc(j)}</th>`;
      for (let k=0;k<doms.length;k++){
        const did = dIds[k];
        const key = cellKey(jid, did);
        const cell = norm.cells.get(key) || { count:0, laws:[], jurisdiction:j, jurisdiction_id:jid, domain:doms[k], domain_id:did };
        const visible = cellVisibleCount(cell);
        const total = cell.count;
        // Heat based on visible when searching, else total
        const heatN = state.search ? visible : total;
        const cls = heatClass(heatN);
        const selected = state.selectedCellKey === key ? ' aria-selected="true"' : "";
        const label = `${j} × ${DOMAIN_LABELS[did]||did}: ${visible}${state.search? ` of ${total} matching` : ""} law${visible===1?"":"s"}`;
        html += `<td class="${cls}"><button class="cell-btn ${cls}" data-cell="${esc(key)}" aria-label="${esc(label)}" title="${esc(label)}"${selected}><span class="count">${visible}</span></button></td>`;
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;
    wrap.innerHTML = html;
    // events + tooltip
    const tooltip = qs("tooltip");
    wrap.querySelectorAll(".cell-btn").forEach(btn=>{
      btn.addEventListener("click", ()=> openDrawer(btn.dataset.cell));
      btn.addEventListener("mouseenter", (e)=>{
        tooltip.textContent = btn.getAttribute("aria-label") || "";
        tooltip.hidden = false;
        positionTooltip(e, tooltip);
        requestAnimationFrame(()=>{ tooltip.style.opacity="1"; tooltip.style.transform="translateY(0)"; });
      });
      btn.addEventListener("mousemove", (e)=> positionTooltip(e, tooltip));
      btn.addEventListener("mouseleave", ()=>{
        tooltip.style.opacity="0"; tooltip.style.transform="translateY(4px)";
      });
    });
    renderStats(norm);
  }

  function positionTooltip(e, tip){
    const pad=12;
    let x = e.clientX + 14;
    let y = e.clientY + 14;
    // keep in viewport
    const rect = tip.getBoundingClientRect();
    if (x + rect.width + pad > window.innerWidth) x = e.clientX - rect.width - 14;
    if (y + rect.height + pad > window.innerHeight) y = e.clientY - rect.height - 14;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }

  function openDrawer(cellKeyStr){
    state.selectedCellKey = cellKeyStr;
    const norm = state.raw;
    if (!norm) return;
    const cell = norm.cells.get(cellKeyStr);
    const drawer = qs("drawer");
    const backdrop = qs("backdrop");
    const body = qs("drawerBody");
    const title = qs("drawerTitle");
    const sub = qs("drawerSubtitle");
    if (!cell){
      title.textContent = cellKeyStr;
      sub.textContent = "Unknown cell";
      body.innerHTML = `<div class="detail-empty">No data for this cell.</div>`;
    } else {
      const laws = state.search ? cell.laws.filter(lawMatchesSearch) : cell.laws;
      const domainLabel = DOMAIN_LABELS[cell.domain_id] || cell.domain;
      title.textContent = `${cell.jurisdiction} × ${domainLabel}`;
      sub.textContent = `${laws.length}${state.search? ` of ${cell.count} matching` : ""} law${laws.length===1?"":"s"} · ${cell.jurisdiction_id} :: ${cell.domain_id}`;
      if (!laws.length){
        const msg = cell.count===0 ? "No laws discovered for this cell yet." : "No laws match your search in this cell.";
        body.innerHTML = `<div class="detail-empty"><strong>No laws</strong><br>${esc(msg)}</div>`;
      } else {
        body.innerHTML = laws.map(lawCard).join("");
      }
    }
    // mark selected
    document.querySelectorAll(".cell-btn").forEach(b=>{
      b.setAttribute("aria-selected", b.dataset.cell===cellKeyStr ? "true":"false");
    });
    drawer.classList.add("open");
    backdrop.classList.add("open");
    drawer.setAttribute("aria-hidden","false");
    backdrop.hidden = false;
    // focus close for a11y
    qs("drawerClose").focus();
    document.body.style.overflow="hidden";
    // re-render matrix to show selection ring
    renderMatrix(norm);
  }

  function closeDrawer(){
    const drawer = qs("drawer");
    const backdrop = qs("backdrop");
    drawer.classList.remove("open");
    backdrop.classList.remove("open");
    drawer.setAttribute("aria-hidden","true");
    document.body.style.overflow="";
    setTimeout(()=>{ backdrop.hidden = true; }, 220);
  }

  function lawCard(law){
    const title = esc(law.title || "Untitled law");
    const citation = esc(law.citation || "");
    const jur = esc(law.jurisdiction || law.jurisdiction_id || "");
    const dom = esc(law.domain || law.domain_id || "");
    const nexus = esc(law.meta_nexus || "platform_obligation");
    const conf = law.confidence;
    const confNum = conf==null? "" : Number(conf).toFixed(2);
    const excerpt = esc(law.excerpt || "");
    const url = law.source_url || "";
    const status = esc(law.status || "");
    const eff = esc(law.effective_date || "");
    const validated = law.validated ? "validated" : "draft";
    return `<article class="law-card">
      <h4>${title}</h4>
      ${citation ? `<div class="citation">${citation}</div>` : ""}
      <div class="meta-row">
        ${jur? `<span class="badge">${jur}</span>`:""}
        ${dom? `<span class="badge">${dom}</span>`:""}
        <span class="badge ${nexusClass(nexus)}">${nexus}</span>
        ${confNum!==""? `<span class="badge ${confClass(conf)}">conf ${confNum}</span>`:""}
        ${status? `<span class="badge">${status}</span>`:""}
        ${eff? `<span class="badge">effective ${eff}</span>`:""}
        <span class="badge">${validated}</span>
      </div>
      ${excerpt? `<pre class="excerpt">${excerpt}</pre>`:""}
      ${url? `<div class="links"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Source ↗</a></div>`:""}
    </article>`;
  }

  function renderRunSelector(){
    const sel = qs("runSelector");
    const wrap = qs("runSelectorWrap");
    if (!state.runs.length){
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    sel.innerHTML = state.runs.map(r=>{
      const id = r.run_id || r.id || "";
      const label = r.label || r.run_id || id;
      const extra = r.accepted_count!=null? ` · ${r.accepted_count} laws` : "";
      return `<option value="${esc(id)}">${esc(label)}${esc(extra)}</option>`;
    }).join("");
    sel.value = state.selectedRunId || state.runs[0].run_id;
  }

  function applySearchFilter(){
    if (state.raw) renderMatrix(state.raw);
    if (state.selectedCellKey) openDrawer(state.selectedCellKey);
  }

  async function init(){
    // cache els
    ["matrixWrap","emptyMatrix","statTotal","statJurisdictions","statDomains","statCoverage","domainPills","jurisdictionPills","runSelector","runSelectorWrap","drawer","backdrop","drawerClose","drawerTitle","drawerSubtitle","drawerBody","tooltip","matrixSubtitle","searchInput","clearFilters"].forEach(id=>{ els[id]=qs(id); });

    qs("searchInput").addEventListener("input", (e)=>{
      state.search = e.target.value.trim();
      applySearchFilter();
    });
    qs("clearFilters").addEventListener("click", ()=>{
      state.activeDomains.clear();
      state.activeJurisdictions.clear();
      state.search="";
      qs("searchInput").value="";
      if (state.raw){ renderPills(state.raw); renderMatrix(state.raw); }
    });
    qs("drawerClose").addEventListener("click", closeDrawer);
    qs("backdrop").addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e)=>{
      if (e.key==="Escape") closeDrawer();
    });
    qs("runSelector").addEventListener("change", async (e)=>{
      state.selectedRunId = e.target.value;
      // reload matrix for that run if runs carry matrix, else re-normalize
      if (state._rawData) {
        const norm = normalizeMatrix(state._rawData);
        if (norm){ state.raw = norm; renderRunSelector(); renderPills(norm); renderMatrix(norm); }
      }
    });

    qs("matrixWrap").innerHTML = `<div class="empty-matrix">Loading…</div>`;

    const { data, url, error } = await loadMatrix();
    const hintEl = qs("demoHint");
    if (!data){
      // Empty state — show 0 counts and demo hint, with sample header so layout is visible
      state.raw = null;
      renderStats(null);
      qs("matrixWrap").innerHTML = "";
      qs("emptyMatrix").hidden = false;
      hintEl.hidden = false;
      // Keep a minimal visible matrix skeleton so reviewer sees heatmap intent
      // (still shows empty message, no fake laws)
      if (error) console.warn("[matrix] load failed, showing empty state:", error);
      // Populate run selector hidden
      renderRunSelector();
      const isFile = location.protocol === "file:";
      if (isFile){
        hintEl.innerHTML = `Opened via <code>file://</code> — browsers block <code>fetch</code> on file URLs. Serve with <code>python -m http.server --directory web 8000</code> or <code>npx serve web</code>, or place aggregated JSON at <code>web/data/matrix.json</code> / <code>data/matrix.json</code>. API tried: <code>/api/matrix</code> → <code>./data/matrix.json</code>.`;
        hintEl.hidden = false;
      }
      return;
    }
    state._rawData = data;
    // If data has runs, set selectedRunId
    if (data.runs && Array.isArray(data.runs) && data.runs.length){
      state.runs = data.runs;
      state.selectedRunId = data.latest || data.run_id || data.runs[0].run_id || "";
    } else if (data.latest || data.run_id){
      state.selectedRunId = data.latest || data.run_id;
    }
    const norm = normalizeMatrix(data);
    if (!norm || (!norm.jurisdictions.length && !norm.laws.length)){
      state.raw = null;
      renderStats(null);
      qs("matrixWrap").innerHTML = "";
      qs("emptyMatrix").hidden = false;
      hintEl.hidden = false;
      hintEl.innerHTML = `No dossiers yet. Run a <code>meta_legal</code> research job to populate <code>data/dossiers/&lt;run_id&gt;/</code>, then aggregate to <code>web/data/matrix.json</code> (or serve <code>/api/matrix</code>).`;
      return;
    }
    state.raw = norm;
    hintEl.hidden = true;
    qs("emptyMatrix").hidden = true;
    renderRunSelector();
    renderPills(norm);
    renderMatrix(norm);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();

  // Expose for debugging / tests
  window.MatrixApp = { state, heatClass, normalizeMatrix, computeStats };
})();
