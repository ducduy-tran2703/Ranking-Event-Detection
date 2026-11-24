"use strict";

const PALETTE = ["#2563eb", "#dc2626", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d"];
const ISSUE_LABELS = {
  missing_author: "Thiếu tác giả",
  empty_content: "Thân bài rỗng",
  short_content: "Thân bài quá ngắn",
  bad_date: "Ngày đăng hỏng",
  future_date: "Ngày ở tương lai",
  duplicate_url: "URL trùng",
  duplicate_id: "article_id trùng",
};
const FILTERED_TABS = new Set(["time", "categories", "browse"]);
const state = { meta: null, tab: "overview", granularity: "day", page: 1, pageSize: 50, charts: {} };

const $ = (id) => document.getElementById(id);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtInt = (n) => Number(n ?? 0).toLocaleString("vi-VN");
const fmtTime = (iso) => (iso ? new Date(iso).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "—");

function colorFor(source) {
  const i = (state.meta?.sources ?? []).indexOf(source);
  return PALETTE[(i >= 0 ? i : 0) % PALETTE.length];
}
const srcCell = (s) => `<span class="dot" style="background:${colorFor(s)}"></span>${esc(s)}`;

async function api(path, params = {}, opts = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined));
  const res = await fetch(qs.toString() ? `${path}?${qs}` : path, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* giữ statusText */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

let toastTimer;
function toast(msg, isError = false) {
  const el = $("toast");
  el.textContent = msg;
  el.className = `show${isError ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = ""; }, isError ? 6000 : 3000);
}

function globalFilters() {
  return { source: $("fSource").value, date_from: $("fFrom").value, date_to: $("fTo").value };
}

function makeChart(id, config) {
  if (typeof Chart === "undefined") throw new Error("Không tải được thư viện biểu đồ (cần Internet)");
  state.charts[id]?.destroy();
  state.charts[id] = new Chart($(id), config);
}

function chartOptions(extra = {}) {
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { position: "bottom" } },
    ...extra,
  };
}

/** Chuyển [{<key>, source, n}] thành nhãn trục + mỗi nguồn một dataset. */
function pivot(rows, key, labels = null) {
  const lbl = labels ?? [...new Set(rows.map((r) => r[key]))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const pos = new Map(lbl.map((l, i) => [l, i]));
  const sources = state.meta.sources.filter((s) => rows.some((r) => r.source === s));
  const datasets = sources.map((s) => {
    const data = new Array(lbl.length).fill(0);
    rows.forEach((r) => { if (r.source === s && pos.has(r[key])) data[pos.get(r[key])] = r.n; });
    return { label: s, data, backgroundColor: colorFor(s), borderColor: colorFor(s) };
  });
  return { labels: lbl, datasets };
}

function renderTable(id, cols, rows, rowAttrs = () => "") {
  const head = `<thead><tr>${cols.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`).join("")}</tr></thead>`;
  const body = rows.length
    ? rows.map((r) => `<tr ${rowAttrs(r)}>${cols.map((c) =>
        `<td class="${c.num ? "num" : ""}">${c.render ? c.render(r) : esc(r[c.key])}</td>`).join("")}</tr>`).join("")
    : `<tr><td colspan="${cols.length}" class="muted">Không có dữ liệu</td></tr>`;
  $(id).innerHTML = head + `<tbody>${body}</tbody>`;
}

function pctBadge(v) {
  const cls = v >= 20 ? "bad" : v >= 5 ? "warn" : "";
  return cls ? `<span class="badge ${cls}">${v}%</span>` : `${v}%`;
}

// ------------------------------------------------------------------ các tab
async function loadOverview() {
  const [ov, tl] = await Promise.all([
    api("/api/stats/overview"), api("/api/stats/timeline", { granularity: "day" })]);
  const t = ov.total;
  $("kpis").innerHTML = [
    ["Tổng số bài", fmtInt(t.articles)], ["Số nguồn", t.sources], ["Số chuyên mục", t.categories],
    ["Số ngày có dữ liệu", t.days], ["Trung vị số từ / bài", fmtInt(t.median_words)],
  ].map(([l, v]) => `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");

  makeChart("chartOverview", {
    type: "bar", data: pivot(tl, "bucket"),
    options: chartOptions({ scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } } }),
  });

  renderTable("tblSources", [
    { label: "Nguồn", render: (r) => srcCell(r.source) },
    { label: "Số bài", num: true, render: (r) => fmtInt(r.articles) },
    { label: "Chuyên mục", num: true, key: "categories" },
    { label: "Số ngày", num: true, key: "active_days" },
    { label: "Bài đầu tiên", key: "first_published" },
    { label: "Bài mới nhất", key: "last_published" },
    { label: "Trung vị số từ", num: true, render: (r) => fmtInt(r.median_words) },
    { label: "Thiếu tác giả", num: true, render: (r) => pctBadge(r.pct_missing_author) },
    { label: "Thân bài rỗng", num: true, render: (r) => pctBadge(r.pct_empty_content) },
    { label: "Quá ngắn", num: true, render: (r) => pctBadge(r.pct_short_content) },
  ], ov.per_source);
}

async function loadTime() {
  const f = globalFilters();
  const [tl, hours] = await Promise.all([
    api("/api/stats/timeline", { ...f, granularity: state.granularity }),
    api("/api/stats/hour-of-day", f)]);
  const data = pivot(tl, "bucket");
  data.datasets.forEach((d) => {
    d.fill = false; d.tension = 0.2; d.pointRadius = state.granularity === "hour" ? 0 : 2;
  });
  makeChart("chartTimeline", { type: "line", data, options: chartOptions({ scales: { y: { beginAtZero: true } } }) });

  const hourData = pivot(hours, "hour", Array.from({ length: 24 }, (_, h) => h));
  hourData.labels = hourData.labels.map((h) => `${h}h`);
  makeChart("chartHour", { type: "bar", data: hourData, options: chartOptions({ scales: { y: { beginAtZero: true } } }) });
}

async function loadCategories() {
  const rows = (await api("/api/stats/categories", globalFilters()))
    .map((r) => ({ ...r, category: r.category ?? "(trống)" }));
  const totals = new Map();
  rows.forEach((r) => totals.set(r.category, (totals.get(r.category) ?? 0) + r.n));
  const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 30).map(([c]) => c);
  makeChart("chartCategories", {
    type: "bar", data: pivot(rows, "category", top),
    options: chartOptions({
      indexAxis: "y",
      interaction: { mode: "index", intersect: false, axis: "y" },
      scales: { x: { stacked: true, beginAtZero: true }, y: { stacked: true } },
    }),
  });
}

async function loadQuality() {
  const q = await api("/api/stats/quality");
  const keys = Object.keys(ISSUE_LABELS);
  renderTable("tblIssues", [
    { label: "Nguồn", render: (r) => srcCell(r.source) },
    { label: "Số bài", num: true, render: (r) => fmtInt(r.articles) },
    ...keys.map((k) => ({
      label: ISSUE_LABELS[k], num: true,
      render: (r) => {
        const n = r[k];
        if (!n) return `<span class="zero">0</span>`;
        const pct = Math.round((n / r.articles) * 1000) / 10;
        return `<a class="cell" data-source="${esc(r.source)}" data-issue="${k}">${fmtInt(n)}</a> ${pctBadge(pct)}`;
      },
    })),
  ], q.issues_per_source);

  renderTable("tblRawSource", [
    { label: "Giá trị gốc", render: (r) => `<code>${esc(r.source_raw)}</code>` },
    { label: "Sau chuẩn hoá", render: (r) => srcCell(r.source) },
    { label: "Số bài", num: true, render: (r) => fmtInt(r.n) },
    { label: "", render: (r) => (r.source_raw === r.source ? `<span class="badge ok">khớp</span>`
                                                            : `<span class="badge warn">đã chuẩn hoá</span>`) },
  ], q.raw_source_values);

  renderTable("tblDupTitles", [
    { label: "Tiêu đề", key: "title" },
    { label: "Số bài", num: true, key: "n" },
    { label: "Nguồn", render: (r) => (r.source_list ?? []).map(srcCell).join("<br>") },
  ], q.duplicate_titles);

  const bins = [...new Set(q.words_histogram.map((r) => r.bin))].sort((a, b) => a - b);
  const words = pivot(q.words_histogram, "bin", bins);
  words.labels = bins.map((b) => (b >= 2000 ? "≥ 2000" : `${b}–${b + 99}`));
  makeChart("chartWords", { type: "bar", data: words, options: chartOptions({ scales: { y: { beginAtZero: true } } }) });

  const tbins = Array.from({ length: 40 }, (_, i) => i + 1);
  const titles = pivot(q.title_words_histogram, "words", tbins);
  titles.labels = tbins.map((w) => (w === 40 ? "≥ 40" : String(w)));
  makeChart("chartTitleWords", { type: "bar", data: titles, options: chartOptions({ scales: { y: { beginAtZero: true } } }) });
}

function fillCategoryOptions() {
  const src = $("fSource").value;
  const cats = [...new Set(state.meta.categories
    .filter((c) => !src || c.source === src).map((c) => c.category))]
    .filter(Boolean).sort((a, b) => a.localeCompare(b, "vi"));
  const current = $("bCategory").value;
  $("bCategory").innerHTML = `<option value="">Tất cả</option>` +
    cats.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
  $("bCategory").value = cats.includes(current) ? current : "";
}

async function loadBrowse() {
  fillCategoryOptions();
  const res = await api("/api/articles", {
    ...globalFilters(),
    category: $("bCategory").value, q: $("bQuery").value.trim(), issue: $("bIssue").value,
    sort: $("bSort").value, page: state.page, page_size: state.pageSize,
  });
  const pages = Math.max(1, Math.ceil(res.total / res.page_size));
  $("browseCount").textContent = `${fmtInt(res.total)} bài khớp bộ lọc`;
  $("pageInfo").textContent = `Trang ${res.page} / ${pages}`;
  $("prevPage").disabled = res.page <= 1;
  $("nextPage").disabled = res.page >= pages;
  renderTable("tblArticles", [
    { label: "Ngày đăng", render: (r) => `<span style="white-space:nowrap">${esc(r.published_at ?? "—")}</span>` },
    { label: "Nguồn", render: (r) => srcCell(r.source) },
    { label: "Chuyên mục", key: "category" },
    { label: "Tiêu đề", render: (r) => `<strong>${esc(r.title)}</strong><div class="muted">${esc(r.sapo)}</div>` },
    { label: "Số từ", num: true, render: (r) => fmtInt(r.n_words) },
  ], res.items, (r) => `data-id="${esc(r.article_id)}"`);
}

async function loadFiles() {
  const files = await api("/api/files");
  const now = Date.now();
  renderTable("tblFiles", [
    { label: "Key", render: (r) => `<code>${esc(r.key)}</code>` },
    { label: "Dung lượng", num: true, render: (r) => (r.size_bytes ? `${(r.size_bytes / 1e6).toFixed(1)} MB` : "0 (thư mục ảo)") },
    { label: "Sửa lần cuối", render: (r) => fmtTime(r.last_modified) },
    { label: "Độ tươi", render: (r) => {
      if (!r.size_bytes) return "";
      const h = (now - new Date(r.last_modified).getTime()) / 3.6e6;
      const txt = h < 48 ? `${Math.round(h)} giờ trước` : `${Math.round(h / 24)} ngày trước`;
      const cls = h > 72 ? "bad" : h > 24 ? "warn" : "ok";
      return `<span class="badge ${cls}">${txt}</span>`;
    } },
  ], files);
}

const LOADERS = { overview: loadOverview, time: loadTime, categories: loadCategories,
                  quality: loadQuality, browse: loadBrowse, files: loadFiles };

async function showTab(tab) {
  state.tab = tab;
  document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab").forEach((s) => s.classList.toggle("active", s.id === `tab-${tab}`));
  $("filters").hidden = !FILTERED_TABS.has(tab);
  if (location.hash !== `#${tab}`) history.replaceState(null, "", `#${tab}`);
  try { await LOADERS[tab](); } catch (e) { toast(e.message, true); }
}

async function openArticle(id) {
  try {
    const a = await api(`/api/articles/${encodeURIComponent(id)}`);
    $("dlgMeta").innerHTML = `${srcCell(a.source)} · ${esc(a.category ?? "")} · ${esc(a.published_at ?? "")} · ${fmtInt(a.n_words)} từ`;
    $("dlgTitle").textContent = a.title ?? "";
    $("dlgSapo").textContent = a.sapo ?? "";
    const safeUrl = /^https?:\/\//i.test(a.url ?? "")
      ? `<a href="${esc(a.url)}" target="_blank" rel="noopener noreferrer">${esc(a.url)}</a>` : esc(a.url);
    $("dlgFields").innerHTML = [
      ["Tác giả", esc(a.author ?? "—")], ["URL", safeUrl], ["article_id", esc(a.article_id)],
      ["source gốc", esc(a.source_raw)], ["published_at gốc", esc(a.published_at_raw)], ["File", esc(a.source_file)],
    ].map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
    $("dlgContent").textContent = a.content_text || "(thân bài rỗng)";
    $("articleDialog").showModal();
  } catch (e) { toast(e.message, true); }
}

async function loadMeta() {
  state.meta = await api("/api/meta");
  $("dataset").textContent = `${state.meta.dataset} · ${fmtInt(state.meta.rows)} bài`;
  $("loaded").textContent = state.meta.loaded_at
    ? `Nạp lúc ${fmtTime(state.meta.loaded_at)} (${Number(state.meta.load_seconds ?? 0).toFixed(1)}s)` : "";
  const current = $("fSource").value;
  $("fSource").innerHTML = `<option value="">Tất cả</option>` +
    state.meta.sources.map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  $("fSource").value = state.meta.sources.includes(current) ? current : "";
  const { min_date: lo, max_date: hi } = state.meta.date_range ?? {};
  ["fFrom", "fTo"].forEach((id) => { if (lo) $(id).min = lo; if (hi) $(id).max = hi; });
}

function openBrowseWith({ source, issue }) {
  $("fSource").value = source ?? "";
  $("bIssue").value = issue ?? "";
  state.page = 1;
  showTab("browse");
}

function wireEvents() {
  $("tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]");
    if (b) showTab(b.dataset.tab);
  });
  const refilter = () => { state.page = 1; if (FILTERED_TABS.has(state.tab)) showTab(state.tab); };
  ["fSource", "fFrom", "fTo"].forEach((id) => $(id).addEventListener("change", refilter));
  $("fReset").addEventListener("click", () => {
    ["fSource", "fFrom", "fTo", "bCategory", "bQuery", "bIssue"].forEach((id) => { $(id).value = ""; });
    refilter();
  });
  $("granularity").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-g]");
    if (!b) return;
    state.granularity = b.dataset.g;
    document.querySelectorAll("#granularity button").forEach((x) => x.classList.toggle("active", x === b));
    loadTime().catch((err) => toast(err.message, true));
  });
  ["bCategory", "bIssue", "bSort"].forEach((id) =>
    $(id).addEventListener("change", () => { state.page = 1; loadBrowse().catch((e) => toast(e.message, true)); }));
  let debounce;
  $("bQuery").addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => { state.page = 1; loadBrowse().catch((e) => toast(e.message, true)); }, 350);
  });
  $("prevPage").addEventListener("click", () => { state.page -= 1; loadBrowse().catch((e) => toast(e.message, true)); });
  $("nextPage").addEventListener("click", () => { state.page += 1; loadBrowse().catch((e) => toast(e.message, true)); });
  $("tblArticles").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr) openArticle(tr.dataset.id);
  });
  $("tblIssues").addEventListener("click", (e) => {
    const a = e.target.closest("a.cell");
    if (a) openBrowseWith({ source: a.dataset.source, issue: a.dataset.issue });
  });
  $("reloadBtn").addEventListener("click", async () => {
    const btn = $("reloadBtn");
    btn.disabled = true; btn.textContent = "Đang tải…";
    try {
      // Chỉ admin: cần đăng nhập ở web (cùng địa chỉ) và gửi lại cookie csrf_token trong header.
      const csrf = (document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/) || [])[1] || "";
      const r = await api("/api/admin/reload", {}, { method: "POST", headers: { "X-CSRF-Token": decodeURIComponent(csrf) } });
      toast(`Đã nạp lại ${fmtInt(r.rows)} bài trong ${r.seconds}s`);
      await loadMeta();
      await showTab(state.tab);
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = "Tải lại từ kho"; }
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  if (typeof Chart !== "undefined") {
    const css = getComputedStyle(document.documentElement);
    Chart.defaults.color = css.getPropertyValue("--muted").trim();
    Chart.defaults.borderColor = css.getPropertyValue("--border").trim();
  }
  wireEvents();
  try {
    await loadMeta();
  } catch (e) {
    $("dataset").textContent = "Không kết nối được API";
    toast(e.message, true);
    return;
  }
  const initial = location.hash.slice(1);
  await showTab(LOADERS[initial] ? initial : "overview");
});
