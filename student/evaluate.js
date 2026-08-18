const courseId = qs("course");
const evalId = qs("evaluation");

let evaluationData = null;
let studentData = null;
let currentPeerIndex = 0; // The Wizard state
let responses = {}; // Storage for selections: { "peerId_criterionId": score }

if (!courseId || !evalId) {
    document.body.innerHTML = `<div class="p-12 text-center text-slate-500 font-bold">Invalid Evaluation Link.</div>`;
}

// Swaps a button's label for a loading state and disables it, so a slow
// connection or an impatient extra tap can't fire the same request twice —
// same double-submit guard used on the lecturer side for course creation.
// The original label is stashed on the element itself, not a shared
// variable, so several buttons can be mid-request independently.
function setBtnLoading(btn, loadingLabel) {
    if (btn.dataset.originalHtml === undefined) btn.dataset.originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = loadingLabel;
}
function resetBtnLoading(btn) {
    if (btn.dataset.originalHtml !== undefined) btn.innerHTML = btn.dataset.originalHtml;
    btn.disabled = false;
}

// Every PIN in this app is a 4-digit number (see backend/rate_limit.py and
// models.py) — filtering keystrokes down to digits as the student types
// catches a stray letter or symbol immediately instead of only after they
// hit Continue. The student ID / name field is deliberately left alone:
// a full name is a legitimate, supported way to log in (see
// Student.find_in_class), so it can't be restricted to digits-only.
function restrictToDigits(input) {
    input.addEventListener("input", () => {
        input.value = input.value.replace(/\D/g, "").slice(0, 4);
    });
}
["newPin", "confirmPin", "loginPin"].forEach(id => restrictToDigits(document.getElementById(id)));

async function init() {
    try {
        evaluationData = await api(`/courses/${courseId}/evaluations/${evalId}`);
    } catch (err) {
        document.getElementById("identifyCard").innerHTML =
            `<p class="p-4 text-center bg-red-50 text-red-600 rounded-xl font-bold">${err.message || "Peer evaluation has closed"}</p>`;
        return;
    }
    document.getElementById("evalTitleDisplay").textContent = evaluationData.title;

    if (evaluationData.status === "closed") {
        document.getElementById("identifyCard").innerHTML =
            `<p class="p-4 text-center bg-red-50 text-red-600 rounded-xl font-bold">Peer evaluation has closed</p>`;
    }
}

let studentPin = "";
let pendingIdentifier = "";

const identifyCard = document.getElementById("identifyCard");
const pinCard = document.getElementById("pinCard");
const pinCreateBlock = document.getElementById("pinCreateBlock");
const pinEnterBlock = document.getElementById("pinEnterBlock");
const identifyError = document.getElementById("identifyError");
const pinError = document.getElementById("pinError");

document.getElementById("findBtn").addEventListener("click", async () => {
    hideError(identifyError);
    const identifier = document.getElementById("identifier").value.trim();
    if (!identifier) return;

    const btn = document.getElementById("findBtn");
    setBtnLoading(btn, "Checking...");
    try {
        const result = await api(`/courses/${courseId}/evaluations/${evalId}/identify`, {
            method: "POST",
            body: JSON.stringify({ identifier }),
        });
        pendingIdentifier = identifier;
        showPinStep(result.name, result.has_pin);
    } catch (err) {
        showError(identifyError, err);
    } finally {
        resetBtnLoading(btn);
    }
});

function showPinStep(name, hasPin) {
    identifyCard.classList.add("hidden");
    pinCard.classList.remove("hidden");
    hideError(pinError);

    if (hasPin) {
        pinCreateBlock.classList.add("hidden");
        pinEnterBlock.classList.remove("hidden");
        document.getElementById("loginGreetName").textContent = name;
        document.getElementById("loginPin").value = "";
        document.getElementById("loginPin").focus();
    } else {
        pinEnterBlock.classList.add("hidden");
        pinCreateBlock.classList.remove("hidden");
        document.getElementById("createGreetName").textContent = name;
        document.getElementById("newPin").value = "";
        document.getElementById("confirmPin").value = "";
        document.getElementById("newPin").focus();
    }
    lucide.createIcons();
}

document.getElementById("pinBackBtn").addEventListener("click", () => {
    pinCard.classList.add("hidden");
    identifyCard.classList.remove("hidden");
    hideError(pinError);
});

document.getElementById("claimPinBtn").addEventListener("click", async () => {
    hideError(pinError);
    const pin = document.getElementById("newPin").value.trim();
    const confirmPin = document.getElementById("confirmPin").value.trim();
    if (!/^\d{4}$/.test(pin)) { showError(pinError, new Error("PIN must be exactly 4 digits.")); return; }
    if (!/^\d{4}$/.test(confirmPin)) { showError(pinError, new Error("Confirm PIN must be exactly 4 digits.")); return; }
    if (pin !== confirmPin) { showError(pinError, new Error("PINs don't match.")); return; }

    const btn = document.getElementById("claimPinBtn");
    setBtnLoading(btn, "Setting PIN...");
    try {
        studentData = await api(`/courses/${courseId}/evaluations/${evalId}/claim-pin`, {
            method: "POST",
            body: JSON.stringify({ identifier: pendingIdentifier, pin, confirm_pin: confirmPin }),
        });
        studentPin = pin;
        startWizard();
    } catch (err) {
        showError(pinError, err);
    } finally {
        resetBtnLoading(btn);
    }
});

document.getElementById("loginPinBtn").addEventListener("click", async () => {
    hideError(pinError);
    const pin = document.getElementById("loginPin").value.trim();
    if (!/^\d{4}$/.test(pin)) { showError(pinError, new Error("PIN must be exactly 4 digits.")); return; }

    const btn = document.getElementById("loginPinBtn");
    setBtnLoading(btn, "Checking...");
    try {
        studentData = await api(`/courses/${courseId}/evaluations/${evalId}/lookup`, {
            method: "POST",
            body: JSON.stringify({ identifier: pendingIdentifier, pin }),
        });
        studentPin = pin;
        startWizard();
    } catch (err) {
        showError(pinError, err);
    } finally {
        resetBtnLoading(btn);
    }
});

function startWizard() {
    identifyCard.classList.add("hidden");
    pinCard.classList.add("hidden");
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

    const btn = document.getElementById("submitBtn");
    setBtnLoading(btn, "Submitting...");
    try {
        await api(`/courses/${courseId}/evaluations/${evalId}/submit`, {
            method: "POST",
            body: JSON.stringify({
                evaluator_student_id: studentData.student.id,
                pin: studentPin,
                scores: formattedScores
            }),
        });
        document.getElementById("formCard").classList.add("hidden");
        document.getElementById("doneCard").classList.remove("hidden");
        lucide.createIcons();
        // No resetBtnLoading here — the card is gone on success, and leaving
        // the button disabled/labeled "Submitting..." is exactly right if
        // the person somehow flips back to this view.
    } catch (err) {
        showError(document.getElementById("submitError"), err);
        resetBtnLoading(btn);
    }
});

init();