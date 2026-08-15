const courseId = qs("course");
if (!courseId) window.location.href = "dashboard.html";

const gotoSection = initSections();
let editingEvalId = null;

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
            <input type="number" class="scale-value w-16 p-2 rounded-lg bg-slate-50 border border-slate-200 text-sm focus:border-orange-600 outline-none" value="${value}" placeholder="0">
            <input type="text" class="scale-label flex-1 p-2 rounded-lg bg-slate-50 border border-slate-200 text-sm focus:border-orange-600 outline-none" value="${label}" placeholder="Label">
            <button class="p-2 text-slate-300 hover:text-red-500 transition-colors remove-row"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
        `;
    }
    div.querySelector(".remove-row").addEventListener("click", () => div.remove());
    return div;
};

// Initial Load
async function loadCourseData() {
    const me = await api("/auth/me");
    if (!me.authenticated) { window.location.href = "login.html"; return; }

    const course = await api(`/courses/${courseId}`);
    document.getElementById("courseName").textContent = course.name;
    document.getElementById("courseCrumb").textContent = course.name;
    document.getElementById("courseEyebrow").textContent = `Course ID: ${course.id}`;
    
    resetForm();
    loadGroups();
    loadEvaluations();
}

// Evaluation Logic
async function loadEvaluations() {
    const evals = await api(`/courses/${courseId}/evaluations`);
    const list = document.getElementById("evalsList");
    
    if (evals.length === 0) {
        list.innerHTML = `<div class="col-span-full p-12 text-center border-2 border-dashed border-slate-100 rounded-3xl text-slate-400">No evaluations created yet.</div>`;
        return;
    }

    list.innerHTML = evals.map(ev => `
        <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm hover:shadow-md transition-all flex justify-between items-center group">
            <div>
                <div class="flex items-center gap-2 mb-1">
                    <h4 class="font-bold text-slate-900">${ev.title}</h4>
                    <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${ev.status === 'open' ? 'bg-green-100 text-green-700' : 'bg-slate-100 text-slate-500'}">
                        ${ev.status}
                    </span>
                </div>
                <p class="text-xs text-slate-400">Created on ${new Date(ev.created_at).toLocaleDateString()}</p>
            </div>
            <div class="flex gap-2">
                <button onclick="openModal(${ev.id})" class="p-2 bg-slate-50 text-slate-600 rounded-xl hover:bg-orange-50 hover:text-orange-600 transition-all" title="Share"><i data-lucide="share-2" class="w-4 h-4"></i></button>
                <a href="results.html?course=${courseId}&evaluation=${ev.id}" class="p-2 bg-slate-50 text-slate-600 rounded-xl hover:bg-orange-50 hover:text-orange-600 transition-all" title="Results"><i data-lucide="pie-chart" class="w-4 h-4"></i></a>
                <button onclick="startEditing(${ev.id})" class="p-2 bg-slate-50 text-slate-600 rounded-xl hover:bg-orange-50 hover:text-orange-600 transition-all" title="Edit"><i data-lucide="settings" class="w-4 h-4"></i></button>
            </div>
        </div>
    `).join("");
    lucide.createIcons();
}

function resetForm() {
    editingEvalId = null;
    document.getElementById("evalFormTitle").textContent = "New Evaluation";
    document.getElementById("cancelEditBtn").classList.add("hidden");
    document.getElementById("createEvalBtn").textContent = "Create Evaluation";
    document.getElementById("evalTitle").value = "";
    document.getElementById("criteriaRows").innerHTML = "";
    document.getElementById("scaleRows").innerHTML = "";
    
    ["Participation", "Quality of Work", "Communication"].forEach(c => 
        document.getElementById("criteriaRows").appendChild(createRow('criterion', c)));
    [[0, "Unacceptable"], [2, "Fair"], [4, "Outstanding"]].forEach(([v, l]) => 
        document.getElementById("scaleRows").appendChild(createRow('scale', v, l)));
    lucide.createIcons();
}

async function startEditing(id) {
    const ev = await api(`/courses/${courseId}/evaluations/${id}`);
    editingEvalId = id;
    document.getElementById("evalFormTitle").textContent = `Edit: ${ev.title}`;
    document.getElementById("createEvalBtn").textContent = "Save Changes";
    document.getElementById("cancelEditBtn").classList.remove("hidden");
    document.getElementById("evalTitle").value = ev.title;
    
    document.getElementById("criteriaRows").innerHTML = "";
    document.getElementById("scaleRows").innerHTML = "";
    ev.criteria.forEach(c => document.getElementById("criteriaRows").appendChild(createRow('criterion', c.name)));
    ev.scale.forEach(s => document.getElementById("scaleRows").appendChild(createRow('scale', s.value, s.label)));
    
    document.getElementById("evalBuilder").scrollIntoView({ behavior: 'smooth' });
    lucide.createIcons();
}

// Groups Logic
async function loadGroups() {
    const groups = await api(`/courses/${courseId}/groups`);
    const list = document.getElementById("groupsList");
    list.innerHTML = groups.map(g => `
        <div class="p-4 bg-slate-50 rounded-2xl border border-slate-100">
            <h5 class="font-bold text-slate-800 text-sm mb-2">${g.group_label}</h5>
            <div class="flex flex-wrap gap-1">
                ${g.students.map(s => `<span class="text-[10px] bg-white border border-slate-200 px-2 py-0.5 rounded-full text-slate-600">${s.name}</span>`).join("")}
            </div>
        </div>
    `).join("");
}

// File Upload Handler
document.getElementById("groupsFile").addEventListener("change", (e) => {
    const name = e.target.files[0]?.name || "Select Excel File (.xlsx, .xls)";
    document.getElementById("fileNameDisplay").textContent = name;
});

document.getElementById("uploadBtn").addEventListener("click", async () => {
    const fileInput = document.getElementById("groupsFile");
    if (!fileInput.files[0]) return;
    const form = new FormData();
    form.append("file", fileInput.files[0]);
    try {
        await api(`/courses/${courseId}/groups/upload`, { method: "POST", body: form });
        loadGroups();
        alert("Groups updated successfully!");
    } catch (err) {
        showError(document.getElementById("uploadError"), err);
    }
});

// Create/Update Evaluation
document.getElementById("createEvalBtn").addEventListener("click", async () => {
    const payload = {
        title: document.getElementById("evalTitle").value.trim(),
        criteria: [...document.querySelectorAll(".criterion-input")].map(i => i.value.trim()),
        scale: [...document.querySelectorAll("#scaleRows .flex")].map(row => ({
            value: parseInt(row.querySelector(".scale-value").value),
            label: row.querySelector(".scale-label").value.trim()
        }))
    };

    try {
        const method = editingEvalId ? "PATCH" : "POST";
        const path = editingEvalId ? `/courses/${courseId}/evaluations/${editingEvalId}` : `/courses/${courseId}/evaluations`;
        await api(path, { method, body: JSON.stringify(payload) });
        resetForm();
        loadEvaluations();
    } catch (err) {
        showError(document.getElementById("evalError"), err);
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

document.getElementById("addScalePoint").addEventListener("click", () => {
    document.getElementById("scaleRows").appendChild(createRow('scale'));
    lucide.createIcons();
});

document.getElementById("cancelEditBtn").addEventListener("click", resetForm);

loadCourseData();