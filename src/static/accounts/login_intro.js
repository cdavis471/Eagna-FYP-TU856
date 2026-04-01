(function () {
  const splash = document.getElementById("login-splash");
  const formShell = document.getElementById("login-form-shell");
  if (!splash) return;

  const introSeenThisSession = sessionStorage.getItem("eagna_login_intro_seen") === "true";

  if (introSeenThisSession) {
    splash.remove();
    if (formShell) {
      formShell.removeAttribute("inert");
    }
    return;
  }

  sessionStorage.setItem("eagna_login_intro_seen", "true");

  if (document.activeElement && typeof document.activeElement.blur === "function") {
    document.activeElement.blur();
  }

  window.setTimeout(function () {
    splash.classList.add("login-splash--hide");
  }, 2800);

  window.setTimeout(function () {
    splash.remove();
    if (formShell) {
      formShell.removeAttribute("inert");
    }
  }, 3600);
})();