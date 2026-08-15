const createError = document.getElementById("createError");

async function checkAuth() {
  const me = await api("/auth/me");
  if (!me.authenticated) {
    window.location.href = "login.html";
    return;
  }
  document.getElementById("whoami").textContent = `${me.name} (${me.email})`;
}

async function loadCourses() {
  const courses = await api("/courses");
  const list = document.getElementById("coursesList");
  if (courses.length === 0) {
    list.innerHTML = `<p class="empty-state">No courses yet — create one above.</p>`;
    return;
  }
  list.innerHTML = "";
  courses.forEach(c => {
    const div = document.createElement("div");
    div.className = "list-item";
    div.innerHTML = `
      <div>
        <strong>${c.name}</strong><br>
        <span class="hint">Created ${new Date(c.created_at).toLocaleDateString()}</span>
      </div>
      <a class="btn btn--ghost btn--sm" href="course.html?course=${c.id}">Open</a>
    `;
    list.appendChild(div);
  });
}

document.getElementById("createCourseBtn").addEventListener("click", async () => {
  hideError(createError);
  const name = document.getElementById("courseName").value.trim();
  if (!name) { showError(createError, new Error("Course name is required.")); return; }
  try {
    await api("/courses", { method: "POST", body: JSON.stringify({ name }) });
    document.getElementById("courseName").value = "";
    await loadCourses();
  } catch (err) {
    showError(createError, err);
  }
});

document.getElementById("logoutBtn").addEventListener("click", async () => {
  try {
    await api("/auth/logout", { method: "POST" });
  } catch (err) {
    // Logging out is a one-way trip regardless — don't strand the lecturer
    // on the dashboard just because the network call hiccuped.
    console.warn("Logout request failed, redirecting anyway:", err);
  }
  window.location.href = "login.html";
});

checkAuth().then(loadCourses).catch(() => { window.location.href = "login.html"; });
