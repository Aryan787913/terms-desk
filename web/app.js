/* Terms Desk demo UI. Skeptic math mirrors skeptic/engine.py exactly. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const usd = (v, dp = 0) => (v < 0 ? "−$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const pct = (v, dp = 0) => (v * 100).toFixed(dp) + "%";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const SPEED = new URLSearchParams(location.search).get("speed") ? +new URLSearchParams(location.search).get("speed") : 1;
const wait = ms => sleep(ms / SPEED);

/* ---------- Skeptic (same as skeptic/engine.py) ---------- */
function expectedValue(A, d, w, r, p0, late, s) {
  const g = Math.max(late - w, 0);
  const pWin = p0 + (1 - p0) * s;
  const cost = d * A * pWin;
  const benefit = (1 - p0) * s * A * r * g / 365;
  return { ev: benefit - cost, cost, benefit, g };
}
function breakEven(d, w, r, p0, late) {
  const g = Math.max(late - w, 0);
  const per = (1 - p0) * (r * g / 365 - d);
  if (per <= 0) return (p0 === 0 && per === 0) ? 0 : null;
  const s = d * p0 / per;
  return s <= 1 ? s : null;
}
function decide(A, d, w, r, p0, late, s) {
  const { ev, cost, benefit, g } = expectedValue(A, d, w, r, p0, late, s);
  const be = breakEven(d, w, r, p0, late);
  const give = d * A * p0;
  let reason;
  if (be === null && r * g / 365 <= d) reason = `Blocked: ${pct(d)} for ${g} days sooner costs more than your ${pct(r)} cost of capital, whoever pays early. Expected giveaway to on-time payers ${usd(give)}.`;
  else if (be === null) reason = `Blocked: even if every slow payer sped up, the early cash would not cover the ${usd(give)} you'd give to clients who pay on time anyway.`;
  else if (ev >= 0) reason = `Approved: pays off if at least ${pct(be)} of slow payers move into the ${w}-day window (you assumed ${pct(s)}).`;
  else reason = `Blocked: needs ${pct(be)} of slow payers to speed up; you assumed ${pct(s)}. Expected giveaway ${usd(give)}.`;
  return { approve: ev >= 0 && be !== null, ev, cost, benefit, be, give, g, reason };
}
const annualized = (d, w, net) => d / (1 - d) * 365 / (net - w);

/* ---------- settings + data ---------- */
const S = { r: 0.36, d: 0.02, w: 10, shift: 0.5 };
const COLORS = ["#0070E0", "#7A5AF8", "#0E9F6E", "#F79009", "#EE46BC", "#06AED4"];

// Fictional clients. p0 = model's P(pays inside 10 days with no discount); late = expected days-to-pay otherwise.
const INCOMING = [
  { id: "nw", client: "Northwind Design Co.", type: "Retainer · Net 30", A: 2000, p0: 0.29, late: 90, hist: "Paid 2 of 7 past invoices on time", real: true },
  { id: "lm", client: "Lumen Labs", type: "Product sprint · Net 30", A: 8000, p0: 0.84, late: 25, hist: "Paid 11 of 13 on time" },
  { id: "kt", client: "Kite & Co.", type: "Brand refresh · Net 30", A: 1200, p0: 0.35, late: 70, hist: "Paid 3 of 9 on time" },
  { id: "ob", client: "Orbit Media", type: "Monthly content · Net 30", A: 4500, p0: 0.74, late: 40, hist: "Paid 8 of 11 on time" },
  { id: "fh", client: "Fernhill Studio", type: "UX audit · Net 30", A: 3200, p0: 0.91, late: 20, hist: "Paid 10 of 11 on time" },
];
INCOMING.forEach((x, i) => { x.color = COLORS[i % COLORS.length]; x.dec = decide(x.A, S.d, S.w, S.r, x.p0, x.late, S.shift); });

// Earlier this month (fictional history) so the dashboard is not empty.
const LEDGER = [
  { date: "Oct 03", client: "Harbor Analytics", amount: 6400, action: "Discount blocked", by: "Skeptic", value: 0.02 * 6400 * 0.88, status: "Blocked" },
  { date: "Oct 07", client: "Pine & Pixel", amount: 1800, action: "2% / 10 days sent", by: "You", value: 1800 * 0.02 * -1, status: "Paid early", days: 61 },
  { date: "Oct 12", client: "Atlas Robotics", amount: 9500, action: "Discount blocked", by: "Skeptic", value: 0.02 * 9500 * 0.9, status: "Blocked" },
  { date: "Oct 16", client: "Bluebird Cafe Group", amount: 2400, action: "Rejected by you", by: "You", value: 0, status: "Rejected" },
  { date: "Oct 21", client: "Cedar Legal", amount: 3800, action: "Discount blocked", by: "Skeptic", value: 0.02 * 3800 * 0.82, status: "Blocked" },
];
const EARLY = [{ amount: 1800, days: 61 }]; // early cash captured
let QUEUE = [];
let sentCount = 1;

/* ---------- navigation ---------- */
const TITLES = { overview: ["Workspace", "Good afternoon"], queue: ["Agent", "Approval queue"], skeptic: ["Decision engine", "The Skeptic"], ledger: ["Audit", "Money ledger"] };
function go(view) {
  $$("nav a").forEach(a => a.classList.toggle("active", a.dataset.view === view));
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  $("#crumb").textContent = TITLES[view][0]; $("#title").textContent = TITLES[view][1];
  if (view === "ledger") renderGrid();
  if (view === "skeptic") renderSkeptic();
}
$$("nav a").forEach(a => a.addEventListener("click", () => go(a.dataset.view)));
window.go = go;

/* ---------- overview ---------- */
function countUp(el, to, fmt, ms = 900) {
  const from = +(el.dataset.v || 0); el.dataset.v = to; const t0 = performance.now();
  const step = t => { const k = Math.min((t - t0) / (ms / SPEED), 1), e = 1 - Math.pow(1 - k, 3); el.textContent = fmt(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
  requestAnimationFrame(step);
}
function renderKPIs() {
  const protectedAmt = LEDGER.filter(l => l.status === "Blocked").reduce((a, l) => a + l.value, 0);
  const captured = EARLY.reduce((a, e) => a + e.amount, 0);
  const avgDays = EARLY.length ? Math.round(EARLY.reduce((a, e) => a + e.days, 0) / EARLY.length) : 0;
  countUp($("#heroProtected"), protectedAmt, v => usd(v));
  countUp($("#heroCaptured"), captured, v => usd(v));
  countUp($("#heroDays"), avgDays, v => Math.round(v));
  countUp($("#heroSent"), sentCount, v => Math.round(v));
  $("#kpiPending").textContent = QUEUE.length;
  $("#kpiBlocked").textContent = LEDGER.filter(l => l.status === "Blocked").length;
  $("#kpiRate").textContent = pct(S.r);
  const b = $("#queueBadge"); b.textContent = QUEUE.length; b.classList.toggle("zero", !QUEUE.length);
  $("#ledgerProtected").textContent = usd(protectedAmt);
}
function feed(icon, cls, text, sub) {
  const li = document.createElement("li");
  li.innerHTML = `<div class="fi ${cls}">${icon}</div><div class="ft">${text}<small>${sub || "just now"}</small></div>`;
  $("#feed").prepend(li);
}
function renderCashChart() {
  // Per open invoice: expected discount cost vs expected value of getting paid sooner (Skeptic, your assumptions).
  const svg = $("#cashChart"), W = 640, H = 240, P = 34, B = 26;
  const data = INCOMING.map(x => ({ n: x.client.split(" ")[0], c: x.dec.cost, b: x.dec.benefit, ok: x.dec.approve }));
  const max = Math.max(...data.map(d => Math.max(d.c, d.b))) * 1.15;
  const slot = (W - 2 * P) / data.length, Y = v => H - P - (H - 2 * P) * v / max;
  let g = "";
  for (let i = 0; i <= 4; i++) { const v = max * i / 4, y = Y(v); g += `<line x1="${P}" x2="${W - 10}" y1="${y}" y2="${y}" stroke="#EEF1F6"/><text x="${P - 6}" y="${y + 4}" font-size="10" fill="#98A2B3" text-anchor="end">${usd(v)}</text>`; }
  data.forEach((d, i) => {
    const x0 = P + slot * i + slot / 2 - B - 3;
    g += `<rect class="gb" x="${x0}" y="${Y(d.b)}" width="${B}" height="${H - P - Y(d.b)}" rx="6" fill="#0070E0"/>`;
    g += `<rect class="gb" x="${x0 + B + 6}" y="${Y(d.c)}" width="${B}" height="${H - P - Y(d.c)}" rx="6" fill="#C3CAD9"/>`;
    g += `<text x="${x0 + B + 3}" y="${H - 12}" font-size="11" fill="#3B4663" text-anchor="middle" font-weight="600">${d.n}</text>`;
    g += `<text x="${x0 + B + 3}" y="${Math.min(Y(d.b), Y(d.c)) - 8}" font-size="11" text-anchor="middle" font-weight="700" fill="${d.ok ? "#0E9F6E" : "#D92D20"}">${d.ok ? "✓" : "✕"}</text>`;
  });
  svg.innerHTML = g;
}
/* ---------- agent run ---------- */
async function runAgent() {
  const btn = $("#runAgent"); btn.disabled = true; btn.innerHTML = '<span class="spark">✦</span> Scanning…';
  feed("⟳", "b", "Agent started: pulled <b>5 draft invoices</b> from PayPal", "Invoicing v2 · sandbox");
  for (const x of INCOMING) {
    await wait(650);
    feed("%", "b", `Scored <b>${x.client}</b>: ${pct(x.p0)} chance of paying on time`, x.hist);
    await wait(350);
    if (x.dec.approve) feed("✓", "g", `Skeptic <b>recommends</b> 2% / 10 days for ${x.client}`, `Break-even at ${pct(x.dec.be)} response`);
    else feed("✕", "r", `Skeptic <b>blocked</b> a discount for ${x.client}`, `Would give away ~${usd(x.dec.give)}`);
    QUEUE.push(x); renderKPIs();
  }
  await wait(400);
  feed("→", "b", `<b>${QUEUE.length} proposals</b> waiting for your approval`, "Nothing sent yet");
  btn.disabled = false; btn.innerHTML = '<span class="spark">✦</span> Run agent';
  renderQueue(); toast(`${QUEUE.length} proposals ready for review`);
}
$("#runAgent").addEventListener("click", runAgent);

/* ---------- queue ---------- */
let filter = "all";
$$("#queueFilter button").forEach(b => b.addEventListener("click", () => { filter = b.dataset.f; $$("#queueFilter button").forEach(x => x.classList.toggle("on", x === b)); renderQueue(); }));
function renderQueue() {
  const list = $("#queueList"); list.innerHTML = "";
  const items = QUEUE.filter(x => filter === "all" || (filter === "approve" ? x.dec.approve : !x.dec.approve));
  $("#queueEmpty").classList.toggle("hidden", QUEUE.length > 0);
  items.forEach(x => {
    const d = x.dec, el = document.createElement("div"); el.className = "prop"; el.id = "prop-" + x.id;
    const initials = x.client.split(/\s+/).filter(w => /[A-Za-z]/.test(w[0])).slice(0, 2).map(w => w[0]).join("");
    const barColor = x.p0 >= 0.7 ? "#0E9F6E" : x.p0 >= 0.5 ? "#F79009" : "#D92D20";
    el.innerHTML = `
      <div class="who"><div class="av" style="background:${x.color}">${initials}</div><div><div class="who-n">${x.client}</div><div class="who-s">${x.type}</div></div></div>
      <div><div class="amt">${usd(x.A)}</div><div class="terms">Proposed: 2% off if paid in 10 days</div>
        <div class="odds"><div class="bar"><i style="width:${x.p0 * 100}%;background:${barColor}"></i></div><span>${pct(x.p0)} on time</span></div></div>
      <div>${d.approve ? `<span class="pill ok">✓ Skeptic: send discount</span>` : `<span class="pill no">✕ Skeptic: no discount</span>`}
        <span class="ev ${d.approve ? "pos" : "neg"}" style="margin-left:8px;font-size:13px">${d.approve ? "EV +" + usd(d.ev) : "saves " + usd(d.give)}</span>
        <div class="why">${d.reason}</div></div>
      <div class="acts">${d.approve
        ? `<button class="btn btn-ok btn-sm" data-a="approve">Approve & send</button><button class="btn btn-ghost btn-sm" data-a="reject">Reject</button>`
        : `<button class="btn btn-primary btn-sm" data-a="plain">Send without discount</button><button class="btn btn-ghost btn-sm" data-a="override">Override</button>`}</div>`;
    el.querySelectorAll("button").forEach(b => b.addEventListener("click", () => act(x, b.dataset.a)));
    list.appendChild(el);
  });
}
function removeFromQueue(x) {
  const el = $("#prop-" + x.id); if (el) el.classList.add("leaving");
  setTimeout(() => { QUEUE = QUEUE.filter(q => q !== x); renderQueue(); renderKPIs(); }, 320 / SPEED);
}
function today() { return new Date().toLocaleDateString("en-US", { month: "short", day: "2-digit" }); }
async function act(x, a) {
  if (a === "approve") return approveFlow(x);
  if (a === "reject") { LEDGER.push({ date: today(), client: x.client, amount: x.A, action: "Rejected by you", by: "You", value: 0, status: "Rejected" }); feed("✕", "r", `You rejected terms for <b>${x.client}</b>`); toast("Rejected. Nothing was sent."); }
  if (a === "plain") { LEDGER.push({ date: today(), client: x.client, amount: x.A, action: "Discount blocked", by: "Skeptic + you", value: x.dec.give, status: "Blocked" }); sentCount++; feed("✓", "g", `Sent <b>${x.client}</b> at full price`, `Protected ~${usd(x.dec.give)}`); toast(`Sent at full price · ~${usd(x.dec.give)} protected`); }
  if (a === "override") { toast("Override needs a written reason. Logged to the ledger."); return; }
  removeFromQueue(x);
}

/* ---------- approval modal ---------- */
async function approveFlow(x) {
  const disc = x.A * S.d, pay = x.A - disc;
  $("#mTitle").textContent = `${x.client} · ${usd(x.A)}`;
  $("#mAmt").textContent = usd(x.A, 2); $("#mDisc").textContent = "−" + usd(disc, 2); $("#mPay").textContent = usd(pay, 2);
  $("#mNote").textContent = `Discount is valid for ${S.w} days. If unpaid by then, Terms Desk updates the invoice back to ${usd(x.A, 2)}.`;
  const steps = x.real ? [
    ["Skeptic approved", `EV +${usd(x.dec.ev, 2)} at your assumptions`],
    ["Created invoice with 2% invoice_discount", "POST /v2/invoicing/invoices → INV2-JCP3-K2T3-VLW6-2ZE5"],
    ["Sent to client", "POST /v2/invoicing/invoices/{id}/send"],
    ["Scheduled discount expiry", `PUT invoice back to ${usd(x.A, 2)} on day ${S.w} if unpaid`],
    ["Payment received", "status PAID · paid_amount $1,960.00"],
  ] : [
    ["Skeptic approved", `EV +${usd(x.dec.ev, 2)} at your assumptions`],
    ["Create invoice with 2% invoice_discount", "simulated in demo"],
    ["Send to client", "simulated in demo"],
    ["Schedule discount expiry", `day ${S.w}`],
  ];
  $("#mSteps").innerHTML = steps.map((s, i) => `<li><span class="sd">${i + 1}</span><div>${s[0]}<code>${s[1]}</code></div></li>`).join("");
  $("#mPaid").classList.add("hidden");
  $("#modal").classList.remove("hidden");
  const lis = $$("#mSteps li");
  for (let i = 0; i < lis.length; i++) {
    lis[i].classList.add("run"); await wait(i === lis.length - 1 && x.real ? 1500 : 850);
    lis[i].classList.remove("run"); lis[i].classList.add("done"); lis[i].querySelector(".sd").textContent = "✓";
  }
  sentCount++;
  if (x.real) {
    $("#mPaidSub").textContent = "Sandbox payment 9K007555N0827933D · $1,960.00";
    $("#mPaid").classList.remove("hidden");
    LEDGER.push({ date: today(), client: x.client, amount: x.A, action: "2% / 10 days sent", by: "You", value: -disc, status: "Paid early", days: x.late - 0 });
    EARLY.push({ amount: pay, days: x.late - 1 });
    feed("$", "g", `<b>${x.client}</b> paid ${usd(pay, 2)} early via PayPal`, "Sandbox · 9K007555N0827933D");
  } else {
    LEDGER.push({ date: today(), client: x.client, amount: x.A, action: "2% / 10 days sent", by: "You", value: 0, status: "Sent" });
    feed("→", "b", `Sent <b>${x.client}</b> with 2% / 10 days`, "Awaiting payment");
  }
  removeFromQueue(x);
}
const closeModal = () => { $("#modal").classList.add("hidden"); renderKPIs(); };
$("#mClose").addEventListener("click", closeModal); $("#mDone").addEventListener("click", closeModal);

/* ---------- skeptic playground ---------- */
const SL = { A: 2000, d: 0.02, w: 10, r: 0.36, p0: 0.29, late: 90, s: 0.5 };
const SLDEF = [
  ["A", "Invoice amount", 500, 20000, 100, v => usd(v), ""],
  ["d", "Discount", 0.005, 0.05, 0.005, v => pct(v, 1), "Offered for paying inside the window"],
  ["w", "Discount window", 5, 20, 1, v => v + " days", ""],
  ["r", "Your cost of capital", 0.05, 0.6, 0.01, v => pct(v), "What a dollar today is worth to you, per year"],
  ["p0", "Chance client pays on time anyway", 0, 1, 0.01, v => pct(v), "From the prediction model"],
  ["late", "Days to pay if slow", 15, 120, 1, v => v + " days", ""],
  ["s", "Slow payers who speed up (your guess)", 0, 1, 0.05, v => pct(v), "Never assumed as fact: try a few values"],
];
function buildSliders() {
  $("#sliders").innerHTML = SLDEF.map(([k, l, mn, mx, st, f, h]) => `<div class="sl"><label>${l}<b id="slv-${k}">${f(SL[k])}</b></label><input type="range" id="sl-${k}" min="${mn}" max="${mx}" step="${st}" value="${SL[k]}">${h ? `<small>${h}</small>` : ""}</div>`).join("");
  SLDEF.forEach(([k, , , , , f]) => $("#sl-" + k).addEventListener("input", e => { SL[k] = +e.target.value; $("#slv-" + k).textContent = f(SL[k]); renderSkeptic(); }));
}
function renderSkeptic() {
  const dc = decide(SL.A, SL.d, SL.w, SL.r, SL.p0, SL.late, SL.s);
  const v = $("#skVerdict"); v.className = "verdict " + (dc.approve ? "ok" : "no"); v.textContent = dc.approve ? "✓ Send the discount" : "✕ Don't discount";
  $("#skEV").textContent = (dc.ev >= 0 ? "+" : "") + usd(dc.ev, 2); $("#skEV").style.color = dc.ev >= 0 ? "var(--green)" : "var(--red)";
  $("#skReason").textContent = dc.reason;
  $("#skBE").textContent = dc.be === null ? "Never" : pct(dc.be);
  $("#skGive").textContent = usd(dc.give);
  $("#skAnn").textContent = pct(annualized(SL.d, SL.w, 30), 1);
  // chart EV vs s
  const svg = $("#skChart"), W = 560, H = 220, P = 18, N = 50;
  const ys = [...Array(N + 1)].map((_, i) => expectedValue(SL.A, SL.d, SL.w, SL.r, SL.p0, SL.late, i / N).ev);
  const mx = Math.max(...ys, 1), mn = Math.min(...ys, -1), pad = (mx - mn) * 0.12;
  const X = i => P + (W - 2 * P) * i / N, Y = v => P + (H - 2 * P) * (mx + pad - v) / (mx - mn + 2 * pad);
  const line = ys.map((v, i) => (i ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1)).join(" ");
  const cx = X(SL.s * N), cy = Y(dc.ev);
  let be = "";
  if (dc.be !== null) be = `<line x1="${X(dc.be * N)}" x2="${X(dc.be * N)}" y1="${P}" y2="${H - P}" stroke="#98A2B3" stroke-dasharray="4 4"/><text x="${X(dc.be * N) + 6}" y="${P + 10}" font-size="11" fill="#6B7590">break-even</text>`;
  svg.innerHTML = `<rect x="${P}" y="${Y(0)}" width="${W - 2 * P}" height="${Math.max(H - P - Y(0), 0)}" fill="#FDECEA" opacity=".55"/>
    <rect x="${P}" y="${P}" width="${W - 2 * P}" height="${Math.max(Y(0) - P, 0)}" fill="#E8F7F0" opacity=".55"/>
    <line x1="${P}" x2="${W - P}" y1="${Y(0)}" y2="${Y(0)}" stroke="#98A2B3"/>
    <text x="${W - P - 4}" y="${Y(0) - 6}" font-size="11" fill="#0E9F6E" text-anchor="end">earns money</text>
    <text x="${W - P - 4}" y="${Y(0) + 15}" font-size="11" fill="#D92D20" text-anchor="end">loses money</text>
    ${be}<path d="${line}" fill="none" stroke="#003087" stroke-width="3"/>
    <circle cx="${cx}" cy="${cy}" r="7" fill="#fff" stroke="${dc.ev >= 0 ? "#0E9F6E" : "#D92D20"}" stroke-width="3"/>`;
}

/* ---------- ledger grid ---------- */
let gridApi = null;
function pill(p) { const s = p.value, c = { "Paid early": "cp-paid", Blocked: "cp-block", Sent: "cp-sent", Rejected: "cp-rej" }[s] || "cp-sent"; return `<span class="cell-pill ${c}">${s}</span>`; }
function renderGrid() {
  const rows = LEDGER.slice().reverse().map(l => ({ ...l }));
  if (gridApi) { gridApi.setGridOption("rowData", rows); return; }
  gridApi = agGrid.createGrid($("#grid"), {
    rowData: rows, animateRows: true, domLayout: "autoHeight", rowHeight: 52, headerHeight: 46,
    defaultColDef: { sortable: true, resizable: true, flex: 1 },
    columnDefs: [
      { field: "date", headerName: "Date", maxWidth: 110 },
      { field: "client", headerName: "Client", flex: 1.4, cellStyle: { fontWeight: 600 } },
      { field: "amount", headerName: "Invoice", valueFormatter: p => usd(p.value), maxWidth: 130 },
      { field: "action", headerName: "Decision", flex: 1.3 },
      { field: "by", headerName: "Decided by", maxWidth: 140 },
      { field: "status", headerName: "Status", cellRenderer: pill, maxWidth: 150 },
      { field: "value", headerName: "Money impact", valueFormatter: p => p.value > 0 ? "+" + usd(p.value) + " kept" : p.value < 0 ? usd(p.value) + " discount" : "—",
        cellStyle: p => ({ fontWeight: 700, color: p.value > 0 ? "#0E9F6E" : p.value < 0 ? "#B54708" : "#98A2B3" }) },
    ],
  });
}

/* ---------- misc ---------- */
let tt; function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.remove("hidden"); clearTimeout(tt); tt = setTimeout(() => t.classList.add("hidden"), 2600 / SPEED); }
const h = new Date().getHours(); TITLES.overview[1] = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"; $("#title").textContent = TITLES.overview[1];
feed("✓", "g", "Connected to <b>PayPal Sandbox</b> · Invoicing v2", "US business account");
buildSliders(); renderKPIs(); renderCashChart(); renderQueue();
