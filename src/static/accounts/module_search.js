(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function normalizeCourseCode(value) {
    return (value || "")
      .trim()
      .toUpperCase()
      .replace(/\s+/g, "");
  }

  function getCourseValue() {
    const courseEl = byId("id_course");
    return normalizeCourseCode(courseEl?.value || "");
  }

  function parseCourses(datasetCourses) {
    return (datasetCourses || "")
      .split(",")
      .map((s) => normalizeCourseCode(s))
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

  function clearAllSelections(modules) {
    for (const module of modules) {
      setSelected(module, false);
    }
  }

  function renderSelected(modules) {
    const container = byId("selected-modules");
    if (!container) return;

    container.replaceChildren();
    const selected = modules.filter(isSelected);

    selected.forEach((m) => {
      const chip = document.createElement("div");
      chip.className = "module-chip";
      chip.title = "Click to remove";

      const label = document.createElement("span");
      label.textContent = m.label;

      const close = document.createElement("span");
      close.className = "chip-x";
      close.textContent = "×";

      chip.append(label, close);

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
    dropdown.replaceChildren();

    if (!course) {
      const item = document.createElement("div");
      item.className = "dropdown-item dropdown-item--disabled";
      item.textContent = "Enter a course first to see matching modules.";
      dropdown.appendChild(item);
      showHelper("Enter or select your course first, then choose modules.");
      return;
    }

    const matches = modules
      .filter((m) => m.allowedCourses.includes(course))
      .filter((m) => m.label.toLowerCase().includes(q))
      .slice(0, 50);

    if (matches.length === 0) {
      const item = document.createElement("div");
      item.className = "dropdown-item dropdown-item--disabled";
      item.textContent = "No matching modules for this course.";
      dropdown.appendChild(item);
      showHelper("");
      return;
    }

    matches.forEach((m) => {
      const item = document.createElement("div");
      item.className = "dropdown-item";
      item.textContent = m.label;

      if (isSelected(m)) {
        item.classList.add("dropdown-item--selected");
      }

      item.addEventListener("click", () => {
        setSelected(m, !isSelected(m));
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

    if (!courseEl || !searchEl || !dropdown) return;

    let previousCourseValue = getCourseValue();

    renderSelected(modules);
    renderDropdown(modules);

    const onCourseChangedExplicitly = () => {
      const nextCourseValue = getCourseValue();

      if (nextCourseValue !== previousCourseValue) {
        previousCourseValue = nextCourseValue;
        searchEl.value = "";
        clearAllSelections(modules);
        renderSelected(modules);
        renderDropdown(modules);

        if (nextCourseValue) {
          showHelper("Course changed. Please choose modules again for this course.");
        } else {
          showHelper("Enter your course first, then choose modules.");
        }
      } else {
        renderDropdown(modules);
      }
    };

    courseEl.addEventListener("input", onCourseChangedExplicitly);
    courseEl.addEventListener("change", onCourseChangedExplicitly);

    searchEl.addEventListener("input", () => renderDropdown(modules));
    searchEl.addEventListener("focus", () => renderDropdown(modules));

    document.addEventListener("click", (e) => {
      if (
        dropdown.contains(e.target) ||
        searchEl.contains(e.target) ||
        courseEl.contains(e.target)
      ) {
        return;
      }

      if (getCourseValue()) {
        dropdown.hidden = false;
      } else {
        dropdown.hidden = true;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", wireUp);
})();