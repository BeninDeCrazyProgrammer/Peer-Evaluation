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
  systemKeyField.style.display = (isRegister || isReset) ? "block" : "none";
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
      if (!name || !email || !password || !systemKey) throw new Error("Fill in every field, including the system key.");
      await api("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password, system_key: systemKey }) });
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
      window.location.href = "dashboard.html";
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
      window.location.href = "dashboard.html";
    }
  } catch (err) {
    showError(errorBox, err);
  }
});
