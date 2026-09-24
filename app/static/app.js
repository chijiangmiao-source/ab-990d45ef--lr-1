"use strict";
/* 束线控制文法 LR(1) 复核页。草稿保留在 localStorage；每次复核带版本号，
   草稿修改或取消后返回的过期结果不得改写当前结论。 */

const FIELDS = ["terminals", "nonterminals", "start", "productions"];
const DRAFT_KEY = "grammar-review-draft-v1";

const SAMPLE_OK = {
  terminals: "int float = + ( ) ;",
  nonterminals: "S T D L",
  start: "S",
  productions: [
    "S -> T ;",
    "T -> D",
    "D -> L = int",
    "L -> L + float",
    "L -> float",
  ].join("\n"),
};

const SAMPLE_CONFLICT = {
  terminals: "if else expr then",
  nonterminals: "S E",
  start: "S",
  productions: ["S -> if E then S", "S -> if E then S else S", "S -> expr"].join("\n"),
};

const $ = (id) => document.getElementById(id);
const els = {};

let draftTimer = null;
let requestSeq = 0;
let inflightSeq = 0;
let controller = null;
let lastAcceptedSeq = 0;

// ------------------------------------------------------------ 草稿

function readDraft() {
  const draft = {};
  for (const f of FIELDS) draft[f] = els[f].value;
  return draft;
}

function writeDraft(flash) {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify(readDraft()));
    els["draft-state"].textContent = flash ? "草稿已保存" : "草稿自动保留中";
  } catch (e) {
    els["draft-state"].textContent = "草稿无法写入本地存储";
  }
  // 草稿变更：使任何在途 / 已展示结果过期
  invalidateResults("草稿已修改");
}

function loadDraft() {
  let saved = null;
  try {
    saved = JSON.parse(localStorage.getItem(DRAFT_KEY) || "null");
  } catch (e) {
    saved = null;
  }
  if (saved && typeof saved === "object") {
    for (const f of FIELDS) if (typeof saved[f] === "string") els[f].value = saved[f];
    els["draft-state"].textContent = "已恢复上次草稿";
  }
}

function fillSample(sample) {
  for (const f of FIELDS) els[f].value = sample[f];
  writeDraft(true);
  resetView();
}

// ------------------------------------------------------------ 过期防护

function invalidateResults(reason) {
  if (inflightSeq !== 0) {
    // 标记在途请求为过期；AbortController 用于取消计算
    if (controller) {
      controller.abort();
      controller = null;
    }
    inflightSeq = 0;
    setBusy(false);
  }
  if (lastAcceptedSeq !== 0) {
    $("stale-note").hidden = false;
    $("stale-note").textContent = `${reason}：以下为过期结果，不代表当前结论。`;
  }
}

function setBusy(busy) {
  $("btn-review").disabled = busy;
  $("btn-cancel").disabled = !busy;
  const banner = $("status-banner");
  if (busy) {
    banner.className = "banner busy";
    banner.textContent = "复核计算中……";
  }
}

function resetView() {
  lastAcceptedSeq = 0;
  $("stale-note").hidden = true;
  for (const id of ["error-panel", "warning-panel", "conflict-panel", "analysis-panel"]) {
    $(id).hidden = true;
  }
  const banner = $("status-banner");
  banner.className = "banner idle";
  banner.textContent = "尚未复核。编辑文法后点击「发起复核」。草稿会自动保留在本浏览器。";
}

// ------------------------------------------------------------ 复核

async function runReview() {
  // 发起前先落盘草稿
  writeDraft(false);
  $("stale-note").hidden = true;

  const seq = ++requestSeq;
  inflightSeq = seq;
  controller = new AbortController();
  setBusy(true);

  try {
    const resp = await fetch("/api/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readDraft()),
      signal: controller.signal,
    });
    const data = await resp.json();
    // 过期结果（期间改了草稿或点了取消）不得改写当前结论
    if (seq !== requestSeq || inflightSeq !== seq) return;
    lastAcceptedSeq = seq;
    inflightSeq = 0;
    controller = null;
    setBusy(false);
    render(data);
  } catch (err) {
    if (seq !== requestSeq || inflightSeq !== seq) return;
    inflightSeq = 0;
    controller = null;
    setBusy(false);
    if (err.name === "AbortError") {
      showCancelStale();
    } else {
      const banner = $("status-banner");
      banner.className = "banner error";
      banner.textContent = `复核请求失败：${err.message}`;
    }
  }
}

function cancelReview() {
  requestSeq++; // 使在途请求版本立即失效
  if (controller) {
    controller.abort();
    controller = null;
  }
  inflightSeq = 0;
  setBusy(false);
  showCancelStale();
}

function showCancelStale() {
  const banner = $("status-banner");
  banner.className = "banner idle";
  banner.textContent = "计算已取消。";
  if (lastAcceptedSeq !== 0) {
    $("stale-note").hidden = false;
    $("stale-note").textContent = "计算已取消：以下为过期结果，不代表当前结论。";
  }
}

// ------------------------------------------------------------ 渲染

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function renderIssues(listEl, issues) {
  listEl.innerHTML = "";
  for (const e of issues) {
    const li = document.createElement("li");
    const where = [];
    if (e.line != null) where.push(`第 ${e.line} 行`);
    if (e.symbol != null) where.push(`符号 ${e.symbol}`);
    li.innerHTML = `<span class="code">${esc(e.code)}</span>` +
      (where.length ? `<strong>${esc(where.join("，"))}</strong>：` : "") +
      esc(e.message);
    listEl.appendChild(li);
  }
}

function render(data) {
  const banner = $("status-banner");
  renderIssues($("error-list"), data.errors || []);
  renderIssues($("warning-list"), data.warnings || []);
  $("error-panel").hidden = !(data.errors && data.errors.length);
  $("warning-panel").hidden = !(data.warnings && data.warnings.length);

  const hasInputErrors = data.errors && data.errors.length > 0;
  const conflict = data.analysis ? data.analysis.conflict : null;
  $("conflict-panel").hidden = !conflict;
  $("analysis-panel").hidden = !data.analysis || hasInputErrors;

  if (hasInputErrors) {
    banner.className = "banner error";
    banner.textContent = `文法输入存在 ${data.errors.length} 个问题，未进入 LR(1) 构造。`;
    return;
  }
  if (conflict) {
    banner.className = "banner conflict";
    banner.textContent = `发现 ${conflict.kindText}冲突：首个冲突位于状态 ${conflict.state}，展望符 ${conflict.lookahead}。该文法不能直接上线。`;
    renderConflict(conflict);
  } else if (data.analysis) {
    banner.className = "banner ok";
    banner.textContent = `复核通过：规范 LR(1) 无冲突，共 ${data.analysis.states.length} 个项目集，文法可用。`;
  }
  if (data.analysis) renderAnalysis(data.analysis);
}

function renderConflict(c) {
  const card = $("conflict-card");
  const items = c.items.map((it) => esc(it.text)).join("<br>");
  card.innerHTML =
    `<span class="kind">${esc(c.kindText)}冲突</span>` +
    `<dl>
       <dt>状态编号</dt><dd>I${c.state}</dd>
       <dt>展望符</dt><dd>${esc(c.lookahead)}</dd>
       <dt>活前缀</dt><dd>${c.prefix.length ? esc(c.prefix.join(" ")) : "ε（初始态）"}</dd>
       <dt>竞争项目</dt><dd>${items}</dd>
       <dt>两项动作</dt><dd>${esc(c.actions[0])}<br>${esc(c.actions[1] || "")}</dd>
     </dl>
     <p class="evidence"><strong>可核查前缀证据：</strong>${esc(c.evidence)}</p>`;
}

function renderAnalysis(a) {
  // nullable / FIRST
  const nf = $("nullable-first");
  nf.innerHTML = "";
  const nullable = new Set(a.nullable);
  for (const sym of Object.keys(a.first)) {
    const div = document.createElement("div");
    div.className = "nf-cell";
    const firstVals = a.first[sym].length ? a.first[sym].join(", ") : "（无）";
    div.innerHTML = `<span class="sym">${esc(sym)}</span>` +
      (nullable.has(sym) ? '<span class="null-tag">nullable</span>' : "") +
      `<div class="vals">FIRST = { ${esc(firstVals)} }</div>`;
    nf.appendChild(div);
  }

  // 项目集
  const states = $("states");
  states.innerHTML = "";
  const conflictState = a.conflict ? a.conflict.state : -1;
  for (const st of a.states) {
    const det = document.createElement("details");
    det.className = "state-block";
    const gotoText = Object.entries(st.goto)
      .map(([sym, to]) => `${esc(sym)} → I${to}`).join("，");
    const prefix = st.prefix.length ? st.prefix.join(" ") : "ε";
    det.open = st.id === 0 || st.id === conflictState;
    det.innerHTML =
      `<summary class="${st.id === conflictState ? "conflict-state" : ""}">` +
      `I${st.id} <span class="meta">活前缀：${esc(prefix)}｜goto：${gotoText || "—"}` +
      (st.id === conflictState ? "｜⚠ 冲突状态" : "") +
      `</span></summary><ul></ul>`;
    const ul = det.querySelector("ul");
    for (const it of st.items) {
      const li = document.createElement("li");
      li.textContent = it.text;
      ul.appendChild(li);
    }
    states.appendChild(det);
  }

  // 动作表
  const las = a.actionTable.lookaheads;
  const thead = $("actionTable").querySelector("thead");
  const tbody = $("actionTable").querySelector("tbody");
  thead.innerHTML = "";
  tbody.innerHTML = "";
  const hr = document.createElement("tr");
  hr.innerHTML = `<th class="state-id">状态</th>` + las.map((s) => `<th>${esc(s)}</th>`).join("");
  thead.appendChild(hr);
  a.actionTable.rows.forEach((row, sid) => {
    const tr = document.createElement("tr");
    let html = `<td class="state-id">I${sid}</td>`;
    for (const s of las) {
      const cell = row[s];
      if (!cell) {
        html += "<td></td>";
      } else if (cell.conflict) {
        html += `<td class="cell-conflict" title="冲突">${esc(cell.actions.join(" / "))}</td>`;
      } else if (cell.action === "acc") {
        html += `<td class="cell-acc">acc</td>`;
      } else {
        html += `<td>${esc(cell.action)}</td>`;
      }
    }
    tr.innerHTML = html;
    tbody.appendChild(tr);
  });
}

// ------------------------------------------------------------ 初始化

function bind() {
  for (const f of FIELDS) els[f] = $(f);
  for (const f of FIELDS) {
    els[f].addEventListener("input", () => {
      clearTimeout(draftTimer);
      els["draft-state"].textContent = "草稿编辑中…";
      draftTimer = setTimeout(writeDraft, 300);
    });
  }
  $("btn-review").addEventListener("click", runReview);
  $("btn-cancel").addEventListener("click", cancelReview);
  $("btn-sample-ok").addEventListener("click", () => fillSample(SAMPLE_OK));
  $("btn-sample-conflict").addEventListener("click", () => fillSample(SAMPLE_CONFLICT));
  $("btn-clear").addEventListener("click", () => {
    for (const f of FIELDS) els[f].value = "";
    writeDraft(true);
    resetView();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bind();
  loadDraft();
});
