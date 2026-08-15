let mode = "login"; // or "register"
const errorBox = document.getElementById("errorBox");
const nameField = document.getElementById("nameField");
const systemKeyField = document.getElementById("systemKeyField");
const formTitle = document.getElementById("formTitle");
const toggleMode = document.getElementById("toggleMode");
const submitBtn = document.getElementById("submitBtn");

toggleMode.addEventListener("click", () => {
  mode = mode === "login" ? "register" : "login";
  applyMode();
  hideError(errorBox);
});

function applyMode() {
  const isRegister = mode === "register";
  nameField.style.display = isRegister ? "block" : "none";
  systemKeyField.style.display = isRegister ? "block" : "none";
  formTitle.textContent = isRegister ? "Create account" : "Log in";
  toggleMode.textContent = isRegister ? "Already have an account?" : "Need an account?";
  submitBtn.textContent = isRegister ? "Create account" : "Log in";
}
applyMode();

submitBtn.addEventListener("click", async () => {
  hideError(errorBox);
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    if (mode === "register") {
      const name = document.getElementById("name").value.trim();
      const systemKey = document.getElementById("systemKey").value;
      if (!name || !email || !password || !systemKey) throw new Error("Fill in every field, including the system key.");
      await api("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password, system_key: systemKey }) });
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    } else {
      if (!email || !password) throw new Error("Fill in every field.");
      await api("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    }
    window.location.href = "dashboard.html";
  } catch (err) {
    showError(errorBox, err);
  }
});
