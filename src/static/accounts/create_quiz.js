const questionBuilder = document.getElementById("question-builder");
const addQuestionButton = document.getElementById("add-question-button");
const createQuizForm = document.getElementById("create-quiz-form");
const questionsPayloadInput = document.getElementById("id_questions_payload");
const initialQuestions = JSON.parse(document.getElementById("initial-quiz-questions").textContent || "[]");

let questionCounter = 0;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function questionTypeOptions(selectedValue) {
  const types = [
    ["MULTIPLE_CHOICE", "Multiple choice"],
    ["MULTIPLE_SELECT", "Multiple select"],
    ["TRUE_FALSE", "True / False"],
  ];

  return types.map(([value, label]) => {
    const selected = selectedValue === value ? "selected" : "";
    return `<option value="${value}" ${selected}>${label}</option>`;
  }).join("");
}

function normalizeOptions(type, data = {}) {
  if (type === "TRUE_FALSE") {
    return [];
  }

  if (Array.isArray(data.options) && data.options.length) {
    const options = data.options.map((option) => ({
      text: option.text || "",
      is_correct: Boolean(option.is_correct),
    }));

    if (options.length === 1) {
      options.push({ text: "", is_correct: false });
    }

    if (!options.length) {
      return [
        { text: "", is_correct: type === "MULTIPLE_CHOICE" },
        { text: "", is_correct: false },
      ];
    }

    return options;
  }

  const legacyOptions = String(data.options_text || "")
    .split("\n")
    .map((value) => value.trim())
    .filter(Boolean);

  let options = legacyOptions.map((text) => ({
    text,
    is_correct: false,
  }));

  if (!options.length) {
    options = [
      { text: "", is_correct: type === "MULTIPLE_CHOICE" },
      { text: "", is_correct: false },
    ];
  }

  if (options.length === 1) {
    options.push({ text: "", is_correct: false });
  }

  if (type === "MULTIPLE_CHOICE") {
    const correctNumber = Number(data.correct_option || 1);
    if (correctNumber >= 1 && correctNumber <= options.length) {
      options = options.map((option, index) => ({
        ...option,
        is_correct: index === (correctNumber - 1),
      }));
    } else if (!options.some((option) => option.is_correct)) {
      options[0].is_correct = true;
    }
  }

  if (type === "MULTIPLE_SELECT") {
    const selectedNumbers = String(data.correct_options || "")
      .split(",")
      .map((part) => Number(part.trim()))
      .filter((value) => Number.isInteger(value) && value >= 1);

    if (selectedNumbers.length) {
      options = options.map((option, index) => ({
        ...option,
        is_correct: selectedNumbers.includes(index + 1),
      }));
    }
  }

  return options;
}

function renderQuestionSettings(card, type, data = {}) {
  const settingsContainer = card.querySelector(".question-settings");

  if (type === "TRUE_FALSE") {
    const selectedValue = String(data.correct_true_false || "true").toLowerCase();

    settingsContainer.innerHTML = `
      <div class="form-group">
        <label>Correct answer</label>
        <select class="question-correct-true-false">
          <option value="true" ${selectedValue === "true" ? "selected" : ""}>True</option>
          <option value="false" ${selectedValue === "false" ? "selected" : ""}>False</option>
        </select>
      </div>
    `;
    return;
  }

  settingsContainer.innerHTML = `
    <div class="form-group">
      <label>Answer options</label>
      <div class="quiz-builder-options"></div>
      <button type="button" class="small-button add-option-button">+ Add answer</button>
      <p class="quiz-builder-note">
        Select the correct answer beside each option. Multiple select can have more than one correct answer.
      </p>
    </div>
  `;

  const optionsContainer = settingsContainer.querySelector(".quiz-builder-options");
  const addOptionButton = settingsContainer.querySelector(".add-option-button");
  const radioName = `question_${card.dataset.questionIndex}_correct`;
  let options = normalizeOptions(type, data);

  function ensureMultipleChoiceSelection() {
    if (type === "MULTIPLE_CHOICE" && options.length && !options.some((option) => option.is_correct)) {
      options[0].is_correct = true;
    }
  }

  function renderOptions() {
    ensureMultipleChoiceSelection();

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
    `).join("");
  }

  optionsContainer.addEventListener("input", function (event) {
    const row = event.target.closest(".quiz-option-editor-row");
    if (!row || !event.target.classList.contains("quiz-option-text")) {
      return;
    }

    const index = Number(row.dataset.optionIndex);
    options[index].text = event.target.value;
  });

  optionsContainer.addEventListener("change", function (event) {
    const row = event.target.closest(".quiz-option-editor-row");
    if (!row || !event.target.classList.contains("quiz-option-correct")) {
      return;
    }

    const index = Number(row.dataset.optionIndex);

    if (type === "MULTIPLE_CHOICE") {
      options = options.map((option, optionIndex) => ({
        ...option,
        is_correct: optionIndex === index,
      }));
      renderOptions();
    } else {
      options[index].is_correct = event.target.checked;
    }
  });

  optionsContainer.addEventListener("click", function (event) {
    if (!event.target.classList.contains("quiz-option-remove")) {
      return;
    }

    const row = event.target.closest(".quiz-option-editor-row");
    const index = Number(row.dataset.optionIndex);
    options.splice(index, 1);

    if (options.length < 2) {
      options.push({ text: "", is_correct: false });
    }

    renderOptions();
  });

  addOptionButton.addEventListener("click", function () {
    options.push({ text: "", is_correct: false });
    renderOptions();
  });

  renderOptions();
}

function addQuestionCard(data = {}) {
  questionCounter += 1;

  const card = document.createElement("div");
  card.className = "quiz-question-editor";
  card.dataset.questionIndex = String(questionCounter);

  const selectedType = data.question_type || "MULTIPLE_CHOICE";

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
        <label>Marks</label>
        <input type="number" step="0.25" min="0.25" class="question-marks" value="${escapeHtml(data.marks || "1.00")}">
      </div>
    </div>

    <div class="question-settings"></div>
  `;

  questionBuilder.appendChild(card);
  renderQuestionSettings(card, selectedType, data);

  card.querySelector(".question-type").addEventListener("change", function () {
    renderQuestionSettings(card, this.value, {});
  });

  card.querySelector(".remove-question-button").addEventListener("click", function () {
    card.remove();
    updateQuestionNumbers();
  });

  updateQuestionNumbers();
}

function updateQuestionNumbers() {
  const cards = [...document.querySelectorAll(".quiz-question-editor")];
  cards.forEach((card, index) => {
    const numberElement = card.querySelector(".question-number");
    if (numberElement) {
      numberElement.textContent = String(index + 1);
    }
  });
}

function serializeQuestions() {
  const cards = [...document.querySelectorAll(".quiz-question-editor")];

  return cards.map((card) => {
    const questionType = card.querySelector(".question-type").value;
    const payload = {
      prompt: card.querySelector(".question-prompt").value,
      question_type: questionType,
      marks: card.querySelector(".question-marks").value,
    };

    if (questionType === "TRUE_FALSE") {
      payload.correct_true_false = card.querySelector(".question-correct-true-false").value;
    } else {
      payload.options = [...card.querySelectorAll(".quiz-option-editor-row")].map((row) => ({
        text: row.querySelector(".quiz-option-text").value,
        is_correct: row.querySelector(".quiz-option-correct").checked,
      }));
    }

    return payload;
  });
}

addQuestionButton.addEventListener("click", function () {
  addQuestionCard({});
});

createQuizForm.addEventListener("submit", function () {
  questionsPayloadInput.value = JSON.stringify(serializeQuestions());
});

if (initialQuestions.length) {
  initialQuestions.forEach((question) => addQuestionCard(question));
} else {
  addQuestionCard({});
}