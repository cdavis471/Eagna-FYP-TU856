const attemptForm = document.getElementById("quiz-attempt-form");
const timerDisplay = document.getElementById("quiz-timer-display");

if (attemptForm && timerDisplay) {
  let remainingSeconds = parseInt(attemptForm.dataset.remainingSeconds || "0", 10);
  let saveInFlight = false;

  function formatSeconds(totalSeconds) {
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function updateTimerDisplay() {
    timerDisplay.textContent = formatSeconds(Math.max(remainingSeconds, 0));
  }

  function saveProgress() {
    if (saveInFlight) return;
    saveInFlight = true;

    const data = new FormData(attemptForm);

    fetch(attemptForm.dataset.saveUrl, {
      method: "POST",
      body: data,
      headers: {
        "X-Requested-With": "XMLHttpRequest",
      },
    })
    .finally(() => {
      saveInFlight = false;
    });
  }

  attemptForm.addEventListener("change", function () {
    saveProgress();

    document.querySelectorAll(".quiz-blank-selected").forEach((span) => {
      const questionId = span.dataset.questionId;
      const checked = attemptForm.querySelector(`input[name="question_${questionId}"]:checked`);
      span.textContent = checked ? checked.parentElement.querySelector("span").textContent : "_____";
    });
  });

  updateTimerDisplay();

  const timerInterval = window.setInterval(function () {
    remainingSeconds -= 1;
    updateTimerDisplay();

    if (remainingSeconds > 0 && remainingSeconds % 15 === 0) {
      saveProgress();
    }

    if (remainingSeconds <= 0) {
      clearInterval(timerInterval);
      saveProgress();
      attemptForm.submit();
    }
  }, 1000);

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") {
      saveProgress();
    }
  });
}