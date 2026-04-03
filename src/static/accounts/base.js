(function () {
  const shell = document.getElementById("notificationShell");
  if (!shell) return;

  const toggle = document.getElementById("notificationToggle");
  const dropdown = document.getElementById("notificationDropdown");
  const moreButton = document.getElementById("notificationMoreButton");

  function closeDropdown() {
    if (!dropdown) return;
    dropdown.hidden = true;
    toggle.setAttribute("aria-expanded", "false");

    if (moreButton) {
      dropdown.classList.remove("notification-dropdown--expanded");
      moreButton.textContent = "View more";
      moreButton.setAttribute("aria-expanded", "false");
    }
  }

  function openDropdown() {
    if (!dropdown) return;
    dropdown.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
  }

  toggle.addEventListener("click", function (event) {
    event.stopPropagation();

    if (dropdown.hidden) {
      openDropdown();
    } else {
      closeDropdown();
    }
  });

  if (dropdown) {
    dropdown.addEventListener("click", function (event) {
      event.stopPropagation();
    });
  }

  if (moreButton) {
    moreButton.addEventListener("click", function (event) {
      event.stopPropagation();

      const expanded = dropdown.classList.toggle("notification-dropdown--expanded");
      moreButton.textContent = expanded ? "View less" : "View more";
      moreButton.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
  }

  document.addEventListener("click", function () {
    closeDropdown();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeDropdown();
    }
  });
})();

(function () {
  const modal = document.getElementById("parsed-modal");
  const modalBody = document.getElementById("parsed-modal-body");

  if (!modal || !modalBody) return;

  function openParsedModal() {
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closeParsedModal() {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    modalBody.replaceChildren();
  }

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target.id === "parsed-modal-body") {
      openParsedModal();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeParsedModal();
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    const backdrop = document.getElementById("parsed-modal-backdrop");
    const closeButton = document.getElementById("parsed-modal-close");

    if (backdrop) {
      backdrop.addEventListener("click", closeParsedModal);
    }

    if (closeButton) {
      closeButton.addEventListener("click", closeParsedModal);
    }
  });
})();

(function () {
  const menus = Array.from(document.querySelectorAll("[data-user-menu]"));
  if (!menus.length) return;

  function closeMenu(menu) {
    menu.classList.remove("user-menu--open");
    const trigger = menu.querySelector("[data-user-menu-trigger]");
    if (trigger) {
      trigger.setAttribute("aria-expanded", "false");
    }
  }

  function openMenu(menu) {
    menus.forEach((item) => {
      if (item !== menu) {
        closeMenu(item);
      }
    });

    menu.classList.add("user-menu--open");

    const trigger = menu.querySelector("[data-user-menu-trigger]");
    if (trigger) {
      trigger.setAttribute("aria-expanded", "true");
    }
  }

  menus.forEach((menu) => {
    const trigger = menu.querySelector("[data-user-menu-trigger]");
    const dropdown = menu.querySelector("[data-user-menu-dropdown]");
    const form = menu.querySelector("[data-user-menu-form]");

    if (!trigger || !dropdown || !form) return;

    trigger.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();

      if (menu.classList.contains("user-menu--open")) {
        closeMenu(menu);
      } else {
        openMenu(menu);
      }
    });

    trigger.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
        event.preventDefault();
        openMenu(menu);
      }
    });

    dropdown.addEventListener("click", function (event) {
      event.stopPropagation();
    });

    form.addEventListener("change", function () {
      form.submit();
    });
  });

  document.addEventListener("click", function () {
    menus.forEach(closeMenu);
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      menus.forEach(closeMenu);
    }
  });
})();

(function () {
  const dropzones = Array.from(document.querySelectorAll("[data-upload-dropzone]"));
  if (!dropzones.length) return;

  function emptyTextFor(input) {
    return input.multiple ? "No files selected" : "No file selected";
  }

  function buildTransfer(files, input) {
    const transfer = new DataTransfer();
    const chosenFiles = input.multiple ? files : files.slice(0, 1);
    chosenFiles.forEach((file) => transfer.items.add(file));
    return transfer;
  }

  function setFiles(input, files) {
    input.files = buildTransfer(files, input).files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function renderFileList(zone, input) {
    const fileList = zone.querySelector("[data-upload-filelist]");
    if (!fileList) return;

    const files = Array.from(input.files || []);

    if (!files.length) {
      fileList.textContent = emptyTextFor(input);
      return;
    }

    const nodes = files.map((file, index) => {
      const chip = document.createElement("span");
      chip.className = "upload-dropzone__file";

      const name = document.createElement("span");
      name.textContent = file.name;

      chip.appendChild(name);

      if (input.multiple) {
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "upload-dropzone__remove";
        remove.setAttribute("aria-label", `Remove ${file.name}`);
        remove.textContent = "×";

        remove.addEventListener("click", function () {
          const nextFiles = Array.from(input.files || []).filter((_, fileIndex) => fileIndex !== index);
          setFiles(input, nextFiles);
        });

        chip.appendChild(remove);
      }

      return chip;
    });

    fileList.replaceChildren(...nodes);
  }

  function mergeDroppedFiles(input, droppedFiles) {
    const existing = input.multiple ? Array.from(input.files || []) : [];
    const combined = input.multiple ? existing.concat(droppedFiles) : droppedFiles.slice(0, 1);
    setFiles(input, combined);
  }

  dropzones.forEach((zone) => {
    const input = zone.querySelector(".upload-dropzone__input");
    if (!input) return;

    renderFileList(zone, input);

    input.addEventListener("change", function () {
      renderFileList(zone, input);
    });

    ["dragenter", "dragover"].forEach((eventName) => {
      zone.addEventListener(eventName, function (event) {
        event.preventDefault();
        event.stopPropagation();
        zone.classList.add("upload-dropzone--dragging");
      });
    });

    ["dragleave", "dragend"].forEach((eventName) => {
      zone.addEventListener(eventName, function (event) {
        event.preventDefault();
        event.stopPropagation();
        zone.classList.remove("upload-dropzone--dragging");
      });
    });

    zone.addEventListener("drop", function (event) {
      event.preventDefault();
      event.stopPropagation();
      zone.classList.remove("upload-dropzone--dragging");

      const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
      if (!files.length) return;

      mergeDroppedFiles(input, files);
    });
  });
})();