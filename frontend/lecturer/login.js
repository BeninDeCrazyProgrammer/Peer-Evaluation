let mode = "login"; // "login" | "register" | "reset"
const errorBox = document.getElementById("errorBox");
const successBox = document.getElementById("successBox");
const nameField = document.getElementById("nameField");
const systemKeyField = document.getElementById("systemKeyField");
const confirmPasswordField = document.getElementById("confirmPasswordField");
const forgotPasswordRow = document.getElementById("forgotPasswordRow");
const passwordLabel = document.getElementById("passwordLabel");
const formTitle = document.getElementById("formTitle");
const toggleMode = document.getElementById("toggleMode");
const submitBtn = document.getElementById("submitBtn");
const backToLoginBtn = document.getElementById("backToLoginBtn");
const forgotPasswordLink = document.getElementById("forgotPasswordLink");

// Invite link (?invite=TOKEN): a course owner invited this email as a TA. After
// logging in or registering, the invite is accepted and they land on the course.
const inviteToken = qs("invite");
let inviteEmail = null;

async function goAfterAuth() {
  if (inviteToken) {
    const res = await api("/invites/accept", { method: "POST", body: JSON.stringify({ token: inviteToken }) });
    window.location.href = `course.html?course=${res.course_id}`;
  } else {
    window.location.href = "dashboard.html";
  }
}

async function initInvite() {
  if (!inviteToken) return;
  const banner = document.getElementById("inviteBanner");
  try {
    const info = await api(`/invites/preview?token=${encodeURIComponent(inviteToken)}`);
    inviteEmail = info.email;
    banner.textContent = `${info.invited_by || "A lecturer"} invited ${info.email} to help with "${info.course_name}". Log in, or create an account with that email, to accept.`;
    banner.style.display = "block";
    document.getElementById("email").value = info.email;
    document.getElementById("email").readOnly = true;
    applyMode();
    // Already signed in? Accept straight away.
    const me = await api("/auth/me");
    if (me.authenticated) {
      try { await goAfterAuth(); }
      catch (err) { showError(errorBox, err); }
    }
  } catch (err) {
    showError(errorBox, err);
  }
}

function hideSuccess() {
  successBox.style.display = "none";
  successBox.textContent = "";
}
function showSuccess(message) {
  successBox.textContent = message;
  successBox.style.display = "block";
}

toggleMode.addEventListener("click", () => {
  mode = mode === "login" ? "register" : "login";
  applyMode();
  hideError(errorBox);
  hideSuccess();
});

forgotPasswordLink.addEventListener("click", () => {
  mode = "reset";
  applyMode();
  hideError(errorBox);
  hideSuccess();
});

backToLoginBtn.addEventListener("click", () => {
  mode = "login";
  applyMode();
  hideError(errorBox);
  hideSuccess();
});

function applyMode() {
  const isRegister = mode === "register";
  const isReset = mode === "reset";

  nameField.style.display = isRegister ? "block" : "none";
  // An invite replaces the department system key when registering.
  systemKeyField.style.display = ((isRegister && !inviteToken) || isReset) ? "block" : "none";
  confirmPasswordField.style.display = isReset ? "block" : "none";
  forgotPasswordRow.style.display = mode === "login" ? "flex" : "none";

  passwordLabel.textContent = isReset ? "New password" : "Password";
  document.getElementById("password").value = "";
  document.getElementById("confirmPassword").value = "";

  toggleMode.style.display = isReset ? "none" : "inline-flex";
  toggleMode.textContent = isRegister ? "Already have an account?" : "Need an account?";
  backToLoginBtn.style.display = isReset ? "inline-flex" : "none";

  formTitle.textContent = isRegister ? "Create account" : isReset ? "Reset password" : "Log in";
  submitBtn.textContent = isRegister ? "Create account" : isReset ? "Reset password" : "Log in";
}
applyMode();

// Every masked input on this page (login/new password, confirm password,
// system key) gets the same toggle — wired once by data-target rather than
// one listener per field, since the same markup pattern repeats three times.
document.querySelectorAll(".show-password-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    const input = document.getElementById(btn.dataset.target);
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    btn.textContent = showing ? "Show" : "Hide";
  });
});

submitBtn.addEventListener("click", async () => {
  hideError(errorBox);
  hideSuccess();
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    if (mode === "register") {
      const name = document.getElementById("name").value.trim();
      const systemKey = document.getElementById("systemKey").value;
      if (!name || !email || !password || (!systemKey && !inviteToken)) throw new Error("Fill in every field, including the system key.");
      await api("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password, system_key: systemKey, invite_token: inviteToken }) });
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      await goAfterAuth();
    } else if (mode === "reset") {
      const systemKey = document.getElementById("systemKey").value;
      const confirmPassword = document.getElementById("confirmPassword").value;
      if (!email || !systemKey || !password || !confirmPassword) throw new Error("Fill in every field, including the system key.");
      if (password !== confirmPassword) throw new Error("Passwords don't match.");
      await api("/auth/reset-password", { method: "POST", body: JSON.stringify({ email, system_key: systemKey, new_password: password }) });
      mode = "login";
      applyMode();
      document.getElementById("email").value = email;
      showSuccess("Password updated — you can now log in with your new password.");
    } else {
      if (!email || !password) throw new Error("Fill in every field.");
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      await goAfterAuth();
    }
  } catch (err) {
    showError(errorBox, err);
  }
});

initInvite();
