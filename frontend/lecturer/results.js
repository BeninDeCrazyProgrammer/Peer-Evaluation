const courseId = qs("course");
const evalId = qs("evaluation");
if (!courseId || !evalId) window.location.href = "dashboard.html";

// Initialize UI
initSections();
document.getElementById("backLink").href = `course.html?course=${courseId}`;
document.getElementById("backLinkMobile").href = `course.html?course=${courseId}`;
// Download via fetch, not a plain link: the session cookie is partitioned to
// this site, so a top-level navigation straight to the API wouldn't carry it.
document.getElementById("exportBtn").addEventListener("click", async (e) => {
    e.preventDefault();
    try {
        const res = await fetch(`${API_BASE}/courses/${courseId}/evaluations/${evalId}/results/export.xlsx`, { credentials: "include" });
        if (!res.ok) {
            let msg = null;
            try { msg = (await res.json()).error; } catch (_) { /* no JSON body */ }
            throw new Error(msg || `Export failed (${res.status})`);
        }
        const url = URL.createObjectURL(await res.blob());
        const a = document.createElement("a");
        a.href = url;
        a.download = `peer-evaluation-results-${evalId}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
    } catch (err) {
        alert(err.message || "Couldn't export results.");
    }
});

let globalData = null; // Store results for drilling
let globalCompletion = null; // Store roster/submission status for the matrix

async function loadPage() {
    const me = await api("/auth/me");
    if (!me.authenticated) { window.location.href = "login.html"; return; }

    const ev = await api(`/courses/${courseId}/evaluations/${evalId}`);
    document.getElementById("evalTitle").textContent = ev.title;

    await refreshData();
}

async function refreshData() {
    const completion = await api(`/courses/${courseId}/evaluations/${evalId}/completion`);
    globalData = await api(`/courses/${courseId}/evaluations/${evalId}/results`);
    globalCompletion = completion;

    renderKPIs(completion, globalData);
    renderCompletionGrid(completion);
    renderAveragesTable(globalData);
    renderRankings(globalData);
    renderMatrix(completion, globalData);
    renderFlags(globalData);
}

const FLAG_STYLE = {
    high:   { label: "High",   cls: "bg-red-100 text-red-700" },
    medium: { label: "Medium", cls: "bg-amber-100 text-amber-700" },
    low:    { label: "Low",    cls: "bg-slate-100 text-slate-600" },
};
const FLAG_TITLE = {
    same_score_everyone: "Same score for everyone",
    uniform_totals: "Same total for everyone",
    low_outlier: "Unusually low compared with the group",
    high_outlier: "Unusually high compared with the group",
};

function renderFlags(data) {
    const flags = data.anomalies;
    const badge = document.getElementById("flagsBadge");
    badge.textContent = flags.length;
    badge.classList.toggle("hidden", flags.length === 0);

    const list = document.getElementById("flagsList");
    if (flags.length === 0) {
        list.innerHTML = `<div class="p-12 text-center border-2 border-dashed border-slate-100 rounded-3xl text-slate-400">No anomalies detected.</div>`;
        return;
    }
    list.innerHTML = flags.map(f => {
        const sev = FLAG_STYLE[f.severity] || FLAG_STYLE.low;
        return `
            <div class="p-4 rounded-xl border border-slate-200 bg-white">
                <div class="flex flex-wrap items-center gap-2 mb-1.5">
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${sev.cls}">${sev.label}</span>
                    <span class="font-bold text-slate-800 text-sm">${esc(FLAG_TITLE[f.type] || f.type)}</span>
                    <span class="text-xs text-slate-400">· ${esc(f.group_label ?? "")}</span>
                </div>
                <p class="text-sm text-slate-600">${esc(f.message)}</p>
                <button class="mt-2 text-orange-600 hover:text-orange-700 font-bold text-xs uppercase tracking-wider"
                        onclick="openEvaluatorDrawer(this.dataset.name)" data-name="${esc(f.ratee_name ?? f.evaluator_name)}">
                    Inspect ${esc(f.ratee_name ?? f.evaluator_name)}
                </button>
            </div>`;
    }).join("");
}

function openEvaluatorDrawer(name) { openDrawer(name); }

function renderKPIs(completion, results) {
    // 1. Completion Rate
    let total = 0, submitted = 0;
    completion.forEach(g => {
        total += g.students.length;
        submitted += g.students.filter(s => s.has_submitted).length;
    });
    const rate = total > 0 ? Math.round((submitted / total) * 100) : 0;
    document.getElementById("statCompletion").textContent = `${rate}%`;

    // 2. Class Average — mean per-criterion score per student (total / number of
    // criteria), so this stays a small, comparable number even though the table's
    // "Total" column below is a sum, not an average.
    const numCriteria = results.criteria.length || 1;
    const totals = results.aggregates.map(a => a.total).filter(v => v !== null);
    const avgs = totals.map(t => t / numCriteria);
    const classAvg = avgs.length > 0 ? (avgs.reduce((a, b) => a + b, 0) / avgs.length).toFixed(2) : "0.00";
    document.getElementById("statAvg").textContent = classAvg;

    // 2b. Total Class Average — plain mean of the Total column itself (not
    // divided by criteria count), so it reads on the same scale as the
    // "Total" badges in the table/Rankings below.
    const totalClassAvg = totals.length > 0 ? (totals.reduce((a, b) => a + b, 0) / totals.length).toFixed(2) : "0.00";
    document.getElementById("statTotalAvg").textContent = totalClassAvg;

    // 3. Flags to review: scoring anomalies found server-side (Evaluation.anomalies)
    const conflicts = results.anomalies.length;
    document.getElementById("statConflicts").textContent = conflicts;
}

function renderCompletionGrid(groups) {
    const grid = document.getElementById("completionGrid");
    grid.innerHTML = groups.map(g => {
        const submitted = g.students.filter(s => s.has_submitted).length;
        const percent = Math.round((submitted / g.students.length) * 100);
        
        return `
            <div class="bg-white border border-slate-200 rounded-xl p-5 shadow-sm">
                <div class="flex justify-between items-start mb-4">
                    <div>
                        <h4 class="font-bold text-slate-800">${esc(g.group_label)}</h4>
                        <p class="text-xs text-slate-400">${g.students.length} Members</p>
                    </div>
                    <div class="text-right">
                        <span class="text-sm font-bold ${percent === 100 ? 'text-green-600' : 'text-orange-600'}">${percent}%</span>
                    </div>
                </div>
                <div class="space-y-2">
                    ${g.students.map(s => `
                        <div class="flex items-center justify-between text-sm">
                            <span class="${s.has_submitted ? 'text-slate-700' : 'text-slate-400 italic'}">${esc(s.name)}</span>
                            <i data-lucide="${s.has_submitted ? 'check-circle' : 'circle'}" 
                               class="w-4 h-4 ${s.has_submitted ? 'text-green-500' : 'text-slate-200'}"></i>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }).join("");
    lucide.createIcons();
}

function renderAveragesTable(data) {
    const head = document.getElementById("aggHead");
    head.innerHTML = `
        <th class="p-4 text-xs font-bold text-slate-500 uppercase">Student</th>
        ${data.criteria.map(c => `<th class="p-4 text-xs font-bold text-slate-500 uppercase text-center">${esc(c.name)}</th>`).join('')}
        <th class="p-4 text-xs font-bold text-slate-500 uppercase text-center">Total</th>
        <th class="p-4 text-xs font-bold text-slate-500 uppercase text-right">Actions</th>
    `;

    const body = document.getElementById("aggBody");
    if (data.aggregates.length === 0) {
        body.innerHTML = `<tr><td colspan="100%" class="p-12 text-center text-slate-400">Waiting for first submission...</td></tr>`;
        return;
    }

    body.innerHTML = data.aggregates.map(s => {
        const byName = Object.fromEntries(s.by_criterion.map(c => [c.criterion, c.average]));
        
        return `
            <tr class="hover:bg-slate-50/50 transition-colors">
                <td class="p-4 font-bold text-slate-800">${esc(s.name)}</td>
                ${data.criteria.map(c => {
                    const val = byName[c.name] ?? "—";
                    const colorClass = val === "—" ? "text-slate-300" : (val < 2 ? "text-red-600 font-bold" : "text-slate-600");
                    return `<td class="p-4 text-center ${colorClass}">${val}</td>`;
                }).join('')}
                <td class="p-4 text-center">
                    <span class="px-3 py-1 bg-slate-900 text-white rounded-full text-xs font-bold">${s.total ?? "—"}</span>
                </td>
                <td class="p-4 text-right">
                    <button onclick="openDrawer(this.dataset.name)" data-name="${esc(s.name)}" class="text-orange-600 hover:text-orange-700 font-bold text-xs uppercase tracking-wider">
                        Inspect
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

let currentRankFilter = "top"; // "top" or "bottom", persists across data refreshes

function renderRankings(data) {
    const body = document.getElementById("rankingBody");
    const ranked = data.aggregates
        .filter(s => s.total !== null)
        .slice()
        .sort((a, b) => currentRankFilter === "top" ? b.total - a.total : a.total - b.total)
        .slice(0, 10);

    if (ranked.length === 0) {
        body.innerHTML = `<tr><td colspan="4" class="p-12 text-center text-slate-400">No submissions yet.</td></tr>`;
        return;
    }

    body.innerHTML = ranked.map((s, i) => `
        <tr class="hover:bg-slate-50/50 transition-colors">
            <td class="p-4 font-bold text-slate-400">${i + 1}</td>
            <td class="p-4 font-bold text-slate-800">${esc(s.name)}</td>
            <td class="p-4 text-slate-500">${esc(s.group_label ?? "—")}</td>
            <td class="p-4 text-center">
                <span class="px-3 py-1 bg-slate-900 text-white rounded-full text-xs font-bold">${s.total}</span>
            </td>
        </tr>
    `).join('');
}

document.querySelectorAll("#rankingFilter .ranking-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        currentRankFilter = btn.dataset.rank;
        document.querySelectorAll("#rankingFilter .ranking-filter-btn").forEach(b => b.classList.toggle("is-active", b === btn));
        if (globalData) renderRankings(globalData);
    });
});
document.querySelector(`#rankingFilter .ranking-filter-btn[data-rank="${currentRankFilter}"]`).classList.add("is-active");

// MATRIX: one evaluator x ratee grid per group, mirroring the paper-form
// layout lecturers already use — rows are who's being rated, columns are
// who's rating, a cell is the total that evaluator gave that person across
// all criteria. Built entirely client-side from data already fetched:
// `completion` gives the full roster per group plus who has/hasn't
// submitted at all; `individual_scores` gives the actual per-criterion
// scores for pairs that do have data.
function renderMatrix(completion, data) {
    const container = document.getElementById("matrixContainer");

    // Sum each (evaluator, ratee) pair's scores across every criterion into
    // one total, keyed by numeric student ids (not names) so this can't be
    // confused by two different students sharing a name.
    const totalsByPair = {};
    data.individual_scores.forEach(row => {
        const key = `${row.evaluator_id}-${row.ratee_id}`;
        totalsByPair[key] = (totalsByPair[key] || 0) + row.score;
    });

    // Flags by pair (outliers) and by evaluator (same-score patterns).
    const flaggedPairs = new Set(data.anomalies.filter(f => f.ratee_id != null).map(f => `${f.evaluator_id}-${f.ratee_id}`));
    const flaggedEvaluators = new Set(data.anomalies.filter(f => f.ratee_id == null).map(f => f.evaluator_id));

    const groupsWithMembers = completion.filter(g => g.students.length > 0);
    if (groupsWithMembers.length === 0) {
        container.innerHTML = `<div class="p-12 text-center border-2 border-dashed border-slate-100 rounded-3xl text-slate-400">No groups in this class yet.</div>`;
        return;
    }

    container.innerHTML = groupsWithMembers.map(group => {
        const students = group.students; // [{id, name, student_id, has_submitted}]

        const headerCells = students.map(e => `<th class="matrix-colhead">${esc(e.name)}${flaggedEvaluators.has(e.id) ? `<span class="matrix-flagmark" title="Flagged: same score pattern, see Flags tab">⚑</span>` : ""}</th>`).join("");

        const rows = students.map(ratee => {
            const cells = students.map(evaluator => {
                if (evaluator.id === ratee.id) {
                    // Diagonal = this student's automatic participation grade.
                    const part = data.participation[evaluator.id];
                    const label = { full: "Full attempt", partial: "Partial attempt", none: "No attempt", "n/a": "No one to rate" }[part?.status] ?? "";
                    const text = part && part.percent !== null ? `${part.percent}%` : "—";
                    const tip = part ? `${evaluator.name}: ${label} (${part.given} of ${part.expected} ratings)` : "Self";
                    return `<td class="matrix-cell matrix-cell--self" title="${esc(tip)}">${text}</td>`;
                }
                if (!evaluator.has_submitted) {
                    return `<td class="matrix-cell matrix-cell--missing" title="${esc(evaluator.name)} did not submit an evaluation">—</td>`;
                }
                const total = totalsByPair[`${evaluator.id}-${ratee.id}`];
                if (total === undefined) {
                    return `<td class="matrix-cell matrix-cell--missing" title="${esc(evaluator.name)} did not evaluate ${esc(ratee.name)}">—</td>`;
                }
                const flagged = flaggedPairs.has(`${evaluator.id}-${ratee.id}`);
                return `<td class="matrix-cell${flagged ? " matrix-cell--flag" : ""}"${flagged ? ` title="Flagged: see Flags tab"` : ""}>${total}</td>`;
            }).join("");
            return `<tr><th class="matrix-rowhead">${esc(ratee.name)}</th>${cells}</tr>`;
        }).join("");

        return `
            <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                <div class="p-4 border-b border-slate-100 bg-slate-50 font-bold text-slate-800">${esc(group.group_label)}</div>
                <div class="overflow-x-auto">
                    <table class="matrix-table w-full">
                        <thead><tr><th class="matrix-corner matrix-rowhead"></th>${headerCells}</tr></thead>
                        <tbody>${rows}</tbody>
                    </table>
                </div>
            </div>
        `;
    }).join("");
}

// THE DRILL-DOWN LOGIC
function openDrawer(studentName) {
    const drawer = document.getElementById("detailDrawer");
    const content = document.getElementById("drawerContent");
    document.getElementById("drawerTitle").textContent = `${studentName}'s Feedback`;

    // Filter raw individual scores from global data
    const feedbackReceived = globalData.individual_scores.filter(r => r.ratee_name === studentName);

    if (feedbackReceived.length === 0) {
        content.innerHTML = `<p class="text-slate-500">No individual scores recorded for this student yet.</p>`;
    } else {
        // Group by Evaluator
        const grouped = {};
        feedbackReceived.forEach(r => {
            if (!grouped[r.evaluator_name]) grouped[r.evaluator_name] = [];
            grouped[r.evaluator_name].push(r);
        });

        content.innerHTML = Object.entries(grouped).map(([evaluator, ratings]) => `
            <div class="mb-6 p-4 bg-slate-50 rounded-xl border border-slate-100">
                <div class="flex items-center gap-2 mb-3 text-slate-500">
                    <i data-lucide="user" class="w-4 h-4"></i>
                    <span class="text-sm font-bold uppercase tracking-tight">Evaluator: ${esc(evaluator)}</span>
                </div>
                <div class="grid grid-cols-2 gap-4">
                    ${ratings.map(r => `
                        <div class="bg-white p-3 rounded border border-slate-200">
                            <p class="text-[10px] uppercase text-slate-400 font-bold">${esc(r.criterion)}</p>
                            <p class="text-lg font-bold text-slate-800">${r.score}</p>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');
    }

    drawer.classList.remove("hidden");
    lucide.createIcons();
}

function closeDrawer() {
    document.getElementById("detailDrawer").classList.add("hidden");
}

document.getElementById("logoutBtn").addEventListener("click", async () => {
    try {
        await api("/auth/logout", { method: "POST" });
    } catch (err) {
        console.warn("Logout request failed, redirecting anyway:", err);
    }
    window.location.href = "login.html";
});

loadPage();