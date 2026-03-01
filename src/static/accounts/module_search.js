(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function getCourseValue() {
    const courseEl = byId("id_course");
    return (courseEl?.value || "").trim();
  }

  function parseCourses(datasetCourses) {
    return (datasetCourses || "")
      .split(",")
      .map(s => s.trim())
      .filter(Boolean);
  }

  function buildModuleIndex() {
    const select = byId("id_module_ids");
    const modules = [];

    if (!select) return modules;

    for (const opt of select.options) {
      modules.push({
        id: opt.value,
        label: opt.text,
        allowedCourses: parseCourses(opt.dataset.courses),
        optionEl: opt,
      });
    }

    return modules;
  }

  function setSelected(module, selected) {
    module.optionEl.selected = selected;
  }

  function isSelected(module) {
    return !!module.optionEl.selected;
  }

  function removeInvalidSelections(modules, course) {
    if (!course) return 0;

    let removed = 0;
    for (const m of modules) {
      if (isSelected(m) && !m.allowedCourses.includes(course)) {
        setSelected(m, false);
        removed += 1;
      }
    }
    return removed;
  }

  function renderSelected(modules) {
    const container = byId("selected-modules");
    if (!container) return;
    container.innerHTML = "";

    const selected = modules.filter(isSelected);

    selected.forEach(m => {
      const chip = document.createElement("div");
      chip.className = "module-chip";
      chip.title = "Click to remove";
      chip.innerHTML = `<span>${m.label}</span><span class="chip-x">×</span>`;
      chip.addEventListener("click", () => {
        setSelected(m, false);
        renderSelected(modules);
        renderDropdown(modules);
      });
      container.appendChild(chip);
    });
  }

  function showHelper(msg) {
    const helper = byId("module-helper");
    if (!helper) return;
    helper.textContent = msg || "";
  }

  function renderDropdown(modules) {
    const dropdown = byId("module-dropdown");
    const input = byId("module-search");
    if (!dropdown || !input) return;

    const q = (input.value || "").trim().toLowerCase();
    const course = getCourseValue();

    dropdown.hidden = false;
    dropdown.innerHTML = "";

    // No Course Selected - Prompt User to Select Course First
    if (!course) {
      const item = document.createElement("div");
      item.className = "dropdown-item dropdown-item--disabled";
      item.textContent = "Select a course first to see matching modules.";
      dropdown.appendChild(item);
      showHelper("Choose your course first, then search modules.");
      return;
    }

    // Filter - Must Match Course | Must Match Search | Must Not Already Be Selected
    const matches = modules
      .filter(m => m.allowedCourses.includes(course))
      .filter(m => m.label.toLowerCase().includes(q))
      .filter(m => !isSelected(m))
      .slice(0, 50);

    if (matches.length === 0) {
      const item = document.createElement("div");
      item.className = "dropdown-item dropdown-item--disabled";
      item.textContent = "No matching modules for this course.";
      dropdown.appendChild(item);
      showHelper("");
      return;
    }

    matches.forEach(m => {
      const item = document.createElement("div");
      item.className = "dropdown-item";
      item.textContent = m.label;
      item.addEventListener("click", () => {
        setSelected(m, true);
        input.value = "";
        renderSelected(modules);
        renderDropdown(modules);
        input.focus();
      });
      dropdown.appendChild(item);
    });

    showHelper("");
  }

  function wireUp() {
    
    const modules = buildModuleIndex();
    const courseEl = byId("id_course");
    const searchEl = byId("module-search");
    const dropdown = byId("module-dropdown");

    // Missing Elements - Cannot Wire Up
    if (!courseEl || !searchEl || !dropdown) return;

    // Initial Render of Selected Modules
    renderSelected(modules);

    // When Course Changes --> Remove Invalid Selected Modules & Refresh Dropdown
    const onCourseChange = () => {
      const course = getCourseValue();
      const removed = removeInvalidSelections(modules, course);
      if (removed > 0) {
        showHelper(`Removed ${removed} module(s) not valid for the selected course.`);
      } else {
        showHelper("");
      }
      renderSelected(modules);
      renderDropdown(modules);
    };

    // Course Change Behaviour
    courseEl.addEventListener("input", onCourseChange);
    courseEl.addEventListener("change", onCourseChange);

    // Search Behaviour
    searchEl.addEventListener("input", () => renderDropdown(modules));
    searchEl.addEventListener("focus", () => renderDropdown(modules));

    // Hide Dropdown On Outside Click
    document.addEventListener("click", (e) => {
      if (dropdown.contains(e.target) || searchEl.contains(e.target)) return;
      dropdown.hidden = true;
    });
  }

  // Initialize on DOM Ready
  document.addEventListener("DOMContentLoaded", wireUp);
})();