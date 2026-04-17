// ==================
// Quiz Form Builder
// ==================
(function () { // Scope quiz builder behaviour.
    const questionBuilder = document.getElementById("question-builder"); // Get the question card container.
    const addQuestionButton = document.getElementById("add-question-button"); // Get the add-question button.
    const createQuizForm = document.getElementById("create-quiz-form"); // Get the quiz creation form.
    const questionsPayloadInput = document.getElementById("id_questions_payload"); // Get the hidden payload input.
    const initialQuestionsElement = document.getElementById("initial-quiz-questions"); // Get the initial questions element.
    const initialQuestions = initialQuestionsElement // Parse server-provided questions when present.
      ? JSON.parse(initialQuestionsElement.textContent || "[]") // Parse the embedded JSON payload.
      : []; // Otherwise start with no questions.

    if (!questionBuilder || !addQuestionButton || !createQuizForm || !questionsPayloadInput) { // Exit when required markup is absent.
      return; // Stop initialisation safely.
    }

  let questionCounter = 0; // Track created question cards.

  function escapeHtml(value) { // Escape text for safe HTML insertion.
    return String(value ?? "") // Start with a safe string.
      .replaceAll("&", "&amp;") // Escape ampersands first.
      .replaceAll("<", "&lt;") // Escape opening angle brackets.
      .replaceAll(">", "&gt;") // Escape closing angle brackets.
      .replaceAll('"', "&quot;"); // Escape double quotes.
  }

  function questionTypeOptions(selectedValue) { // Build question type option markup.
    const types = [ // Define supported question types.
      ["MULTIPLE_CHOICE", "Multiple choice"], // Single-correct option questions.
      ["MULTIPLE_SELECT", "Multiple select"], // Multi-correct option questions.
      ["TRUE_FALSE", "True / False"], // Boolean answer questions.
    ];

    return types.map(([value, label]) => { // Render each select option.
      const selected = selectedValue === value ? "selected" : ""; // Mark the current option selected.
      return `<option value="${value}" ${selected}>${label}</option>`; // Return the option markup.
    }).join(""); // Join options into one HTML string.
  }

  function normalizeOptions(type, data = {}) { // Normalise option payload shapes.
    if (type === "TRUE_FALSE") { // True/false questions do not use options.
      return []; // Return an empty options array.
    }

    if (Array.isArray(data.options) && data.options.length) { // Reuse existing structured options when available.
      const options = data.options.map((option) => ({ // Clone each structured option.
        text: option.text || "", // Preserve the option text.
        is_correct: Boolean(option.is_correct), // Preserve the correctness flag.
      }));

      if (options.length === 1) { // Ensure at least two option rows.
        options.push({ text: "", is_correct: false }); // Add a blank second option.
      }

      if (!options.length) { // Provide defaults when options become empty.
        return [ // Return default blank options.
          { text: "", is_correct: type === "MULTIPLE_CHOICE" }, // Preselect first option for single choice.
          { text: "", is_correct: false }, // Add a second blank option.
        ];
      }

      return options; // Return the structured option list.
    }

    const legacyOptions = String(data.options_text || "") // Read legacy newline-separated options.
      .split("\n") // Split into individual lines.
      .map((value) => value.trim()) // Trim each option value.
      .filter(Boolean); // Remove empty lines.

    let options = legacyOptions.map((text) => ({ // Convert legacy text into option objects.
      text, // Preserve the option text.
      is_correct: false, // Default options to incorrect.
    }));

    if (!options.length) { // Provide defaults when nothing exists.
      options = [ // Start with two blank options.
        { text: "", is_correct: type === "MULTIPLE_CHOICE" }, // Preselect first option for single choice.
        { text: "", is_correct: false }, // Add a second blank option.
      ];
    }

    if (options.length === 1) { // Ensure at least two option rows.
      options.push({ text: "", is_correct: false }); // Add a blank second option.
    }

    if (type === "MULTIPLE_CHOICE") { // Restore single-correct selections when needed.
      const correctNumber = Number(data.correct_option || 1); // Read the legacy correct option number.
      if (correctNumber >= 1 && correctNumber <= options.length) { // Apply only valid correct indexes.
        options = options.map((option, index) => ({ // Rebuild options with correctness flags.
          ...option, // Preserve existing option fields.
          is_correct: index === (correctNumber - 1), // Mark the selected correct option.
        }));
      } else if (!options.some((option) => option.is_correct)) { // Ensure one correct answer exists.
        options[0].is_correct = true; // Default the first option to correct.
      }
    }

    if (type === "MULTIPLE_SELECT") { // Restore multi-select correctness when needed.
      const selectedNumbers = String(data.correct_options || "") // Read the legacy selected options field.
        .split(",") // Split the comma-separated numbers.
        .map((part) => Number(part.trim())) // Convert values to numbers.
        .filter((value) => Number.isInteger(value) && value >= 1); // Keep only valid positive integers.

      if (selectedNumbers.length) { // Apply only when valid indexes exist.
        options = options.map((option, index) => ({ // Rebuild options with correctness flags.
          ...option, // Preserve existing option fields.
          is_correct: selectedNumbers.includes(index + 1), // Mark selected options as correct.
        }));
      }
    }

    return options; // Return the normalised option list.
  }

  function renderQuestionSettings(card, type, data = {}) { // Render settings for the chosen question type.
    const settingsContainer = card.querySelector(".question-settings"); // Get the settings container for this card.

    if (type === "TRUE_FALSE") { // Render true/false-specific settings.
      const selectedValue = String(data.correct_true_false || "true").toLowerCase(); // Read the selected boolean value.

      settingsContainer.innerHTML = `
        <div class="form-group">
          <label>Correct answer</label>
          <select class="question-correct-true-false">
            <option value="true" ${selectedValue === "true" ? "selected" : ""}>True</option>
            <option value="false" ${selectedValue === "false" ? "selected" : ""}>False</option>
          </select>
        </div>
      `;
      return; // Stop after rendering true/false settings.
    }

    settingsContainer.innerHTML = `
      <div class="form-group">
        <label>Answer Options</label>
        <div class="quiz-builder-options"></div>
        <button type="button" class="small-button add-option-button">+ Add Answer</button>
        <p class="quiz-builder-note">
          Select the correct answer beside each option. Multiple select can have more than one correct answer.
        </p>
      </div>
    `;

    const optionsContainer = settingsContainer.querySelector(".quiz-builder-options"); // Get the options editor container.
    const addOptionButton = settingsContainer.querySelector(".add-option-button"); // Get the add-option button.
    const radioName = `question_${card.dataset.questionIndex}_correct`; // Build a unique radio group name.
    let options = normalizeOptions(type, data); // Start with normalised option data.

    function ensureMultipleChoiceSelection() { // Guarantee one correct single-choice answer.
      if (type === "MULTIPLE_CHOICE" && options.length && !options.some((option) => option.is_correct)) { // Check whether single choice lacks a correct answer.
        options[0].is_correct = true; // Default the first option to correct.
      }
    }

    function renderOptions() { // Render the editable option rows.
      ensureMultipleChoiceSelection(); // Enforce a single-choice default.

      optionsContainer.innerHTML = options.map((option, index) => `
        <div class="quiz-option-editor-row" data-option-index="${index}">
          <label class="quiz-option-choice">
            <input
              type="${type === "MULTIPLE_CHOICE" ? "radio" : "checkbox"}"
              class="quiz-option-correct"
              ${type === "MULTIPLE_CHOICE" ? `name="${radioName}"` : ""}
              ${option.is_correct ? "checked" : ""}
            >
            <span>${type === "MULTIPLE_CHOICE" ? "Correct" : "Include"}</span>
          </label>

          <input
            type="text"
            class="quiz-option-text"
            value="${escapeHtml(option.text)}"
            placeholder="Answer option ${index + 1}"
          >

          ${
            index >= 2
              ? `<button type="button" class="small-button quiz-option-remove">Remove</button>`
              : `<span class="quiz-option-spacer"></span>`
          }
        </div>
      `).join(""); // Join rows into one HTML string.
    }

    optionsContainer.addEventListener("input", function (event) { // Track option text edits.
      const row = event.target.closest(".quiz-option-editor-row"); // Find the edited option row.
      if (!row || !event.target.classList.contains("quiz-option-text")) { // Ignore unrelated input events.
        return; // Stop when no option text changed.
      }

      const index = Number(row.dataset.optionIndex); // Read the edited option index.
      options[index].text = event.target.value; // Store the edited option text.
    });

    optionsContainer.addEventListener("change", function (event) { // Track correctness changes.
      const row = event.target.closest(".quiz-option-editor-row"); // Find the changed option row.
      if (!row || !event.target.classList.contains("quiz-option-correct")) { // Ignore unrelated change events.
        return; // Stop when correctness did not change.
      }

      const index = Number(row.dataset.optionIndex); // Read the changed option index.

      if (type === "MULTIPLE_CHOICE") { // Enforce one correct single-choice option.
        options = options.map((option, optionIndex) => ({ // Rebuild all option correctness flags.
          ...option, // Preserve existing option fields.
          is_correct: optionIndex === index, // Mark only the chosen option correct.
        }));
        renderOptions(); // Re-render the option rows.
      } else { // Allow multiple correct answers.
        options[index].is_correct = event.target.checked; // Store the checkbox state directly.
      }
    });

    optionsContainer.addEventListener("click", function (event) { // Handle option removal clicks.
      if (!event.target.classList.contains("quiz-option-remove")) { // Ignore unrelated clicks.
        return; // Stop when remove was not clicked.
      }

      const row = event.target.closest(".quiz-option-editor-row"); // Find the clicked option row.
      const index = Number(row.dataset.optionIndex); // Read the removed option index.
      options.splice(index, 1); // Remove the selected option.

      if (options.length < 2) { // Keep at least two option rows.
        options.push({ text: "", is_correct: false }); // Add a blank fallback option.
      }

      renderOptions(); // Re-render the option rows.
    });

    addOptionButton.addEventListener("click", function () { // Append a new blank option.
      options.push({ text: "", is_correct: false }); // Add a blank option object.
      renderOptions(); // Re-render the option rows.
    });

    renderOptions(); // Render the initial option rows.
  }

  function addQuestionCard(data = {}) { // Append a new editable question card.
    questionCounter += 1; // Increment the question counter.

    const card = document.createElement("div"); // Create the question card wrapper.
    card.className = "quiz-question-editor"; // Apply card styling.
    card.dataset.questionIndex = String(questionCounter); // Store the question index on the card.

    const selectedType = data.question_type || "MULTIPLE_CHOICE"; // Default to multiple choice questions.

    card.innerHTML = `
      <div class="assessment-card-topline">
        <h3 class="card-title">Question <span class="question-number">${questionCounter}</span></h3>
        <button type="button" class="small-button remove-question-button">Remove</button>
      </div>

      <div class="form-group">
        <label>Prompt</label>
        <textarea rows="3" class="week-description-input question-prompt">${escapeHtml(data.prompt || "")}</textarea>
      </div>

      <div class="workflow-form-grid workflow-form-grid--triple">
        <div class="form-group">
          <label>Question type</label>
          <select class="question-type">
            ${questionTypeOptions(selectedType)}
          </select>
        </div>

        <div class="form-group">
          <label>Marks - Weighted To Set % of Module</label>
          <input type="number" step="0.25" min="0.25" class="question-marks" value="${escapeHtml(data.marks || "1.00")}">
        </div>
      </div>

      <div class="question-settings"></div>
    `;

    questionBuilder.appendChild(card); // Add the card to the builder.
    renderQuestionSettings(card, selectedType, data); // Render settings for the initial type.

    card.querySelector(".question-type").addEventListener("change", function () { // Re-render settings after type changes.
      renderQuestionSettings(card, this.value, {}); // Reset settings for the chosen type.
    });

    card.querySelector(".remove-question-button").addEventListener("click", function () { // Remove a question card.
      card.remove(); // Remove the card from the DOM.
      updateQuestionNumbers(); // Renumber remaining questions.
    });

    updateQuestionNumbers(); // Refresh visible question numbers.
  }

  function updateQuestionNumbers() { // Sync visible question numbers.
    const cards = [...document.querySelectorAll(".quiz-question-editor")]; // Collect all current question cards.
    cards.forEach((card, index) => { // Walk every question card.
      const numberElement = card.querySelector(".question-number"); // Find the visible question number.
      if (numberElement) { // Update only when element exists.
        numberElement.textContent = String(index + 1); // Show the one-based question number.
      }
    });
  }

  function serializeQuestions() { // Convert cards into a submission payload.
    const cards = [...document.querySelectorAll(".quiz-question-editor")]; // Collect all current question cards.

    return cards.map((card) => { // Serialize one card at a time.
      const questionType = card.querySelector(".question-type").value; // Read the selected question type.
      const payload = { // Start the question payload object.
        prompt: card.querySelector(".question-prompt").value, // Store the question prompt.
        question_type: questionType, // Store the selected question type.
        marks: card.querySelector(".question-marks").value, // Store the question marks.
      };

      if (questionType === "TRUE_FALSE") { // Serialize true/false settings directly.
        payload.correct_true_false = card.querySelector(".question-correct-true-false").value; // Store the selected boolean answer.
      } else { // Serialize option-based question settings.
        payload.options = [...card.querySelectorAll(".quiz-option-editor-row")].map((row) => ({ // Collect all option rows.
          text: row.querySelector(".quiz-option-text").value, // Store the option text.
          is_correct: row.querySelector(".quiz-option-correct").checked, // Store the correctness flag.
        }));
      }

      return payload; // Return the serialized question payload.
    });
  }

  addQuestionButton.addEventListener("click", function () { // Add a blank question card.
    addQuestionCard({}); // Append a new empty question.
  });

  createQuizForm.addEventListener("submit", function () { // Build JSON before form submit.
    questionsPayloadInput.value = JSON.stringify(serializeQuestions()); // Store the serialized questions payload.
  });

  if (initialQuestions.length) { // Restore existing quiz questions when present.
    initialQuestions.forEach((question) => addQuestionCard(question)); // Add one card per existing question.
  } else { // Otherwise start with one blank question.
    addQuestionCard({}); // Append the initial empty question.
  }
})();