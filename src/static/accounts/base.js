// =====================
// Notification Dropdown
// =====================
(function () { // Scope notification dropdown behaviour.
  const shell = document.getElementById("notificationShell"); // Get the notification shell element.
  if (!shell) return; // Exit when notifications are absent.

  const toggle = document.getElementById("notificationToggle"); // Get the dropdown toggle button.
  const dropdown = document.getElementById("notificationDropdown"); // Get the dropdown panel element.
  const moreButton = document.getElementById("notificationMoreButton"); // Get the optional expand button.

  function closeDropdown() { // Hide the notification dropdown.
    if (!dropdown) return; // Exit when dropdown is unavailable.
    dropdown.hidden = true; // Hide the dropdown panel.
    toggle.setAttribute("aria-expanded", "false"); // Mark the toggle as collapsed.

    if (moreButton) { // Reset the expanded state when present.
      dropdown.classList.remove("notification-dropdown--expanded"); // Remove expanded dropdown styling.
      moreButton.textContent = "View more"; // Restore the default button label.
      moreButton.setAttribute("aria-expanded", "false"); // Mark the expand button collapsed.
    }
  }

  function openDropdown() { // Show the notification dropdown.
    if (!dropdown) return; // Exit when dropdown is unavailable.
    dropdown.hidden = false; // Reveal the dropdown panel.
    toggle.setAttribute("aria-expanded", "true"); // Mark the toggle as expanded.
  }

  toggle.addEventListener("click", function (event) { // Toggle the dropdown on click.
    event.stopPropagation(); // Stop the document handler closing it.

    if (dropdown.hidden) { // Open when currently hidden.
      openDropdown(); // Reveal the dropdown panel.
    } else { // Otherwise it is already open.
      closeDropdown(); // Collapse the dropdown panel.
    }
  });

  if (dropdown) { // Only bind when the dropdown exists.
    dropdown.addEventListener("click", function (event) { // Keep inside clicks from bubbling.
      event.stopPropagation(); // Prevent outside click closure.
    });
  }

  if (moreButton) { // Only bind when the button exists.
    moreButton.addEventListener("click", function (event) { // Expand or collapse extra items.
      event.stopPropagation(); // Prevent document click handling.

      const expanded = dropdown.classList.toggle("notification-dropdown--expanded"); // Toggle expanded dropdown styling.
      moreButton.textContent = expanded ? "View less" : "View more"; // Update the button label.
      moreButton.setAttribute("aria-expanded", expanded ? "true" : "false"); // Sync button accessibility state.
    });
  }

  document.addEventListener("click", function () { // Close on outside clicks.
    closeDropdown(); // Collapse the notification dropdown.
  });

  document.addEventListener("keydown", function (event) { // Listen for escape presses.
    if (event.key === "Escape") { // Close only on escape.
      closeDropdown(); // Collapse the notification dropdown.
    }
  });
})();

// ============
// Parsed Modal
// ============
(function () { // Scope parsed document modal behaviour.
  const modal = document.getElementById("parsed-modal"); // Get the modal wrapper.
  const modalBody = document.getElementById("parsed-modal-body"); // Get the modal content area.

  if (!modal || !modalBody) return; // Exit when modal markup is absent.

  function openParsedModal() { // Display the parsed modal.
    modal.classList.remove("hidden"); // Remove the hidden class.
    modal.setAttribute("aria-hidden", "false"); // Mark the modal visible.
  }

  function closeParsedModal() { // Hide and reset the modal.
    modal.classList.add("hidden"); // Reapply the hidden class.
    modal.setAttribute("aria-hidden", "true"); // Mark the modal hidden.
    modalBody.replaceChildren(); // Clear any injected modal content.
  }

  document.body.addEventListener("htmx:afterSwap", function (event) { // Open after HTMX content loads.
    if (event.detail.target.id === "parsed-modal-body") { // Only react to modal-body swaps.
      openParsedModal(); // Reveal the parsed content modal.
    }
  });

  document.addEventListener("keydown", function (event) { // Listen for escape presses.
    if (event.key === "Escape") { // Close only on escape.
      closeParsedModal(); // Hide and reset the modal.
    }
  });

  document.addEventListener("DOMContentLoaded", function () { // Bind modal controls after load.
    const backdrop = document.getElementById("parsed-modal-backdrop"); // Get the modal backdrop.
    const closeButton = document.getElementById("parsed-modal-close"); // Get the close button.

    if (backdrop) { // Only bind when backdrop exists.
      backdrop.addEventListener("click", closeParsedModal); // Close when backdrop is clicked.
    }

    if (closeButton) { // Only bind when button exists.
      closeButton.addEventListener("click", closeParsedModal); // Close when button is clicked.
    }
  });
})();

// =========
// User Menu
// =========
(function () { // Scope user menu interactions.
  const menus = Array.from(document.querySelectorAll("[data-user-menu]")); // Collect all user menus.
  if (!menus.length) return; // Exit when no menus exist.

  function closeMenu(menu) { // Collapse a user menu.
    menu.classList.remove("user-menu--open"); // Remove the open state class.
    const trigger = menu.querySelector("[data-user-menu-trigger]"); // Find the trigger inside the menu.
    if (trigger) { // Only update when trigger exists.
      trigger.setAttribute("aria-expanded", "false"); // Mark the trigger collapsed.
    }
  }

  function openMenu(menu) { // Open one menu and close others.
    menus.forEach((item) => { // Iterate over every menu.
      if (item !== menu) { // Skip the target menu.
        closeMenu(item); // Close all other menus.
      }
    });

    menu.classList.add("user-menu--open"); // Add the open state class.

    const trigger = menu.querySelector("[data-user-menu-trigger]"); // Find the trigger inside the menu.
    if (trigger) { // Only update when trigger exists.
      trigger.setAttribute("aria-expanded", "true"); // Mark the trigger expanded.
    }
  }

  menus.forEach((menu) => { // Bind behaviour for each menu.
    const trigger = menu.querySelector("[data-user-menu-trigger]"); // Get the menu trigger.
    const dropdown = menu.querySelector("[data-user-menu-dropdown]"); // Get the menu dropdown.
    const form = menu.querySelector("[data-user-menu-form]"); // Get the menu form.

    if (!trigger || !dropdown || !form) return; // Skip incomplete menu markup.

    trigger.addEventListener("click", function (event) { // Toggle the menu on click.
      event.preventDefault(); // Stop default button behaviour.
      event.stopPropagation(); // Prevent document click handling.

      if (menu.classList.contains("user-menu--open")) { // Close when already open.
        closeMenu(menu); // Collapse the current menu.
      } else { // Otherwise the menu is closed.
        openMenu(menu); // Expand the current menu.
      }
    });

    trigger.addEventListener("keydown", function (event) { // Support keyboard opening.
      if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") { // Match supported keys.
        event.preventDefault(); // Stop native key behaviour.
        openMenu(menu); // Expand the current menu.
      }
    });

    dropdown.addEventListener("click", function (event) { // Keep dropdown clicks internal.
      event.stopPropagation(); // Prevent document click closure.
    });

    form.addEventListener("change", function () { // Submit when selection changes.
      form.submit(); // Post the updated preference form.
    });
  });

  document.addEventListener("click", function () { // Close menus on outside clicks.
    menus.forEach(closeMenu); // Collapse every open menu.
  });

  document.addEventListener("keydown", function (event) { // Listen for escape presses.
    if (event.key === "Escape") { // Close only on escape.
      menus.forEach(closeMenu); // Collapse every open menu.
    }
  });
})();

// ===============
// Upload Dropzone
// ===============
(function () { // Scope upload dropzone behaviour.
  const dropzones = Array.from(document.querySelectorAll("[data-upload-dropzone]")); // Collect all upload zones.
  if (!dropzones.length) return; // Exit when no dropzones exist.

  function emptyTextFor(input) { // Return the empty-state label.
    return input.multiple ? "No files selected" : "No file selected"; // Match single or multiple wording.
  }

  function buildTransfer(files, input) { // Build a mutable file transfer.
    const transfer = new DataTransfer(); // Create a new transfer container.
    const chosenFiles = input.multiple ? files : files.slice(0, 1); // Limit to one file when required.
    chosenFiles.forEach((file) => transfer.items.add(file)); // Add each chosen file.
    return transfer; // Return the populated transfer.
  }

  function setFiles(input, files) { // Replace the input file list.
    input.files = buildTransfer(files, input).files; // Apply the rebuilt file collection.
    input.dispatchEvent(new Event("change", { bubbles: true })); // Trigger downstream change handlers.
  }

  function renderFileList(zone, input) { // Render chips for current files.
    const fileList = zone.querySelector("[data-upload-filelist]"); // Find the file list container.
    if (!fileList) return; // Exit when list markup is absent.

    const files = Array.from(input.files || []); // Read files from the input.

    if (!files.length) { // Show the empty state when needed.
      fileList.textContent = emptyTextFor(input); // Render the empty-state text.
      return; // Stop after rendering the empty state.
    }

    const nodes = files.map((file, index) => { // Build one chip per file.
      const chip = document.createElement("span"); // Create the file chip wrapper.
      chip.className = "upload-dropzone__file"; // Apply the chip styling class.

      const name = document.createElement("span"); // Create the filename element.
      name.textContent = file.name; // Show the uploaded filename.

      chip.appendChild(name); // Append the filename to the chip.

      if (input.multiple) { // Show remove buttons only for multi-upload.
        const remove = document.createElement("button"); // Create the remove button.
        remove.type = "button"; // Prevent accidental form submission.
        remove.className = "upload-dropzone__remove"; // Apply remove button styling.
        remove.setAttribute("aria-label", `Remove ${file.name}`); // Add an accessible remove label.
        remove.textContent = "×"; // Display the remove glyph.

        remove.addEventListener("click", function () { // Remove the chosen file on click.
          const nextFiles = Array.from(input.files || []).filter((_, fileIndex) => fileIndex !== index); // Exclude the clicked file.
          setFiles(input, nextFiles); // Reapply the remaining files.
        });

        chip.appendChild(remove); // Append the remove button.
      }

      return chip; // Return the completed file chip.
    });

    fileList.replaceChildren(...nodes); // Replace the list with new chips.
  }

  function mergeDroppedFiles(input, droppedFiles) { // Merge dropped files into the input.
    const existing = input.multiple ? Array.from(input.files || []) : []; // Keep existing files for multi-upload.
    const combined = input.multiple ? existing.concat(droppedFiles) : droppedFiles.slice(0, 1); // Limit single inputs to one file.
    setFiles(input, combined); // Apply the merged file list.
  }

  dropzones.forEach((zone) => { // Bind behaviour for each dropzone.
    const input = zone.querySelector(".upload-dropzone__input"); // Get the hidden file input.
    if (!input) return; // Skip malformed dropzone markup.

    renderFileList(zone, input); // Render any initial file list.

    input.addEventListener("change", function () { // Refresh chips after manual selection.
      renderFileList(zone, input); // Re-render the file list.
    });

    ["dragenter", "dragover"].forEach((eventName) => { // Bind active drag events.
      zone.addEventListener(eventName, function (event) { // Highlight the zone while dragging.
        event.preventDefault(); // Allow dropping files here.
        event.stopPropagation(); // Prevent outer drag handlers.
        zone.classList.add("upload-dropzone--dragging"); // Apply dragging visual state.
      });
    });

    ["dragleave", "dragend"].forEach((eventName) => { // Bind drag exit events.
      zone.addEventListener(eventName, function (event) { // Remove highlight when drag leaves.
        event.preventDefault(); // Stop default browser handling.
        event.stopPropagation(); // Prevent outer drag handlers.
        zone.classList.remove("upload-dropzone--dragging"); // Remove dragging visual state.
      });
    });

    zone.addEventListener("drop", function (event) { // Accept dropped files.
      event.preventDefault(); // Stop the browser opening files.
      event.stopPropagation(); // Prevent outer drop handlers.
      zone.classList.remove("upload-dropzone--dragging"); // Remove dragging visual state.

      const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []); // Read dropped files safely.
      if (!files.length) return; // Exit when nothing was dropped.

      mergeDroppedFiles(input, files); // Merge dropped files into the input.
    });
  });
})();
