/* ── 볼 수 있는 화면 ─────────────────────────────────────────
   고치는 기능은 이미 서버에서 담당자만 되게 막혀 있다. 그런데도
   "자산 등록" 같은 화면이 보이면, 쓸 수 없는 화면을 들여다보게 되고
   남의 업무에 말이 오간다. 볼 일이 없는 화면은 아예 안 보이는 편이 낫다.

   목록은 **서버가 준다** (/auth/me 의 views). 화면 파일에 박아 두면
   권한을 바꿀 때마다 파일을 고쳐 배포해야 한다. 누가 무엇을 보는지는
   담당자가 「권한」 화면에서 정한다.

   서버가 아직 안 알려줬을 때만 쓰는 대비값. 화면이 통째로 안 뜨는 것보다
   최소한만 보이는 편이 낫다. */
const FALLBACK_VIEWS = ["employees", "seats", "ips", "extensions"];

function myViews() {
  const v = state.user?.views;
  return Array.isArray(v) && v.length ? v : FALLBACK_VIEWS;
}
// 「권한」은 담당자만. 서버 목록에 없어도 담당자면 보여준다.
function canSee(view) {
  if (view === "permissions") return isAdmin();
  return myViews().includes(view);
}
function firstView() { return isAdmin() ? "dashboard" : myViews()[0]; }

/* 고칠 수 있나.
   **체크한 화면은 보기와 고치기 둘 다** 된다. 보기만 되고 고치기는 안 되면
   전화 담당자가 내선을 못 바꾸니 쓸모가 없다.

   어느 화면의 일인지는 버튼에 data-need 로 적어 둔다. 자리 배치에서 연
   서랍 안에 자산 지급 버튼이 섞여 있는 식이라, 지금 보는 화면만으로는
   판단할 수 없기 때문이다.

   화면에서 감추는 것은 정리일 뿐이다. 진짜 차단은 서버가 한다. */
function canEdit(view) { return canSee(view || state.view); }

const titles = {
  workspace: "직원별 현황",
  seats: "자리 배치",
  dashboard: "대시보드",
  assets: "자산 등록",
  employees: "직원 명단",
  ips: "IP 관리",
  extensions: "내선 관리",
  software: "소프트웨어",
  rentals: "렌탈",
  permissions: "권한",
};

const ASSET_TYPES = {
  LAPTOP: "노트북",
  DESKTOP: "데스크탑",
  MONITOR: "모니터",
  SERVER: "서버",
  NETWORK: "네트워크 장비",
  OTHER: "기타",
};

const ASSET_STATUS = {
  IN_USE: "사용 중",
  STORAGE: "보관",
  REPAIR: "수리",
  DISPOSED: "폐기",
};

// 차트 계열 색. 고정 순서로 배정한다 (색맹 대비 검증을 통과한 조합이므로 순서를 바꾸지 않는다).
const SERIES_COLORS = ["#2a78d6", "#1baf7a", "#eda100", "#008300"];

const state = {
  view: "dashboard",
  workspace: [],
  assets: [],
  softwareProducts: [],
  freeIps: [],
  expanded: new Set(),
  selected: null,        // 드로어에 띄운 직원 id
  picker: null,          // 드로어에서 열려 있는 선택 상자 ("give" | "license" | "ip:<id>" | "sw:<id>")
  licensesByEmployee: {},
  licenseHolders: [],
  licenseUsage: [],
  seats: [],
  seatFloors: [],
  seatFloor: null,       // 지금 보고 있는 층
  seatPicker: null,      // 사람을 고르는 중인 빈 자리 id
  seatEdit: false,       // 배치 편집 모드 (책상을 끌어 옮기는 상태)
  seatUndo: [],          // 되돌릴 일들. 편집 모드를 나가면 비운다
  extensions: [],        // 내선번호
  ipKind: "",           // IP 관리에서 보고 있는 종류 ("" | NETWORK | PHONE)
  managedRows: {},
  page: 1,
  pageSize: 50,
  // 예전 자체 로그인 때 쓰던 토큰. 이제 로그인은 포털이 하므로 항상 비운다.
  // 예전에 8081 로 접속했던 사람의 브라우저에 낡은 토큰이 남아 있는데,
  // 그걸 그대로 들고 다니면 엉뚱한 "세션이 만료되었습니다" 가 뜬다.
  token: "",
  user: null,
};

const apiBase = () => {
  // 숨은 입력(#apiBase)에 값이 있으면 그걸 쓴다 (수동 오버라이드용).
  const override = document.querySelector("#apiBase").value.replace(/\/$/, "");
  if (override) return override;
  // 개발: 정적 서버(3000/3001)에서 열면 로컬 백엔드(8000)로.
  // 배포: nginx 가 /api 를 백엔드로 프록시하므로 같은 주소의 /api 로.
  return /^https?:\/\/(localhost|127\.0\.0\.1):(3000|3001)$/.test(location.origin)
    ? "http://localhost:8000"
    : "/api";
};
const $ = (selector) => document.querySelector(selector);

let pendingRequests = 0;

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  pendingRequests += 1;
  document.body.classList.add("is-loading");
  try {
    const response = await fetch(`${apiBase()}${path}`, { ...options, headers });
    // 토큰 수명(60분)이 지나면 모든 요청이 401이 된다.
    // 영어 원문("Could not validate credentials")을 그대로 보여주지 말고
    // 로그인 화면으로 돌려보낸다. (로그인 시도 자체의 401은 token이 없으므로 제외)
    if (response.status === 401 && state.token) {
      state.token = "";
      state.user = null;
      localStorage.removeItem("assetPortalToken");
      updateAuthUI();
      throw new Error("세션이 만료되었습니다. 다시 로그인해주세요.");
    }
    if (!response.ok) {
      const body = await response.text();
      throw new Error(errorMessage(body) || response.statusText);
    }
    return response.status === 204 ? null : response.json();
  } finally {
    pendingRequests = Math.max(0, pendingRequests - 1);
    if (pendingRequests === 0) document.body.classList.remove("is-loading");
  }
}

// FastAPI는 오류를 {"detail": "..."} 로 돌려준다. 사용자에게 raw JSON을 보여주지 않는다.
function errorMessage(body) {
  try {
    const parsed = JSON.parse(body);
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) return parsed.detail.map((item) => item.msg).join(", ");
  } catch {
    /* 평문 응답 */
  }
  return body;
}

const isAdmin = () => state.user?.role === "ADMIN";

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    el.hidden = true;
  }, 2600);
}

function formData(form) {
  return Object.fromEntries([...new FormData(form).entries()].filter(([, value]) => value !== ""));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

// ---------------------------------------------------------------- 정렬 (표 머리글 클릭)

// 표별 정렬 상태. { 표이름: { key, dir } }, dir 1=오름차순 -1=내림차순
const sortState = {};

// key가 없는 컬럼(펼침 화살표, 작업 버튼)은 정렬 대상이 아니다.
function sortableHead(tableKey, columns) {
  return columns.map((column) => {
    if (!column.key) return `<th class="${column.className || ""}">${column.label || ""}</th>`;
    const current = sortState[tableKey];
    const active = current?.key === column.key;
    const arrow = active ? (current.dir === 1 ? "▲" : "▼") : "";
    return `
      <th class="sortable ${active ? "sorted" : ""} ${column.sticky ? "sticky-col" : ""}" data-sort="${column.key}">
        ${column.label}<span class="sort-ind">${arrow}</span>
      </th>
    `;
  }).join("");
}

function sortValueOf(columns, row, key) {
  const column = columns.find((item) => item.key === key);
  return column?.sortValue ? column.sortValue(row) : row[key];
}

function applySort(tableKey, columns, rows) {
  const current = sortState[tableKey];
  if (!current) return rows;

  return [...rows].sort((a, b) => {
    const left = sortValueOf(columns, a, current.key);
    const right = sortValueOf(columns, b, current.key);
    const leftEmpty = left === null || left === undefined || left === "";
    const rightEmpty = right === null || right === undefined || right === "";

    // 빈 값은 오름/내림과 무관하게 항상 뒤로 보낸다.
    if (leftEmpty && rightEmpty) return 0;
    if (leftEmpty) return 1;
    if (rightEmpty) return -1;

    const result = (typeof left === "number" && typeof right === "number")
      ? left - right
      : String(left).localeCompare(String(right), "ko", { numeric: true });
    return result * current.dir;
  });
}

// 좁은 화면에서는 표 머리글이 숨겨져(카드 전환) 클릭할 수 없으므로 같은 컬럼 정보로 정렬 바를 만든다.
function sortBar(tableKey, columns) {
  const current = sortState[tableKey];
  const choices = columns
    .filter((column) => column.key)
    .map((column) =>
      `<option value="${column.key}" ${current?.key === column.key ? "selected" : ""}>${column.label}</option>`)
    .join("");

  return `
    <div class="sort-bar">
      <span>정렬</span>
      <select data-sort-select>
        <option value="">기본 순서</option>
        ${choices}
      </select>
      <button type="button" class="secondary" data-sort-dir ${current ? "" : "disabled"}>
        ${current?.dir === -1 ? "▼ 내림차순" : "▲ 오름차순"}
      </button>
    </div>
  `;
}

function bindSort(tableKey, target, rerender) {
  const container = $(target);

  container.addEventListener("click", (event) => {
    const th = event.target.closest("th[data-sort]");
    if (th) {
      const key = th.dataset.sort;
      const current = sortState[tableKey];
      sortState[tableKey] = current?.key === key ? { key, dir: -current.dir } : { key, dir: 1 };
      return rerender();
    }
    if (event.target.closest("[data-sort-dir]")) {
      const current = sortState[tableKey];
      if (!current) return;
      sortState[tableKey] = { key: current.key, dir: -current.dir };
      rerender();
    }
  });

  container.addEventListener("change", (event) => {
    if (!event.target.matches("[data-sort-select]")) return;
    const key = event.target.value;
    if (!key) delete sortState[tableKey];
    else sortState[tableKey] = { key, dir: sortState[tableKey]?.dir ?? 1 };
    rerender();
  });
}

// ---------------------------------------------------------------- 표시 헬퍼

function assetNo(asset) {
  return asset.asset_no || "미등록";
}

function assetKind(asset) {
  const base = ASSET_TYPES[asset.asset_type] || "자산";
  return asset.purchase_type === "RENTAL" ? `${base}(임대)` : base;
}

function assetLabel(asset) {
  return `${assetNo(asset)} · ${assetKind(asset)}${asset.model ? ` · ${asset.model}` : ""}`;
}

function assetSpec(asset) {
  return [asset.model, asset.cpu, asset.memory_gb ? `${asset.memory_gb}GB` : "", asset.os]
    .filter(Boolean)
    .join(" · ") || "사양 정보 없음";
}

function storageAssets() {
  return state.assets.filter((asset) => asset.status === "STORAGE");
}

function options(items, labelFn, valueKey, emptyText) {
  return [`<option value="">${emptyText}</option>`]
    .concat(items.map((item) => `<option value="${item[valueKey]}">${escapeHtml(labelFn(item))}</option>`))
    .join("");
}

// ---------------------------------------------------------------- 데이터 적재

async function loadWorkspace() {
  const [workspace, assets, softwareProducts, freeIps, licenseHeld, licenseUsage, extensions] =
    await Promise.all([
      api("/employees/workspace"),
      api("/assets/"),
      api("/software-products"),
      api("/ip-addresses/free?kind=NETWORK"),
      api("/license-assignments/?active_only=true"),
      api("/license-assignments/usage"),
      api("/extensions/"),
    ]);
  state.workspace = workspace;
  state.assets = assets;
  state.softwareProducts = softwareProducts;
  state.freeIps = freeIps;
  state.extensions = extensions;
  // 직원 id -> 보유 라이선스 목록
  state.licensesByEmployee = {};
  for (const row of licenseHeld) {
    (state.licensesByEmployee[row.employee_id] ||= []).push(row);
  }
  state.licenseUsage = licenseUsage;
  renderWorkspace();
}

// 직원별 현황의 열. 표(table)가 아니라 grid 로 그리지만 정렬 규칙은 같이 쓴다.
const WORKSPACE_COLUMNS = [
  { label: "#" },
  // 사번과 이름을 한 칸에 붙여 두면 붙어 보이고 사번으로 정렬도 못 한다.
  // 직원 명단 표와 같이 따로 둔다.
  { key: "emp_no", label: "사번" },
  { key: "name", label: "이름" },
  { key: "department", label: "부서 / 직책", sortValue: (row) => row.department || "" },
  { key: "asset", label: "자산", sortValue: (row) => row.assets[0]?.asset_no || "" },
  { key: "license", label: "라이선스",
    sortValue: (row) => (state.licensesByEmployee[row.id] || []).length },
  { key: "ip", label: "IP", sortValue: (row) => row.assets[0]?.ips[0]?.ip_address || "" },
  { key: "extension", label: "내선",
    sortValue: (row) => (/^\d+$/.test(row.extension || "") ? Number(row.extension) : row.extension || "") },
  { key: "status", label: "상태",
    sortValue: (row) => (row.status === "ACTIVE" ? "재직" : "퇴사") },
];

function renderWorkspace() {
  const query = $("#workspaceSearch").value.trim().toLowerCase();
  const status = $("#workspaceStatus").value;
  state.pageSize = Number($("#pageSize").value);

  const rows = state.workspace.filter((employee) => {
    if (status && employee.status !== status) return false;
    if (!query) return true;
    const haystack = [
      employee.emp_no,
      employee.name,
      employee.department,
      employee.position,
      employee.extension,
      employee.phone_ip,
      ...employee.assets.flatMap((asset) => [
        asset.asset_no,
        asset.label_no,
        asset.model,
        ...asset.ips.map((ip) => ip.ip_address),
        ...asset.software.map((software) => software.name),
      ]),
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });

  // 정렬을 고르지 않았으면 이름순이 기본
  if (!sortState.workspace) sortState.workspace = { key: "name", dir: 1 };
  const sorted = applySort("workspace", WORKSPACE_COLUMNS, rows);

  $("#workspaceHead").innerHTML = WORKSPACE_COLUMNS.map((column) => {
    if (!column.key) return `<span>${column.label}</span>`;
    const current = sortState.workspace;
    const active = current?.key === column.key;
    const arrow = active ? (current.dir === 1 ? "▲" : "▼") : "";
    return `<span class="sortable ${active ? "sorted" : ""}" data-sort="${column.key}">`
      + `${column.label}<span class="sort-ind">${arrow}</span></span>`;
  }).join("");

  const totalPages = Math.max(1, Math.ceil(sorted.length / state.pageSize));
  state.page = Math.min(Math.max(1, state.page), totalPages);
  const start = (state.page - 1) * state.pageSize;
  const paged = sorted.slice(start, start + state.pageSize);

  $("#workspaceRows").innerHTML = paged
    .map((employee, i) => employeeRow(employee, start + i + 1))
    .join("") || `<div class="empty">해당하는 직원이 없습니다.</div>`;

  const spares = storageAssets().length;
  $("#storageCount").textContent = `보관 자산 ${spares}대`;
  $("#pageInfo").textContent = rows.length
    ? `${start + 1}-${Math.min(start + state.pageSize, rows.length)} / ${rows.length}명 · ${state.page}/${totalPages}페이지`
    : "0명";
  $("#prevPage").disabled = state.page <= 1;
  $("#nextPage").disabled = state.page >= totalPages;
  renderDrawer();
  updateAuthUI();
}

// 목록 행에는 버튼을 두지 않는다. 행을 클릭하면 오른쪽 드로어가 열리고,
// 지급·회수·부여 같은 작업은 전부 거기서 한다. (GLPI 방식)
function employeeRow(employee, rowNo) {
  const selected = state.selected === employee.id;
  const assets = employee.assets;
  const summary = assets.length
    ? assets.map(assetKind).join(", ")
    : `<span class="muted">-</span>`;
  const ips = assets.flatMap((asset) => asset.ips.map((ip) => ip.ip_address));
  const licenses = state.licensesByEmployee[employee.id] || [];

  return `
    <div class="row ${selected ? "selected" : ""}" data-select="${employee.id}">
      <span class="rownum mono">${rowNo}</span>
      <span class="mono cell-empno">${escapeHtml(employee.emp_no || "-")}</span>
      <span class="cell-name"><strong>${escapeHtml(employee.name)}</strong></span>
      <span>${escapeHtml(employee.department || "-")}${employee.position ? ` / ${escapeHtml(employee.position)}` : ""}</span>
      <span>${summary}</span>
      <span>${licenses.length ? `${licenses.length}종` : `<span class="muted">-</span>`}</span>
      <span class="mono">${ips.length ? ips.map(escapeHtml).join(", ") : `<span class="muted">-</span>`}</span>
      <span class="mono cell-ext">${employee.extension
        ? escapeHtml(employee.extension)
          + (employee.phone_ip ? `<br /><small class="muted">${escapeHtml(employee.phone_ip)}</small>` : "")
        : `<span class="muted">-</span>`}</span>
      <span class="status ${employee.status}">${employee.status === "ACTIVE" ? "재직" : "퇴사"}</span>
    </div>
  `;
}

// ---------------------------------------------------------------- 드로어

function renderDrawer() {
  const drawer = $("#drawer");
  const backdrop = $("#drawerBackdrop");
  const employee = state.workspace.find((row) => row.id === state.selected);
  if (!employee) {
    drawer.hidden = true;
    backdrop.hidden = true;
    return;
  }
  drawer.hidden = false;
  backdrop.hidden = false;

  const licenses = state.licensesByEmployee[employee.id] || [];
  const spares = storageAssets();
  const active = employee.status === "ACTIVE";

  drawer.innerHTML = `
    <div class="drawer-head">
      <div>
        <h3>${escapeHtml(employee.name)}
          <span class="status ${employee.status}">${active ? "재직" : "퇴사"}</span>
        </h3>
        <p>${escapeHtml(employee.emp_no)} · ${escapeHtml(employee.department || "-")}${employee.position ? ` / ${escapeHtml(employee.position)}` : ""}${employee.extension ? ` · 내선 ${escapeHtml(employee.extension)}` : ""}${employee.phone_ip ? ` (${escapeHtml(employee.phone_ip)})` : ""}</p>
      </div>
      <span class="spacer"></span>
      <button class="icon-btn" data-close-drawer title="닫기">×</button>
    </div>

    <div class="drawer-scroll">
      <section class="d-sec">
        <header>
          <h4>자산 <span class="count">${employee.assets.length}</span></h4>
          <span class="spacer"></span>
          ${active ? `<button class="link admin-only" data-need="assets" data-picker="give">＋ 지급</button>` : ""}
        </header>
        ${state.picker === "give" ? givePicker(employee, spares) : ""}
        <div class="d-assets">
          ${employee.assets.map((asset) => drawerAsset(asset)).join("")
            || `<div class="d-empty">지급된 자산이 없습니다.</div>`}
        </div>
      </section>

      <section class="d-sec">
        <header>
          <h4>내선번호</h4>
          <span class="spacer"></span>
          ${active && !employee.extension
            ? `<button class="link admin-only" data-need="extensions" data-picker="ext">＋ 부여</button>` : ""}
        </header>
        ${state.picker === "ext" ? extPicker(employee) : ""}
        ${employee.extension
          ? `<div class="ext-line">
               <strong class="mono">${escapeHtml(employee.extension)}</strong>
               ${employee.phone_ip
                 ? `<span class="muted mono">${escapeHtml(employee.phone_ip)}</span>`
                 : `<span class="muted">전화기 IP 없음</span>`}
               <span class="spacer"></span>
               <button class="link danger-link admin-only" data-need="extensions" data-release-ext="${employee.id}">회수</button>
             </div>`
          : `<div class="d-empty">부여된 내선번호가 없습니다.</div>`}
      </section>

      <section class="d-sec">
        <header>
          <h4>라이선스 <span class="count">${licenses.length}</span></h4>
          <span class="spacer"></span>
          ${active ? `<button class="link admin-only" data-need="software" data-picker="license">＋ 부여</button>` : ""}
        </header>
        ${state.picker === "license" ? licensePicker(licenses) : ""}
        <div class="lic-list">
          ${licenses.map((row) => `
            <span class="lic-chip">
              ${escapeHtml(row.software_name || "?")}
              <button class="chip-x admin-only" data-need="software" data-revoke-license="${row.id}" title="회수">×</button>
            </span>
          `).join("") || `<span class="d-empty">보유한 라이선스가 없습니다.</span>`}
        </div>
      </section>
    </div>

    <div class="drawer-foot">
      ${active
        ? `<button class="danger admin-only" data-need="employees" data-offboard="${employee.id}">퇴사 처리</button>`
        : `<button class="secondary admin-only" data-need="employees" data-reinstate="${employee.id}">복직 처리</button>`}
    </div>
  `;
  updateAuthUI();
}

function drawerAsset(asset) {
  const ip = asset.ips[0];
  const ipPicker = state.picker === `ip:${asset.id}`;
  const swPicker = state.picker === `sw:${asset.id}`;
  const installed = new Set(asset.software.map((software) => software.name));
  const available = state.softwareProducts.filter((product) => !installed.has(product.name));

  // 엑셀에서 열이 밀려 들어와 사양(OS 등)에 IP 가 그대로 박힌 자료가 있다.
  // 그대로 두면 같은 IP 가 한 카드에 두 번 보인다.
  const spec = [asset.model, asset.cpu, asset.memory_gb ? `${asset.memory_gb}GB` : "", asset.os]
    .filter(Boolean)
    .map(String)
    .filter((part) => !ip || part.trim() !== ip.ip_address)
    .join(" · ");

  return `
    <div class="d-asset">
      <div class="d-asset-top">
        <strong class="mono">${escapeHtml(assetNo(asset))}</strong>
        <span class="tag">${assetKind(asset)}</span>
        <span class="spacer"></span>
        <span class="hover-actions">
          <button class="link admin-only" data-need="ips" data-picker="ip:${asset.id}">IP</button>
          <button class="link admin-only" data-need="software" data-picker="sw:${asset.id}">SW</button>
          <button class="link danger-link admin-only" data-need="assets" data-return="${asset.id}">회수</button>
        </span>
      </div>

      <dl class="d-fields">
        <dt>사양</dt>
        <dd>${spec ? escapeHtml(spec) : `<span class="muted">정보 없음</span>`}</dd>

        <dt>IP</dt>
        <dd class="mono">${ip ? escapeHtml(ip.ip_address) : `<span class="muted">없음</span>`}</dd>

        <dt>SW</dt>
        <dd class="chipwrap">
          ${asset.software.map((software) => `
            <span class="chip" title="${escapeHtml(software.name)}">${escapeHtml(software.name)}<button class="chip-x admin-only" data-need="software" data-remove-sw="${software.id}" title="제거">×</button></span>
          `).join("") || `<span class="muted">없음</span>`}
        </dd>
      </dl>

      ${ipPicker ? `
        <div class="picker">
          <select data-ip-select="${asset.id}">
            ${options(state.freeIps, (item) => `${item.ip_address}${item.range ? ` (${item.range})` : ""}`, "ip_address", ip ? "다른 IP 선택" : "미사용 IP 선택")}
          </select>
          <button class="secondary admin-only" data-need="ips" data-apply-ip="${asset.id}" data-ip-assignment="${ip?.id || ""}">${ip ? "변경" : "할당"}</button>
          ${ip ? `<button class="secondary admin-only" data-need="ips" data-release-ip="${ip.id}">해제</button>` : ""}
        </div>` : ""}

      ${swPicker ? swChecklist(asset, available) : ""}
    </div>
  `;
}

// 한 대에 서너 개씩 깔리는 게 보통이라, 하나 고르고 닫히고 다시 열고를
// 반복해야 했다. 한 번에 여러 개 고를 수 있게 체크상자로 둔다.
function swChecklist(asset, available) {
  if (!available.length) {
    return `<div class="picker"><span class="muted">더 추가할 소프트웨어가 없습니다.</span></div>`;
  }

  const sorted = available.slice()
    .sort((a, b) => String(a.name).localeCompare(String(b.name), "ko"));

  return `
    <div class="sw-pick">
      <input class="sw-search" data-sw-search="${asset.id}" placeholder="이름으로 걸러보기" />
      <div class="sw-grid" data-sw-list="${asset.id}">
        ${sorted.map((product) => `
          <label class="sw-item" data-sw-name="${escapeHtml(String(product.name).toLowerCase())}">
            <input type="checkbox" data-sw-check="${asset.id}" value="${product.id}" />
            <span>${escapeHtml(product.name)}</span>
          </label>`).join("")}
      </div>
      <div class="sw-foot">
        <span class="muted" data-sw-count="${asset.id}">0개 선택</span>
        <span class="spacer"></span>
        <button class="link" data-sw-cancel="1">취소</button>
        <button class="secondary admin-only" data-need="software" data-add-sw="${asset.id}">추가</button>
      </div>
    </div>`;
}

function givePicker(employee, spares) {
  return `
    <div class="picker">
      <select data-give-select="${employee.id}">
        ${options(spares, assetLabel, "id", spares.length ? "보관 자산 선택" : "보관 중인 자산 없음")}
      </select>
      <button class="secondary admin-only" data-need="assets" data-give="${employee.id}">지급</button>
    </div>
  `;
}

function extPicker(employee) {
  // 아직 아무도 안 쓰는 번호만. 한 사람에 번호 하나라 남의 번호는 못 준다.
  const free = (state.extensions || [])
    .filter((row) => !row.employee_id)
    .sort((a, b) => (/^\d+$/.test(a.number) && /^\d+$/.test(b.number)
      ? Number(a.number) - Number(b.number)
      : String(a.number).localeCompare(String(b.number))));

  return `
    <div class="picker">
      <select data-ext-select>
        ${options(free,
          (row) => `${row.number}${row.zone ? ` (${row.zone})` : ""}${row.ip_address ? ` · ${row.ip_address}` : ""}`,
          "id",
          free.length ? "내선번호 선택" : "빈 번호가 없습니다 — 내선 관리에서 등록하세요")}
      </select>
      <button class="secondary admin-only" data-need="extensions" data-grant-ext="${employee.id}">부여</button>
    </div>
  `;
}

function licensePicker(held) {
  // 이미 갖고 있는 라이선스는 목록에서 뺀다. 남은 것은 여유 수량과 함께 보여준다.
  const heldPools = new Set(held.map((row) => row.license_pool_id));
  const pools = state.licenseUsage.filter((row) => !heldPools.has(row.license_pool_id));
  return `
    <div class="picker">
      <select data-license-select>
        ${options(
          pools,
          (row) => `${row.software_name}${row.available_count != null
            ? ` (여유 ${row.available_count}${row.available_count <= 0 ? " — 초과됨" : ""})` : ""}`,
          "license_pool_id",
          pools.length ? "라이선스 선택" : "부여할 라이선스 없음",
        )}
      </select>
      <button class="secondary admin-only" data-need="software" data-grant-license>부여</button>
    </div>
  `;
}

// ---------------------------------------------------------------- 자산 등록

async function loadAssets() {
  const [assets, workspace] = await Promise.all([api("/assets/"), api("/employees/workspace")]);
  state.assets = assets;
  state.workspace = workspace;
  renderAssets();
}

// 사용자(쓰는 사람)를 맨 앞에 둔다. 창을 줄이면 오른쪽이 잘려서
// 정작 제일 자주 찾는 이름이 안 보였다.
const ASSET_COLUMNS = [
  { key: "holder", label: "사용자", sticky: true },
  { key: "asset_no", label: "자산번호" },
  { key: "label_no", label: "라벨번호" },
  { key: "asset_type", label: "유형", sortValue: (row) => ASSET_TYPES[row.asset_type] || "" },
  { key: "purchase_type", label: "구분", sortValue: (row) => (row.purchase_type === "RENTAL" ? "임대" : "구매") },
  { key: "model", label: "모델" },
  { key: "cpu", label: "CPU" },
  { key: "memory_gb", label: "메모리" },
  { key: "os", label: "OS" },
  { key: "status", label: "상태", sortValue: (row) => ASSET_STATUS[row.status] || "" },
];

function renderAssets() {
  // 자산을 쓰는 사람을 같이 보여줘야 "지금 지급 중인 자산"을 지우는 실수를 막을 수 있다.
  const holderOf = new Map();
  state.workspace.forEach((employee) => {
    employee.assets.forEach((asset) => holderOf.set(asset.id, employee.name));
  });

  const query = $("#assetSearch").value.trim().toLowerCase();
  const status = $("#assetStatusFilter").value;
  const rows = state.assets
    .map((asset) => ({ ...asset, holder: holderOf.get(asset.id) || "" }))
    .filter((asset) => {
      if (status && asset.status !== status) return false;
      if (!query) return true;
      return [asset.asset_no, asset.label_no, asset.model, asset.cpu, asset.holder]
        .join(" ").toLowerCase().includes(query);
    });

  const sorted = applySort("assets", ASSET_COLUMNS, rows);

  $("#assetCount").textContent = `${sorted.length}대`;
  $("#assetsTable").innerHTML = `
    ${sortBar("assets", ASSET_COLUMNS)}
    <table>
      <thead><tr>${sortableHead("assets", ASSET_COLUMNS)}</tr></thead>
      <tbody>
        ${sorted.map(assetViewRow).join("")}
      </tbody>
    </table>
  `;
  updateAuthUI();
}

function assetViewRow(asset) {
  return `
    <tr class="clickable" data-open-asset="${asset.id}">
      <td class="sticky-col" data-label="사용자">${asset.holder ? escapeHtml(asset.holder) : `<span class="muted">-</span>`}</td>
      <td class="mono" data-label="자산번호">${asset.asset_no ? escapeHtml(asset.asset_no) : `<span class="muted">미등록</span>`}</td>
      <td class="mono" data-label="라벨번호">${escapeHtml(asset.label_no || "-")}</td>
      <td data-label="유형">${ASSET_TYPES[asset.asset_type] || "-"}</td>
      <td data-label="구분">${asset.purchase_type === "RENTAL" ? "임대" : "구매"}</td>
      <td data-label="모델">${escapeHtml(asset.model || "-")}</td>
      <td data-label="CPU">${escapeHtml(asset.cpu || "-")}</td>
      <td data-label="메모리">${asset.memory_gb ? `${asset.memory_gb}GB` : "-"}</td>
      <td data-label="OS">${escapeHtml(asset.os || "-")}</td>
      <td data-label="상태"><span class="status ${asset.status}">${ASSET_STATUS[asset.status] || asset.status}</span></td>
    </tr>
  `;
}

// ---------------------------------------------------------------- 직원 등록

async function loadEmployees() {
  state.workspace = await api("/employees/workspace");
  renderEmployees();
}

const EMPLOYEE_COLUMNS = [
  { key: "emp_no", label: "사번" },
  { key: "name", label: "이름" },
  { key: "department", label: "부서" },
  { key: "position", label: "직책" },
  { key: "rank", label: "직급" },
  { key: "email", label: "이메일" },
  { key: "asset_count", label: "보유 자산", sortValue: (row) => row.assets.length },
  { key: "status", label: "상태", sortValue: (row) => (row.status === "ACTIVE" ? "재직" : "퇴사") },
];

function renderEmployees() {
  const query = $("#employeeSearch").value.trim().toLowerCase();
  const filtered = state.workspace.filter((employee) =>
    !query || [employee.emp_no, employee.name, employee.department]
      .join(" ").toLowerCase().includes(query)
  );
  const rows = applySort("employees", EMPLOYEE_COLUMNS, filtered);

  $("#employeeCount").textContent = `${rows.length}명`;

  // 부서/직책/직급 입력에 기존 값들을 자동완성으로 제공한다.
  // 팀을 별도 테이블로 만들지 않아도 표기 통일("마케팅팀" vs "마케팅 팀")은 이걸로 잡힌다.
  const datalist = (id, values) =>
    `<datalist id="${id}">${[...new Set(values.filter(Boolean))].sort()
      .map((v) => `<option value="${escapeHtml(v)}"></option>`).join("")}</datalist>`;
  const datalists =
    datalist("dl-dept", state.workspace.map((e) => e.department)) +
    datalist("dl-position", state.workspace.map((e) => e.position)) +
    datalist("dl-rank", state.workspace.map((e) => e.rank));

  const viewRow = (employee) => `
    <tr class="clickable" data-open-employee="${employee.id}">
      <td class="mono" data-label="사번">${escapeHtml(employee.emp_no)}</td>
      <td data-label="이름">${escapeHtml(employee.name)}</td>
      <td data-label="부서">${escapeHtml(employee.department || "-")}</td>
      <td data-label="직책">${escapeHtml(employee.position || "-")}</td>
      <td data-label="직급">${escapeHtml(employee.rank || "-")}</td>
      <td data-label="이메일">${escapeHtml(employee.email || "-")}</td>
      <td data-label="보유 자산">${employee.assets.length ? `${employee.assets.length}대` : `<span class="muted">0대</span>`}</td>
      <td data-label="상태"><span class="status ${employee.status}">${employee.status === "ACTIVE" ? "재직" : "퇴사"}</span></td>
    </tr>`;

  $("#employeesTable").innerHTML = `
    ${datalists}
    ${sortBar("employees", EMPLOYEE_COLUMNS)}
    <table>
      <thead><tr>${sortableHead("employees", EMPLOYEE_COLUMNS)}</tr></thead>
      <tbody>
        ${rows.map(viewRow).join("")}
      </tbody>
    </table>
  `;
  updateAuthUI();
}

// ---------------------------------------------------------------- 기타 화면

// data-label은 좁은 화면에서 각 칸의 항목명을 보여주기 위한 것이다 (styles.css 카드 전환).
function table(tableKey, target, columns, rows) {
  const sorted = applySort(tableKey, columns, rows);
  const body = sorted.map((row) =>
    `<tr>${columns.map((column) =>
      `<td data-label="${column.label}">${escapeHtml(row[column.key] ?? "")}</td>`).join("")}</tr>`
  ).join("");
  $(target).innerHTML = `
    ${sortBar(tableKey, columns)}
    <table>
      <thead><tr>${sortableHead(tableKey, columns)}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

async function loadDashboard() {
  const [data, breakdown] = await Promise.all([
    api("/dashboard/summary"),
    api("/dashboard/breakdown"),
  ]);

  const metrics = [
    ["총 자산", data.total_assets],
    ["사용 중", data.assigned_assets],
    ["보관", data.storage_assets],
    ["수리", data.repair_assets],
    ["렌탈 만료 예정", data.rental_expiring],
    ["라이선스 만료 예정", data.license_expiring],
    ["IP 사용률", `${data.ip_usage_rate}%`],
  ];
  $("#summaryCards").innerHTML = metrics
    .map(([label, value]) => `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");

  stackedBar("#statusChart", breakdown.by_status, (key) => ASSET_STATUS[key] || key);
  stackedBar("#typeChart", breakdown.by_type, (key) => ASSET_TYPES[key] || key);
}

// 부분-전체 비율은 가로 스택 막대로 그린다. 색은 항목 순서에 고정 배정(순위에 따라 바뀌지 않음).
function stackedBar(target, items, labelOf) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  if (!total) {
    $(target).innerHTML = `<p class="muted">데이터가 없습니다.</p>`;
    return;
  }

  const segments = items.map((item, index) => ({
    label: labelOf(item.key),
    count: item.count,
    percent: Math.round((item.count / total) * 100),
    color: SERIES_COLORS[index % SERIES_COLORS.length],
  }));

  $(target).innerHTML = `
    <div class="stack" role="img" aria-label="${escapeHtml(
      segments.map((segment) => `${segment.label} ${segment.count}대`).join(", ")
    )}">
      ${segments.map((segment) => `
        <span class="stack-seg" style="flex: ${segment.count}; background: ${segment.color};"></span>
      `).join("")}
    </div>
    <ul class="legend">
      ${segments.map((segment) => `
        <li>
          <span class="swatch" style="background: ${segment.color};"></span>
          <span class="legend-label">${escapeHtml(segment.label)}</span>
          <span class="legend-value">${segment.count}대 · ${segment.percent}%</span>
        </li>
      `).join("")}
    </ul>
  `;
}

async function loadIps() {
  // 전화기 IP 는 내선번호에 붙으므로 내선 목록도 필요하다.
  const [ranges, assignments, assets, extensions] = await Promise.all([
    api("/ip-ranges"),
    api("/ip-assignments"),
    api("/assets/"),
    api("/extensions/"),
  ]);
  state.assets = assets;
  state.ipAssignments = assignments;
  state.extensions = extensions;
  renderManaged("ipRanges", ranges);
  renderIpAssignments();
  await renderIpForm();
}

// ---- IP 하나씩 넣는 폼 ----
//
// 고를 대상과 빈 IP 후보가 '구분'에 따라 달라진다.

async function renderIpForm() {
  const form = $("#ipAssignForm");
  const kind = form.kind.value;

  if (kind === "PHONE") {
    // 이미 IP 가 붙은 내선은 뺀다 — 내선 하나에 IP 하나다.
    const free = (state.extensions || []).filter((e) => !e.ip_address);
    $("#ipTarget").innerHTML = options(free,
      (e) => `내선 ${e.number}${e.employee_name ? ` · ${e.employee_name}` : " · (빈 번호)"}`,
      "id", "내선번호 선택");
    hint(free.length
      ? ""
      : ((state.extensions || []).length
          ? "모든 내선번호에 이미 IP 가 붙어 있습니다."
          : "내선번호가 없습니다. '내선 관리' 에서 번호를 먼저 등록하세요."));
  } else {
    const assets = (state.assets || [])
      .slice().sort((a, b) => String(a.asset_no).localeCompare(String(b.asset_no)));
    $("#ipTarget").innerHTML = options(assets, assetLabel, "id", "자산 선택");
    hint("");
  }

  // 빈 IP 후보. 구분에 맞는 대역에서만 뽑는다.
  try {
    const free = await api(`/ip-addresses/free?kind=${kind}`);
    $("#dl-free-ip").innerHTML = free.slice(0, 400)
      .map((row) => `<option value="${escapeHtml(row.ip_address)}"></option>`).join("");
  } catch {
    $("#dl-free-ip").innerHTML = "";
  }

  function hint(message) {
    $("#ipAssignHint").textContent = message;
    $("#ipAssignHint").hidden = !message;
  }
}

$("#ipAssignForm").kind.addEventListener("change", () => {
  renderIpForm().catch((error) => toast(error.message));
});

$("#ipAssignForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!guard("ips")) return;

  const form = event.target;
  const kind = form.kind.value;
  const target = form.target.value;
  const ip = form.ip_address.value.trim();

  if (!target) return toast(kind === "PHONE" ? "내선번호를 고르세요." : "자산을 고르세요.");
  if (!ip) return toast("IP 주소를 입력하세요.");

  const payload = { kind, ip_address: ip, status: "USED" };
  payload[kind === "PHONE" ? "extension_id" : "asset_id"] = target;
  if (form.hostname.value.trim()) payload.hostname = form.hostname.value.trim();

  try {
    await api("/ip-assignments", { method: "POST", body: JSON.stringify(payload) });
    form.ip_address.value = "";
    form.hostname.value = "";
    await loadIps();
    toast(`${ip} 를 등록했습니다.`);
  } catch (error) {
    toast(error.message);
  }
});

const IP_KIND_LABEL = { NETWORK: "네트워크", PHONE: "전화기" };

const IP_ASSIGNMENT_COLUMNS = [
  { key: "ip_address", label: "IP", className: "mono" },
  { key: "kind", label: "구분",
    render: (row) => IP_KIND_LABEL[row.kind] || row.kind || "-" },
  // 네트워크 IP 는 자산번호를, 전화기 IP 는 내선번호와 쓰는 사람을 보여준다.
  { key: "target", label: "붙은 곳",
    sortValue: (row) => row.asset_no || row.extension_number || "",
    // 사람 이름은 옆 '사용자' 칸에 있다. 여기서 또 쓰면 같은 값이 두 번 나온다.
    render: (row) => (row.kind === "PHONE"
      ? `내선 ${escapeHtml(row.extension_number || "-")}`
      : escapeHtml(row.asset_no || "-")) },
  // '붙은 곳' 은 어느 장비/번호에 달렸는지, '사용자' 는 그걸 쓰는 사람이다.
  // 예전 '호스트' 칸은 자료마다 자산번호가 들어 있기도 하고 사람 이름이
  // 들어 있기도 해서 헷갈렸다. 메모 성격이라 모달에서만 보여준다.
  { key: "employee_name", label: "사용자",
    render: (row) => (row.employee_name
      ? `${escapeHtml(row.employee_name)}<br /><small class="muted">${escapeHtml(row.employee_department || "-")}</small>`
      : `<span class="muted">-</span>`) },
  { key: "status", label: "상태" },
];

function renderIpAssignments() {
  const all = state.ipAssignments || [];
  const rows = state.ipKind ? all.filter((row) => row.kind === state.ipKind) : all;

  const phones = all.filter((row) => row.kind === "PHONE").length;
  $("#ipCount").textContent = `전체 ${all.length}개 · 전화기 ${phones}개`;

  const sorted = applySort("ipAssignments", IP_ASSIGNMENT_COLUMNS, rows);
  const body = sorted.map((row) => `
    <tr class="clickable" data-open-ip="${row.id}">${IP_ASSIGNMENT_COLUMNS.map((column) => {
      const value = column.render ? column.render(row) : escapeHtml(row[column.key] ?? "-");
      return `<td data-label="${column.label}" class="${column.className || ""}">${value}</td>`;
    }).join("")}</tr>`).join("");

  $("#ipAssignmentsTable").innerHTML = `
    ${sortBar("ipAssignments", IP_ASSIGNMENT_COLUMNS)}
    <table class="managed">
      <thead><tr>${sortableHead("ipAssignments", IP_ASSIGNMENT_COLUMNS)}</tr></thead>
      <tbody>${body || `<tr><td class="muted empty" colspan="${IP_ASSIGNMENT_COLUMNS.length}">해당하는 IP 가 없습니다.</td></tr>`}</tbody>
    </table>
  `;
}

// 줄을 누르면 모달. 다른 표와 같은 조작이다.
$("#ipAssignmentsTable").addEventListener("click", (event) => {
  const rowEl = event.target.closest("[data-open-ip]");
  if (!rowEl) return;
  const row = (state.ipAssignments || []).find((item) => item.id === rowEl.dataset.openIp);
  if (!row) return;

  const where = row.kind === "PHONE"
    ? `내선 ${row.extension_number || "-"}`
    : `자산 ${row.asset_no || "-"}`;
  const who = row.employee_name ? ` · ${row.employee_name}` : " · (쓰는 사람 없음)";

  openEdit({
    title: row.ip_address,
    need: "ips",
    subtitle: `${IP_KIND_LABEL[row.kind] || row.kind} · ${where}${who}`,
    fields: [
      { name: "ip_address", label: "IP 주소", type: "text", value: row.ip_address },
      { name: "hostname", label: "호스트명 (메모)", type: "text", value: row.hostname,
        hint: "장비 이름 등 자유 메모입니다. 사용자는 위 부제목에 나옵니다." },
      { name: "mac_address", label: "MAC 주소", type: "text", value: row.mac_address },
      // 전화기 IP 는 내선에 붙어 있는 한 늘 '사용 중'이라 고를 것이 없다.
      // 골라봐야 서버가 되돌리고, 그 사이 화면만 헷갈린다.
      ...(row.kind === "PHONE" ? [] : [
        { name: "status", label: "상태", type: "select",
          options: { USED: "사용 중", RESERVED: "예약", FREE: "비어 있음" },
          value: row.status || "USED",
          hint: "'비어 있음' 으로 두면 그 주소를 다른 곳에 다시 줄 수 있습니다." },
      ]),
    ],
    async onSave(payload) {
      await api(`/ip-assignments/${row.id}`, { method: "PUT", body: JSON.stringify(payload) });
      toast("수정했습니다.");
      await loadIps();
      // 내선·직원별 현황에도 전화기 IP 가 나오므로 같이 새로 받는다
      if (state.workspace.length) await loadWorkspace();
    },
    async onDelete() {
      if (!await ask(`${row.ip_address} 를 목록에서 지울까요?\n${where} 에서 떨어집니다.`,
                     { ok: "삭제" })) return false;
      await api(`/ip-assignments/${row.id}`, { method: "DELETE" });
      toast("IP 를 지웠습니다.");
      await loadIps();
      if (state.workspace.length) await loadWorkspace();
      return true;
    },
  });
});

$("#ipKindTabs").addEventListener("click", (event) => {
  const button = event.target.closest("[data-ip-kind]");
  if (!button) return;
  state.ipKind = button.dataset.ipKind;
  [...$("#ipKindTabs").children].forEach((el) =>
    el.classList.toggle("on", el === button));
  renderIpAssignments();
});

// ------------------------------------------------------------------ 내선 관리
//
// IP 와 비슷하지만 붙는 대상이 다르다. IP 는 장비에, 내선은 사람에게 붙는다.
// 그래서 자리를 옮겨도 번호는 그 사람을 따라간다.

async function loadExtensions() {
  // 사람을 고르는 상자를 그리려면 직원 명단이 필요하다.
  if (!state.workspace.length) await loadWorkspace();
  state.extensions = await api("/extensions/");

  // 구역은 쓰던 값을 그대로 다시 고를 수 있게 (오타로 '3층'/'3F' 가 섞이는 걸 줄인다)
  const zones = [...new Set(state.extensions.map((row) => row.zone).filter(Boolean))].sort();
  $("#dl-ext-zone").innerHTML = zones.map((z) => `<option value="${escapeHtml(z)}"></option>`).join("");

  renderExtensions();
}

const EXTENSION_COLUMNS = [
  { key: "number", label: "내선번호", className: "mono",
    // 문자열로 정렬하면 1000 이 900 앞에 온다
    sortValue: (row) => (/^\d+$/.test(row.number) ? Number(row.number) : row.number) },
  { key: "employee_name", label: "사용자",
    render: (row) => (row.employee_name
      ? `<strong>${escapeHtml(row.employee_name)}</strong>`
      : `<span class="muted">빈 번호</span>`) },
  { key: "employee_department", label: "부서" },
  { key: "ip_address", label: "전화기 IP", className: "mono",
    render: (row) => (row.ip_address
      ? escapeHtml(row.ip_address)
      : `<span class="muted">-</span>`) },
  { key: "zone", label: "구역" },
  { key: "note", label: "메모" },
];

function renderExtensions() {
  const query = ($("#extensionSearch").value || "").trim().toLowerCase();
  const filter = $("#extensionFilter").value;

  const rows = (state.extensions || []).filter((row) => {
    if (filter === "used" && !row.employee_id) return false;
    if (filter === "free" && row.employee_id) return false;
    if (!query) return true;
    return [row.number, row.zone, row.note, row.employee_name,
            row.employee_no, row.employee_department]
      .filter(Boolean).some((v) => String(v).toLowerCase().includes(query));
  });

  const free = (state.extensions || []).filter((row) => !row.employee_id).length;
  $("#extensionCount").textContent =
    `${state.extensions.length}개 · 빈 번호 ${free}개`;

  // 행을 누르면 모달이 뜬다 (자산 등록·직원 명단과 같은 조작).
  // 공용 table() 은 render 와 행 클릭을 지원하지 않아서 여기서 직접 그린다.
  const sorted = applySort("extensions", EXTENSION_COLUMNS, rows);
  const body = sorted.map((row) => `
    <tr class="clickable" data-open-extension="${row.id}">
      ${EXTENSION_COLUMNS.map((column) => {
        const value = column.render
          ? column.render(row)
          : escapeHtml(row[column.key] || "-");
        return `<td data-label="${column.label}" class="${column.className || ""}">${value}</td>`;
      }).join("")}
    </tr>`).join("");

  $("#extensionsTable").innerHTML = `
    ${sortBar("extensions", EXTENSION_COLUMNS)}
    <table class="managed">
      <thead><tr>${sortableHead("extensions", EXTENSION_COLUMNS)}</tr></thead>
      <tbody>${body || `<tr><td class="muted empty" colspan="${EXTENSION_COLUMNS.length}">해당하는 번호가 없습니다.</td></tr>`}</tbody>
    </table>
  `;
  updateAuthUI();
}

// ---- 내선 화면의 조작 ----

// ---- 자료 넣기 (엑셀·CSV 올리기) ----
//
// 미리보기 먼저 보여주고, 한 번 더 눌러야 실제로 들어간다.
// 남의 자료를 한 방에 갈아엎는 일은 없어야 한다.

let importPreview = null;   // 미리보기 결과. 이게 있어야 [넣기] 가 열린다
// 고른 파일과 덮어쓰기 여부는 여기에 들고 있는다.
// 미리보기 결과를 그리면서 모달을 다시 그리는데, 그때 <input type=file> 이
// 새로 만들어지면서 고른 파일이 날아간다. DOM 에만 의지하면 [넣기] 를 누를 때
// "파일을 고르세요" 가 뜬다.
let importFile = null;
let importOverwrite = false;
let importKind = "extensions";   // 지금 무엇을 넣는 중인가

/* 자료 넣기는 화면마다 대상이 다르지만 **하는 일은 같다** —
   파일 고르기 → 미리보기 → 넣기. 그래서 창은 하나만 두고 여기 적힌
   차이만 갈아 끼운다. 창을 대상마다 만들면 한쪽만 고치는 일이 생긴다. */
const IMPORT_KINDS = {
  extensions: {
    need: "extensions",
    title: "내선번호 자료 넣기",
    path: "/extensions/import",
    overwriteLabel: "이미 있는 번호도 파일 내용으로 덮어쓰기",
    help: `첫 줄에 칸 이름이 있어야 합니다. <b>내선번호</b> 칸은 꼭 필요하고,
           <b>이름 · IP · 사번 · 부서 · 구역 · 메모</b> 는 있으면 같이 읽습니다.<br />
           예) <code>내선번호 | 이름 | IP</code> → <code>1234 | 정예호 | 10.10.100.11</code>`,
    columns: [
      ["내선", (r) => r.number, "mono"],
      ["사용자", (r) => r.employee_name || "(빈 번호)"],
      ["전화기 IP", (r) => r.ip || "-", "mono"],
      ["구역", (r) => r.zone || "-"],
    ],
    reload: async () => {
      await loadExtensions();
      if (state.workspace.length) await loadWorkspace();
    },
  },
  employees: {
    need: "employees",
    title: "직원 명단 자료 넣기",
    path: "/employees/import",
    overwriteLabel: "이미 있는 사번도 파일 내용으로 덮어쓰기",
    help: `첫 줄에 칸 이름이 있어야 합니다. <b>사번 · 이름</b> 은 꼭 필요하고,
           <b>부서 · 직책 · 상태 · 이메일 · 입사일 · 연락처</b> 는 있으면 같이 읽습니다.<br />
           위의 <b>CSV 내려받기</b> 로 받은 파일이 그대로 양식입니다.<br />
           상태에 <b>퇴사</b> 라고 적으면 퇴사 처리됩니다. 비워 두면 재직입니다.`,
    columns: [
      ["사번", (r) => r.emp_no, "mono"],
      ["이름", (r) => r.name],
      ["부서", (r) => r.department || "-"],
      ["상태", (r) => ({ACTIVE: "재직", INACTIVE: "퇴사", LEAVE: "휴직"}[r.status])],
    ],
    reload: async () => { await loadEmployees(); },
  },
  assets: {
    need: "assets",
    title: "자산 자료 넣기",
    path: "/assets/import",
    overwriteLabel: "이미 있는 자산번호도 파일 내용으로 덮어쓰기",
    help: `첫 줄에 칸 이름이 있어야 합니다. <b>자산번호</b> 는 꼭 필요하고,
           <b>유형 · 제조사 · 모델 · CPU · 메모리 · 운영체제 · 상태 · 사용자</b> 는
           있으면 같이 읽습니다.<br />
           위의 <b>CSV 내려받기</b> 로 받은 파일이 그대로 양식입니다.<br />
           <b>사용자</b> 에 이름이나 사번을 적으면 그 사람에게 지급 처리까지 합니다.`,
    columns: [
      ["자산번호", (r) => r.asset_no, "mono"],
      ["유형", (r) => ASSET_TYPES[r.asset_type] || r.asset_type],
      ["모델", (r) => r.model || "-"],
      ["사용자", (r) => r.holder_name || "(보관)"],
    ],
    reload: async () => { await loadAssets(); },
  },
  ips: {
    need: "ips",
    title: "IP 자료 넣기",
    path: "/ip-assignments/import",
    overwriteLabel: "이미 쓰이고 있는 IP 도 파일 내용으로 덮어쓰기",
    help: `첫 줄에 칸 이름이 있어야 합니다. <b>IP</b> 칸은 꼭 필요하고,
           <b>구분 · 자산번호 · 내선 · 호스트명 · MAC</b> 은 있으면 같이 읽습니다.<br />
           위의 <b>CSV 내려받기</b> 로 받은 파일이 그대로 양식입니다.<br />
           예) <code>IP | 자산번호 | 호스트명</code> → <code>10.20.30.100 | HAF03467 | pc-01</code>`,
    columns: [
      ["IP", (r) => r.ip, "mono"],
      ["구분", (r) => (r.kind === "PHONE" ? "전화기" : "네트워크")],
      ["붙는 곳", (r) => r.asset_no || (r.extension ? `내선 ${r.extension}` : "-"), "mono"],
      ["대역", (r) => r.range_name || "-"],
    ],
    reload: async () => { await loadIps(); },
  },
};

function openImport(kind) {
  const spec = IMPORT_KINDS[kind];
  if (!spec) return;
  if (!guard(spec.need)) return;
  importKind = kind;
  importPreview = null;
  importFile = null;
  importOverwrite = false;
  renderImport();
  $("#importModal").hidden = false;
  $("#importBackdrop").hidden = false;
}

$("#extImportBtn").addEventListener("click", () => openImport("extensions"));
$("#ipImportBtn").addEventListener("click", () => openImport("ips"));
$("#empImportBtn").addEventListener("click", () => openImport("employees"));
$("#assetImportBtn").addEventListener("click", () => openImport("assets"));

function closeImport() {
  $("#importModal").hidden = true;
  $("#importBackdrop").hidden = true;
  importPreview = null;
  importFile = null;
}

// 파일을 고르거나 덮어쓰기를 켜면 앞서 본 미리보기는 더 이상 맞지 않는다
$("#importModal").addEventListener("change", (event) => {
  if (event.target.id === "importFile") {
    importFile = event.target.files?.[0] || null;
    importPreview = null;
    renderImport();
  }
  if (event.target.id === "importOverwrite") {
    importOverwrite = event.target.checked;
    importPreview = null;
    renderImport();
  }
});

$("#importBackdrop").addEventListener("click", closeImport);

function renderImport(busy = false) {
  const preview = importPreview;
  const spec = IMPORT_KINDS[importKind];

  const summary = preview ? `
    <div class="edit-extra">
      <p><b>${preview.new.length}개</b> 새로 들어갑니다
        ${preview.update.length ? ` · <b>${preview.update.length}개</b> 덮어씁니다` : ""}
        ${preview.skipped.length ? ` · <b>${preview.skipped.length}줄</b>은 건너뜁니다` : ""}
      </p>
      <p class="muted" style="font-size:12.5px">찾은 칸: ${escapeHtml(preview.columns.join(", "))}</p>

      ${preview.new.length ? `
        <table class="spec-table">
          <thead><tr>${spec.columns.map(([label]) => `<th>${escapeHtml(label)}</th>`).join("")}</tr></thead>
          <tbody>
            ${preview.new.slice(0, 12).map((row) => `
              <tr>${spec.columns.map(([label, get, cls]) => {
                const text = String(get(row) ?? "-");
                const dim = text === "-" || text.startsWith("(");
                // data-label — 좁은 화면에서 머리글이 숨을 때 이름표가 된다
                return `<td class="${cls || ""}" data-label="${escapeHtml(label)}">${dim
                  ? `<span class="muted">${escapeHtml(text)}</span>` : escapeHtml(text)}</td>`;
              }).join("")}</tr>`).join("")}
          </tbody>
        </table>
        ${preview.new.length > 12 ? `<p class="muted">… 그리고 ${preview.new.length - 12}개 더</p>` : ""}
      ` : ""}

      ${preview.skipped.length ? `
        <p style="margin-top:14px"><b>건너뛰는 줄</b> — 엑셀에서 고치고 다시 올리면 됩니다.</p>
        <ul class="skip-list">
          ${preview.skipped.slice(0, 15).map((line) => `<li>${escapeHtml(line)}</li>`).join("")}
          ${preview.skipped.length > 15 ? `<li class="muted">… 그리고 ${preview.skipped.length - 15}줄 더</li>` : ""}
        </ul>` : ""}
    </div>` : "";

  $("#importModal").innerHTML = `
    <div class="drawer-head">
      <div>
        <h3>${escapeHtml(spec.title)}</h3>
        <p>엑셀(.xlsx) 이나 CSV 를 올리면 먼저 무엇이 들어갈지 보여줍니다.</p>
      </div>
      <span class="spacer"></span>
      <button class="icon-btn" data-import-close title="닫기">×</button>
    </div>

    <div class="drawer-scroll">
      <p class="muted" style="margin-top:0;font-size:13px;line-height:1.8">${spec.help}</p>

      <label class="field">
        <span>파일</span>
        <input type="file" id="importFile" accept=".xlsx,.xlsm,.csv" />
        ${importFile ? `<small class="hint">고른 파일: ${escapeHtml(importFile.name)}</small>` : ""}
      </label>

      <label class="check">
        <input type="checkbox" id="importOverwrite" ${importOverwrite ? "checked" : ""} />
        <span>${escapeHtml(spec.overwriteLabel)}</span>
      </label>

      ${summary}
    </div>

    <div class="drawer-foot">
      <span class="spacer"></span>
      <button class="secondary" data-import-close>닫기</button>
      <button class="secondary" data-import-preview ${busy ? "disabled" : ""}>미리보기</button>
      <button data-import-apply ${preview && (preview.new.length || preview.update.length) && !busy ? "" : "disabled"}>
        넣기
      </button>
    </div>
  `;
  updateAuthUI();
}

async function sendImport(apply) {
  if (!importFile) {
    toast("파일을 고르세요.");
    return null;
  }

  const body = new FormData();
  body.append("file", importFile);
  body.append("apply", apply ? "true" : "false");
  body.append("overwrite", importOverwrite ? "true" : "false");

  renderImport(true);
  // 주의: FormData 를 보낼 때는 Content-Type 을 우리가 정하면 안 된다.
  // 경계 문자열(boundary)이 빠져서 서버가 못 읽는다. 그래서 api() 대신 fetch 를 쓴다.
  const response = await fetch(`${apiBase()}${IMPORT_KINDS[importKind].path}`, {
    method: "POST",
    headers: state.token ? { Authorization: `Bearer ${state.token}` } : {},
    body,
  });
  const text = await response.text();
  if (!response.ok) {
    importPreview = null;
    renderImport();
    throw new Error(errorText(text) || `요청 실패 (${response.status})`);
  }
  return JSON.parse(text);
}

$("#importModal").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.dataset.importClose !== undefined) return closeImport();

  try {
    if (button.dataset.importPreview !== undefined) {
      const result = await sendImport(false);
      if (!result) return renderImport();
      importPreview = result;
      renderImport();
      if (!importPreview.new.length && !importPreview.update.length) {
        toast("새로 넣을 것이 없습니다. 아래 이유를 확인하세요.");
      }
      return;
    }

    if (button.dataset.importApply !== undefined) {
      const result = await sendImport(true);
      if (!result) return renderImport();
      const spec = IMPORT_KINDS[importKind];
      closeImport();
      await spec.reload();
      toast(`${result.added}개를 넣었습니다.`
        + (result.updated ? ` (덮어쓴 것 ${result.updated}개)` : "")
        + (result.skipped.length ? ` · ${result.skipped.length}줄은 건너뛰었습니다.` : ""));
    }
  } catch (error) {
    toast(error.message);
  }
});

$("#extensionSearch").addEventListener("input", renderExtensions);
$("#extensionFilter").addEventListener("change", renderExtensions);
bindSort("extensions", "#extensionsTable", renderExtensions);

$("#extensionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!guard("extensions")) return;

  const payload = formData(event.target);
  // IP 는 내선 표가 아니라 ip_assignments 에 들어간다. 폼에서만 같이 받는다.
  const ip = (payload.ip_address || "").trim();
  delete payload.ip_address;

  try {
    const created = await api("/extensions/", { method: "POST", body: JSON.stringify(payload) });
    if (ip) await savePhoneIp(created.id, ip, null);
    event.target.reset();
    await loadExtensions();
    toast(ip ? "내선번호와 전화기 IP 를 등록했습니다." : "내선번호를 등록했습니다.");
  } catch (error) {
    toast(error.message);
  }
});

// 전화기 IP 를 붙이거나 바꾸거나 뗀다.
// IP 는 ip_assignments 에 살고, 내선 하나에 하나만 붙는다.
async function savePhoneIp(extensionId, nextIp, currentIp) {
  if ((nextIp || "") === (currentIp || "")) return;

  const existing = await api(`/ip-assignments?extension_id=${extensionId}`);

  // 주의: 지우고 다시 만들면 안 된다. 새 주소가 이미 쓰이는 것이면 만들기가
  // 막히는데, 그때는 이미 지운 뒤라 멀쩡하던 IP 까지 날아간다.
  // 있던 줄을 고치는 쪽으로 하면 실패해도 원래 것이 그대로 남는다.
  if (existing.length && nextIp) {
    await api(`/ip-assignments/${existing[0].id}`, {
      method: "PUT", body: JSON.stringify({ ip_address: nextIp }),
    });
    // 혹시 둘 이상 붙어 있었다면(있으면 안 되지만) 나머지는 정리한다
    for (const row of existing.slice(1)) {
      await api(`/ip-assignments/${row.id}`, { method: "DELETE" });
    }
    return;
  }

  if (existing.length && !nextIp) {
    for (const row of existing) {
      await api(`/ip-assignments/${row.id}`, { method: "DELETE" });
    }
    return;
  }

  if (nextIp) {
    await api("/ip-assignments", {
      method: "POST",
      body: JSON.stringify({ kind: "PHONE", extension_id: extensionId, ip_address: nextIp }),
    });
  }
}

$("#extensionsTable").addEventListener("click", (event) => {
  const rowEl = event.target.closest("[data-open-extension]");
  if (!rowEl) return;
  const row = state.extensions.find((item) => item.id === rowEl.dataset.openExtension);
  if (!row) return;

  // 이미 다른 번호를 쓰고 있는 사람은 고를 수 없다 — 서버도 막지만,
  // 애초에 목록에 안 보여야 헛걸음을 안 한다.
  const takenIds = new Set(state.extensions
    .filter((item) => item.employee_id && item.id !== row.id)
    .map((item) => item.employee_id));
  const free = state.workspace
    .filter((e) => e.status === "ACTIVE" && !takenIds.has(e.id))
    .sort((a, b) => a.name.localeCompare(b.name, "ko"));

  openEdit({
    title: `내선 ${row.number}`,
    need: "extensions",
    subtitle: row.employee_name
      ? `${row.employee_name} · ${row.employee_department || "-"}`
      : "아직 아무도 안 쓰는 번호",
    fields: [
      { name: "number", label: "내선번호", type: "text", value: row.number },
      { name: "__holder", label: "사용자", type: "select",
        options: Object.fromEntries([["", "(빈 번호)"],
          ...free.map((e) => [e.id, `${e.name} (${e.department || "-"})`])]),
        value: row.employee_id || "",
        hint: "한 사람에 번호 하나입니다. 이미 다른 번호를 쓰는 사람은 목록에 없습니다." },
      { name: "__ip", label: "전화기 IP", type: "text", value: row.ip_address,
        hint: "비우면 IP 를 떼어냅니다. 같은 주소를 두 곳에 줄 수는 없습니다." },
      { name: "zone", label: "구역", type: "text", value: row.zone },
      { name: "note", label: "메모", type: "text", value: row.note },
    ],
    async onSave(payload) {
      const nextHolder = payload.__holder || null;
      const nextIp = (payload.__ip || "").trim();
      delete payload.__holder;
      delete payload.__ip;

      await api(`/extensions/${row.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      await savePhoneIp(row.id, nextIp, row.ip_address);

      const current = row.employee_id || null;
      if (nextHolder !== current) {
        await api(`/extensions/${row.id}/employee`, {
          method: "PUT", body: JSON.stringify({ employee_id: nextHolder }),
        });
        toast(nextHolder ? "사용자를 지정했습니다." : "번호를 비웠습니다.");
      } else {
        toast("수정했습니다.");
      }
      await loadExtensions();
      // 직원별 현황·배치도·IP 관리에도 나오므로 같이 새로 받는다
      if (state.workspace.length) await loadWorkspace();
      if (state.ipAssignments) state.ipAssignments = await api("/ip-assignments");
    },
    async onDelete() {
      if (!await ask(`내선 ${row.number} 를 목록에서 지울까요?`, { ok: "삭제" })) return false;
      await api(`/extensions/${row.id}`, { method: "DELETE" });
      toast("내선번호를 지웠습니다.");
      await loadExtensions();
      return true;
    },
  });
});

async function loadSoftware() {
  const [products, licenses, installations, assets, held] = await Promise.all([
    api("/software-products"),
    api("/license-pools"),
    api("/software-installations"),
    api("/assets/"),
    // 소프트웨어마다 '누가 쓰고 있는지'를 보여주려면 부여 현황이 필요하다.
    api("/license-assignments/?active_only=true"),
  ]);
  state.softwareProducts = products;
  state.installations = installations;
  state.assets = assets;
  state.licenseHolders = held;
  renderManaged("software", products);
  renderManaged("licenses", licenses);
}

async function loadRentals() {
  const [rows, assets] = await Promise.all([api("/rental-contracts/"), api("/assets/")]);
  state.assets = assets;
  renderManaged("rentals", rows);
}

// ------------------------------------------- 관리형 테이블: 펼쳐서 상세 보기 + 수정 + 삭제
// 소프트웨어 · 라이선스 · 렌탈 · IP 대역이 같은 구조라 하나의 설정으로 처리한다.

const MANAGED = {
  software: {
    target: "#softwareTable",
    path: "/software-products",
    load: loadSoftware,
    label: (row) => row.name,
    columns: [
      { key: "name", label: "제품명", edit: "text" },
      { key: "vendor", label: "벤더", edit: "text" },
      { key: "license_type", label: "유형", edit: "text" },
      {
        key: "installs",
        label: "설치",
        render: (row) => `${installsOf(row.id).length}대`,
        sortValue: (row) => installsOf(row.id).length,
      },
    ],
    detail: (row) => {
      const installed = installsOf(row.id);
      const assetsById = new Map(state.assets.map((asset) => [asset.id, asset]));
      // 이 소프트웨어의 라이선스를 지금 보유한 사람들.
      // 예전에는 직원별 현황을 한 명씩 열어봐야 알 수 있었다.
      const holders = (state.licenseHolders || [])
        .filter((h) => h.software_name === row.name)
        .sort((a, b) => (a.employee_name || "").localeCompare(b.employee_name || "", "ko"));
      return `
        <dl class="detail">
          <dt>설명</dt><dd>${escapeHtml(row.description || "-")}</dd>
          <dt>라이선스 보유</dt>
          <dd>${holders.length
            ? `<span class="chip">${holders.length}명</span>
               <ul class="detail-list">${holders.map((h) =>
                 `<li>${escapeHtml(h.employee_name || "?")}</li>`).join("")}</ul>`
            : `<span class="muted">보유한 직원이 없습니다.</span>`}</dd>
          <dt>설치된 자산</dt>
          <dd>${installed.length
            ? `<span class="chip">${installed.length}대</span>
               <ul class="detail-list">${installed.map((install) => {
                const asset = assetsById.get(install.asset_id);
                return `<li>${escapeHtml(asset ? assetLabel(asset) : "알 수 없는 자산")}</li>`;
              }).join("")}</ul>`
            : `<span class="muted">설치된 자산이 없습니다.</span>`}</dd>
        </dl>
      `;
    },
  },

  licenses: {
    target: "#licensesTable",
    path: "/license-pools",
    load: loadSoftware,
    label: (row) => productName(row.software_id),
    columns: [
      {
        key: "software_id",
        label: "제품",
        edit: "select",
        options: () => Object.fromEntries(state.softwareProducts.map((p) => [p.id, p.name])),
        render: (row) => escapeHtml(productName(row.software_id)),
      },
      { key: "purchased_count", label: "구매", edit: "number" },
      { key: "used_count", label: "사용", edit: "number" },
      { key: "expire_date", label: "만료일", edit: "date" },
    ],
    detail: (row) => `
      <dl class="detail">
        <dt>잔여 수량</dt><dd>${(row.purchased_count || 0) - (row.used_count || 0)}개</dd>
        <dt>만료일</dt><dd>${escapeHtml(row.expire_date || "-")}</dd>
        <dt>만료 알림</dt><dd>${row.alert_days || 30}일 전</dd>
      </dl>
    `,
  },

  rentals: {
    target: "#rentalsTable",
    path: "/rental-contracts",
    load: loadRentals,
    label: (row) => row.contract_no || row.vendor,
    columns: [
      { key: "vendor", label: "업체", edit: "text" },
      { key: "contract_no", label: "계약번호", edit: "text" },
      { key: "start_date", label: "시작일", edit: "date" },
      { key: "end_date", label: "종료일", edit: "date" },
      { key: "monthly_fee", label: "월 비용", edit: "number" },
      {
        key: "status",
        label: "상태",
        edit: "select",
        options: () => ({ ACTIVE: "진행 중", ENDED: "종료" }),
        render: (row) => (row.status === "ENDED" ? "종료" : "진행 중"),
      },
    ],
    detail: (row) => {
      const asset = state.assets.find((item) => item.id === row.asset_id);
      return `
        <dl class="detail">
          <dt>대상 자산</dt><dd>${escapeHtml(asset ? assetLabel(asset) : "-")}</dd>
          <dt>계약 기간</dt><dd>${escapeHtml(row.start_date || "-")} ~ ${escapeHtml(row.end_date || "-")}</dd>
          <dt>월 비용</dt><dd>${row.monthly_fee ? `${Number(row.monthly_fee).toLocaleString()}원` : "-"}</dd>
        </dl>
      `;
    },
  },

  ipRanges: {
    target: "#ipRangesTable",
    path: "/ip-ranges",
    load: loadIps,
    label: (row) => row.name,
    columns: [
      { key: "name", label: "대역명", edit: "text" },
      { key: "kind", label: "구분", edit: "select",
        options: () => ({ NETWORK: "네트워크 (PC·서버)", PHONE: "전화기" }),
        render: (row) => IP_KIND_LABEL[row.kind] || "네트워크" },
      { key: "start_ip", label: "시작", edit: "text" },
      { key: "end_ip", label: "종료", edit: "text" },
      { key: "vlan", label: "VLAN", edit: "text" },
    ],
    detail: (row) => {
      const used = (state.ipAssignments || []).filter((item) => item.ip_range_id === row.id).length;
      return `
        <dl class="detail">
          <dt>범위</dt><dd>${escapeHtml(row.start_ip)} ~ ${escapeHtml(row.end_ip)}</dd>
          <dt>게이트웨이</dt><dd>${escapeHtml(row.gateway || "-")}</dd>
          <dt>DNS</dt><dd>${escapeHtml(row.dns || "-")}</dd>
          <dt>할당된 IP</dt><dd>${used}개</dd>
          <dt>설명</dt><dd>${escapeHtml(row.description || "-")}</dd>
        </dl>
      `;
    },
  },
};

function installsOf(softwareId) {
  return (state.installations || []).filter((item) => item.software_id === softwareId);
}

function productName(softwareId) {
  return state.softwareProducts.find((product) => product.id === softwareId)?.name || "알 수 없는 제품";
}

function renderManaged(key, rows) {
  if (rows) state.managedRows[key] = rows;
  const config = MANAGED[key];
  const data = applySort(key, config.columns, state.managedRows[key] || []);

  // 행을 누르면 모달이 열린다. 펼침 화살표와 작업 버튼 열은 없앴다
  // (자산 등록·직원 명단과 같은 조작으로 맞춤).
  const head = config.columns;

  $(config.target).innerHTML = `
    ${sortBar(key, config.columns)}
    <table class="managed">
      <thead><tr>${sortableHead(key, head)}</tr></thead>
      <tbody>
        ${data.length
          ? data.map((row) => managedRow(key, config, row)).join("")
          : `<tr><td class="muted empty" colspan="${config.columns.length}">데이터가 없습니다.</td></tr>`}
      </tbody>
    </table>
  `;
  updateAuthUI();
}

function managedRow(key, config, row) {
  const cells = config.columns.map((column) => {
    const value = column.render ? column.render(row) : escapeHtml(row[column.key] ?? "-");
    return `<td data-label="${column.label}">${value}</td>`;
  }).join("");

  return `<tr class="clickable" data-open-managed="${key}:${row.id}">${cells}</tr>`;
}

function bindManaged(key) {
  const config = MANAGED[key];

  $(config.target).addEventListener("click", (event) => {
    const rowEl = event.target.closest("[data-open-managed]");
    if (!rowEl) return;
    const row = (state.managedRows[key] || [])
      .find((item) => item.id === rowEl.dataset.openManaged.split(":")[1]);
    if (!row) return;

    openEdit({
      title: config.label(row) || "항목",
      subtitle: config.subtitle ? config.subtitle(row) : "",
      // edit 이 지정된 열만 고칠 수 있다. 계산해서 보여주는 열(설치 대수 등)은 제외.
      fields: config.columns.filter((column) => column.edit).map((column) => ({
        name: column.key,
        label: column.label,
        type: column.edit === "select" ? "select" : column.edit,
        options: column.edit === "select" ? column.options() : undefined,
        value: row[column.key],
      })),
      extra: config.detail ? config.detail(row) : "",
      async onSave(payload) {
        await api(`${config.path}/${row.id}`, { method: "PUT", body: JSON.stringify(payload) });
        toast("수정했습니다.");
        await config.load();
      },
      async onDelete() {
        if (!await ask(`${config.label(row)} 항목을 삭제할까요?`, { ok: "삭제" })) return false;
        try {
          await api(`${config.path}/${row.id}`, { method: "DELETE" });
        } catch (error) {
          // 부여 이력처럼 딸린 자료가 있으면 서버가 409 로 막고 이유를 알려준다.
          // 그 이유를 그대로 보여주고, 이력까지 지울지 한 번 더 묻는다.
          if (!/이력|force=true/.test(error.message)) throw error;
          const reason = error.message.replace(" 이력까지 지우려면 force=true 로 요청하세요.", "");
          if (!await ask(`${reason}\n이력까지 함께 지울까요?`, { ok: "이력까지 삭제" })) return false;
          await api(`${config.path}/${row.id}?force=true`, { method: "DELETE" });
        }
        toast("삭제했습니다.");
        await config.load();
        return true;
      },
    });
  });
}

Object.keys(MANAGED).forEach((key) => {
  bindManaged(key);
  bindSort(key, MANAGED[key].target, () => renderManaged(key));
});

// 직원별 현황은 표가 아니라 grid 라서 th 대신 span 을 누른다.
$("#workspaceHead").addEventListener("click", (event) => {
  const cell = event.target.closest("[data-sort]");
  if (!cell) return;
  const key = cell.dataset.sort;
  const current = sortState.workspace;
  sortState.workspace = current?.key === key ? { key, dir: -current.dir } : { key, dir: 1 };
  state.page = 1;
  renderWorkspace();
});

bindSort("assets", "#assetsTable", renderAssets);
bindSort("employees", "#employeesTable", renderEmployees);
bindSort("ipAssignments", "#ipAssignmentsTable", renderIpAssignments);

// ---------------------------------------------------------------- 편집 모달
//
// 목록에서 행을 누르면 뜨는 편집창. 자산 등록·직원 명단이 같이 쓴다.
// 예전에는 표 안에서 줄이 펼쳐지며 고치는 방식이었는데, 직원별 현황은
// 모달이라 화면마다 조작법이 달랐다. 오른쪽 끝 '수정' 버튼도 가로 스크롤
// 밖으로 밀려 잘 안 보였다. 그래서 전부 모달로 맞춘다.

let editState = null;   // { onSave, onDelete, need }

/* need: 이 편집창이 어느 화면의 일인가. 체크한 화면만 고칠 수 있으므로
   저장·삭제 버튼도 그 화면 기준으로 켜고 끈다. 안 주면 지금 보는 화면. */
function openEdit({ title, subtitle, fields, onSave, onDelete, deleteLabel = "삭제", need,
                    datalists = {}, extra = "" }) {
  editState = { onSave, onDelete, need: need || state.view };

  const control = (f) => {
    if (f.type === "readonly") {
      return `<div class="ro mono">${escapeHtml(f.value ?? "-")}</div>`;
    }
    if (f.type === "select") {
      return `<select data-field="${f.name}">
        ${Object.entries(f.options).map(([key, text]) =>
          `<option value="${key}"${String(f.value) === key ? " selected" : ""}>${escapeHtml(text)}</option>`).join("")}
      </select>`;
    }
    // 이미 쓰인 값 중에서 고르거나, 없으면 직접 적는 칸.
    // datalist 는 타이핑한 글자로 후보를 걸러버려서 "다 안 보인다"는 오해를 산다.
    // 진짜 목록(select)을 두고, 없는 값만 입력칸으로 넘어가게 한다.
    if (f.type === "combo") {
      const value = f.value ?? "";
      const choices = [...new Set((f.choices || []).filter(Boolean))]
        .sort((a, b) => String(a).localeCompare(String(b), "ko"));
      const known = choices.includes(value);
      return `
        <select data-combo="${f.name}">
          <option value=""${!value ? " selected" : ""}>(비움)</option>
          ${choices.map((c) =>
            `<option value="${escapeHtml(c)}"${known && c === value ? " selected" : ""}>${escapeHtml(c)}</option>`).join("")}
          <option value="__custom"${value && !known ? " selected" : ""}>+ 직접 입력…</option>
        </select>
        <input data-field="${f.name}" class="combo-input" type="text"
               value="${escapeHtml(value)}" placeholder="새 값을 입력"
               ${known || !value ? "hidden" : ""} />`;
    }
    return `<input data-field="${f.name}" type="${f.type || "text"}"
      ${f.list ? `list="${f.list}"` : ""} value="${escapeHtml(f.value ?? "")}" />`;
  };

  $("#editModal").innerHTML = `
    <div class="drawer-head">
      <div>
        <h3>${escapeHtml(title)}</h3>
        ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
      </div>
      <span class="spacer"></span>
      <button class="icon-btn" data-edit-close title="닫기">×</button>
    </div>

    <div class="drawer-scroll">
      ${Object.entries(datalists).map(([id, values]) => `
        <datalist id="${id}">
          ${[...new Set(values.filter(Boolean))].sort()
            .map((v) => `<option value="${escapeHtml(v)}"></option>`).join("")}
        </datalist>`).join("")}
      <div class="edit-grid">
        ${fields.map((f) => `
          <label class="field">
            <span>${escapeHtml(f.label)}</span>
            ${control(f)}
            ${f.hint ? `<small class="hint">${escapeHtml(f.hint)}</small>` : ""}
          </label>`).join("")}
      </div>
      ${extra ? `<div class="edit-extra">${extra}</div>` : ""}
    </div>

    <div class="drawer-foot">
      ${onDelete ? `<button class="danger admin-only" data-need="${escapeHtml(need || state.view)}" data-edit-delete>${escapeHtml(deleteLabel)}</button>` : ""}
      <span class="spacer"></span>
      <button class="secondary" data-edit-close>닫기</button>
      <button class="admin-only" data-need="${escapeHtml(need || state.view)}" data-edit-save>저장</button>
    </div>
  `;
  $("#editModal").classList.remove("wide");
  $("#editModal").hidden = false;
  $("#editBackdrop").hidden = false;
  updateAuthUI();
  $("#editModal").querySelector("[data-field]")?.focus();
}

function closeEdit() {
  editState = null;
  $("#editModal").classList.remove("wide");
  $("#editModal").hidden = true;
  $("#editBackdrop").hidden = true;
}

function editValues() {
  const payload = {};
  $("#editModal").querySelectorAll("[data-field]").forEach((el) => {
    const raw = el.value.trim();
    payload[el.dataset.field] = raw === "" ? null : raw;
  });
  return payload;
}

$("#editBackdrop").addEventListener("click", closeEdit);

// 콤보: 목록에서 고르면 입력칸에 옮겨 담고, '직접 입력'을 고르면 입력칸을 연다.
$("#editModal").addEventListener("change", (event) => {
  const select = event.target.closest("[data-combo]");
  if (!select) return;
  const input = $(`#editModal [data-field="${select.dataset.combo}"]`);
  if (!input) return;
  if (select.value === "__custom") {
    input.hidden = false;
    input.value = "";
    input.focus();
  } else {
    input.value = select.value;
    input.hidden = true;
  }
});

$("#editModal").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button || !editState) return;

  if (button.dataset.editClose !== undefined) return closeEdit();

  if (button.dataset.editDelete !== undefined) {
    if (!guard(editState?.need)) return;
    try {
      // 무엇을 지우는지 묻는 문구는 화면마다 달라서 각자 맡긴다.
      if (await editState.onDelete()) closeEdit();
    } catch (error) {
      toast(error.message);
    }
    return;
  }

  if (button.dataset.editSave !== undefined) {
    if (!guard(editState?.need)) return;
    try {
      await editState.onSave(editValues());
      closeEdit();
    } catch (error) {
      toast(error.message);
    }
  }
});

// ---------------------------------------------------------------- 값 정리
//
// 제조사·모델·CPU·운영체제는 자산마다 문자열로 들어 있다 보니
// "Windows 11" 과 "Windows11" 처럼 같은 것을 다르게 적은 값이 쌓인다.
// 어떤 값이 몇 대에 쓰이는지 보여주고, 한 번에 다른 값으로 합치거나 지운다.

const SPEC_FIELD_LABELS = {
  manufacturer: "제조사",
  model: "모델",
  cpu: "CPU",
  os: "운영체제",
};

async function openSpecClean(field = "os") {
  const values = await api(`/assets/spec-values?field=${field}`);

  const rows = values.map((row) => `
    <tr>
      <td data-label="값">${escapeHtml(row.value)}</td>
      <td class="num" data-label="대수">${row.count}대</td>
      <td data-label="합칠 곳">
        <select data-merge-to="${escapeHtml(row.value)}">
          <option value="__keep">그대로 둠</option>
          ${values.filter((other) => other.value !== row.value).map((other) =>
            `<option value="${escapeHtml(other.value)}">→ ${escapeHtml(other.value)}</option>`).join("")}
          <option value="">→ (값 비우기)</option>
        </select>
      </td>
      <td class="actions">
        <button class="secondary admin-only" data-need="extensions" data-apply-merge="${escapeHtml(row.value)}">적용</button>
      </td>
    </tr>`).join("");

  $("#editModal").innerHTML = `
    <div class="drawer-head">
      <div>
        <h3>값 정리</h3>
        <p>같은 뜻인데 다르게 적힌 값을 하나로 합칩니다.</p>
      </div>
      <span class="spacer"></span>
      <button class="icon-btn" data-edit-close title="닫기">×</button>
    </div>

    <div class="drawer-scroll">
      <div class="seg" id="specTabs">
        ${Object.entries(SPEC_FIELD_LABELS).map(([key, label]) => `
          <button class="seg-btn ${key === field ? "on" : ""}" data-spec-field="${key}">${label}</button>`).join("")}
      </div>

      ${values.length ? `
        <table class="spec-table">
          <thead><tr><th>값</th><th class="num">쓰는 자산</th><th>바꿀 값</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <p class="muted" style="font-size:12px;margin-top:10px">
          '적용'을 누르면 그 값을 쓰는 자산이 모두 바뀝니다. 되돌리려면 반대로 한 번 더 하면 됩니다.
        </p>` : `<div class="d-empty">${escapeHtml(SPEC_FIELD_LABELS[field])}에 등록된 값이 없습니다.</div>`}
    </div>

    <div class="drawer-foot">
      <span class="spacer"></span>
      <button class="secondary" data-edit-close>닫기</button>
    </div>
  `;
  // 이 창은 저장 버튼이 없다. 각 줄의 '적용'이 곧 저장이다.
  editState = { onSave: null, onDelete: null, specField: field, need: "extensions" };
  // 값·건수·바꿀 값·적용 네 칸이라 편집 모달보다 넓어야 버튼이 안 잘린다.
  $("#editModal").classList.add("wide");
  $("#editModal").hidden = false;
  $("#editBackdrop").hidden = false;
  updateAuthUI();
}

$("#specCleanBtn").addEventListener("click", async () => {
  if (!guard("extensions")) return;
  try {
    await openSpecClean("os");
  } catch (error) {
    toast(error.message);
  }
});

$("#editModal").addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-spec-field]");
  if (tab) {
    try {
      await openSpecClean(tab.dataset.specField);
    } catch (error) {
      toast(error.message);
    }
    return;
  }

  const apply = event.target.closest("[data-apply-merge]");
  if (!apply || !editState?.specField) return;
  if (!guard("extensions")) return;

  const from = apply.dataset.applyMerge;
  const select = $(`#editModal [data-merge-to="${CSS.escape(from)}"]`);
  const to = select.value;
  if (to === "__keep") return toast("바꿀 값을 고르세요.");

  const what = to === "" ? "값을 비웁니다" : `'${to}' 로 바꿉니다`;
  if (!await ask(`'${from}' 을(를) 쓰는 자산을 모두 ${what}.`, { ok: "적용" })) return;

  try {
    const result = await api("/assets/spec-values/replace", {
      method: "POST",
      body: JSON.stringify({ field: editState.specField, from_value: from, to_value: to }),
    });
    toast(`${result.changed}대를 바꿨습니다.`);
    await loadAssets();
    await openSpecClean(editState.specField);
  } catch (error) {
    toast(error.message);
  }
});


// ---------------------------------------------------------------- 확인창
//
// 브라우저 기본 confirm() 은 주소창까지 나오고 화면 분위기와 따로 논다.
// 같은 자리에 쓰는 약속을 그대로 두고(await ask(...) 가 true/false) 모양만 바꾼다.

let confirmResolve = null;

function ask(message, { ok = "확인", danger = true } = {}) {
  const backdrop = $("#confirmBackdrop");
  const okBtn = $("#confirmOk");

  $("#confirmText").textContent = message;
  okBtn.textContent = ok;
  okBtn.classList.toggle("danger", danger);
  backdrop.hidden = false;
  okBtn.focus();

  return new Promise((resolve) => {
    confirmResolve = resolve;
  });
}

function closeConfirm(answer) {
  if (!confirmResolve) return;
  $("#confirmBackdrop").hidden = true;
  const resolve = confirmResolve;
  confirmResolve = null;
  resolve(answer);
}

$("#confirmOk").addEventListener("click", () => closeConfirm(true));
$("#confirmCancel").addEventListener("click", () => closeConfirm(false));
// 바깥을 눌러도 닫히지만, 그건 '취소'다. 실수로 지워지면 안 된다.
$("#confirmBackdrop").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) closeConfirm(false);
});
document.addEventListener("keydown", (event) => {
  // 확인창이 떠 있으면 그게 우선이다 (편집 모달 위에 겹쳐 뜨므로)
  if (confirmResolve) {
    if (event.key === "Escape") closeConfirm(false);
    if (event.key === "Enter") closeConfirm(true);
    return;
  }
  if (event.key === "Escape" && editState) closeEdit();
});

// ---------------------------------------------------------------- 자리 배치
//
// 엑셀 배치도를 그대로 옮긴 격자다. seats 의 row_idx/col_idx/span 이
// CSS grid 의 grid-row / grid-column 과 1:1로 대응한다.
// 자리를 누르면 직원별 현황에서 쓰던 상세 모달을 그대로 띄운다.

async function loadSeats() {
  // 모달이 state.workspace 를 보고 그리므로 직원 자료도 같이 받아둔다.
  if (!state.workspace.length) await loadWorkspace();
  const [floors, seats] = await Promise.all([
    api("/seats/floors"),
    api("/seats/"),
  ]);
  state.seatFloors = floors;
  state.seats = seats;
  if (!state.seatFloor || !floors.some((f) => f.floor === state.seatFloor)) {
    state.seatFloor = floors[0]?.floor || null;
  }
  renderSeatMap();
}

function seatMatches(seat, query) {
  if (!query) return false;
  const fields = [seat.label, seat.team, seat.employee_name, seat.employee_no,
                  seat.employee_department, seat.employee_position,
                  seat.employee_extension];
  // '직책자' 로도 찾을 수 있게
  if (seat.is_manager) fields.push("직책자");
  return fields
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query));
}

function renderSeatMap() {
  const floors = state.seatFloors;
  const query = ($("#seatSearch").value || "").trim().toLowerCase();

  // 사람을 찾을 때 층부터 고르게 하면 불편하다. 지금 층에 없고 다른 층에 있으면
  // 그 층으로 알아서 넘어간다.
  if (query) {
    const here = state.seats.some((s) => s.floor === state.seatFloor && seatMatches(s, query));
    if (!here) {
      const other = state.seats.find((s) => seatMatches(s, query));
      if (other) state.seatFloor = other.floor;
    }
  }

  $("#seatFloors").innerHTML = floors.map((f) => `
    <button class="seg-btn ${f.floor === state.seatFloor ? "on" : ""}" data-seat-floor="${escapeHtml(f.floor)}">
      ${escapeHtml(f.floor)}
    </button>
  `).join("");

  const current = floors.find((f) => f.floor === state.seatFloor);
  const seats = state.seats.filter((s) => s.floor === state.seatFloor);

  if (current) {
    const empty = current.desk_count - current.seated_count;
    $("#seatSummary").textContent =
      `자리 ${current.desk_count}개 · 배치 ${current.seated_count}명 · 빈자리 ${empty}개`;
  } else {
    $("#seatSummary").textContent = "";
  }

  if (!seats.length) {
    $("#seatMap").innerHTML = `
      <div class="d-empty">
        배치도가 아직 없습니다.
        <code>python scripts/import_layout.py --yes</code> 로 엑셀을 불러오세요.
      </div>`;
    return;
  }

  // 검색어가 있으면 맞는 칸만 도드라지게 (나머지는 흐리게)
  const hits = query ? seats.filter((s) => seatMatches(s, query)).length : 0;

  const map = $("#seatMap");
  const cols = current?.cols || 19;
  map.style.setProperty("--cols", cols);
  map.classList.toggle("searching", !!query);
  map.classList.toggle("editing", state.seatEdit);

  // 편집 모드에서는 격자 전체에 '놓을 자리'를 깔아둔다.
  // 칸이 없는 곳도 목표가 되어야 옮기거나 새로 만들 수 있다.
  let slots = "";
  if (state.seatEdit) {
    const rows = Math.max(current?.rows || 0, 1) + 2;   // 아래로 두 줄 여유
    const taken = new Set();
    seats.forEach((seat) => {
      for (let r = seat.row_idx; r < seat.row_idx + seat.row_span; r += 1) {
        for (let c = seat.col_idx; c < seat.col_idx + seat.col_span; c += 1) {
          taken.add(`${r}:${c}`);
        }
      }
    });
    for (let r = 1; r <= rows; r += 1) {
      for (let c = 1; c <= cols; c += 1) {
        if (taken.has(`${r}:${c}`)) continue;
        slots += `<div class="slot" data-slot="${r}:${c}"
                       style="grid-row:${r};grid-column:${c}"></div>`;
      }
    }
  }

  map.innerHTML = slots + seats.map((seat) => seatCell(seat, query)).join("");

  if (query && !hits) toastOnce("검색 결과가 없습니다.");
}

let lastToast = "";
function toastOnce(message) {
  if (lastToast === message) return;
  lastToast = message;
  setTimeout(() => { lastToast = ""; }, 1500);
  toast(message);
}


/* ── 배치도의 칸 고치기 ──────────────────────────────────────
   회의실·창고·팀 이름 같은 것은 그동안 화면에서 고칠 방법이 없었다.
   서버는 처음부터 받아 줬는데(PATCH /seats/{id}) 화면이 부르지 않았을 뿐이다.

   프린터·팩스처럼 **사람도 자산도 아닌 것**은 「공간」으로 둔다. 자산 대장에
   넣으면 "쓰는 사람 없음" 자산이 쌓이고, 그건 지급·회수를 축으로 만든
   대장의 뜻과 어긋난다. 자산번호를 남기고 싶으면 메모에 적으면 된다. */
const SEAT_KINDS = {
  DESK:  "자리 — 사람이 앉는 곳",
  ROOM:  "공간 — 회의실·창고·프린터·팩스",
  LABEL: "글자 — 팀 이름 같은 표시",
};

function openSeatEdit(seatId) {
  const seat = state.seats.find((s) => s.id === seatId);
  if (!seat) return;
  openEdit({
    title: seat.label || (seat.kind === "DESK" ? "빈 자리" : "칸"),
    subtitle: `${state.seatFloor} · ${seat.row_idx}행 ${seat.col_idx}열`,
    need: "seats",
    fields: [
      { name: "kind", label: "종류", type: "select", value: seat.kind,
        options: SEAT_KINDS,
        hint: "자리로 바꾸면 사람을 앉힐 수 있습니다. 공간·글자로 바꾸면 앉아 있던 사람은 떨어집니다." },
      { name: "label", label: "이름", type: "text", value: seat.label || "",
        hint: "회의실, 창고, 프린터, 재무팀 …" },
      { name: "team", label: "팀", type: "text", value: seat.team || "",
        hint: "자리일 때 이름 아래에 작게 나옵니다. 비워도 됩니다." },
      { name: "note", label: "메모", type: "text", value: seat.note || "",
        hint: "자산번호 같은 것을 적어 두면 마우스를 올렸을 때 보입니다." },
      // 엑셀의 병합셀에 해당한다. 회의실처럼 여러 칸을 차지하는 것에 쓴다.
      { name: "col_span", label: "가로 칸수", type: "number", value: seat.col_span || 1,
        hint: "1 이면 한 칸. 늘리면 오른쪽으로 넓어집니다." },
      { name: "row_span", label: "세로 칸수", type: "number", value: seat.row_span || 1,
        hint: "1 이면 한 칸. 늘리면 아래로 길어집니다. 다른 칸과 겹치면 알려 드립니다." },
    ],
    onSave: async (values) => {
      // 고치기 전 값을 담아 둔다. 되돌리면 그대로 다시 넣는다.
      const back = { kind: seat.kind, label: seat.label, team: seat.team, note: seat.note,
                     row_span: seat.row_span, col_span: seat.col_span };
      await api(`/seats/${seatId}`, { method: "PATCH", body: JSON.stringify(values) });
      pushUndo(`${seat.label || "칸"} 고침`, () =>
        api(`/seats/${seatId}`, { method: "PATCH", body: JSON.stringify(back) }));
      await loadSeats();
      toast("칸을 고쳤습니다.");
    },
    onDelete: async () => {
      // 지운 칸을 되살리려면 있던 값이 다 필요하다.
      const back = { floor: seat.floor, row_idx: seat.row_idx, col_idx: seat.col_idx,
                     row_span: seat.row_span, col_span: seat.col_span,
                     kind: seat.kind, label: seat.label, team: seat.team };
      await api(`/seats/${seatId}`, { method: "DELETE" });
      pushUndo(`${seat.label || "칸"} 지움`, () =>
        api("/seats/", { method: "POST", body: JSON.stringify(back) }));
      await loadSeats();
      toast("칸을 지웠습니다.");
    },
    deleteLabel: "칸 삭제",
  });
}


/* ── 되돌리기 ────────────────────────────────────────────────
   배치 편집 중에 실수로 칸을 끌어 옮기면 예전에는 방법이 없었다.
   편집을 끝내 버리면 잘못된 채로 남는다.

   되돌릴 "일" 을 쌓아 두고 하나씩 되짚는다. 화면만 되돌리는 것이 아니라
   서버에도 같은 요청을 보낸다 — 화면과 서버가 갈라지면 새로고침 한 번에
   되돌린 것이 없던 일이 된다.

   편집 모드를 나가면 비운다. 한참 전 일을 되돌리면 그 사이에 다른 사람이
   고친 것까지 뒤엎을 수 있다. */
function pushUndo(label, run) {
  state.seatUndo.push({ label, run });
  if (state.seatUndo.length > 30) state.seatUndo.shift();
  paintUndo();
}

function paintUndo() {
  const btn = $("#seatUndoBtn");
  if (!btn) return;
  const n = state.seatUndo.length;
  btn.hidden = !(state.seatEdit && n);
  btn.textContent = n ? `되돌리기 (${n})` : "되돌리기";
  btn.title = n ? `방금 한 일: ${state.seatUndo[n - 1].label}` : "";
}

async function undoSeat() {
  const item = state.seatUndo.pop();
  if (!item) return;
  try {
    await item.run();
    await loadSeats();
    toast(`되돌렸습니다 — ${item.label}`);
  } catch (error) {
    toast(error.message);
  }
  paintUndo();
}


/* ── CSV 내려받기 ────────────────────────────────────────────
   지금 보고 있는 화면의 목록을 그대로 파일로 받는다.

   **이게 곧 양식이다.** 빈 표에 칸 이름만 있는 양식 파일을 따로 두지
   않는 이유가 이것이다 — 실제 값이 들어 있는 파일을 고치는 편이,
   빈칸에 무엇을 넣어야 하는지 짐작하는 것보다 훨씬 쉽다.

   칸 이름은 **가져오기가 알아듣는 이름**과 같게 둔다. 받아서 고쳐서
   그대로 올리면 되도록.

   엑셀이 CSV 를 열 때 UTF-8 인지 모르고 cp949 로 읽어서 한글이 깨진다.
   맨 앞에 BOM 을 붙이면 엑셀이 UTF-8 로 알아본다. */
const CSV_SPECS = {
  employees: () => ({
    name: "직원명단",
    columns: [
      ["사번", (r) => r.emp_no], ["이름", (r) => r.name],
      ["부서", (r) => r.department], ["직책", (r) => r.position],
      ["상태", (r) => (r.status === "ACTIVE" ? "재직" : "퇴사")],
      ["이메일", (r) => r.email], ["입사일", (r) => r.joined_at],
    ],
    rows: () => state.workspace || [],
  }),
  assets: () => ({
    name: "자산",
    columns: [
      ["자산번호", (r) => r.asset_no], ["라벨번호", (r) => r.label_no],
      ["유형", (r) => ASSET_TYPES[r.asset_type] || r.asset_type],
      ["구분", (r) => (r.purchase_type === "RENTAL" ? "임대" : "구매")],
      ["제조사", (r) => r.manufacturer], ["모델", (r) => r.model],
      ["CPU", (r) => r.cpu], ["메모리", (r) => r.memory_gb],
      ["운영체제", (r) => r.os], ["상태", (r) => ASSET_STATUS[r.status] || r.status],
      ["사용자", (r) => r.holder],
    ],
    rows: () => state.assets || [],
  }),
  ips: () => ({
    name: "IP",
    columns: [
      ["IP", (r) => r.ip_address],
      ["구분", (r) => (r.kind === "PHONE" ? "전화기" : "네트워크")],
      ["자산번호", (r) => r.asset_no], ["내선", (r) => r.extension_number],
      ["호스트명", (r) => r.hostname], ["MAC", (r) => r.mac_address],
      ["사용자", (r) => r.employee_name], ["부서", (r) => r.employee_department],
      ["상태", (r) => r.status],
    ],
    // 화면에서 걸러 놓은 그대로 받는다 (전체 / 네트워크 / 전화기)
    rows: () => (state.ipKind
      ? (state.ipAssignments || []).filter((r) => r.kind === state.ipKind)
      : (state.ipAssignments || [])),
  }),
  extensions: () => ({
    name: "내선번호",
    columns: [
      ["내선번호", (r) => r.number], ["사번", (r) => r.employee_emp_no],
      ["이름", (r) => r.employee_name], ["부서", (r) => r.employee_department],
      ["구역", (r) => r.zone], ["IP", (r) => r.ip_address], ["메모", (r) => r.note],
    ],
    rows: () => state.extensions || [],
  }),
  software: () => ({
    name: "소프트웨어",
    columns: [
      ["제품", (r) => r.name], ["제조사", (r) => r.vendor],
      ["버전", (r) => r.version], ["라이선스 종류", (r) => r.license_type],
      ["메모", (r) => r.note],
    ],
    rows: () => state.softwareProducts || [],
  }),
  rentals: () => ({
    name: "렌탈",
    columns: [
      ["계약명", (r) => r.title], ["업체", (r) => r.vendor],
      ["시작", (r) => r.start_date], ["종료", (r) => r.end_date],
      ["월 비용", (r) => r.monthly_cost], ["메모", (r) => r.note],
    ],
    rows: () => (state.managedRows?.rentals || []),
  }),
  seats: () => ({
    name: "자리배치",
    columns: [
      ["층", (r) => r.floor], ["행", (r) => r.row_idx], ["열", (r) => r.col_idx],
      ["종류", (r) => ({DESK: "자리", ROOM: "공간", LABEL: "글자"}[r.kind] || r.kind)],
      ["이름", (r) => r.label], ["팀", (r) => r.team],
      ["앉은 사람", (r) => r.employee_name], ["메모", (r) => r.note],
    ],
    rows: () => state.seats || [],
  }),
};

function csvCell(value) {
  const text = value === null || value === undefined ? "" : String(value);
  // 쉼표·따옴표·줄바꿈이 들어 있으면 따옴표로 감싼다. 안 그러면 칸이 밀린다.
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadCsv() {
  const spec = CSV_SPECS[state.view]?.();
  if (!spec) return toast("이 화면은 내려받을 목록이 없습니다.");
  const rows = spec.rows();
  if (!rows.length) return toast("내려받을 것이 없습니다.");

  const lines = [spec.columns.map(([label]) => csvCell(label)).join(",")];
  for (const row of rows) {
    lines.push(spec.columns.map(([, get]) => csvCell(get(row))).join(","));
  }
  // \ufeff = BOM. 이게 없으면 엑셀이 cp949 로 읽어 한글이 깨진다.
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${spec.name}_${stamp()}.csv`;
  // 문서에 붙여 두고 누른다. 붙이지 않으면 브라우저에 따라 눌러도 아무 일이
  // 안 일어난다. 주소 지우기(revoke)도 곧바로 하면 받다 말고 끊긴다.
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1000);
  toast(`${rows.length}줄을 내려받았습니다.`);
}

/* 파일 이름에 넣을 날짜. 같은 이름으로 여러 번 받으면
   "자산 (3).csv" 처럼 쌓여서 어느 게 최신인지 알 수 없다. */
function stamp() {
  const d = new Date();
  const two = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}`;
}

function seatCell(seat, query) {
  const style =
    `grid-row:${seat.row_idx}/span ${seat.row_span};` +
    `grid-column:${seat.col_idx}/span ${seat.col_span};`;
  const hit = query && seatMatches(seat, query) ? " hit" : "";

  // 편집 모드에서만 끌 수 있다. 평소에 끌리면 지나가다 배치가 틀어진다.
  const drag = state.seatEdit ? ` draggable="true" data-drag="${seat.id}"` : "";

  if (seat.kind !== "DESK") {
    const cls = seat.kind === "ROOM" ? "room" : "label";
    // 편집 모드에서만 고칠 수 있게 한다. 평소에 연필이 떠 있으면
    // 배치도를 보기만 하려는 사람에게 방해가 된다.
    const pen = state.seatEdit
      ? `<button class="seat-pen admin-only" data-need="seats"
           data-seat-edit="${seat.id}" title="이름 고치기">✎</button>` : "";
    return `<div class="seat ${cls}${hit}" style="${style}"${drag} data-seat="${seat.id}">
      <span>${escapeHtml(seat.label || "")}</span>${pen}
    </div>`;
  }

  const seated = !!seat.employee_id;
  const picking = state.seatPicker === seat.id;

  if (picking) {
    // 빈 자리에 사람을 앉힐 때만 열리는 작은 선택 상자
    const seatedIds = new Set(state.seats.filter((s) => s.employee_id).map((s) => s.employee_id));
    const free = state.workspace
      .filter((e) => e.status === "ACTIVE" && !seatedIds.has(e.id))
      .sort((a, b) => a.name.localeCompare(b.name, "ko"));
    return `<div class="seat desk picking" style="${style}">
      <select data-seat-select="${seat.id}">
        ${options(free, (e) => `${e.name} (${e.department || "-"})`, "id", "직원 선택")}
      </select>
      <div class="seat-actions">
        <button class="link admin-only" data-need="seats" data-seat-assign="${seat.id}">지정</button>
        <button class="link" data-seat-cancel="1">취소</button>
        <!-- 엑셀에서 책상이 아닌 네모까지 빈 자리로 읽혔을 때 지우는 용도 -->
        <button class="link danger-link admin-only" data-need="seats" data-seat-remove="${seat.id}">칸 삭제</button>
      </div>
    </div>`;
  }

  // 한 칸이 60px 남짓이라 이름 말고는 다 잘린다. 부서는 두 칸 이상일 때만 쓰고,
  // 나머지는 마우스를 올렸을 때 나오는 설명(title)에 담는다.
  const dept = seat.employee_department || seat.team || "";
  const wide = seat.col_span >= 2;
  // 직책자 여부는 직원 명단의 '직책'에서 나온다 (엑셀의 ● 은 쓰지 않는다).
  // 승진·보직 변경이 있으면 직원 정보만 고치면 배치도가 따라간다.
  const tip = [seat.employee_name || seat.label, dept,
               seat.employee_position,
               seat.employee_extension ? `내선 ${seat.employee_extension}` : null,
               seat.asset_count ? `자산 ${seat.asset_count}대` : null]
    .filter(Boolean).join(" · ");

  const body = seated
    ? `<strong>${escapeHtml(seat.employee_name)}</strong>
       ${wide && dept ? `<small>${escapeHtml(dept)}</small>` : ""}
       ${seat.asset_count ? `<span class="seat-badge">${seat.asset_count}</span>` : ""}
       <button class="seat-x admin-only" data-need="seats" data-seat-clear="${seat.id}" title="자리 비우기">×</button>`
    : `<strong class="muted">${escapeHtml(seat.label || "빈 자리")}</strong>
       ${wide && seat.team ? `<small>${escapeHtml(seat.team)}</small>` : ""}
       ${state.seatEdit ? `<button class="seat-pen admin-only" data-need="seats"
            data-seat-edit="${seat.id}" title="칸 고치기">✎</button>` : ""}`;

  return `<div class="seat desk ${seated ? "seated" : "empty"}${hit}${seat.is_manager ? " marked" : ""}"
               style="${style}" data-seat="${seat.id}"${drag} title="${escapeHtml(tip)}">
    ${body}
  </div>`;
}

async function seatAssign(seatId, employeeId) {
  await api(`/seats/${seatId}/employee`, {
    method: "PUT",
    body: JSON.stringify({ employee_id: employeeId }),
  });
  state.seatPicker = null;
  await loadSeats();
}


/* ── 권한 화면 ───────────────────────────────────────────────
   담당자만 본다. 이 앱에 한 번이라도 들어온 사람이 목록에 뜨고,
   체크한 화면만 그 사람에게 보인다.

   포털 사용자 목록을 이 앱은 모른다. 그래서 아이디를 손으로 받아 적는
   대신 "들어온 적 있는 사람"을 모아 둔다 — 오타로 권한이 안 먹는 일이
   생기지 않는다. */
let permData = null;

async function loadPermissions() {
  permData = await api("/permissions");
  $("#permDefaults").textContent = permData.defaults
    .map((v) => (permData.views.find((x) => x.id === v) || {}).label || v)
    .join(" · ");
  renderPermissions();
}

/* ★ 칸마다 data-label 을 단다. 좁은 화면(860px 이하)에서는 표가
   행=카드로 바뀌면서 머리글(thead)이 숨고, 대신 td::before 가
   data-label 을 읽어 항목 이름을 그린다 (styles.css 의 카드 모드).

   여기에 data-label 이 없어서 폰에서는 **이름표 없는 체크상자 아홉 개**만
   떴다. 무엇을 켜고 끄는지 알 수 없으니 손댈 수가 없는 화면이었다.
   머리글에 쓰는 v.label 을 그대로 넘겨 주면 된다.

   사람 칸(.perm-name)과 저장 칸(.actions)은 이름표가 필요 없어서
   CSS 에서 ::before 를 끈다. */
function renderPermissions() {
  if (!permData) return;
  const q = ($("#permSearch")?.value || "").trim().toLowerCase();
  const people = permData.people.filter((p) =>
    !q || `${p.name} ${p.dept} ${p.user_id}`.toLowerCase().includes(q));

  if (!people.length) {
    $("#permTable").innerHTML = `<p class="muted">${
      q ? "찾는 사람이 없습니다." : "아직 아무도 들어온 적이 없습니다."}</p>`;
    return;
  }

  $("#permTable").innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th style="min-width:150px">사람</th>
          ${permData.views.map((v) => `<th style="text-align:center">${escapeHtml(v.label)}</th>`).join("")}
          <th style="width:90px"></th>
        </tr>
      </thead>
      <tbody>
        ${people.map((p) => `
          <tr data-perm-row="${escapeHtml(p.user_id)}">
            <td class="perm-name">
              <strong>${escapeHtml(p.name || p.user_id)}</strong>
              <div class="muted" style="font-size:12px">
                ${escapeHtml(p.dept || "-")} · ${escapeHtml(p.user_id)}
                ${p.custom ? "" : ' · <span title="따로 정하지 않아 기본값이 적용됩니다">기본</span>'}
              </div>
            </td>
            ${permData.views.map((v) => `
              <td class="perm-check" data-label="${escapeHtml(v.label)}" style="text-align:center">
                <input type="checkbox" data-perm="${escapeHtml(p.user_id)}"
                  value="${v.id}" ${(p.custom ? p.views : permData.defaults).includes(v.id) ? "checked" : ""} />
              </td>`).join("")}
            <td class="actions"><button type="button" class="secondary" data-perm-save="${escapeHtml(p.user_id)}">저장</button></td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

document.addEventListener("input", (event) => {
  if (event.target.id === "permSearch") renderPermissions();
});

document.addEventListener("click", async (event) => {
  const btn = event.target.closest("[data-perm-save]");
  if (!btn) return;
  const uid = btn.dataset.permSave;
  const views = Array.from(
    document.querySelectorAll(`input[data-perm="${CSS.escape(uid)}"]:checked`))
    .map((el) => el.value);
  try {
    await api(`/permissions/${encodeURIComponent(uid)}`, {
      method: "PUT", body: JSON.stringify({ views }),
    });
    toast(views.length ? "저장했습니다. 그 사람이 새로고침하면 반영됩니다."
                       : "기본값으로 되돌렸습니다.");
    await loadPermissions();
  } catch (error) {
    toast(error.message);
  }
});

const loaders = {
  workspace: loadWorkspace,
  seats: loadSeats,
  dashboard: loadDashboard,
  assets: loadAssets,
  employees: loadEmployees,
  ips: loadIps,
  extensions: loadExtensions,
  software: loadSoftware,
  rentals: loadRentals,
  permissions: loadPermissions,
};

async function refresh() {
  if (!state.user) return updateAuthUI();
  try {
    await loaders[state.view]();
  } catch (error) {
    toast(error.message);
  }
}

// ---------------------------------------------------------------- 인증

// 화면에 보일 역할 이름. ADMIN/USER 를 그대로 두면 한글 화면에 영어만 튄다.
// 뜻도 다르다 — 여기서 ADMIN 은 시스템 관리자가 아니라 이 서비스의 담당자다.
const roleLabel = (r) => (r === "ADMIN" ? "담당자" : "일반");

function updateAuthUI() {
  const loggedIn = !!state.user;
  const who = loggedIn ? `${state.user.username} · ${roleLabel(state.user.role)}` : "";
  $("#loginStatus").textContent = loggedIn ? who : "로그인 필요";
  const session = $("#sessionStatus");
  if (session) session.textContent = who;

  document.body.classList.toggle("app-mode", loggedIn);
  $("#loginGate").hidden = loggedIn;
  $("#appShell").hidden = !loggedIn;
  $("#sidebar").hidden = !loggedIn;

  const hint = $("#adminHint");
  if (hint) hint.hidden = isAdmin();
  /* 고치는 버튼은 흐리게 두지 않고 **감춘다.**
     흐린 버튼이 남아 있으면 "왜 안 눌리지" 하고 눌러 보게 되고,
     고장난 화면처럼 읽힌다. 전부 누르는 버튼이라 감춰도 자리가 안 뜬다.
     disabled 도 함께 걸어 둔다 — 감췄더라도 눌리는 길이 남으면 안 된다.

     data-need 는 그 버튼이 어느 화면의 일인지다. 없으면 지금 보는 화면. */
  document.querySelectorAll(".admin-only").forEach((el) => {
    const ok = canEdit(el.dataset.need);
    el.disabled = !ok;
    el.hidden = !ok;
  });

  // 볼 일 없는 메뉴는 지운다. 눌러도 안 되는 메뉴를 남겨 두면
  // "고장났나" 로 읽힌다.
  document.querySelectorAll(".nav-item").forEach((el) => {
    el.hidden = !canSee(el.dataset.view);
  });
  // 지금 보고 있는 화면이 못 볼 화면이면 (해시로 직접 들어온 경우)
  // 첫 화면으로 돌린다.
  if (loggedIn && state.view && !canSee(state.view)) applyView(firstView(), true);
}

async function restoreSession() {
  // 로그인은 사내 포털이 한다. 토큰이 아니라 포털이 붙여 준 헤더로 판별하므로
  // 저장된 토큰이 없어도 항상 물어봐야 한다.
  // 예전처럼 토큰이 있을 때만 물으면, 로그인 화면만 뜨고 아무것도 안 보인다.
  try {
    state.user = await api("/auth/me");
  } catch {
    // 여기까지 왔다면 포털이 이미 막았어야 할 상황이다.
    state.user = null;
  }
  updateAuthUI();
}

function logout() {
  // 로그인 상태는 포털 쿠키가 들고 있다. 이 앱에서 지워 봐야 아무 일도
  // 일어나지 않으므로, 포털로 보내서 거기서 끊게 한다.
  //
  // 이 앱이 포털에서 열린 탭이면 **그 탭을 닫고 포털 탭으로 돌아간다.**
  // 그냥 이동시키면 포털 탭이 하나 더 늘어난다 (portal/static/back.js).
  if (window.goPortal) return window.goPortal();
  location.href = "/";
}

// ---------------------------------------------------------------- 이벤트

function guard(view) {
  if (canEdit(view)) return true;
  // 담당자는 포털 관리자 화면에서 정한다. 이 앱은 판정하지 않는다.
  toast("이 화면을 고칠 권한이 없습니다. 필요하시면 IT 담당자에게 문의해주세요.");
  return false;
}

// ---------------------------------------------------------------- 주소로 화면 고르기
//
// 챗에서 "김도연 어디 앉아?" 를 물어보고 [바로가기] 를 누르면 **자리 배치**
// 화면이 바로 열려야 한다. 예전에는 무엇을 물었든 대시보드로 떨어져서,
// 누른 사람이 왼쪽 메뉴에서 한 번 더 찾아 들어가야 했다.
//
// history.pushState 가 아니라 해시(#seats)를 쓴다. 이 앱은 포털 nginx 뒤에서
// /it-asset/ 로 붙는데, 경로를 바꾸면 그 상태로 새로고침할 때 서버가 없는
// 경로를 찾다가 404 를 낸다. 해시는 서버로 가지 않으므로 어디에 붙어도 돈다.
//
//   /it-asset/#seats     자리 배치
//   /it-asset/#workspace 직원별 현황
//   /it-asset/#software  소프트웨어
//
// 모르는 이름이면 그냥 무시하고 대시보드를 연다.

let hashLock = false;          // 우리가 바꾼 해시에 스스로 반응하지 않게

function viewFromHash() {
  const name = (location.hash || "").replace(/^#\/?/, "");
  return titles[name] ? name : null;
}

/* 「CSV 내려받기」 버튼은 **하나뿐**이고, 화면을 옮길 때마다 그 화면의
   자리(.csv-slot)로 옮겨 붙인다.

   위쪽 막대에 두었더니, 양식을 받으러 위로 갔다가 「자료 넣기」를 누르러
   다시 아래로 내려와야 했다. 받기와 넣기는 이어지는 일이라 붙어 있어야 한다.

   화면마다 버튼을 만들지 않는 이유는 늘 같다 — 하나만 고치는 일이 생긴다. */
function paintCsvBtn() {
  const btn = $("#csvBtn");
  if (!btn) return;
  const spec = CSV_SPECS[state.view];
  btn.hidden = !spec;
  if (!spec) return;
  const slot = document.querySelector(`#${state.view} .csv-slot`);
  if (slot && btn.parentElement !== slot) slot.appendChild(btn);
}

function applyView(view, pushHash) {
  if (!titles[view]) return;
  // 메뉴만 감추면 주소창에 #assets 을 쳐서 들어올 수 있다.
  // (이건 화면 정리이지 자물쇠가 아니다 — 진짜 차단은 서버의 require_admin 이 한다)
  if (!canSee(view)) {
    view = firstView();
    pushHash = true;      // 주소도 같이 고친다. 안 그러면 주소는 #assets 인데
                          // 화면은 직원 명단인, 말이 안 맞는 상태로 남는다.
  }
  state.view = view;
  document.querySelectorAll(".nav-item").forEach((item) =>
    item.classList.toggle("active", item.dataset.view === view));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $(`#${view}`).classList.add("active");
  $("#pageTitle").textContent = titles[view];
  paintCsvBtn();
  if (pushHash && (location.hash || "").replace(/^#\/?/, "") !== view) {
    hashLock = true;
    location.hash = view;      // 뒤로가기로 앞 화면에 돌아갈 수 있게 남긴다
    setTimeout(() => { hashLock = false; }, 0);
  }
}

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    applyView(button.dataset.view, true);
    refresh();
  });
});

// 뒤로/앞으로, 또는 주소를 직접 고쳤을 때
window.addEventListener("hashchange", () => {
  if (hashLock) return;
  const view = viewFromHash() || firstView();
  if (view === state.view) return;
  applyView(view, false);
  refresh();
});

$("#refreshBtn").addEventListener("click", refresh);
$("#scrollTopBtn").addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
$("#scrollBottomBtn").addEventListener("click", () =>
  window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" }));

["#workspaceSearch", "#workspaceStatus", "#pageSize"].forEach((selector) => {
  const el = $(selector);
  el.addEventListener(el.tagName === "INPUT" ? "input" : "change", () => {
    state.page = 1;
    renderWorkspace();
  });
});

$("#prevPage").addEventListener("click", () => {
  state.page -= 1;
  renderWorkspace();
  $("#workspace .toolbar").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("#nextPage").addEventListener("click", () => {
  state.page += 1;
  renderWorkspace();
  $("#workspace .toolbar").scrollIntoView({ behavior: "smooth", block: "start" });
});

// 직원별 현황: 행 펼치기 + 지급/회수/IP/SW
// 목록 행 클릭 = 드로어 열기. 작업 버튼은 목록에 없다.
$("#workspaceRows").addEventListener("click", (event) => {
  const row = event.target.closest("[data-select]");
  if (!row) return;
  const id = row.dataset.select;
  state.selected = state.selected === id ? null : id;
  state.picker = null;
  renderWorkspace();
});


// 상세 모달 닫기. 직원별 현황에서 열었든 자리 배치에서 열었든 알맞게 다시 그린다.
function closeDetail() {
  state.selected = null;
  state.picker = null;
  if (state.view === "seats") {
    renderDrawer();
    renderSeatMap();
  } else {
    renderWorkspace();
  }
}

$("#drawerBackdrop").addEventListener("click", closeDetail);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.selected) closeDetail();
});

// ---- 자리 배치 화면의 조작 ----

$("#seatSearch").addEventListener("input", () => {
  if (state.view === "seats") renderSeatMap();
});

$("#seatFloors").addEventListener("click", (event) => {
  const button = event.target.closest("[data-seat-floor]");
  if (!button) return;
  state.seatFloor = button.dataset.seatFloor;
  state.seatPicker = null;
  renderSeatMap();
});

// ---- 배치 편집: 칸을 끌어 옮기고, 빈 격자에 새 책상을 만든다 ----

$("#csvBtn").addEventListener("click", downloadCsv);

$("#seatUndoBtn").addEventListener("click", () => {
  if (!guard("seats")) return;
  undoSeat();
});

$("#seatEditBtn").addEventListener("click", () => {
  if (!guard("seats")) return;
  state.seatEdit = !state.seatEdit;
  // 편집을 나가면 되돌릴 일도 비운다. 한참 전 일을 되돌리면
  // 그 사이 다른 사람이 고친 것까지 뒤엎을 수 있다.
  if (!state.seatEdit) state.seatUndo = [];
  paintUndo();
  state.seatPicker = null;
  $("#seatEditBtn").classList.toggle("on", state.seatEdit);
  $("#seatEditBtn").textContent = state.seatEdit ? "편집 끝내기" : "배치 편집";
  toast(state.seatEdit
    ? "칸을 끌어서 옮기고, 빈 곳을 누르면 책상이 생깁니다."
    : "배치 편집을 끝냈습니다.");
  renderSeatMap();
});

let draggingSeat = null;

$("#seatMap").addEventListener("dragstart", (event) => {
  const cell = event.target.closest("[data-drag]");
  if (!cell) return;
  draggingSeat = cell.dataset.drag;
  event.dataTransfer.effectAllowed = "move";
  // 파이어폭스는 데이터가 없으면 드래그를 시작하지 않는다
  event.dataTransfer.setData("text/plain", draggingSeat);
  cell.classList.add("dragging");
});

$("#seatMap").addEventListener("dragend", (event) => {
  event.target.closest("[data-drag]")?.classList.remove("dragging");
  draggingSeat = null;
});

$("#seatMap").addEventListener("dragover", (event) => {
  const slot = event.target.closest("[data-slot]");
  if (!slot || !draggingSeat) return;
  event.preventDefault();                 // 이걸 해야 놓을 수 있다
  slot.classList.add("over");
});

$("#seatMap").addEventListener("dragleave", (event) => {
  event.target.closest("[data-slot]")?.classList.remove("over");
});

$("#seatMap").addEventListener("drop", async (event) => {
  const slot = event.target.closest("[data-slot]");
  if (!slot || !draggingSeat) return;
  event.preventDefault();
  slot.classList.remove("over");

  const [row, col] = slot.dataset.slot.split(":").map(Number);
  const id = draggingSeat;
  draggingSeat = null;

  // 옮기기 전 자리를 기억해 둔다. 되돌리려면 그 값이 있어야 한다.
  const before = state.seats.find((x) => x.id === id);
  const back = before ? { row_idx: before.row_idx, col_idx: before.col_idx } : null;

  try {
    await api(`/seats/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ row_idx: row, col_idx: col }),
    });
    if (back) {
      pushUndo(`${before.label || "칸"} 옮김`, () =>
        api(`/seats/${id}`, { method: "PATCH", body: JSON.stringify(back) }));
    }
    await loadSeats();
  } catch (error) {
    toast(error.message);
  }
});

$("#seatMap").addEventListener("click", async (event) => {
  const button = event.target.closest("button");

  // 편집 모드에서 빈 격자를 누르면 그 자리에 책상을 만든다
  const slot = event.target.closest("[data-slot]");
  if (slot && state.seatEdit) {
    if (!guard("seats")) return;
    const [row, col] = slot.dataset.slot.split(":").map(Number);
    // 무엇을 만들지 먼저 묻는다. 예전에는 무조건 책상이 생겨서,
    // 회의실이나 프린터 자리를 만들려면 만든 뒤 다시 고쳐야 했다.
    openEdit({
      title: "새 칸",
      subtitle: `${state.seatFloor} · ${row}행 ${col}열`,
      need: "seats",
      fields: [
        { name: "kind", label: "종류", type: "select", value: "DESK",
          options: SEAT_KINDS },
        { name: "label", label: "이름", type: "text", value: "",
          hint: "자리는 비워 두면 '빈 자리'로 나옵니다. 공간·글자는 적어 주세요." },
        { name: "team", label: "팀", type: "text", value: "" },
      ],
      onSave: async (values) => {
        const made = await api("/seats/", {
          method: "POST",
          body: JSON.stringify({ floor: state.seatFloor, row_idx: row, col_idx: col, ...values }),
        });
        if (made?.id) {
          pushUndo(`${values.label || "칸"} 만듦`, () =>
            api(`/seats/${made.id}`, { method: "DELETE" }));
        }
        await loadSeats();
        toast("칸을 만들었습니다.");
      },
    });
    return;
  }

  if (button?.dataset.seatEdit) {
    if (!guard("seats")) return;
    return openSeatEdit(button.dataset.seatEdit);
  }

  if (button?.dataset.seatCancel !== undefined) {
    state.seatPicker = null;
    return renderSeatMap();
  }

  // 책상이 아닌 칸 지우기
  if (button?.dataset.seatRemove) {
    if (!guard("seats")) return;
    if (!await ask("이 칸을 배치도에서 지울까요?\n실제 책상이 아니라 엑셀에서 잘못 읽힌 네모일 때 씁니다.",
                   { ok: "칸 삭제" })) return;
    try {
      await api(`/seats/${button.dataset.seatRemove}`, { method: "DELETE" });
      state.seatPicker = null;
      await loadSeats();
      toast("칸을 지웠습니다.");
    } catch (error) {
      toast(error.message);
    }
    return;
  }

  // 자리 비우기. 다른 곳의 회수·삭제와 마찬가지로 한 번 묻는다 —
  // 작은 × 라서 지나가다 눌리기 쉽다.
  if (button?.dataset.seatClear) {
    if (!guard("seats")) return;
    const seat = state.seats.find((s) => s.id === button.dataset.seatClear);
    const who = seat?.employee_name || "이 직원";
    if (!await ask(`${who} 님을 이 자리에서 비울까요?`, { ok: "비우기" })) return;
    try {
      await seatAssign(button.dataset.seatClear, null);
      toast("자리를 비웠습니다.");
    } catch (error) {
      toast(error.message);
    }
    return;
  }

  // 사람 지정
  if (button?.dataset.seatAssign) {
    if (!guard("seats")) return;
    const seatId = button.dataset.seatAssign;
    const employeeId = $(`[data-seat-select="${seatId}"]`).value;
    if (!employeeId) return toast("직원을 선택하세요.");
    try {
      await seatAssign(seatId, employeeId);
      toast("자리에 배치했습니다.");
    } catch (error) {
      toast(error.message);
    }
    return;
  }

  const cell = event.target.closest("[data-seat]");
  if (!cell) return;
  const seat = state.seats.find((s) => s.id === cell.dataset.seat);
  if (!seat) return;

  if (seat.employee_id) {
    // 앉아 있는 사람 → 직원별 현황에서 쓰던 상세 모달을 그대로 연다
    state.selected = seat.employee_id;
    state.picker = null;
    renderDrawer();
    return;
  }

  // 빈 자리 → 관리자면 사람을 고를 수 있게
  if (!canEdit("seats")) return toast("빈 자리입니다.");
  state.seatPicker = state.seatPicker === seat.id ? null : seat.id;
  renderSeatMap();
});

// 소프트웨어 고르는 상자: 검색과 '몇 개 골랐는지'.
// 화면을 다시 그리면 체크가 풀리므로, 여기서는 DOM 만 만지고 다시 그리지 않는다.
$("#drawer").addEventListener("input", (event) => {
  const assetId = event.target.dataset.swSearch;
  if (!assetId) return;
  const needle = event.target.value.trim().toLowerCase();
  $(`[data-sw-list="${assetId}"]`).querySelectorAll("[data-sw-name]").forEach((item) => {
    item.hidden = !!needle && !item.dataset.swName.includes(needle);
  });
});

$("#drawer").addEventListener("change", (event) => {
  const assetId = event.target.dataset.swCheck;
  if (!assetId) return;
  const picked = document.querySelectorAll(`[data-sw-check="${assetId}"]:checked`).length;
  $(`[data-sw-count="${assetId}"]`).textContent = `${picked}개 선택`;
});

// 드로어 안의 모든 작업. 기존 데이터 계약(data-give, data-return ...)을 그대로 쓴다.
$("#drawer").addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;

  if (button.dataset.closeDrawer !== undefined) return closeDetail();

  // 선택 상자 토글: 같은 걸 다시 누르면 닫힌다. 한 번에 하나만 연다.
  if (button.dataset.picker) {
    state.picker = state.picker === button.dataset.picker ? null : button.dataset.picker;
    return renderDrawer();
  }

  const {
    give, applyIp, releaseIp, addSw, removeSw, offboard, reinstate,
  } = button.dataset;
  const returnId = button.dataset.return;
  const revokeLicense = button.dataset.revokeLicense;
  const grantLicense = button.dataset.grantLicense !== undefined;
  const swCancel = button.dataset.swCancel !== undefined;
  if (swCancel) {
    state.picker = null;
    return renderDrawer();
  }
  const grantExt = button.dataset.grantExt;
  const releaseExt = button.dataset.releaseExt;

  if (!give && !returnId && !applyIp && !releaseIp && !addSw && !removeSw
    && !offboard && !reinstate && !revokeLicense && !grantLicense
    && !grantExt && !releaseExt) return;
  // 버튼마다 어느 화면의 일인지 적혀 있다 (data-need).
  // 자리 배치에서 연 서랍에 자산·IP·소프트웨어 버튼이 섞여 있어서,
  // 지금 보는 화면만으로는 판단할 수 없다.
  if (!guard(button.dataset.need)) return;

  try {
    if (give) {
      const select = $(`[data-give-select="${give}"]`);
      if (!select.value) return toast("지급할 보관 자산을 선택하세요.");
      await api(`/assets/${select.value}/assign`, {
        method: "POST",
        body: JSON.stringify({ employee_id: give }),
      });
      state.picker = null;
      toast("자산을 지급했습니다.");
    } else if (returnId) {
      if (!await ask("이 자산을 회수해 보관 자산으로 되돌릴까요?", { ok: "회수" })) return;
      await api(`/assets/${returnId}/return`, { method: "POST" });
      toast("회수했습니다. 보관 자산으로 이동합니다.");
    } else if (applyIp) {
      const select = $(`[data-ip-select="${applyIp}"]`);
      if (!select.value) return toast("IP를 선택하세요.");
      const assignmentId = button.dataset.ipAssignment;
      if (assignmentId) {
        await api(`/ip-assignments/${assignmentId}`, {
          method: "PUT",
          body: JSON.stringify({ ip_address: select.value }),
        });
      } else {
        await api("/ip-assignments", {
          method: "POST",
          body: JSON.stringify({ asset_id: applyIp, ip_address: select.value }),
        });
      }
      state.picker = null;
      toast("IP를 반영했습니다.");
    } else if (releaseIp) {
      await api(`/ip-assignments/${releaseIp}`, { method: "DELETE" });
      state.picker = null;
      toast("IP를 해제했습니다.");
    } else if (addSw) {
      const picked = [...document.querySelectorAll(`[data-sw-check="${addSw}"]:checked`)]
        .map((box) => box.value);
      if (!picked.length) return toast("추가할 소프트웨어를 고르세요.");

      // 하나가 실패해도 나머지는 들어가야 한다. 실패한 것만 모아서 알려준다.
      const failed = [];
      for (const softwareId of picked) {
        try {
          await api("/software-installations", {
            method: "POST",
            body: JSON.stringify({ asset_id: addSw, software_id: softwareId }),
          });
        } catch (error) {
          const name = state.softwareProducts.find((p) => p.id === softwareId)?.name || softwareId;
          failed.push(`${name} (${error.message})`);
        }
      }
      state.picker = null;
      toast(failed.length
        ? `${picked.length - failed.length}개 추가 · 실패: ${failed.join(", ")}`
        : `소프트웨어 ${picked.length}개를 추가했습니다.`);
    } else if (removeSw) {
      await api(`/software-installations/${removeSw}`, { method: "DELETE" });
      toast("소프트웨어를 제거했습니다.");
    } else if (grantExt) {
      const select = $("[data-ext-select]");
      if (!select?.value) return toast("내선번호를 선택하세요.");
      await api(`/extensions/${select.value}/employee`, {
        method: "PUT", body: JSON.stringify({ employee_id: grantExt }),
      });
      state.picker = null;
      toast("내선번호를 부여했습니다.");
    } else if (releaseExt) {
      const row = (state.extensions || []).find((item) => item.employee_id === releaseExt);
      if (!row) return toast("부여된 내선번호가 없습니다.");
      if (!await ask(`내선 ${row.number} 를 회수할까요?\n번호는 남고 사용자만 빠집니다.`,
                     { ok: "회수" })) return;
      await api(`/extensions/${row.id}/employee`, {
        method: "PUT", body: JSON.stringify({ employee_id: null }),
      });
      toast("내선번호를 회수했습니다.");
    } else if (grantLicense) {
      const select = $("[data-license-select]");
      if (!select.value) return toast("부여할 라이선스를 선택하세요.");
      await api("/license-assignments/", {
        method: "POST",
        body: JSON.stringify({
          license_pool_id: select.value,
          employee_id: state.selected,
        }),
      });
      state.picker = null;
      toast("라이선스를 부여했습니다.");
    } else if (revokeLicense) {
      if (!await ask("이 라이선스를 회수할까요? 직원은 그대로 재직 상태입니다.", { ok: "회수" })) return;
      await api(`/license-assignments/${revokeLicense}/release`, { method: "POST" });
      toast("라이선스를 회수했습니다.");
    } else if (offboard) {
      if (!await ask("퇴사 처리하면 보유 자산·IP·라이선스가 모두 회수됩니다. 진행할까요?", { ok: "퇴사 처리" })) return;
      await api(`/employees/${offboard}/offboard`, { method: "POST" });
      toast("퇴사 처리했습니다. 자산·라이선스를 모두 회수했습니다.");
    } else if (reinstate) {
      await api(`/employees/${reinstate}`, {
        method: "PUT",
        body: JSON.stringify({ status: "ACTIVE" }),
      });
      toast("복직 처리했습니다.");
    }
    await loadWorkspace();
  } catch (error) {
    toast(error.message);
  }
});

// 자산 등록: 자산번호 수정 · 삭제
$("#assetSearch").addEventListener("input", renderAssets);
$("#assetStatusFilter").addEventListener("change", renderAssets);

// 자산 등록: 행을 누르면 편집 모달
$("#assetsTable").addEventListener("click", (event) => {
  const row = event.target.closest("[data-open-asset]");
  if (!row) return;
  const asset = state.assets.find((item) => item.id === row.dataset.openAsset);
  if (!asset) return;

  // 지금 이 자산을 쓰고 있는 사람
  const holder = state.workspace.find((emp) =>
    emp.assets.some((a) => a.id === asset.id));
  const active = state.workspace
    .filter((emp) => emp.status === "ACTIVE")
    .sort((a, b) => a.name.localeCompare(b.name, "ko"));

  // 이미 쓰인 값들을 모아 드롭다운으로 제공한다. 새 값은 그냥 타이핑하면 되고,
  // 목록에 있는 걸 고르면 표기가 저절로 통일된다("Windows 11 Pro" vs "windows 11pro").
  const used = (key) => state.assets.map((a) => a[key]);

  openEdit({
    title: assetNo(asset),
    need: "assets",
    subtitle: `${ASSET_TYPES[asset.asset_type] || "자산"} · ${asset.purchase_type === "RENTAL" ? "임대" : "구매"}`,
    fields: [
      { name: "asset_no", label: "자산번호", value: asset.asset_no },
      { name: "label_no", label: "라벨번호", value: asset.label_no },
      { name: "asset_type", label: "유형", type: "select", options: ASSET_TYPES, value: asset.asset_type },
      { name: "purchase_type", label: "구분", type: "select",
        options: { PURCHASE: "구매", RENTAL: "임대" }, value: asset.purchase_type || "PURCHASE" },
      { name: "manufacturer", label: "제조사", type: "combo",
        value: asset.manufacturer, choices: used("manufacturer") },
      { name: "model", label: "모델", type: "combo",
        value: asset.model, choices: used("model") },
      { name: "serial_no", label: "시리얼번호", value: asset.serial_no },
      { name: "cpu", label: "CPU", type: "combo", value: asset.cpu, choices: used("cpu") },
      { name: "memory_gb", label: "메모리(GB)", type: "number", value: asset.memory_gb },
      { name: "storage_gb", label: "저장장치(GB)", type: "number", value: asset.storage_gb },
      { name: "os", label: "운영체제", type: "combo", value: asset.os, choices: used("os") },
      // 사용자를 여기서 바로 지정한다. 예전에는 '직원별 현황'으로 건너가야 했고,
      // 상태만 '사용 중'으로 바꿔두면 보관 목록에서도 빠져 어디서도 지급할 수 없었다.
      { name: "__holder", label: "사용자", type: "select",
        options: Object.fromEntries([["", "(미지정 · 보관)"],
          ...active.map((e) => [e.id, `${e.name} (${e.department || "-"})`])]),
        value: holder?.id || "",
        hint: "사람을 지정하면 상태가 '사용 중'으로, 비우면 '보관'으로 바뀝니다." },
      { name: "status", label: "상태", type: "select", options: ASSET_STATUS, value: asset.status },
    ],
    async onSave(payload) {
      const nextHolder = payload.__holder || null;
      delete payload.__holder;

      // 사양 먼저 저장하고, 지급/회수를 뒤에 한다.
      // 지급·회수가 상태를 바꾸므로 순서를 뒤집으면 폼의 상태값이 덮어써 버린다.
      await api(`/assets/${asset.id}`, { method: "PUT", body: JSON.stringify(payload) });

      const current = holder?.id || null;
      if (nextHolder !== current) {
        if (nextHolder) {
          await api(`/assets/${asset.id}/assign`, {
            method: "POST", body: JSON.stringify({ employee_id: nextHolder }),
          });
          toast("사용자를 지정하고 '사용 중'으로 바꿨습니다.");
        } else {
          await api(`/assets/${asset.id}/return`, { method: "POST" });
          toast("자산을 회수해 '보관'으로 바꿨습니다.");
        }
      } else {
        toast("자산 정보를 수정했습니다. 직원별 현황에도 함께 반영됩니다.");
      }
      await loadAssets();
    },
    async onDelete() {
      const warning = asset.status === "IN_USE" ? "이 자산은 현재 직원에게 지급 중입니다.\n" : "";
      if (!await ask(`${warning}${assetNo(asset)} 자산을 삭제할까요? IP·소프트웨어·지급 이력도 함께 삭제됩니다.`,
                     { ok: "삭제" })) return false;
      await api(`/assets/${asset.id}`, { method: "DELETE" });
      toast("자산을 삭제했습니다.");
      await loadAssets();
      return true;
    },
  });
});

$("#employeesTable").addEventListener("click", (event) => {
  const row = event.target.closest("[data-open-employee]");
  if (!row) return;
  const employee = state.workspace.find((item) => item.id === row.dataset.openEmployee);
  if (!employee) return;

  const count = employee.assets.length;

  openEdit({
    title: employee.name,
    need: "employees",
    subtitle: `${employee.emp_no} · ${employee.department || "부서 없음"}`,
    fields: [
      // 사번은 엑셀 임포트·이력의 연결 고리라 여기서는 고치지 않는다.
      { name: "emp_no", label: "사번", type: "readonly", value: employee.emp_no },
      { name: "name", label: "이름", value: employee.name },
      { name: "department", label: "부서", value: employee.department, list: "dl-dept" },
      { name: "position", label: "직책", value: employee.position, list: "dl-position" },
      { name: "rank", label: "직급", value: employee.rank, list: "dl-rank" },
      { name: "email", label: "이메일", value: employee.email },
      { name: "phone", label: "연락처", value: employee.phone },
    ],
    async onSave(payload) {
      delete payload.emp_no;   // 읽기 전용이라 값이 안 실리지만 확실히 해둔다
      if (!payload.name) throw new Error("이름은 비울 수 없습니다.");
      await api(`/employees/${employee.id}`, { method: "PUT", body: JSON.stringify(payload) });
      toast("저장했습니다.");
      await loadEmployees();
    },
    async onDelete() {
      const message = count
        ? `${employee.name} 직원에게 지급된 자산 ${count}대를 회수하고 삭제할까요?`
        : `${employee.name} 직원을 삭제할까요?`;
      if (!await ask(message, { ok: "삭제" })) return false;
      await api(`/employees/${employee.id}?force=${count ? "true" : "false"}`, { method: "DELETE" });
      toast("직원을 삭제했습니다.");
      await loadEmployees();
      return true;
    },
  });
});

// 등록 폼
function submitForm(selector, path, message, need) {
  $(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!guard(need)) return;
    try {
      await api(path, { method: "POST", body: JSON.stringify(formData(event.target)) });
      event.target.reset();
      toast(message);
      await refresh();
    } catch (error) {
      toast(error.message);
    }
  });
}

submitForm("#assetForm", "/assets/", "자산을 등록했습니다.", "assets");
submitForm("#employeeForm", "/employees/", "직원을 등록했습니다.", "employees");
submitForm("#ipRangeForm", "/ip-ranges", "IP 대역을 등록했습니다.", "ips");
submitForm("#softwareForm", "/software-products", "소프트웨어 제품을 등록했습니다.", "software");

$("#loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const token = await api("/auth/login", { method: "POST", body: JSON.stringify(formData(event.target)) });
    state.token = token.access_token;
    localStorage.setItem("assetPortalToken", state.token);
    state.user = await api("/auth/me");
    event.target.reset();
    updateAuthUI();
    toast("로그인했습니다.");
    await refresh();
  } catch (error) {
    toast(error.message);
  }
});

$("#sideLogoutBtn").addEventListener("click", logout);

// 처음 열 때도 주소에 적힌 화면으로 간다.
// (챗의 바로가기는 /it-asset/#seats 처럼 온다)
// 화면을 정하기 **전에** 누구인지부터 안다.
// 예전에는 주소의 화면을 먼저 열고 나중에 사람을 확인했는데, 그러면
// 담당자가 /it-asset/#assets 로 들어와도 그 순간에는 아직 "담당자 아님"
// 이라서 엉뚱한 화면으로 튕긴다.
const startView = viewFromHash();
restoreSession().then(() => {
  applyView(startView || firstView(), false);
  refresh();
});
