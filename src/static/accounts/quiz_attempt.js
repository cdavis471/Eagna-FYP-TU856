// ============
// Quiz Attempt
// ============
const attemptForm = document.getElementById("quiz-attempt-form"); // Get the quiz attempt form.
const timerDisplay = document.getElementById("quiz-timer-display"); // Get the timer display element.

if (attemptForm && timerDisplay) { // Run only when quiz markup exists.
  let remainingSeconds = parseInt(attemptForm.dataset.remainingSeconds || "0", 10); // Read the remaining attempt time.
  let saveInFlight = false; // Track whether a save request is active.

  function formatSeconds(totalSeconds) { // Format seconds as minutes and seconds.
    const minutes = Math.floor(totalSeconds / 60); // Derive the minute portion.
    const seconds = totalSeconds % 60; // Derive the second portion.
    return `${minutes}:${String(seconds).padStart(2, "0")}`; // Return a zero-padded time string.
  }

  function updateTimerDisplay() { // Refresh the timer text.
    timerDisplay.textContent = formatSeconds(Math.max(remainingSeconds, 0)); // Clamp and display remaining time.
  }

  function saveProgress() { // Persist current quiz answers.
    if (saveInFlight) return; // Skip overlapping save requests.
    saveInFlight = true; // Mark a save request as active.

    const data = new FormData(attemptForm); // Capture current form answers.

    fetch(attemptForm.dataset.saveUrl, { // Send the save request.
      method: "POST", // Post quiz progress to the server.
      body: data, // Send the current form payload.
      headers: { // Include request metadata headers.
        "X-Requested-With": "XMLHttpRequest", // Identify the request as AJAX.
      },
    })
    .finally(() => { // Clear the in-flight flag afterwards.
      saveInFlight = false; // Allow future save requests.
    });
  }

  attemptForm.addEventListener("change", function () { // Save and refresh blanks on answer change.
    saveProgress(); // Persist current quiz answers.

    document.querySelectorAll(".quiz-blank-selected").forEach((span) => { // Update each fill-in display.
      const questionId = span.dataset.questionId; // Read the related question id.
      const checked = attemptForm.querySelector(`input[name="question_${questionId}"]:checked`); // Find the selected answer input.
      span.textContent = checked ? checked.parentElement.querySelector("span").textContent : "_____"; // Show selected text or placeholder.
    });
  });

  updateTimerDisplay(); // Render the initial timer state.

  const timerInterval = window.setInterval(function () { // Tick the timer every second.
    remainingSeconds -= 1; // Decrement the remaining time.
    updateTimerDisplay(); // Refresh the timer display.

    if (remainingSeconds > 0 && remainingSeconds % 15 === 0) { // Autosave every fifteen seconds.
      saveProgress(); // Persist current quiz answers.
    }

    if (remainingSeconds <= 0) { // End the attempt when time expires.
      clearInterval(timerInterval); // Stop the timer interval.
      saveProgress(); // Save final progress before submit.
      attemptForm.submit(); // Submit the quiz attempt form.
    }
  }, 1000);

  document.addEventListener("visibilitychange", function () { // Save when tab visibility changes.
    if (document.visibilityState === "hidden") { // Only save when leaving the tab.
      saveProgress(); // Persist current quiz answers.
    }
  });
}