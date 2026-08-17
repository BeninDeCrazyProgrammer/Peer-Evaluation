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
      <div style="display:flex; gap:8px;">
        <a class="btn btn--ghost btn--sm" href="course.html?course=${c.id}">Open</a>
        <button class="btn btn--ghost btn--sm delete-course-btn" data-id="${c.id}" data-name="${c.name}">Delete</button>
      </div>
    `;
    list.appendChild(div);
  });
  list.querySelectorAll(".delete-course-btn").forEach(btn => {
    btn.addEventListener("click", () => deleteCourse(btn.dataset.id, btn.dataset.name));
  });
}

async function deleteCourse(courseId, name) {
  if (!confirm(`Delete "${name}"? This permanently removes its groups, students, evaluations, and every submission ever recorded for it. This can't be undone.`)) return;
  try {
    await api(`/courses/${courseId}`, { method: "DELETE" });
    await loadCourses();
  } catch (err) {
    showError(createError, err);
  }
}

const createCourseBtn = document.getElementById("createCourseBtn");
createCourseBtn.addEventListener("click", async () => {
  hideError(createError);
  const name = document.getElementById("courseName").value.trim();
  if (!name) { showError(createError, new Error("Course name is required.")); return; }
  // Without this, a double-click (or a slow connection tempting a second
  // click before the first request lands) fires two POSTs and creates two
  // identical courses — the backend's own duplicate-name check now also
  // catches that, but disabling the button is what stops it from feeling
  // broken in the meantime.
  createCourseBtn.disabled = true;
  try {
    await api("/courses", { method: "POST", body: JSON.stringify({ name }) });
    document.getElementById("courseName").value = "";
    await loadCourses();
  } catch (err) {
    showError(createError, err);
  } finally {
    createCourseBtn.disabled = false;
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
