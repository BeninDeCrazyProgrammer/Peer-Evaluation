const courseId = qs("course");
if (!courseId) window.location.href = "dashboard.html";

const gotoSection = initSections();
let editingEvalId = null;

// Rating-scale presets. "custom" isn't filled by a click — it's what the
// dropdown falls back to display-wise once someone hand-edits a preset's rows.
const SCALE_PRESETS = {
    distinguished: [[3, "Distinguished"], [2, "Proficient"], [1, "Basic"], [0, "Unacceptable"]],
    satisfactory: [
        [4, "Excellent/Outstanding"], [3, "Above Satisfactory"], [2, "Satisfactory"],
        [1, "Below Satisfactory"], [0, "Unacceptable"],
    ],
    simple3: [[4, "Outstanding"], [2, "Fair"], [0, "Unacceptable"]],
};

// Default criteria match the group-work rubric (Frandsen 2004 / Parr 2003) —
// same set the lecturer's own printed rubric uses.
const DEFAULT_CRITERIA = [
    "Workload",
    "Getting Organized",
    "Participation in Discussions",
    "Meeting Deadlines",
    "Showing up for Meetings",
    "Providing Feedback",
    "Receiving Feedback",
];

// UI Helpers
const createRow = (type, value = "", label = "") => {
    const div = document.createElement("div");
    div.className = "flex items-center gap-2 group animate-slide-in";
    if (type === 'criterion') {
        div.innerHTML = `
            <input type="text" class="criterion-input flex-1 p-2 rounded-lg bg-slate-50 border border-slate-200 text-sm focus:border-orange-600 outline-none" value="${value}" placeholder="Criterion name">
            <button class="p-2 text-slate-300 hover:text-red-500 transition-colors remove-row"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
        `;
    } else {
        div.innerHTML = `
            <input type="text" class="scale-label !flex-1 min-w-0 p-2 rounded-lg bg-slate-50 border border-slate-200 text-sm focus:border-orange-600 outline-none" value="${label}" placeholder="Label">
            <input type="number" class="scale-value !w-16 shrink-0 p-2 rounded-lg bg-slate-50 border border-slate-200 text-sm focus:border-orange-600 outline-none" value="${value}" placeholder="0">
            <button class="p-2 text-slate-300 hover:text-red-500 transition-colors remove-row"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
        `;
    }
    if (type === "scale") {
        div.querySelector(".remove-row").addEventListener("click", () => {
            div.remove();
            markScaleAsCustom();
        });
        div.querySelector(".scale-value").addEventListener("input", markScaleAsCustom);
        div.querySelector(".scale-label").addEventListener("input", markScaleAsCustom);
    } else {
        div.querySelector(".remove-row").addEventListener("click", () => div.remove());
    }
    return div;
};

function applyScalePreset(name) {
    const rows = document.getElementById("scaleRows");
    rows.innerHTML = "";
    SCALE_PRESETS[name].forEach(([v, l]) => rows.appendChild(createRow("scale", v, l)));
    lucide.createIcons();
}

// If someone hand-edits a preset's rows (or adds/removes a point), the
// dropdown shouldn't keep claiming a preset that no longer matches — flip it
// to "Custom" so what's shown always matches what will actually be saved.
let suppressCustomFlag = false;
function markScaleAsCustom() {
    if (suppressCustomFlag) return;
    document.getElementById("scalePreset").value = "custom";
}

document.getElementById("scalePreset").addEventListener("change", (e) => {
    if (e.target.value === "custom") return; // nothing to fill, they're already editing freely
    applyScalePreset(e.target.value);
});

document.getElementById("addScalePoint").addEventListener("click", () => {
    document.getElementById("scaleRows").appendChild(createRow("scale"));
    document.getElementById("scalePreset").value = "custom";
    lucide.createIcons();
});

// Initial Load
async function loadCourseData() {
    const me = await api("/auth/me");
    if (!me.authenticated) { window.location.href = "login.html"; return; }

    const course = await api(`/courses/${courseId}`);
    document.getElementById("courseName").textContent = course.name;
    document.getElementById("courseCrumb").textContent = course.name;
    document.getElementById("courseEyebrow").textContent = `Course ID: ${course.id}`;

    resetForm();
    await loadClasses();
    loadEvaluations();
}

// Evaluation Logic
let loadedEvals = [];
const expandedEvalIds = new Set();
const evalDetailsCache = {};

function formatDeadline(iso) {
    if (!iso) return null;
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// <input type="datetime-local"> wants "YYYY-MM-DDTHH:MM" in LOCAL time, no
// offset — this converts a stored UTC ISO string to that shape for prefill.
function toDatetimeLocalValue(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const pad = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// The reverse: a datetime-local value is implicitly local time with no
// offset — new Date() parses it as such, and toISOString() gives back a
// proper UTC ISO string the backend can compare against datetime.now(utc).
function fromDatetimeLocalValue(value) {
    if (!value) return null;
    return new Date(value).toISOString();
}

async function loadEvaluations() {
    loadedEvals = await api(`/courses/${courseId}/evaluations`);
    const list = document.getElementById("evalsList");

    if (loadedEvals.length === 0) {
        list.innerHTML = `<div class="p-12 text-center border-2 border-dashed border-slate-100 rounded-3xl text-slate-400">No evaluations created yet.</div>`;
        return;
    }

    list.innerHTML = loadedEvals.map(ev => {
        const isOpen = ev.status === "open";
        const deadlineText = ev.deadline
            ? `${isOpen ? "Closes" : "Closed"} ${formatDeadline(ev.deadline)}`
            : null;
        return `
        <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div class="p-5 flex flex-wrap items-center justify-between gap-3 cursor-pointer hover:bg-slate-50/60 transition-colors" onclick="toggleEvalCard(${ev.id})">
                <div class="flex items-center gap-3 min-w-0">
                    <i data-lucide="chevron-right" class="w-4 h-4 text-slate-400 shrink-0 transition-transform" data-eval-chevron="${ev.id}" style="${expandedEvalIds.has(ev.id) ? 'transform:rotate(90deg)' : ''}"></i>
                    <div class="min-w-0">
                        <div class="flex items-center gap-2 flex-wrap">
                            <h4 class="font-bold text-slate-900 truncate">${ev.title}</h4>
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider shrink-0 ${isOpen ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}">
                                ${ev.status}
                            </span>
                            ${ev.class_name ? `<span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider shrink-0 bg-indigo-50 text-indigo-600">${ev.class_name}</span>` : ""}
                        </div>
                        <p class="text-xs text-slate-400">Created ${new Date(ev.created_at).toLocaleDateString()}${deadlineText ? ` · ${deadlineText}` : ""}</p>
                    </div>
                </div>
                <div class="flex gap-2 shrink-0" onclick="event.stopPropagation()">
                    <button onclick="openModal(${ev.id})" class="btn btn--ghost btn--sm"><i data-lucide="share-2" class="w-4 h-4"></i> Share</button>
                    <a href="results.html?course=${courseId}&evaluation=${ev.id}" class="btn btn--ghost btn--sm"><i data-lucide="pie-chart" class="w-4 h-4"></i> Results</a>
                    <button onclick="startEditing(${ev.id})" class="btn btn--ghost btn--sm"><i data-lucide="settings" class="w-4 h-4"></i> Settings</button>
                </div>
            </div>
            <div class="${expandedEvalIds.has(ev.id) ? '' : 'hidden'} border-t border-slate-100 p-5 bg-slate-50/50" data-eval-body="${ev.id}">
                <p class="text-xs text-slate-400">Loading...</p>
            </div>
        </div>
    `;
    }).join("");
    lucide.createIcons();

    // Re-render bodies for any cards that were already expanded before this reload.
    expandedEvalIds.forEach(id => { if (evalDetailsCache[id]) renderEvalCardBody(id); });
}

async function toggleEvalCard(id) {
    const body = document.querySelector(`[data-eval-body="${id}"]`);
    const chevron = document.querySelector(`[data-eval-chevron="${id}"]`);
    if (expandedEvalIds.has(id)) {
        expandedEvalIds.delete(id);
        body.classList.add("hidden");
        chevron.style.transform = "";
        return;
    }
    expandedEvalIds.add(id);
    body.classList.remove("hidden");
    chevron.style.transform = "rotate(90deg)";

    if (!evalDetailsCache[id]) {
        const full = await api(`/courses/${courseId}/evaluations/${id}`);
        evalDetailsCache[id] = full;
    }
    renderEvalCardBody(id);
}

function renderEvalCardBody(id) {
    const body = document.querySelector(`[data-eval-body="${id}"]`);
    if (!body) return;
    const full = evalDetailsCache[id];
    body.innerHTML = `
        <div class="grid sm:grid-cols-2 gap-6 mb-6">
            <div>
                <p class="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Assessment Criteria</p>
                <ul class="space-y-1">
                    ${full.criteria.map(c => `<li class="text-sm text-slate-700 bg-white border border-slate-200 rounded-lg px-3 py-1.5">${c.name}</li>`).join("")}
                </ul>
            </div>
            <div>
                <p class="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2">Rating Scale</p>
                <ul class="space-y-1">
                    ${full.scale.map(s => `<li class="text-sm text-slate-700 bg-white border border-slate-200 rounded-lg px-3 py-1.5 flex items-center justify-between"><span>${s.label}</span><span class="font-mono font-bold text-orange-600">${s.value}</span></li>`).join("")}
                </ul>
            </div>
        </div>
        <div class="border-t border-slate-200 pt-4 flex flex-wrap items-end gap-3">
            <div>
                <label class="block text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-1.5">Deadline</label>
                <input type="datetime-local" data-deadline-input="${id}" value="${toDatetimeLocalValue(full.deadline)}" class="p-2 rounded-lg bg-white border border-slate-200 text-sm outline-none focus:border-orange-600">
            </div>
            <button onclick="saveDeadline(${id})" class="btn btn--ghost btn--sm">Update Deadline</button>
            <span class="text-xs text-slate-400" data-deadline-status="${id}"></span>
        </div>
    `;
    lucide.createIcons();
}

async function saveDeadline(id) {
    const input = document.querySelector(`[data-deadline-input="${id}"]`);
    const deadline = fromDatetimeLocalValue(input.value);
    try {
        await api(`/courses/${courseId}/evaluations/${id}/deadline`, {
            method: "PATCH",
            body: JSON.stringify({ deadline }),
        });
        delete evalDetailsCache[id]; // stale — force a re-fetch below
        await loadEvaluations(); // re-renders the list (updated badge/deadline text); this
                                  // card stays expanded since its id is still in expandedEvalIds
        const full = await api(`/courses/${courseId}/evaluations/${id}`);
        evalDetailsCache[id] = full;
        renderEvalCardBody(id);
    } catch (err) {
        const statusEl = document.querySelector(`[data-deadline-status="${id}"]`);
        if (statusEl) statusEl.textContent = err.message || "Couldn't update deadline.";
    }
}

function resetForm() {
    editingEvalId = null;
    document.getElementById("evalFormTitle").textContent = "New Evaluation";
    document.getElementById("cancelEditBtn").classList.add("hidden");
    document.getElementById("createEvalBtn").textContent = "Create Evaluation";
    document.getElementById("evalTitle").value = "";
    document.getElementById("evalDeadline").value = "";
    document.getElementById("criteriaRows").innerHTML = "";

    const classSelect = document.getElementById("evalClass");
    classSelect.disabled = false;
    document.getElementById("evalClassHint").textContent = "Which class's roster this evaluation runs against. Can't be changed after creation.";

    DEFAULT_CRITERIA.forEach(c =>
        document.getElementById("criteriaRows").appendChild(createRow('criterion', c)));

    document.getElementById("scalePreset").value = "distinguished";
    applyScalePreset("distinguished");
    lucide.createIcons();
}

// Does this saved scale exactly match one of the presets? Used so the
// dropdown reflects reality when editing an existing evaluation, instead of
// always defaulting to "Custom".
function detectScalePreset(scale) {
    for (const [name, points] of Object.entries(SCALE_PRESETS)) {
        if (points.length === scale.length &&
            points.every(([v, l], i) => v === scale[i].value && l === scale[i].label)) {
            return name;
        }
    }
    return "custom";
}

async function startEditing(id) {
    const ev = await api(`/courses/${courseId}/evaluations/${id}`);
    editingEvalId = id;
    document.getElementById("evalFormTitle").textContent = `Edit: ${ev.title}`;
    document.getElementById("createEvalBtn").textContent = "Save Changes";
    document.getElementById("cancelEditBtn").classList.remove("hidden");
    document.getElementById("evalTitle").value = ev.title;
    document.getElementById("evalDeadline").value = toDatetimeLocalValue(ev.deadline);

    // Class is fixed at creation — show which one this evaluation belongs
    // to, but don't let it be changed here (the backend doesn't allow it).
    const classSelect = document.getElementById("evalClass");
    if (![...classSelect.options].some(o => o.value === String(ev.class_id))) {
        classSelect.innerHTML = loadedClasses.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
    }
    classSelect.value = ev.class_id;
    classSelect.disabled = true;
    document.getElementById("evalClassHint").textContent = "Class can't be changed after an evaluation is created.";

    document.getElementById("criteriaRows").innerHTML = "";
    document.getElementById("scaleRows").innerHTML = "";
    ev.criteria.forEach(c => document.getElementById("criteriaRows").appendChild(createRow('criterion', c.name)));

    suppressCustomFlag = true; // populating from saved data isn't a "hand edit"
    ev.scale.forEach(s => document.getElementById("scaleRows").appendChild(createRow('scale', s.value, s.label)));
    suppressCustomFlag = false;
    document.getElementById("scalePreset").value = detectScalePreset(ev.scale);

    gotoSection("builder");
    lucide.createIcons();
}

// Classes Logic
let loadedClasses = [];
const expandedClassIds = new Set();
const classRosterCache = {};

function renderEvalClassSelect() {
    const select = document.getElementById("evalClass");
    const hint = document.getElementById("evalClassHint");
    if (loadedClasses.length === 0) {
        select.innerHTML = `<option value="">No classes yet</option>`;
        hint.textContent = "Create a class under the Classes tab first — an evaluation always runs against one class's roster.";
        return;
    }
    select.innerHTML = loadedClasses.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
}

async function loadClasses() {
    loadedClasses = await api(`/courses/${courseId}/classes`);
    renderClassesList();
    renderEvalClassSelect();
}

function renderClassesList() {
    const list = document.getElementById("classesList");
    if (loadedClasses.length === 0) {
        list.innerHTML = `<div class="p-12 text-center border-2 border-dashed border-slate-100 rounded-3xl text-slate-400">No classes yet — create one above (e.g. "2026 Level 300") to start uploading a roster.</div>`;
        return;
    }
    list.innerHTML = loadedClasses.map(cls => `
        <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden" data-class-card="${cls.id}">
            <div class="p-5 flex flex-wrap items-center justify-between gap-3 cursor-pointer hover:bg-slate-50/60 transition-colors" onclick="toggleClassCard(${cls.id})">
                <div class="flex items-center gap-3 min-w-0">
                    <i data-lucide="chevron-right" class="w-4 h-4 text-slate-400 shrink-0 transition-transform" data-class-chevron="${cls.id}" style="${expandedClassIds.has(cls.id) ? 'transform:rotate(90deg)' : ''}"></i>
                    <div class="min-w-0">
                        <h4 class="font-bold text-slate-900 truncate">${cls.name}</h4>
                        <p class="text-xs text-slate-400">Created ${new Date(cls.created_at).toLocaleDateString()}</p>
                    </div>
                </div>
                <div class="flex gap-2 shrink-0" onclick="event.stopPropagation()">
                    <button onclick="deleteClass(${cls.id}, '${cls.name.replace(/'/g, "\\'")}')" class="btn btn--ghost btn--sm"><i data-lucide="trash-2" class="w-4 h-4"></i> Delete</button>
                </div>
            </div>
            <div class="${expandedClassIds.has(cls.id) ? '' : 'hidden'} border-t border-slate-100 p-5 bg-slate-50/50 space-y-6" data-class-body="${cls.id}">
                ${classBodyHtml(cls.id)}
            </div>
        </div>
    `).join("");
    lucide.createIcons();

    // Re-render rosters for any cards that were already expanded before this reload.
    expandedClassIds.forEach(id => loadClassRoster(id));
}

function classBodyHtml(classId) {
    return `
        <div class="bg-white rounded-2xl border border-slate-200 p-5">
            <h5 class="font-bold text-slate-800 text-sm mb-2">Import Student Groups</h5>
            <p class="text-xs text-slate-500 mb-4">Upload an Excel sheet with columns for <code class="bg-slate-100 px-1 rounded text-orange-600 font-bold">Group</code>, <code class="bg-slate-100 px-1 rounded text-orange-600 font-bold">Name</code>, and <code class="bg-slate-100 px-1 rounded text-orange-600 font-bold">ID</code>. Re-uploading replaces this class's roster only — other classes are untouched.</p>
            <div class="flex items-center justify-center w-full">
                <label class="flex flex-col items-center justify-center w-full h-24 border-2 border-slate-200 border-dashed rounded-2xl cursor-pointer bg-slate-50 hover:bg-slate-100 transition-all">
                    <div class="flex flex-col items-center justify-center pt-3 pb-4">
                        <i data-lucide="upload-cloud" class="w-6 h-6 text-slate-400 mb-1"></i>
                        <p class="text-xs text-slate-500 font-medium" data-class-filename="${classId}">Select Excel File (.xlsx, .xls)</p>
                    </div>
                    <input type="file" class="hidden class-file-input" data-class-id="${classId}" accept=".xlsx,.xls" />
                </label>
            </div>
            <div class="flex items-center justify-between mt-4">
                <div class="text-red-500 text-xs font-medium hidden" data-class-upload-error="${classId}"></div>
                <button class="btn btn--clay btn--sm class-upload-btn" data-class-id="${classId}">Sync Group List</button>
            </div>
        </div>
        <div>
            <h5 class="font-bold text-slate-800 text-sm mb-1">Current Roster</h5>
            <p class="text-xs text-slate-400 mb-3">Students set their own PIN the first time they open the evaluation link — you never see or share it. If someone forgets theirs (or the wrong person claimed a name/ID), use <span class="font-bold text-slate-500">Reset</span> to let them set a new one.</p>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" data-class-roster="${classId}">
                <p class="text-xs text-slate-400">Loading...</p>
            </div>
        </div>
    `;
}

function toggleClassCard(id) {
    const body = document.querySelector(`[data-class-body="${id}"]`);
    const chevron = document.querySelector(`[data-class-chevron="${id}"]`);
    if (expandedClassIds.has(id)) {
        expandedClassIds.delete(id);
        body.classList.add("hidden");
        chevron.style.transform = "";
        return;
    }
    expandedClassIds.add(id);
    body.classList.remove("hidden");
    chevron.style.transform = "rotate(90deg)";
    loadClassRoster(id);
}

async function loadClassRoster(classId) {
    const groups = await api(`/courses/${courseId}/classes/${classId}/groups`);
    classRosterCache[classId] = groups;
    const container = document.querySelector(`[data-class-roster="${classId}"]`);
    if (!container) return;
    if (groups.length === 0) {
        container.innerHTML = `<p class="text-xs text-slate-400">No roster uploaded yet.</p>`;
        return;
    }
    container.innerHTML = groups.map(g => `
        <div class="p-4 bg-slate-50 rounded-2xl border border-slate-100">
            <h5 class="font-bold text-slate-800 text-sm mb-2">${g.group_label}</h5>
            <div class="space-y-1">
                ${g.students.map(s => `
                    <div class="flex items-center justify-between text-xs bg-white border border-slate-200 rounded-lg px-2 py-1.5 gap-2">
                        <span class="text-slate-700 font-medium truncate">${s.name}</span>
                        <span class="flex items-center gap-2 shrink-0">
                            ${s.pin_set
                                ? `<span class="text-[10px] font-bold text-green-700 bg-green-50 px-2 py-0.5 rounded-full">PIN set</span>
                                   <button onclick="resetStudentPin(${classId}, ${s.id}, '${s.name.replace(/'/g, "\\'")}')" class="text-[10px] font-bold text-slate-400 hover:text-red-600 uppercase">Reset</button>`
                                : `<span class="text-[10px] font-bold text-slate-400 bg-slate-100 px-2 py-0.5 rounded-full">Not set yet</span>`}
                        </span>
                    </div>
                `).join("")}
            </div>
        </div>
    `).join("");
}

// Students create their own PIN the first time they open the evaluation
// link — the lecturer never sees or distributes it. The only lecturer-side
// lever is resetting it (forgotten PIN, or the wrong person claimed it).
async function resetStudentPin(classId, studentId, name) {
    if (!confirm(`Reset the PIN for ${name}? They'll be asked to set a new one next time they open the evaluation link.`)) return;
    try {
        await api(`/courses/${courseId}/classes/${classId}/groups/students/${studentId}/reset-pin`, { method: "POST" });
        loadClassRoster(classId);
    } catch (err) {
        alert(err.message || "Couldn't reset PIN.");
    }
}

async function deleteClass(classId, name) {
    if (!confirm(`Delete "${name}"? This permanently removes its roster (groups and students) and every evaluation created for it, along with all their submissions. This can't be undone.`)) return;
    try {
        await api(`/courses/${courseId}/classes/${classId}`, { method: "DELETE" });
        expandedClassIds.delete(classId);
        delete classRosterCache[classId];
        await loadClasses();
        loadEvaluations(); // that class's evaluations are gone too
    } catch (err) {
        alert(err.message || "Couldn't delete class.");
    }
}

document.getElementById("createClassBtn").addEventListener("click", async () => {
    const input = document.getElementById("newClassName");
    const name = input.value.trim();
    const errorBox = document.getElementById("createClassError");
    hideError(errorBox);
    if (!name) { showError(errorBox, new Error("Class name is required.")); return; }
    try {
        await api(`/courses/${courseId}/classes`, { method: "POST", body: JSON.stringify({ name }) });
        input.value = "";
        await loadClasses();
    } catch (err) {
        showError(errorBox, err);
    }
});

// Event delegation for per-class upload controls — these are rendered
// dynamically (one set per class card), so a single document-level listener
// keyed off data-class-id handles all of them instead of re-binding after
// every render.
document.addEventListener("change", (e) => {
    if (!e.target.classList.contains("class-file-input")) return;
    const classId = e.target.dataset.classId;
    const name = e.target.files[0]?.name || "Select Excel File (.xlsx, .xls)";
    const label = document.querySelector(`[data-class-filename="${classId}"]`);
    if (label) label.textContent = name;
});

document.addEventListener("click", async (e) => {
    const btn = e.target.closest(".class-upload-btn");
    if (!btn) return;
    const classId = btn.dataset.classId;
    const fileInput = document.querySelector(`.class-file-input[data-class-id="${classId}"]`);
    const errorBox = document.querySelector(`[data-class-upload-error="${classId}"]`);
    hideError(errorBox);
    if (!fileInput.files[0]) { showError(errorBox, new Error("Choose a file first.")); return; }
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    try {
        await api(`/courses/${courseId}/classes/${classId}/groups/upload`, { method: "POST", body: form });
        loadClassRoster(classId);
        alert("Groups updated successfully!");
    } catch (err) {
        showError(errorBox, err);
    }
});

// Create/Update Evaluation
document.getElementById("createEvalBtn").addEventListener("click", async () => {
    const classId = document.getElementById("evalClass").value;
    const title = document.getElementById("evalTitle").value.trim();
    const deadline = fromDatetimeLocalValue(document.getElementById("evalDeadline").value);
    const criteria = [...document.querySelectorAll(".criterion-input")]
        .map(i => i.value.trim())
        .filter(Boolean);
    const scale = [...document.querySelectorAll("#scaleRows .flex")]
        .map(row => ({
            value: parseInt(row.querySelector(".scale-value").value, 10),
            label: row.querySelector(".scale-label").value.trim(),
        }))
        .filter(s => s.label && !Number.isNaN(s.value));

    const errorBox = document.getElementById("evalError");
    hideError(errorBox);
    const editedId = editingEvalId;
    if (!editedId && !classId) { showError(errorBox, new Error("Select a class for this evaluation — create one under the Classes tab if there isn't one yet.")); return; }
    if (!title) { showError(errorBox, new Error("Title is required.")); return; }
    if (criteria.length < 1) { showError(errorBox, new Error("Add at least one criterion.")); return; }
    if (scale.length < 2) { showError(errorBox, new Error("The scale needs at least 2 points with a value and a label.")); return; }

    // class_id is fixed at creation and immutable afterward (the select is
    // disabled while editing — see startEditing), so it's only sent on create.
    const payload = editedId ? { title, criteria, scale, deadline } : { class_id: classId, title, criteria, scale, deadline };

    try {
        const method = editedId ? "PATCH" : "POST";
        const path = editedId ? `/courses/${courseId}/evaluations/${editedId}` : `/courses/${courseId}/evaluations`;
        await api(path, { method, body: JSON.stringify(payload) });
        if (editedId) delete evalDetailsCache[editedId]; // stale — card will re-fetch if expanded again
        resetForm();
        gotoSection("evaluations");
        loadEvaluations();
    } catch (err) {
        showError(errorBox, err);
    }
});

// Modal Helpers
async function openModal(id) {
    const data = await api(`/courses/${courseId}/evaluations/${id}/link`);
    document.getElementById("shareLink").textContent = data.link;
    document.getElementById("qrImage").src = `data:image/png;base64,${data.qr_code_png_base64}`;
    document.getElementById("linkModal").classList.remove("hidden");
    document.getElementById("linkModal").classList.add("flex");
}

function closeModal() {
    document.getElementById("linkModal").classList.add("hidden");
}

function copyLink() {
    navigator.clipboard.writeText(document.getElementById("shareLink").textContent);
    alert("Link copied!");
}

// Final Wiring
document.getElementById("addCriterion").addEventListener("click", () => {
    document.getElementById("criteriaRows").appendChild(createRow('criterion'));
    lucide.createIcons();
});

document.getElementById("cancelEditBtn").addEventListener("click", () => {
    resetForm();
    gotoSection("evaluations");
});

document.getElementById("newEvalBtn").addEventListener("click", () => {
    resetForm();
    gotoSection("builder");
});

document.getElementById("backToEvalsBtn").addEventListener("click", () => {
    resetForm();
    gotoSection("evaluations");
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
    try {
        await api("/auth/logout", { method: "POST" });
    } catch (err) {
        console.warn("Logout request failed, redirecting anyway:", err);
    }
    window.location.href = "login.html";
});

loadCourseData();