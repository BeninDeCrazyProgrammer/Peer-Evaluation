let mode = "login"; // or "register"
const errorBox = document.getElementById("errorBox");
const nameField = document.getElementById("nameField");
const formTitle = document.getElementById("formTitle");
const toggleMode = document.getElementById("toggleMode");
const submitBtn = document.getElementById("submitBtn");

toggleMode.addEventListener("click", () => {
  mode = mode === "login" ? "register" : "login";
  const isRegister = mode === "register";
  nameField.style.display = isRegister ? "block" : "none";
  formTitle.textContent = isRegister ? "Create account" : "Log in";
  toggleMode.textContent = isRegister ? "Already have an account?" : "Need an account?";
  submitBtn.textContent = isRegister ? "Create account" : "Log in";
  hideError(errorBox);
});

submitBtn.addEventListener("click", async () => {
  hideError(errorBox);
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    if (mode === "register") {
      const name = document.getElementById("name").value.trim();
      if (!name || !email || !password) throw new Error("Fill in every field.");
      await api("/auth/register", { method: "POST", body: JSON.stringify({ name, email, password }) });
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

document.getElementById("googleBtn").addEventListener("click", (e) => {
  e.preventDefault();
  window.location.href = `${API_BASE}/auth/google/start`;
});
