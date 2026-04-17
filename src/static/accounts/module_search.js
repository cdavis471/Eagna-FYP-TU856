// =============
// Module Search
// =============
(function () { // Scope module search behaviour.
  function byId(id) { // Fetch an element by id.
    return document.getElementById(id); // Return the matching element.
  }

  function normalizeCourseCode(value) { // Normalise entered course codes.
    return (value || "") // Start with a safe string.
      .trim() // Remove outer whitespace.
      .toUpperCase() // Standardise casing for matching.
      .replace(/\s+/g, ""); // Remove inner spaces.
  }

  function getCourseValue() { // Read the current course input.
    const courseEl = byId("id_course"); // Get the course field element.
    return normalizeCourseCode(courseEl?.value || ""); // Return the normalised course code.
  }

  function parseCourses(datasetCourses) { // Split allowed course codes.
    return (datasetCourses || "") // Start with a safe string.
      .split(",") // Split the dataset into values.
      .map((s) => normalizeCourseCode(s)) // Normalise each course code.
      .filter(Boolean); // Remove empty values.
  }

  function buildModuleIndex() { // Build a searchable module list.
    const select = byId("id_module_ids"); // Get the backing select element.
    const modules = []; // Store indexed module details.

    if (!select) return modules; // Exit when the select is missing.

    for (const opt of select.options) { // Walk every option in the select.
      modules.push({ // Store searchable metadata for each module.
        id: opt.value, // Preserve the option value.
        label: opt.text, // Preserve the visible label.
        allowedCourses: parseCourses(opt.dataset.courses), // Parse supported course codes.
        isLockedCurrent: opt.dataset.lockedCurrent === "true", // Mark already joined current modules.
        optionEl: opt, // Keep a reference to the source option.
      });
    }

    return modules; // Return the indexed module list.
  }

  function setSelected(module, selected) { // Toggle a module selection.
    if (module.isLockedCurrent) return; // Prevent changes to already joined current modules.
    module.optionEl.selected = selected; // Update the backing option state.
  }

  function isSelected(module) { // Check whether a module is selected.
    return !!module.optionEl.selected; // Return the option selected state.
  }

  function clearAllSelections(modules) { // Clear every selected module.
    for (const module of modules) { // Walk all indexed modules.
      if (!module.isLockedCurrent) { // Only clear newly selectable modules.
        setSelected(module, false); // Deselect the current module.
      }
    }
  }

  function renderSelected(modules) { // Render chips for selected modules.
    const container = byId("selected-modules"); // Get the chip container.
    if (!container) return; // Exit when chip markup is absent.

    container.replaceChildren(); // Clear existing chips first.
    const selected = modules.filter((module) => isSelected(module) && !module.isLockedCurrent); // Collect removable selections only.

    selected.forEach((m) => { // Render one chip per selection.
      const chip = document.createElement("div"); // Create the chip wrapper.
      chip.className = "module-chip"; // Apply chip styling.
      chip.title = "Click to remove"; // Add a removal hint.

      const label = document.createElement("span"); // Create the chip label.
      label.textContent = m.label; // Show the module name.

      const close = document.createElement("span"); // Create the close marker.
      close.className = "chip-x"; // Apply close styling.
      close.textContent = "×"; // Show the close glyph.

      chip.append(label, close); // Append chip contents.

      chip.addEventListener("click", () => { // Remove a selection on click.
        setSelected(m, false); // Deselect the clicked module.
        renderSelected(modules); // Refresh the selected chips.
        renderDropdown(modules); // Refresh dropdown selection states.
      });

      container.appendChild(chip); // Append the completed chip.
    });
  }

  function showHelper(msg) { // Update helper text below search.
    const helper = byId("module-helper"); // Get the helper text element.
    if (!helper) return; // Exit when helper markup is absent.
    helper.textContent = msg || ""; // Show the supplied helper message.
  }

  function renderDropdown(modules) { // Render matching dropdown modules.
    const dropdown = byId("module-dropdown"); // Get the dropdown container.
    const input = byId("module-search"); // Get the search input.
    if (!dropdown || !input) return; // Exit when required markup is absent.

    const q = (input.value || "").trim().toLowerCase(); // Normalise the search query.
    const course = getCourseValue(); // Read the selected course code.

    dropdown.hidden = false; // Keep the dropdown visible while active.
    dropdown.replaceChildren(); // Clear previous dropdown items.

    if (!course) { // Prompt for a course when missing.
      const item = document.createElement("div"); // Create a disabled dropdown item.
      item.className = "dropdown-item dropdown-item--disabled"; // Apply disabled item styling.
      item.textContent = "Enter a course first to see matching modules."; // Show the missing-course prompt.
      dropdown.appendChild(item); // Append the prompt item.
      showHelper("Enter or select your course first, then choose modules."); // Show helper guidance.
      return; // Stop before trying to match modules.
    }

    const matches = modules // Start matching against indexed modules.
      .filter((m) => m.allowedCourses.includes(course)) // Keep modules allowed for the course.
      .filter((m) => m.label.toLowerCase().includes(q)) // Keep modules matching the query.
      .slice(0, 50); // Limit the number of rendered items.

    if (matches.length === 0) { // Show an empty result message.
      const item = document.createElement("div"); // Create a disabled dropdown item.
      item.className = "dropdown-item dropdown-item--disabled"; // Apply disabled item styling.
      item.textContent = "No matching modules for this course."; // Show the empty-state message.
      dropdown.appendChild(item); // Append the empty-state item.
      showHelper(""); // Clear the helper message.
      return; // Stop after rendering the empty state.
    }

    matches.forEach((m) => { // Render one item per match.
      const item = document.createElement("div"); // Create the dropdown item.
      item.className = "dropdown-item"; // Apply dropdown item styling.
      item.textContent = m.label; // Show the module label.

      if (m.isLockedCurrent) { // Mark modules the student already has.
        item.classList.add("dropdown-item--locked"); // Apply locked styling.
        item.textContent = `${m.label} — Already Joined`; // Clarify the state.
      } else if (isSelected(m)) { // Mark already selected new modules.
        item.classList.add("dropdown-item--selected"); // Apply selected item styling.
      }

      if (!m.isLockedCurrent) { // Only attach click behaviour to selectable modules.
        item.addEventListener("click", () => { // Toggle selection on click.
          setSelected(m, !isSelected(m)); // Flip the selection state.
          renderSelected(modules); // Refresh the selected chips.
          renderDropdown(modules); // Refresh dropdown highlighting.
          input.focus(); // Return focus to the search field.
        });
      }

      dropdown.appendChild(item); // Append the dropdown item.
    });

    showHelper(""); // Clear helper text when matches exist.
  }

  function wireUp() { // Attach module search handlers.
    const modules = buildModuleIndex(); // Build the searchable module list.
    const courseEl = byId("id_course"); // Get the course input.
    const searchEl = byId("module-search"); // Get the search input.
    const dropdown = byId("module-dropdown"); // Get the dropdown container.

    if (!courseEl || !searchEl || !dropdown) return; // Exit when required markup is absent.

    let previousCourseValue = getCourseValue(); // Track the last known course value.

    renderSelected(modules); // Render any existing selections.
    renderDropdown(modules); // Render the initial dropdown state.

    const onCourseChangedExplicitly = () => { // Reset modules after course changes.
      const nextCourseValue = getCourseValue(); // Read the latest course value.

      if (nextCourseValue !== previousCourseValue) { // React only to actual changes.
        previousCourseValue = nextCourseValue; // Store the latest course value.
        searchEl.value = ""; // Clear the module search query.
        clearAllSelections(modules); // Remove incompatible selected modules.
        renderSelected(modules); // Refresh the selected chips.
        renderDropdown(modules); // Refresh the dropdown items.

        if (nextCourseValue) { // Show course-changed guidance when present.
          showHelper("Course changed. Please choose modules again for this course."); // Prompt for reselection.
        } else { // Otherwise no course is selected.
          showHelper("Enter your course first, then choose modules."); // Prompt for a course first.
        }
      } else { // Otherwise the course value stayed the same.
        renderDropdown(modules); // Refresh dropdown results only.
      }
    };

    courseEl.addEventListener("input", onCourseChangedExplicitly); // Track typing in the course field.
    courseEl.addEventListener("change", onCourseChangedExplicitly); // Track committed course changes.

    searchEl.addEventListener("input", () => renderDropdown(modules)); // Filter results as the user types.
    searchEl.addEventListener("focus", () => renderDropdown(modules)); // Refresh results when focused.

    document.addEventListener("click", (e) => { // Manage outside-click dropdown behaviour.
      if ( // Ignore clicks inside related controls.
        dropdown.contains(e.target) || // Keep dropdown clicks active.
        searchEl.contains(e.target) || // Keep search clicks active.
        courseEl.contains(e.target) // Keep course clicks active.
      ) {
        return; // Stop when click is inside controls.
      }

      if (getCourseValue()) { // Keep the dropdown visible with a course.
        dropdown.hidden = false; // Leave the dropdown open.
      } else { // Otherwise hide it without a course.
        dropdown.hidden = true; // Hide the dropdown completely.
      }
    });
  }

  document.addEventListener("DOMContentLoaded", wireUp); // Initialise after the DOM loads.
})();