const courseId = qs("course");
const evalId = qs("evaluation");

let evaluationData = null;
let studentData = null;
let currentPeerIndex = 0; // The Wizard state
let responses = {}; // Storage for selections: { "peerId_criterionId": score }

if (!courseId || !evalId) {
    document.body.innerHTML = `<div class="p-12 text-center text-slate-500 font-bold">Invalid Evaluation Link.</div>`;
}

async function init() {
    evaluationData = await api(`/courses/${courseId}/evaluations/${evalId}`);
    document.getElementById("evalTitleDisplay").textContent = evaluationData.title;
    
    if (evaluationData.status === "closed") {
        document.getElementById("identifyCard").innerHTML = `<p class="p-4 text-center bg-red-50 text-red-600 rounded-xl font-bold">This evaluation is now closed.</p>`;
    }
}

document.getElementById("findBtn").addEventListener("click", async () => {
    const identifier = document.getElementById("identifier").value.trim();
    if (!identifier) return;

    try {
        studentData = await api(`/courses/${courseId}/evaluations/${evalId}/lookup`, {
            method: "POST",
            body: JSON.stringify({ identifier }),
        });
        startWizard();
    } catch (err) {
        showError(document.getElementById("identifyError"), err);
    }
});

function startWizard() {
    document.getElementById("identifyCard").classList.add("hidden");
    document.getElementById("formCard").classList.remove("hidden");
    renderCurrentStep();
}

function renderCurrentStep() {
    const peer = studentData.peers_to_evaluate[currentPeerIndex];
    const totalPeers = studentData.peers_to_evaluate.length;

    // Update Header
    document.getElementById("currentPeerName").textContent = `Rating ${peer.name}`;
    document.getElementById("progressText").textContent = `Peer ${currentPeerIndex + 1} of ${totalPeers}`;
    
    // Update Step Indicators
    const indicators = document.getElementById("stepIndicators");
    indicators.innerHTML = studentData.peers_to_evaluate.map((_, i) => `
        <div class="step-indicator ${i === currentPeerIndex ? 'is-active' : (i < currentPeerIndex ? 'is-complete' : '')}"></div>
    `).join('');

    // Render Criteria
    const container = document.getElementById("criteriaContainer");
    container.innerHTML = evaluationData.criteria.map(c => `
        <div class="criterion-row">
            <label class="block text-sm font-bold text-slate-700 mb-3">${c.name}</label>
            <div class="flex gap-2 flex-wrap">
                ${evaluationData.scale.map(s => {
                    const key = `${peer.id}_${c.id}`;
                    const isActive = responses[key] === s.value;
                    return `
                        <button onclick="selectScore(${peer.id}, ${c.id}, ${s.value})" 
                                class="rating-pill ${isActive ? 'is-active' : ''}">
                            ${s.label}<br><span class="text-xs opacity-60">Score: ${s.value}</span>
                        </button>
                    `;
                }).join('')}
            </div>
        </div>
    `).join('');

    // Navigation Buttons
    document.getElementById("prevBtn").classList.toggle("hidden", currentPeerIndex === 0);
    
    const isLastPeer = currentPeerIndex === totalPeers - 1;
    document.getElementById("nextBtn").classList.toggle("hidden", isLastPeer);
    document.getElementById("submitBtn").classList.toggle("hidden", !isLastPeer);

    checkValidation();
    lucide.createIcons();
}

function selectScore(peerId, criterionId, value) {
    const key = `${peerId}_${criterionId}`;
    responses[key] = value;
    renderCurrentStep(); // Refresh UI to show active state
}

function checkValidation() {
    const peer = studentData.peers_to_evaluate[currentPeerIndex];
    const peerCriteria = evaluationData.criteria.map(c => `${peer.id}_${c.id}`);
    const allFilled = peerCriteria.every(key => responses.hasOwnProperty(key));
    
    document.getElementById("nextBtn").disabled = !allFilled;
    document.getElementById("submitBtn").disabled = !allFilled;
}

document.getElementById("nextBtn").addEventListener("click", () => {
    currentPeerIndex++;
    renderCurrentStep();
});

document.getElementById("prevBtn").addEventListener("click", () => {
    currentPeerIndex--;
    renderCurrentStep();
});

document.getElementById("submitBtn").addEventListener("click", async () => {
    const formattedScores = Object.entries(responses).map(([key, score]) => {
        const [ratee_student_id, criterion_id] = key.split("_");
        return {
            ratee_student_id: parseInt(ratee_student_id),
            criterion_id: parseInt(criterion_id),
            score: score
        };
    });

    try {
        await api(`/courses/${courseId}/evaluations/${evalId}/submit`, {
            method: "POST",
            body: JSON.stringify({
                evaluator_student_id: studentData.student.id,
                scores: formattedScores
            }),
        });
        document.getElementById("formCard").classList.add("hidden");
        document.getElementById("doneCard").classList.remove("hidden");
        lucide.createIcons();
    } catch (err) {
        showError(document.getElementById("submitError"), err);
    }
});

init();