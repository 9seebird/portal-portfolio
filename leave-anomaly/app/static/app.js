// 휴가 이상감지 · 화면 스크립트
// 서버 주소는 반드시 상대경로("api/...")로 부른다. 이 앱은 포털 아래 /leave-anomaly/ 로 붙기 때문에
// "/api/..." 처럼 슬래시로 시작하면 포털 최상위를 찾아가 404 가 난다.

let me = null;
let criteria = null;
let holidays = { official: {}, company: [] };
let result = { episodes: [], lowUsage: { rows: [], elapsedPct: 0, dayOfYear: 0 }, spikes: [], unknownAmPm: 0, meta: {} };
let view = "pattern";
let tierFilter = [];

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

async function api(path, options) {
  const res = await fetch(path, { cache: "no-store", ...options });
  let payload = null;
  try { payload = await res.json(); } catch { payload = null; }
  if (!res.ok) throw new Error((payload && payload.detail) || `요청 실패 (${res.status})`);
  return payload;
}

function showError(message) {
  const box = $("errNote");
  if (!message) { box.classList.add("hidden"); return; }
  box.textContent = message;
  box.classList.remove("hidden");
}

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function fmtDate(key) {
  if (!key) return "";
  const [y, m, d] = key.split("-").map(Number);
  const label = holidays.official[key] || (holidays.company.find((h) => h.date === key) || {}).name;
  const wd = "일월화수목금토"[new Date(y, m - 1, d).getDay()];
  return `${m}/${d}(${wd})${label ? ` ${label}` : ""}`;
}

function fmtDays(v) {
  const n = Math.round(Number(v) * 1000) / 1000;
  return Number.isFinite(n) ? String(n) : "0";
}

function orgLabel(org) {
  const parts = String(org || "").split(/[,/·]/).map((s) => s.trim()).filter(Boolean);
  if (!parts.length) return "";
  return parts.length > 1 ? `${parts[0]} 외 ${parts.length - 1}` : parts[0];
}

// ---------------------------------------------------------------------------
// 시작
// ---------------------------------------------------------------------------
async function boot() {
  $("refDate").value = todayKey();
  try {
    me = await api("api/me");
  } catch (error) {
    $("whoBox").textContent = "포털을 통해 접속해 주세요.";
    $("denyCard").hidden = false;
    return;
  }
  // 이 앱은 권한 구분 없이, 포털을 통해 접속한 사람이면 누구나 모든 기능을 쓸 수 있다.
  $("whoBox").textContent = `${me.name || me.id} · ${me.dept || "부서 미기재"}`;
  $("appBody").hidden = false;
  bindEvents();
  criteria = await api("api/criteria");
  renderCriteria();
  await refreshHolidays();
  await refreshDatasets();
  await runAnalysis();
}

function bindEvents() {
  mountUpload($("usageDrop"), $("usageFile"), "usage");
  mountUpload($("accrualDrop"), $("accrualFile"), "accrual");
  $("refDate").addEventListener("change", runAnalysis);
  $("btnReload").addEventListener("click", runAnalysis);
  $("btnDelUsage").addEventListener("click", () => removeDataset("usage"));
  $("btnDelAccrual").addEventListener("click", () => removeDataset("accrual"));
  $("btnAddHoliday").addEventListener("click", addHoliday);
  $("tabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-view]");
    if (!button) return;
    view = button.dataset.view;
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b === button));
    renderBody();
  });
}

function mountUpload(zone, input, kind) {
  input.addEventListener("change", () => {
    const file = input.files && input.files[0];
    if (file) upload(kind, file);
    input.value = "";
  });
  const stop = (event) => { event.preventDefault(); event.stopPropagation(); };
  ["dragenter", "dragover"].forEach((n) => zone.addEventListener(n, (e) => { stop(e); zone.classList.add("dragging"); }));
  ["dragleave", "dragend", "drop"].forEach((n) => zone.addEventListener(n, (e) => { stop(e); zone.classList.remove("dragging"); }));
  zone.addEventListener("drop", (event) => {
    const file = event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files[0];
    if (file) upload(kind, file);
  });
}

// ---------------------------------------------------------------------------
// 데이터
// ---------------------------------------------------------------------------
async function upload(kind, file) {
  const status = $(kind === "usage" ? "usageStatus" : "accrualStatus");
  showError("");
  status.textContent = `${file.name} 올리는 중…`;
  const form = new FormData();
  form.append("file", file);
  try {
    const out = await api(`api/datasets/${kind}`, { method: "POST", body: form });
    status.textContent = `${out.filename} · ${out.rowCount}건`;
    await runAnalysis();
  } catch (error) {
    status.textContent = "업로드 실패";
    showError(error.message);
  }
}

async function removeDataset(kind) {
  showError("");
  try {
    await api(`api/datasets/${kind}`, { method: "DELETE" });
    $(kind === "usage" ? "usageStatus" : "accrualStatus").textContent = "끌어다 놓거나 클릭";
    await runAnalysis();
  } catch (error) {
    showError(error.message);
  }
}

async function refreshDatasets() {
  try {
    const data = await api("api/datasets");
    ["usage", "accrual"].forEach((kind) => {
      const info = data[kind];
      $(kind === "usage" ? "usageStatus" : "accrualStatus").textContent =
        info ? `${info.filename} · ${info.rowCount}건` : "끌어다 놓거나 클릭";
    });
  } catch { /* 화면 표시만 실패하는 것이라 무시 */ }
}

async function refreshHolidays() {
  try { holidays = await api("api/holidays"); } catch { /* 무시 */ }
  renderHolidayChips();
}

function renderHolidayChips() {
  const box = $("holidayChips");
  if (!holidays.company.length) {
    box.innerHTML = `<span style="background:transparent;padding-left:0;color:#94a3b8">등록된 회사 자체 휴일이 없습니다.</span>`;
    return;
  }
  box.innerHTML = holidays.company
    .map((h) => `<span>${esc(h.name)} ${esc(h.date)}<button data-del="${esc(h.date)}" title="삭제">×</button></span>`)
    .join("");
  box.querySelectorAll("button[data-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`api/holidays/${btn.dataset.del}`, { method: "DELETE" });
        await refreshHolidays();
        await runAnalysis();
      } catch (error) { showError(error.message); }
    });
  });
}

async function addHoliday() {
  const date = $("holDate").value;
  const name = $("holName").value.trim();
  if (!date || !name) { showError("회사휴일 날짜와 이름을 모두 입력해 주세요."); return; }
  showError("");
  try {
    await api("api/holidays", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ date, name }),
    });
    $("holName").value = "";
    await refreshHolidays();
    await runAnalysis();
  } catch (error) { showError(error.message); }
}

async function runAnalysis() {
  const ref = $("refDate").value || todayKey();
  try {
    result = await api(`api/analysis?ref=${encodeURIComponent(ref)}`);
    showError("");
  } catch (error) {
    showError(error.message);
    return;
  }
  $("tabPattern").textContent = result.episodes.length;
  $("tabLow").textContent = result.lowUsage.rows.length;
  $("tabSpike").textContent = result.spikes.length;

  const meta = $("metaNote");
  const parts = [];
  if (result.meta.usage) parts.push(`사용내역 ${esc(result.meta.usage.filename)} (${result.meta.usage.rowCount}건)`);
  if (result.meta.accrual) parts.push(`발생내역 ${esc(result.meta.accrual.filename)} (${result.meta.accrual.rowCount}건)`);
  if (parts.length) { meta.innerHTML = `현재 데이터 · ${parts.join(" · ")}`; meta.classList.remove("hidden"); }
  else meta.classList.add("hidden");

  const warn = $("warnNote");
  if (result.unknownAmPm > 0) {
    warn.innerHTML = `시작시간이 없어 오전/오후를 판정하지 못한 반차/반반차가 <b>${result.unknownAmPm}건</b> 있습니다. 정확한 가중치를 위해 원본을 확인해 주세요.`;
    warn.classList.remove("hidden");
  } else warn.classList.add("hidden");

  renderBody();
}

// ---------------------------------------------------------------------------
// 결과 표
// ---------------------------------------------------------------------------
function renderBody() {
  const host = $("body");
  if (view === "low") host.innerHTML = renderLow();
  else if (view === "spike") host.innerHTML = renderSpike();
  else host.innerHTML = renderPattern();

  host.querySelectorAll("tr[data-expand]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const detail = $(tr.dataset.expand);
      const slot = detail.querySelector(".detailslot");
      if (slot && !slot.dataset.built) {
        slot.innerHTML = buildDetail(result.episodes[Number(tr.dataset.idx)]);
        slot.dataset.built = "1";
      }
      detail.classList.toggle("open");
    });
  });

  const tf = $("tierFilter");
  if (tf) tf.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-tier]");
    if (!btn) return;
    const tier = btn.dataset.tier;
    if (tier === "all") tierFilter = [];
    else if (tierFilter.includes(tier)) tierFilter = tierFilter.filter((t) => t !== tier);
    else tierFilter = [...tierFilter, tier];
    renderBody();
  });
}

function tierClass(tier) {
  return tier === "위험" ? "danger" : tier === "검토" ? "review" : "observe";
}

function renderPattern() {
  const all = result.episodes;
  if (!all.length) return `<div class="empty-state">감지된 이상 패턴이 없습니다.</div>`;
  const count = (label) => all.filter((e) => e.tier === label).length;
  const shown = all.map((episode, index) => ({ episode, index }))
    .filter(({ episode }) => tierFilter.length === 0 || tierFilter.includes(episode.tier));
  const people = new Set(shown.map((s) => s.episode.name)).size;
  const chip = (tier) => {
    const on = tier === "all" ? tierFilter.length === 0 : tierFilter.includes(tier);
    const n = tier === "all" ? all.length : count(tier);
    return `<button data-tier="${tier}" class="${on ? "active" : ""}">${tier === "all" ? "전체" : tier} ${n}</button>`;
  };
  const rows = shown.map(({ episode, index }) => `
    <tr data-expand="pat${index}" data-idx="${index}" class="clickrow">
      <td><b>${esc(episode.name)}</b><span class="sub2">${esc(orgLabel(episode.org))}</span></td>
      <td><span class="badge ${tierClass(episode.tier)}">${esc(episode.tier)}</span></td>
      <td class="num">${episode.round}/${episode.rounds}</td>
      <td>${esc(fmtDate(episode.detectedDate))}</td>
      <td class="num">${episode.score.toFixed(2)}</td>
      <td class="num">${episode.count}</td>
      <td class="num">▾</td>
    </tr>
    <tr class="detailrow" id="pat${index}"><td colspan="7"><div class="detailslot"></div></td></tr>`).join("");
  return `
    <div class="tier-filter" id="tierFilter">${chip("all")}${chip("위험")}${chip("검토")}${chip("관찰")}</div>
    <div class="tablewrap"><table class="grid">
      <thead><tr><th>대상자</th><th>분류</th><th class="num">회차</th><th>최근 감지일</th><th class="num">점수</th><th class="num">건수</th><th></th></tr></thead>
      <tbody>${rows || `<tr><td colspan="7" class="empty-state">선택한 등급의 감지가 없습니다.</td></tr>`}</tbody>
    </table></div>
    <p class="hint">등급을 눌러 위험·검토·관찰을 섞어서 볼 수 있습니다(다시 누르면 해제). 감지 인원 ${people}명. 행을 누르면 날짜별 상세가 펼쳐집니다.</p>`;
}

function buildDetail(episode) {
  if (!episode) return "";
  const rows = episode.events.map((event) => `
    <tr><td>${esc(fmtDate(event.date))}</td><td>${esc(event.label)}</td><td class="num">${event.weight.toFixed(2)}</td></tr>`).join("");
  return `<table class="detail"><thead><tr><th>날짜</th><th>유형</th><th class="num">가중치</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function strip(pairs) {
  return `<div class="summary-strip">${pairs.map(([k, v]) => `<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join("")}</div>`;
}

function renderLow() {
  const data = result.lowUsage;
  const cfg = criteria ? criteria.lowUsage : { gapPoint: 25, minAccrued: 10 };
  const head = strip([["기준일", $("refDate").value], ["올해 경과", `${data.dayOfYear}일 (${data.elapsedPct}%)`], ["저사용 대상", `${data.rows.length}명`]]);
  if (!result.meta.accrual) return `<div class="empty-state">연차 <b>발생내역</b>을 올리면 저사용 대상자를 계산합니다.</div>`;
  if (!data.rows.length) return `${head}<div class="empty-state">기준(격차 ${cfg.gapPoint}%p↑ · 발생 ${cfg.minAccrued}일↑)에 해당하는 저사용자가 없습니다.</div>`;
  const rows = data.rows.map((p) => `
    <tr>
      <td><b>${esc(p.name)}</b><span class="sub2">${esc(orgLabel(p.org))}</span></td>
      <td class="num">${fmtDays(p.accrued)}일</td>
      <td class="num">${fmtDays(p.used)}일</td>
      <td class="num">${p.usePct.toFixed(0)}%</td>
      <td class="num">${fmtDays(p.remain)}일</td>
      <td class="num"><span class="badge ${p.gap >= cfg.gapPoint + 10 ? "danger" : "observe"}">▼ ${p.gap.toFixed(0)}%p</span></td>
    </tr>`).join("");
  return `${head}
    <div class="tablewrap"><table class="grid">
      <thead><tr><th>대상자</th><th class="num">발생</th><th class="num">사용</th><th class="num">사용률</th><th class="num">잔여</th><th class="num">경과대비 격차</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="hint">사용률이 연중 경과율(${data.elapsedPct}%)보다 ${cfg.gapPoint}%p 이상 낮고 발생 ${cfg.minAccrued}일 이상인 사람. 격차가 클수록 연차를 쌓아두고 있다는 신호입니다.</p>`;
}

function renderSpike() {
  const cfg = criteria ? criteria.spike : { windowDays: 60, minRecentDays: 3, ratio: 2.5 };
  const head = strip([["기준일", $("refDate").value], ["관찰창", `최근 ${cfg.windowDays}일`], ["급증 대상", `${result.spikes.length}명`]]);
  if (!result.meta.usage) return `<div class="empty-state">연차 사용내역을 올려주세요.</div>`;
  if (!result.spikes.length) return `${head}<div class="empty-state">최근 사용 급증 대상자가 없습니다.</div>`;
  const rows = result.spikes.map((p) => `
    <tr>
      <td><b>${esc(p.name)}</b><span class="sub2">${esc(orgLabel(p.org))}</span></td>
      <td class="num">${fmtDays(p.recentDays)}일</td>
      <td class="num">${fmtDays(p.expected)}일</td>
      <td class="num"><span class="badge danger">${p.ratio === null ? "신규" : "×" + p.ratio.toFixed(1)}</span></td>
      <td class="dates">${p.recentDates.slice(0, 8).map((d) => `<span>${esc(fmtDate(d))}</span>`).join("")}</td>
    </tr>`).join("");
  return `${head}
    <div class="tablewrap"><table class="grid">
      <thead><tr><th>대상자</th><th class="num">최근 ${cfg.windowDays}일 사용</th><th class="num">직전 기대치</th><th class="num">배수</th><th>최근 사용일</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <p class="hint">직전 기간 평균으로 기대되는 사용량보다 최근 ${cfg.windowDays}일 사용이 ${cfg.ratio}배 이상 많고, 최소 ${cfg.minRecentDays}일 이상 사용한 사람. 안 쓰다가 갑자기 몰아 쓰는 신호입니다.</p>`;
}

function renderCriteria() {
  if (!criteria) return;
  const w = criteria.weights;
  const labels = [["종일 연차", "fullAnnual"], ["오전 반차", "halfAM"], ["오전 반반차", "quarterAM"], ["오전 반반반차", "eighthAM"],
                  ["오후 반차", "halfPM"], ["오후 반반차", "quarterPM"], ["오후 반반반차", "eighthPM"]];
  const matrix = labels.map(([label, key]) =>
    `<tr><td>${label}</td>${[1, 2, 3, 4, 5].map((d) => `<td class="num">${w[key][d]}</td>`).join("")}</tr>`).join("");
  $("criteriaBody").innerHTML = `
    <p><b>공통</b> — 대상은 휴가그룹 <b>연차휴가</b>. 사람 식별은 <b>사원번호</b> 기준(같은 날짜 다른 사원번호 중복은 제거). 같은 날 여러 휴가는 <b>합산</b>합니다(반차+반차=연차 1.0). 차감일수: 연차 1·반차 0.5·반반차 0.25·반반반차 0.125. 오전/오후는 시작 시간으로 판정합니다.</p>
    <p><b>① 이상 패턴</b> — 최근 <b>${criteria.windowDays}일</b> 안에서 <b>고립된 평일 연차</b>가 반복되는지 봅니다. 고립 = 공휴일·회사휴일이 붙지 않고, 본인 다른 연차와 부재가 실제로 이어지지 않으며, 전사 ${Math.round(criteria.massLeaveRatio * 100)}%↑ 집단연차일이 아닌 날. <b>주말은 없는 날로 취급</b>해 금요일+월요일은 연달아로 봅니다. 가중치는 <b>유형 × 요일</b>로 부여합니다.</p>
    <table class="detail"><thead><tr><th>유형</th><th class="num">월</th><th class="num">화</th><th class="num">수</th><th class="num">목</th><th class="num">금</th></tr></thead><tbody>${matrix}</tbody></table>
    <p>분류: <b style="color:#e11d48">위험</b> = 점수 ${criteria.tiers.danger.minScore}↑ <b>그리고</b> 고립 ${criteria.tiers.danger.minCount}회↑ · <b style="color:#b45309">검토</b> = 점수 ${criteria.tiers.review.minScore}↑ <b>또는</b> 고립 ${criteria.tiers.review.minCount}회↑ · <b style="color:#a16207">관찰</b> = 점수 ${criteria.tiers.observe.minScore}↑.</p>
    <p><b>② 저사용</b> — 연중 경과율(경과일/${criteria.lowUsage.yearDays})과 개인 사용률(사용/발생) 격차가 <b>${criteria.lowUsage.gapPoint}%p↑</b> &amp; 발생 <b>${criteria.lowUsage.minAccrued}일↑</b>.</p>
    <p><b>③ 급증</b> — 최근 <b>${criteria.spike.windowDays}일</b> 사용이 직전 기대치의 <b>${criteria.spike.ratio}배↑</b> &amp; 최소 <b>${criteria.spike.minRecentDays}일↑</b>.</p>
    <p>기준일은 위에서 바꾸고, 모든 임계값은 서버의 <code>app/config.py</code> 에서 조정합니다.</p>`;
}

boot();
