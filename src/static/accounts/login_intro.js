// ===========
// Login Intro
// ===========
(function () { // Scope the login splash behaviour.
  const splash = document.getElementById("login-splash"); // Get the splash screen element.
  const formShell = document.getElementById("login-form-shell"); // Get the login form wrapper.
  if (!splash) return; // Exit when splash markup is absent.

  const introSeenThisSession = sessionStorage.getItem("eagna_login_intro_seen") === "true"; // Check whether the intro already ran.

  if (introSeenThisSession) { // Skip the intro after first visit.
    splash.remove(); // Remove the splash immediately.
    if (formShell) { // Only update when the form exists.
      formShell.removeAttribute("inert"); // Re-enable interaction with the form.
    }
    return; // Stop after restoring the form.
  }

  sessionStorage.setItem("eagna_login_intro_seen", "true"); // Mark the intro as already shown.

  if (document.activeElement && typeof document.activeElement.blur === "function") { // Blur any focused element safely.
    document.activeElement.blur(); // Remove accidental initial focus.
  }

  window.setTimeout(function () { // Start the splash fade-out.
    splash.classList.add("login-splash--hide"); // Apply the hide animation class.
  }, 2800);

  window.setTimeout(function () { // Remove the splash after animation.
    splash.remove(); // Remove the splash from the DOM.
    if (formShell) { // Only update when the form exists.
      formShell.removeAttribute("inert"); // Re-enable interaction with the form.
    }
  }, 3600);
})();