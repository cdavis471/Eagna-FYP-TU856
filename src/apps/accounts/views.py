from django.contrib.auth.decorators import login_required  # Imports decorator to ensure some views are only accessible to authenticated users
from django.contrib.auth.views import LoginView  # Imports Django’s built-in class-based login view for handling authentication
from django.shortcuts import redirect, render, get_object_or_404  # Common shortcuts for redirects, rendering templates, and fetching objects or returning 404
from django.urls import reverse  # Used to dynamically resolve URL patterns by their name
from django.utils import timezone  # Provides timezone-aware datetime utilities compatible with Django settings
from django.http import Http404, JsonResponse  # Exception used to immediately return a 404 Not Found response / Class for returning JSON responses in views
from django.db.models import Count, Q  # ORM helpers: Count for aggregation and Q for complex query filters
from django.views.decorators.http import require_http_methods  # Decorator to restrict allowed HTTP methods per view
from datetime import datetime, timedelta  # Standard library datetime class used for parsing date and time input / timedelta for date arithmetic
from decimal import Decimal, InvalidOperation  # Standard library Decimal class for precise decimal arithmetic / InvalidOperation for handling invalid decimal operations
from django.contrib import messages  # Django's messaging framework for passing one-time messages to templates
from django.core.files.base import ContentFile  # Utility for creating file objects from raw content, used in file handling
from django.db import transaction  # Provides atomic transaction management for database operations, ensuring data integrity
from .document_parsing import build_rendered_html_from_blocks, parse_uploaded_office_file
from .models import User, Module, Assignment, AssignmentSubmission, AssignmentGrade, AssignmentFile, SubmissionFile, ModuleWeek, ModuleWeekFile, ParsedDocument, ParsedDocumentImage, Quiz, QuizQuestion, QuizOption, QuizAttempt, QuizAnswer  # Imports all custom models referenced by these views
import re  # Regular expressions module, used for validating input
import json # Standard library for working with JSON data, used in some views for parsing or returning JSON payloads

# Temporary
import traceback
from django.http import HttpResponse
from django.utils.html import escape

# Shared Navigation Menu Items (used in multiple views for consistent header/footer links)
def _shared_nav_items():
    return [
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},
        {"label": "Website", "url": "https://www.tudublin.ie/"},
    ]

# Parsed Document Handling
# Rebuild the rendered HTML for a parsed document based on its blocks and associated images, and optionally save the updated document. 
# This is used after parsing a new document or when updating an existing one to ensure the rendered HTML reflects the current parsed content and images.
def _rebuild_parsed_document_html(parsed_document: ParsedDocument, save: bool = True) -> str:
    image_lookup = {
        image.token: {
            "src": image.image.url,
            "alt_text": image.alt_text or "",
        }
        for image in parsed_document.images.all()
    }

    parsed_document.rendered_html = build_rendered_html_from_blocks(
        parsed_document.parsed_blocks or [],
        image_lookup=image_lookup,
    )

    if save:
        parsed_document.save(update_fields=["rendered_html", "updated_at"])

    return parsed_document.rendered_html

# Persistent Parsed Document Creation with Error Handling
# This function takes the raw parsed payload from the document parsing process, creates a ParsedDocument record, saves associated images, and builds the rendered HTML. 
# If any step fails, it ensures that all created records and files are cleaned up to maintain data integrity.
def _persist_parsed_document(
    *,
    parsed_payload: dict,
    week_file: ModuleWeekFile | None = None,
    assignment_file: AssignmentFile | None = None,
) -> ParsedDocument:
    parsed_document = ParsedDocument.objects.create(
        week_file=week_file,
        assignment_file=assignment_file,
        source_extension=parsed_payload["extension"],
        parser_status=ParsedDocument.Status.PROCESSING,
        parsed_blocks=parsed_payload["blocks"],
        page_count=parsed_payload["page_count"],
    )

    created_images: list[ParsedDocumentImage] = []

    try:
        for image_data in parsed_payload.get("images", []):
            image_obj = ParsedDocumentImage(
                parsed_document=parsed_document,
                token=image_data["token"],
                display_order=image_data.get("display_order") or 0,
                page_number=image_data.get("page_number"),
                original_name=image_data.get("filename", ""),
                alt_text=image_data.get("alt_text", ""),
            )
            image_obj.image.save(
                image_data["filename"],
                ContentFile(image_data["content"]),
                save=True,
            )
            created_images.append(image_obj)

        _rebuild_parsed_document_html(parsed_document, save=False)

        parsed_document.parser_status = ParsedDocument.Status.READY
        parsed_document.parse_error = ""
        parsed_document.save(update_fields=["rendered_html", "parser_status", "parse_error", "updated_at"])

        return parsed_document

    except Exception:
        for image in created_images:
            if image.image:
                image.image.delete(save=False)

        ParsedDocumentImage.objects.filter(parsed_document=parsed_document).delete()
        parsed_document.delete()
        raise

# Authorization Check for Parsed Document Access
# This function retrieves a ParsedDocument by its ID and checks if the given user has permission to access it based on their role and module associations. 
# It returns the parsed document and its source module if authorized, or raises a 404 error if the document doesn't exist or the user isn't authorized to view it.
def _get_authorised_parsed_document(parsed_id: int, user: User) -> tuple[ParsedDocument, Module]:
    parsed_document = get_object_or_404(
        ParsedDocument.objects.select_related(
            "week_file__week__module",
            "assignment_file__assignment__module",
        ).prefetch_related("images"),
        pk=parsed_id,
    )

    module = parsed_document.get_source_module()
    if module is None:
        raise Http404("Parsed document not found")

    if user.is_student():
        if not user.student_profile.modules.filter(pk=module.pk).exists():
            raise Http404("Parsed document not found")
    elif user.is_lecturer():
        if not user.lecturer_profile.modules.filter(pk=module.pk).exists():
            raise Http404("Parsed document not found")
    else:
        raise Http404("Parsed document not found")

    return parsed_document, module

# Rollover Maintenance
def _rollover_modules_if_due():
    today = timezone.localdate()
    qs = Module.objects.filter(is_active=True).exclude(start_date__isnull=True)
    for m in qs:
        if m.needs_rollover(today=today):
            m.rollover(today=today)

def _parse_form_datetime(date_str, time_str, label, errors):
    if not date_str:
        errors.append(f"{label} date is required.")
        return None
    if not time_str:
        errors.append(f"{label} time is required.")
        return None

    try:
        dt = datetime.fromisoformat(f"{date_str} {time_str}")
    except ValueError:
        errors.append(f"Invalid {label.lower()} date/time format.")
        return None

    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _parse_decimal_value(raw_value, label, errors, minimum=None):
    try:
        value = Decimal(str(raw_value).strip())
    except (InvalidOperation, TypeError, ValueError):
        errors.append(f"{label} must be a valid number.")
        return None

    if minimum is not None and value < Decimal(str(minimum)):
        errors.append(f"{label} must be at least {minimum}.")
        return None

    return value.quantize(Decimal("0.01"))


def _parse_positive_int(raw_value, label, errors, minimum=1):
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError):
        errors.append(f"{label} must be a whole number.")
        return None

    if value < minimum:
        errors.append(f"{label} must be at least {minimum}.")
        return None

    return value


def _parse_questions_payload(raw_payload, errors):
    try:
        payload = json.loads(raw_payload or "[]")
    except json.JSONDecodeError:
        errors.append("Question data could not be read. Please rebuild the quiz form and try again.")
        return []

    if not isinstance(payload, list) or not payload:
        errors.append("At least one question is required.")
        return []

    valid_types = {choice[0] for choice in QuizQuestion.Type.choices}
    parsed_questions = []

    for index, item in enumerate(payload, start=1):
        prompt = (item.get("prompt") or "").strip()
        question_type = (item.get("question_type") or "").strip()
        marks = _parse_decimal_value(item.get("marks", "1"), f"Question {index} marks", errors, minimum=Decimal("0.25"))

        if not prompt:
            errors.append(f"Question {index} prompt is required.")

        if question_type not in valid_types:
            errors.append(f"Question {index} has an invalid question type.")

        normalized = {
            "prompt": prompt,
            "question_type": question_type,
            "marks": marks or Decimal("1.00"),
            "options": [],
        }

        if question_type in {
            QuizQuestion.Type.MULTIPLE_CHOICE,
            QuizQuestion.Type.MULTIPLE_SELECT,
            QuizQuestion.Type.FILL_BLANK,
        }:
            options = [
                line.strip()
                for line in (item.get("options_text") or "").splitlines()
                if line.strip()
            ]

            if len(options) < 2:
                errors.append(f"Question {index} must have at least two options.")

            if question_type in {
                QuizQuestion.Type.MULTIPLE_CHOICE,
                QuizQuestion.Type.FILL_BLANK,
            }:
                try:
                    correct_number = int(str(item.get("correct_option") or "").strip())
                except ValueError:
                    correct_number = None
                    errors.append(f"Question {index} must have one correct option number.")

                if correct_number is not None and not (1 <= correct_number <= len(options)):
                    errors.append(f"Question {index} correct option number is out of range.")

                normalized["options"] = [
                    {
                        "text": option_text,
                        "is_correct": (position == (correct_number - 1)) if correct_number is not None else False,
                    }
                    for position, option_text in enumerate(options)
                ]

            elif question_type == QuizQuestion.Type.MULTIPLE_SELECT:
                raw_correct_numbers = str(item.get("correct_options") or "")
                parsed_numbers = []

                for part in raw_correct_numbers.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        parsed_numbers.append(int(part))
                    except ValueError:
                        errors.append(f"Question {index} multiple-select correct answers must be comma-separated numbers.")
                        parsed_numbers = []
                        break

                parsed_numbers = sorted(set(parsed_numbers))

                if not parsed_numbers:
                    errors.append(f"Question {index} must have at least one correct option number.")

                if any(number < 1 or number > len(options) for number in parsed_numbers):
                    errors.append(f"Question {index} has a correct option number outside the available options.")

                normalized["options"] = [
                    {
                        "text": option_text,
                        "is_correct": ((position + 1) in parsed_numbers),
                    }
                    for position, option_text in enumerate(options)
                ]

        elif question_type == QuizQuestion.Type.TRUE_FALSE:
            correct_true_false = (item.get("correct_true_false") or "").strip().lower()
            if correct_true_false not in {"true", "false"}:
                errors.append(f"Question {index} must choose either True or False as the correct answer.")

            normalized["options"] = [
                {"text": "True", "is_correct": correct_true_false == "true"},
                {"text": "False", "is_correct": correct_true_false == "false"},
            ]

        parsed_questions.append(normalized)

    return parsed_questions


def _create_quiz_questions(quiz, question_payloads):
    for question_index, question_data in enumerate(question_payloads, start=1):
        question = QuizQuestion.objects.create(
            quiz=quiz,
            prompt=question_data["prompt"],
            question_type=question_data["question_type"],
            marks=question_data["marks"],
            display_order=question_index,
        )

        for option_index, option_data in enumerate(question_data["options"], start=1):
            QuizOption.objects.create(
                question=question,
                text=option_data["text"],
                is_correct=option_data["is_correct"],
                display_order=option_index,
            )


def _get_student_quiz_state(quiz, student, now=None):
    now = now or timezone.now()

    attempts = list(
        quiz.attempts.filter(student=student).order_by("-attempt_number", "-started_at")
    )
    active_attempt = next((attempt for attempt in attempts if attempt.is_active()), None)
    latest_submitted_attempt = next((attempt for attempt in attempts if attempt.submitted_at), None)

    attempts_used = len(attempts)
    remaining_attempts = max(quiz.max_attempts - attempts_used, 0)

    if active_attempt:
        status_label = "Attempt in progress"
        is_clickable = True
    elif not quiz.is_published:
        status_label = "Draft"
        is_clickable = False
    elif now < quiz.open_datetime:
        status_label = "Not open yet"
        is_clickable = False
    elif now > quiz.close_datetime:
        status_label = "Closed"
        is_clickable = bool(latest_submitted_attempt)
    elif remaining_attempts > 0:
        status_label = "Open"
        is_clickable = True
    else:
        status_label = "Attempts used"
        is_clickable = bool(latest_submitted_attempt)

    return {
        "active_attempt": active_attempt,
        "latest_submitted_attempt": latest_submitted_attempt,
        "attempts_used": attempts_used,
        "remaining_attempts": remaining_attempts,
        "status_label": status_label,
        "is_clickable": is_clickable,
    }


def _build_question_rows(quiz, attempt=None):
    answer_lookup = {}
    if attempt is not None:
        answer_lookup = {
            answer.question_id: answer
            for answer in attempt.answers.all()
        }

    rows = []
    for question_number, question in enumerate(
        quiz.questions.prefetch_related("options").all(),
        start=1,
    ):
        answer = answer_lookup.get(question.id)
        selected_option_id = answer.selected_option_id if answer else None
        selected_option_ids = set(answer.selected_option_ids or []) if answer else set()

        options = []
        for option in question.options.all():
            option_is_selected = (
                option.id == selected_option_id
                or option.id in selected_option_ids
            )
            options.append(
                {
                    "id": option.id,
                    "text": option.text,
                    "is_correct": option.is_correct,
                    "selected": option_is_selected,
                }
            )

        selected_texts = [option["text"] for option in options if option["selected"]]
        correct_texts = [option["text"] for option in options if option["is_correct"]]

        rows.append(
            {
                "id": question.id,
                "number": question_number,
                "prompt": question.prompt,
                "question_type": question.question_type,
                "marks": question.marks,
                "awarded_marks": answer.awarded_marks if answer else Decimal("0.00"),
                "options": options,
                "selected_answer_text": ", ".join(selected_texts) if selected_texts else "No answer selected",
                "correct_answer_text": ", ".join(correct_texts) if correct_texts else "",
            }
        )

    return rows


def _upsert_attempt_answers(attempt, post_data):
    quiz = attempt.quiz
    questions = quiz.questions.prefetch_related("options").all()

    for question in questions:
        answer, _ = QuizAnswer.objects.get_or_create(
            attempt=attempt,
            question=question,
        )

        valid_option_ids = {option.id for option in question.options.all()}

        if question.question_type == QuizQuestion.Type.MULTIPLE_SELECT:
            raw_ids = post_data.getlist(f"question_{question.id}")
            cleaned_ids = []
            for raw_id in raw_ids:
                try:
                    option_id = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if option_id in valid_option_ids and option_id not in cleaned_ids:
                    cleaned_ids.append(option_id)

            answer.selected_option = None
            answer.selected_option_ids = cleaned_ids
            answer.save(update_fields=["selected_option", "selected_option_ids"])

        else:
            raw_id = (post_data.get(f"question_{question.id}") or "").strip()
            selected_option = None
            if raw_id:
                try:
                    option_id = int(raw_id)
                except ValueError:
                    option_id = None
                if option_id in valid_option_ids:
                    selected_option = question.options.get(pk=option_id)

            answer.selected_option = selected_option
            answer.selected_option_ids = []
            answer.save(update_fields=["selected_option", "selected_option_ids"])


def _grade_attempt(attempt, auto_submitted=False):
    quiz = attempt.quiz
    questions = quiz.questions.prefetch_related("options").all()
    answer_lookup = {
        answer.question_id: answer
        for answer in attempt.answers.all()
    }

    total_raw = Decimal("0.00")
    total_possible = Decimal("0.00")

    for question in questions:
        total_possible += question.marks

        answer, _ = QuizAnswer.objects.get_or_create(
            attempt=attempt,
            question=question,
        )

        awarded = Decimal("0.00")
        is_correct = False
        correct_options = [option for option in question.options.all() if option.is_correct]

        if question.question_type in {
            QuizQuestion.Type.MULTIPLE_CHOICE,
            QuizQuestion.Type.TRUE_FALSE,
            QuizQuestion.Type.FILL_BLANK,
        }:
            correct_option = correct_options[0] if correct_options else None
            if correct_option and answer.selected_option_id == correct_option.id:
                awarded = question.marks
                is_correct = True

        elif question.question_type == QuizQuestion.Type.MULTIPLE_SELECT:
            correct_ids = {option.id for option in correct_options}
            selected_ids = set(answer.selected_option_ids or [])

            if correct_ids:
                unit_value = question.marks / Decimal(len(correct_ids))
                positives = unit_value * Decimal(len(selected_ids & correct_ids))
                negatives = unit_value * Decimal(len(selected_ids - correct_ids))
                awarded = positives - negatives

                if awarded < Decimal("0.00"):
                    awarded = Decimal("0.00")
                if awarded > question.marks:
                    awarded = question.marks

                is_correct = selected_ids == correct_ids

        awarded = awarded.quantize(Decimal("0.01"))
        answer.awarded_marks = awarded
        answer.is_correct = is_correct
        answer.save(update_fields=["awarded_marks", "is_correct"])

        total_raw += awarded

    if total_possible > Decimal("0.00"):
        weighted_score = (total_raw / total_possible) * quiz.max_mark
    else:
        weighted_score = Decimal("0.00")

    attempt.raw_score = total_raw.quantize(Decimal("0.01"))
    attempt.weighted_score = weighted_score.quantize(Decimal("0.01"))
    attempt.submitted_at = timezone.now()
    attempt.status = (
        QuizAttempt.Status.AUTO_SUBMITTED
        if auto_submitted
        else QuizAttempt.Status.SUBMITTED
    )
    attempt.save(update_fields=["raw_score", "weighted_score", "submitted_at", "status"])

    return attempt


def _auto_submit_expired_attempt_if_needed(quiz, student):
    active_attempt = (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )

    if active_attempt and active_attempt.is_expired():
        _grade_attempt(active_attempt, auto_submitted=True)

    return (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )

def _build_student_module_assessment_items(module, student, now):
    submitted_assignment_ids = set(
        AssignmentSubmission.objects.filter(
            assignment__module=module,
            student=student,
        ).values_list("assignment_id", flat=True)
    )

    items = []

    for assignment in module.assignments.prefetch_related("files__parsed_document").all():
        items.append(
            {
                "kind": "assignment",
                "label": "Assignment",
                "title": assignment.title,
                "description": assignment.description,
                "url": reverse("accounts:assignment_detail", args=[module.code, assignment.id]),
                "is_clickable": True,
                "date_label": "Due",
                "date_value": assignment.due_datetime,
                "max_mark": assignment.max_mark,
                "status_label": "Submitted" if assignment.id in submitted_assignment_ids else "",
                "detail_line": "",
                "file_names": [f.original_name or f.file.name for f in assignment.files.all()],
                "sort_at": assignment.due_datetime,
            }
        )

    for quiz in module.quizzes.filter(is_published=True).all():
        state = _get_student_quiz_state(quiz, student, now=now)
        items.append(
            {
                "kind": "quiz",
                "label": "Quiz",
                "title": quiz.title,
                "description": quiz.description,
                "url": reverse("accounts:quiz_detail", args=[module.code, quiz.id]),
                "is_clickable": state["is_clickable"],
                "date_label": "Closes",
                "date_value": quiz.close_datetime,
                "max_mark": quiz.max_mark,
                "status_label": state["status_label"],
                "detail_line": f"Time limit: {quiz.time_limit_minutes} mins · Attempts: {state['attempts_used']}/{quiz.max_attempts}",
                "file_names": [],
                "sort_at": quiz.close_datetime,
            }
        )

    return sorted(items, key=lambda item: item["sort_at"])


def _build_lecturer_module_assessment_items(module):
    items = []

    assignments = (
        module.assignments
        .all()
        .annotate(
            total_submissions=Count("submissions", distinct=True),
            ungraded_submissions=Count(
                "submissions",
                filter=Q(submissions__grade__isnull=True),
                distinct=True,
            ),
        )
        .prefetch_related("files__parsed_document")
    )

    for assignment in assignments:
        items.append(
            {
                "kind": "assignment",
                "label": "Assignment",
                "title": assignment.title,
                "description": assignment.description,
                "url": reverse("accounts:assignment_detail", args=[module.code, assignment.id]),
                "is_clickable": True,
                "date_label": "Due",
                "date_value": assignment.due_datetime,
                "max_mark": assignment.max_mark,
                "status_label": "",
                "detail_line": f"Submissions: {assignment.total_submissions} ({assignment.ungraded_submissions} ungraded)",
                "file_names": [f.original_name or f.file.name for f in assignment.files.all()],
                "sort_at": assignment.due_datetime,
            }
        )

    quizzes = (
        module.quizzes
        .all()
        .annotate(
            total_attempts=Count("attempts", distinct=True),
            submitted_attempts=Count(
                "attempts",
                filter=Q(attempts__submitted_at__isnull=False),
                distinct=True,
            ),
        )
    )

    for quiz in quizzes:
        items.append(
            {
                "kind": "quiz",
                "label": "Quiz",
                "title": quiz.title,
                "description": quiz.description,
                "url": reverse("accounts:quiz_detail", args=[module.code, quiz.id]),
                "is_clickable": True,
                "date_label": "Closes",
                "date_value": quiz.close_datetime,
                "max_mark": quiz.max_mark,
                "status_label": "Published" if quiz.is_published else "Draft",
                "detail_line": f"Attempts started: {quiz.total_attempts} · Submitted: {quiz.submitted_attempts}",
                "file_names": [],
                "sort_at": quiz.close_datetime,
            }
        )

    return sorted(items, key=lambda item: item["sort_at"])

def _build_student_dashboard_items(student, modules_qs, now):
    items = []

    upcoming_assignments = (
        Assignment.objects.filter(
            module__in=modules_qs,
            due_datetime__gte=now,
        )
        .exclude(submissions__student=student)
        .select_related("module")
        .order_by("due_datetime")
    )

    for assignment in upcoming_assignments:
        items.append(
            {
                "kind": "assignment",
                "label": "Assignment",
                "title": assignment.title,
                "description": assignment.description,
                "module_title": assignment.module.title,
                "module_code": assignment.module.code,
                "url": reverse("accounts:assignment_detail", args=[assignment.module.code, assignment.id]),
                "is_clickable": True,
                "date_label": "Due",
                "date_value": assignment.due_datetime,
                "max_mark": assignment.max_mark,
                "status_label": "",
                "detail_line": "",
                "sort_at": assignment.due_datetime,
            }
        )

    candidate_quizzes = (
        Quiz.objects.filter(
            module__in=modules_qs,
            is_published=True,
            close_datetime__gte=now,
        )
        .select_related("module")
        .order_by("close_datetime")
    )

    for quiz in candidate_quizzes:
        state = _get_student_quiz_state(quiz, student, now=now)

        if state["remaining_attempts"] <= 0 and not state["active_attempt"]:
            continue

        items.append(
            {
                "kind": "quiz",
                "label": "Quiz",
                "title": quiz.title,
                "description": quiz.description,
                "module_title": quiz.module.title,
                "module_code": quiz.module.code,
                "url": reverse("accounts:quiz_detail", args=[quiz.module.code, quiz.id]),
                "is_clickable": state["is_clickable"],
                "date_label": "Closes",
                "date_value": quiz.close_datetime,
                "max_mark": quiz.max_mark,
                "status_label": state["status_label"],
                "detail_line": f"Time limit: {quiz.time_limit_minutes} mins · Attempts: {state['attempts_used']}/{quiz.max_attempts}",
                "sort_at": quiz.close_datetime,
            }
        )

    return sorted(items, key=lambda item: item["sort_at"])[:8]

class RoleBasedLoginView(LoginView):  # Custom login view that extends Django’s built-in LoginView to add role-based redirects
    template_name = "accounts/login.html"  # Specifies the template to use when displaying the login form

    def get_success_url(self):  # Overrides method to control where a user is redirected after successful login
        # Redirect based on role
        user: User = self.request.user  # Grabs the authenticated user object from the current request
        if user.is_student():  # If the user has the student role, send them to the student dashboard
            return "/student-dashboard/"
        if user.is_lecturer():  # If the user has the lecturer role, send them to the lecturer dashboard
            return "/lecturer-dashboard/"
        return "/"  # fallback  # If neither role matches, fall back to redirecting to the site root
    
def register_student(request):
    # If someone is already logged in, don't let them register again
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""
        course_raw = request.POST.get("course") or ""
        course = _normalize_course_code(course_raw)
        module_ids = request.POST.getlist("module_ids")  # multiple values

        errors: dict[str, list[str]] = {}

        # Presence Checks
        if not first_name:
            errors.setdefault("first_name", []).append("First name is required.")
        if not last_name:
            errors.setdefault("last_name", []).append("Surname is required.")
        if not email:
            errors.setdefault("email", []).append("Student email is required.")
        if not password1 or not password2:
            errors.setdefault("password", []).append("Both password fields are required.")
        if not course:
            errors.setdefault("course", []).append("Course code is required.")
        elif not COURSE_CODE_RE.match(course):
            errors.setdefault("course", []).append(
                "Course code must be 3–10 characters and contain only letters / numbers."
            )
        if not module_ids:
            errors.setdefault("modules", []).append("Please select at least one module.")

        # Email Rules
        if email and not email.endswith("@mytudublin.ie"):
            errors.setdefault("email", []).append(
                "Student email must end with @mytudublin.ie."
            )

        if email and User.objects.filter(username=email).exists():
            errors.setdefault("email", []).append(
                "An account already exists for this email address."
            )

        # Password Rules
        if password1 and password2 and password1 != password2:
            errors.setdefault("password", []).append("Passwords do not match.")

        pw_errors = _validate_password_strength(password1)
        if pw_errors:
            errors.setdefault("password", []).extend(pw_errors)

        # Course validity: must be one of the codes from allowed_courses
        valid_courses = _get_all_valid_courses()
        if course and course not in valid_courses:
            errors.setdefault("course", []).append(
                "Selected course is not recognised for any module."
            )

        # Modules must exist and allow this course
        selected_modules = []
        if module_ids:
            selected_modules = list(
                Module.objects.filter(pk__in=module_ids, is_active=True).filter(
                    Q(allowed_courses=[]) | Q(allowed_courses__contains=[course])
                )
            )
            if len(selected_modules) != len(module_ids):
                errors.setdefault("modules", []).append(
                    "One or more selected modules are invalid for the chosen course."
                )

        if errors:
            # Re-render form with errors + previous data
            all_modules = Module.objects.filter(is_active=True).order_by("code")
            context = {
                "errors": errors,
                "form_data": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "course": course,
                    "module_ids": module_ids,
                },
                "valid_courses": valid_courses,
                "modules": all_modules,
            }
            return render(request, "accounts/registration.html", context)

        # Create User + StudentProfile
        user = User.objects.create_user(
            username=email,         # login identifier
            email=email,            # store real email as well
            password=password1,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.STUDENT,
        )

        # Use the part before '@' as student_number (e.g. 'C20441826')
        student_number = email.split("@")[0]

        from .models import StudentProfile  # local import to avoid circulars

        student_profile = StudentProfile.objects.create(
            user=user,
            student_number=student_number,
            course=course,  # store course code here
        )

        # Link modules (through ModuleEnrollmentStudent via the M2M)
        student_profile.modules.set(selected_modules)

        messages.success(
            request,
            "Registration Successful. You can now log in with your student email and password!",
        )
        return redirect("accounts:login")

    # ---- GET: show empty form ----
    valid_courses = _get_all_valid_courses()
    all_modules = Module.objects.filter(is_active=True).order_by("code")

    context = {
        "errors": {},
        "form_data": {},
        "valid_courses": valid_courses,
        "modules": all_modules,
    }
    return render(request, "accounts/registration.html", context)

@login_required
def dashboard(request):
    _rollover_modules_if_due()
    user: User = request.user

    nav_items = _shared_nav_items()
    now = timezone.now()

    if user.is_student():
        template = "accounts/student_dashboard.html"
        student = user.student_profile

        modules_qs = (
            student.modules
            .filter(is_active=True)
            .prefetch_related("lecturers__user")
            .order_by("code")
        )

        upcoming_items = _build_student_dashboard_items(student, modules_qs, now)

        context = {
            "user": user,
            "nav_items": nav_items,
            "modules": modules_qs,
            "upcoming_items": upcoming_items,
        }

    elif user.is_lecturer():
        template = "accounts/lecturer_dashboard.html"
        lecturer = user.lecturer_profile

        modules_qs = lecturer.modules.filter(is_active=True).order_by("code")

        ungraded_submissions_qs = (
            AssignmentSubmission.objects.filter(
                assignment__module__in=modules_qs,
                grade__isnull=True,
            )
            .select_related(
                "assignment",
                "assignment__module",
                "student",
                "student__user",
            )
            .order_by("-submitted_at")[:10]
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "modules": modules_qs,
            "ungraded_submissions": ungraded_submissions_qs,
        }

    else:
        return redirect("accounts:login")

    return render(request, template, context)


@login_required
def module_detail(request, code):
    user: User = request.user
    nav_items = _shared_nav_items()

    try:
        module = (
            Module.objects
            .prefetch_related("assignments__files", "quizzes")
            .get(code=code)
        )
    except Module.DoesNotExist:
        raise Http404("Module not found")

    run_start, run_end = module.current_cycle_window()
    now = timezone.now()

    if user.is_student():
        student = user.student_profile
        if not student.modules.filter(pk=module.pk).exists():
            raise Http404("Module not found")

        role = "student"

        assessment_items = _build_student_module_assessment_items(module, student, now)

        weeks = (
            module.weeks
            .filter(files__isnull=False)
            .prefetch_related("files__parsed_document")
            .order_by("week_number")
            .distinct()
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "module": module,
            "role": role,
            "assessment_items": assessment_items,
            "weeks": weeks,
            "run_start": run_start,
            "run_end": run_end,
        }

    elif user.is_lecturer():
        lecturer = user.lecturer_profile
        if not lecturer.modules.filter(pk=module.pk).exists():
            raise Http404("Module not found")

        role = "lecturer"

        for wn in range(1, 31):
            ModuleWeek.objects.get_or_create(
                module=module,
                week_number=wn,
                defaults={"title": f"Week {wn}"},
            )

        assessment_items = _build_lecturer_module_assessment_items(module)

        weeks = (
            module.weeks
            .all()
            .prefetch_related("files__parsed_document")
            .order_by("week_number")
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "module": module,
            "role": role,
            "assessment_items": assessment_items,
            "weeks": weeks,
            "run_start": run_start,
            "run_end": run_end,
        }

    else:
        return redirect("accounts:login")

    return render(request, "accounts/module_detail.html", context)


@login_required  # Restrict file uploads to authenticated users
def upload_week_file(request, code, week_number):  # View for lecturers to upload a file to a specific module week

    user: User = request.user  # Get the logged-in user
    if not user.is_lecturer():  # Check that the user is a lecturer before proceeding
        raise Http404("Not found")  # Return 404 to hide this functionality from non-lecturers

    lecturer = user.lecturer_profile  # Retrieve Lecturer profile tied to this user
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Fetch module by code that is taught by this lecturer or 404

    week, _ = ModuleWeek.objects.get_or_create(  # Fetch the ModuleWeek instance for this module and week number, creating if missing
        module=module,  # Attach the week to the fetched module
        week_number=week_number,  # Use supplied week number from the URL
        defaults={"title": f"Week {week_number}"},  # If a new week is created, assign a default title with week number
    )

    if request.method == "POST":
        if "file" not in request.FILES:
            messages.error(request, "Please choose a .docx or .pptx file to upload.")
            return redirect("accounts:module_detail", code=module.code)

        uploaded = request.FILES["file"]

        try:
            parsed_payload = parse_uploaded_office_file(uploaded)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("accounts:module_detail", code=module.code)
        
        except Exception:
            messages.error(
               request,
               "The file could not be translated into accessible HTML. "
               "Please upload a readable .docx or .pptx containing text, tables, and images.",
            )
            return redirect("accounts:module_detail", code=module.code)

        week_file = None

        try:
            with transaction.atomic():
                week_file = ModuleWeekFile.objects.create(
                    week=week,
                    file=uploaded,
                    original_name=uploaded.name,
                    uploaded_by=user,
                )

                _persist_parsed_document(
                    parsed_payload=parsed_payload,
                    week_file=week_file,
                )

        except Exception:
            if week_file and week_file.file:
                week_file.file.delete(save=False)

            messages.error(
                request,
                "The file was not published because parsing/storage failed.",
            )
            return redirect("accounts:module_detail", code=module.code)

        messages.success(request, "Weekly file uploaded and parsed successfully.")

    return redirect("accounts:module_detail", code=module.code)  # After processing, redirect back to the module detail page


@login_required  # Only authenticated users can access week description editing
def edit_week_description(request, code, week_number):  # View allowing lecturers to edit text description for a week

    user: User = request.user  # Retrieve the current user
    if not user.is_lecturer():  # Confirm the user has lecturer role
        raise Http404("Not found")  # Return 404 to disallow non-lecturer access

    lecturer = user.lecturer_profile  # Get Lecturer profile for authorization
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Ensure module exists and is taught by this lecturer

    week, _ = ModuleWeek.objects.get_or_create(  # Get or create corresponding ModuleWeek for the provided week number
        module=module,  # Tie the week to the selected module
        week_number=week_number,  # Identify which week is being edited
        defaults={"title": f"Week {week_number}"},  # Assign default title if the week is newly created
    )

    if request.method == "POST":  # Only update when submitted via POST
        description = request.POST.get("description", "").strip()  # Extract and clean the new description text from the form
        week.description = description  # Assign the description to the week object
        week.save()  # Persist the changes to the database

    return redirect("accounts:module_detail", code=module.code)  # Redirect back to the module detail page afterward


@login_required
@require_http_methods(["GET", "POST"])
def create_assignment(request, code):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    errors = []

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        due_date_str = request.POST.get("due_date", "").strip()
        due_time_str = request.POST.get("due_time", "").strip()
        max_mark_str = request.POST.get("max_mark", "").strip() or "100"

        if not title:
            errors.append("Title is required.")
        if not due_date_str:
            errors.append("Due date is required.")
        if not due_time_str:
            errors.append("Due time is required.")

        due_dt = None
        if due_date_str and due_time_str:
            try:
                due_dt = datetime.fromisoformat(f"{due_date_str} {due_time_str}")
            except ValueError:
                errors.append("Invalid due date/time format.")

        try:
            max_mark_val = float(max_mark_str)
        except ValueError:
            errors.append("Max mark must be a number.")
            max_mark_val = 100.0

        uploaded_files = request.FILES.getlist("files")
        parsed_file_payloads: list[tuple] = []

        if not errors and uploaded_files:
            for uploaded in uploaded_files:
                try:
                    parsed_payload = parse_uploaded_office_file(uploaded)
                    parsed_file_payloads.append((uploaded, parsed_payload))
                except ValueError as exc:
                    errors.append(f"{uploaded.name}: {exc}")
                except Exception:
                    errors.append(
                        f"{uploaded.name}: The file could not be translated into accessible HTML."
                    )

        if not errors and due_dt is not None:
            assignment = None
            created_assignment_files: list[AssignmentFile] = []

            try:
                with transaction.atomic():
                    assignment = Assignment.objects.create(
                        module=module,
                        title=title,
                        description=description,
                        due_datetime=timezone.make_aware(due_dt)
                        if timezone.is_naive(due_dt)
                        else due_dt,
                        max_mark=max_mark_val,
                    )

                    for uploaded, parsed_payload in parsed_file_payloads:
                        assignment_file = AssignmentFile.objects.create(
                            assignment=assignment,
                            file=uploaded,
                            original_name=uploaded.name,
                            uploaded_by=user,
                        )
                        created_assignment_files.append(assignment_file)

                        _persist_parsed_document(
                            parsed_payload=parsed_payload,
                            assignment_file=assignment_file,
                        )

            except Exception:
                for assignment_file in created_assignment_files:
                    if assignment_file.file:
                        assignment_file.file.delete(save=False)
                errors.append(
                    "The assignment was not published because one or more uploaded files "
                    "failed during parsing/storage."
                )
            else:
                messages.success(request, "Assignment created successfully.")
                return redirect(
                    "accounts:assignment_detail",
                    code=module.code,
                    assignment_id=assignment.id,
                )

    else:
        due_date_str = ""
        due_time_str = ""
        title = ""
        description = ""
        max_mark_str = "100"

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "errors": errors,
        "initial": {
            "title": title,
            "description": description,
            "due_date": due_date_str,
            "due_time": due_time_str,
            "max_mark": max_mark_str,
        },
    }
    return render(request, "accounts/create_assignment.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def create_quiz(request, code):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    errors = []
    initial_questions = []

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        open_date_str = request.POST.get("open_date", "").strip()
        open_time_str = request.POST.get("open_time", "").strip()
        close_date_str = request.POST.get("close_date", "").strip()
        close_time_str = request.POST.get("close_time", "").strip()
        time_limit_minutes = _parse_positive_int(
            request.POST.get("time_limit_minutes", "20"),
            "Time limit",
            errors,
            minimum=1,
        )
        max_attempts = _parse_positive_int(
            request.POST.get("max_attempts", "1"),
            "Attempt count",
            errors,
            minimum=1,
        )
        max_mark = _parse_decimal_value(
            request.POST.get("max_mark", "100"),
            "Max mark",
            errors,
            minimum=Decimal("1.00"),
        )
        is_published = request.POST.get("is_published") == "on"

        if not title:
            errors.append("Title is required.")

        open_dt = _parse_form_datetime(open_date_str, open_time_str, "Open", errors)
        close_dt = _parse_form_datetime(close_date_str, close_time_str, "Close", errors)

        if open_dt and close_dt and close_dt <= open_dt:
            errors.append("Close date/time must be later than the open date/time.")

        raw_questions_payload = request.POST.get("questions_payload", "")
        try:
            initial_questions = json.loads(raw_questions_payload or "[]")
        except json.JSONDecodeError:
            initial_questions = []

        question_payloads = _parse_questions_payload(raw_questions_payload, errors)

        if not errors:
            with transaction.atomic():
                quiz = Quiz.objects.create(
                    module=module,
                    title=title,
                    description=description,
                    open_datetime=open_dt,
                    close_datetime=close_dt,
                    time_limit_minutes=time_limit_minutes,
                    max_attempts=max_attempts,
                    max_mark=max_mark,
                    is_published=is_published,
                )

                _create_quiz_questions(quiz, question_payloads)

            messages.success(request, "Quiz created successfully.")
            return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)

    else:
        initial_questions = []

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "errors": errors,
        "initial": {
            "title": request.POST.get("title", "") if request.method == "POST" else "",
            "description": request.POST.get("description", "") if request.method == "POST" else "",
            "open_date": request.POST.get("open_date", "") if request.method == "POST" else "",
            "open_time": request.POST.get("open_time", "") if request.method == "POST" else "",
            "close_date": request.POST.get("close_date", "") if request.method == "POST" else "",
            "close_time": request.POST.get("close_time", "") if request.method == "POST" else "",
            "time_limit_minutes": request.POST.get("time_limit_minutes", "20") if request.method == "POST" else "20",
            "max_attempts": request.POST.get("max_attempts", "1") if request.method == "POST" else "1",
            "max_mark": request.POST.get("max_mark", "100") if request.method == "POST" else "100",
            "is_published": (request.POST.get("is_published") == "on") if request.method == "POST" else True,
        },
        "initial_questions": initial_questions,
    }
    return render(request, "accounts/create_quiz.html", context)


@login_required
def quiz_detail(request, code, quiz_id):
    user: User = request.user
    nav_items = _shared_nav_items()
    now = timezone.now()

    module = get_object_or_404(Module, code=code)
    quiz = get_object_or_404(
        Quiz.objects.select_related("module").prefetch_related("questions__options"),
        pk=quiz_id,
        module=module,
    )

    if user.is_lecturer():
        lecturer = user.lecturer_profile
        if not lecturer.modules.filter(pk=module.pk).exists():
            raise Http404("Quiz not found")

        question_rows = _build_question_rows(quiz)
        attempts = (
            quiz.attempts
            .select_related("student__user")
            .order_by("-started_at")
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "module": module,
            "quiz": quiz,
            "role": "lecturer",
            "question_rows": question_rows,
            "attempts": attempts,
        }
        return render(request, "accounts/quiz_detail.html", context)

    if user.is_student():
        student = user.student_profile
        if not student.modules.filter(pk=module.pk).exists():
            raise Http404("Quiz not found")

        if not quiz.is_published:
            raise Http404("Quiz not found")

        _auto_submit_expired_attempt_if_needed(quiz, student)

        state = _get_student_quiz_state(quiz, student, now=timezone.now())
        active_attempt = state["active_attempt"]
        latest_submitted_attempt = state["latest_submitted_attempt"]

        can_start_attempt = (
            quiz.is_published
            and timezone.now() >= quiz.open_datetime
            and timezone.now() <= quiz.close_datetime
            and active_attempt is None
            and state["attempts_used"] < quiz.max_attempts
        )

        question_rows = []
        remaining_seconds = 0

        if active_attempt:
            question_rows = _build_question_rows(quiz, attempt=active_attempt)
            remaining_seconds = max(
                0,
                int((active_attempt.expires_at - timezone.now()).total_seconds())
            )
        elif latest_submitted_attempt:
            question_rows = _build_question_rows(quiz, attempt=latest_submitted_attempt)

        context = {
            "user": user,
            "nav_items": nav_items,
            "module": module,
            "quiz": quiz,
            "role": "student",
            "state": state,
            "active_attempt": active_attempt,
            "submitted_attempt": latest_submitted_attempt,
            "can_start_attempt": can_start_attempt,
            "question_rows": question_rows,
            "remaining_seconds": remaining_seconds,
        }
        return render(request, "accounts/quiz_detail.html", context)

    return redirect("accounts:login")


@login_required
@require_http_methods(["POST"])
def start_quiz_attempt(request, code, quiz_id):
    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    module = get_object_or_404(Module, code=code)
    if not student.modules.filter(pk=module.pk).exists():
        raise Http404("Not found")

    quiz = get_object_or_404(Quiz, pk=quiz_id, module=module, is_published=True)

    now = timezone.now()
    if now < quiz.open_datetime or now > quiz.close_datetime:
        messages.error(request, "This quiz is not currently open.")
        return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)

    existing_active_attempt = (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )
    if existing_active_attempt:
        return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)

    attempts_used = quiz.attempts.filter(student=student).count()
    if attempts_used >= quiz.max_attempts:
        messages.error(request, "You have used all available attempts for this quiz.")
        return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)

    requested_expiry = now + timedelta(minutes=quiz.time_limit_minutes)
    expires_at = min(requested_expiry, quiz.close_datetime)

    QuizAttempt.objects.create(
        quiz=quiz,
        student=student,
        attempt_number=attempts_used + 1,
        expires_at=expires_at,
        status=QuizAttempt.Status.IN_PROGRESS,
    )

    return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)


@login_required
@require_http_methods(["POST"])
def save_quiz_progress(request, code, quiz_id):
    user: User = request.user
    if not user.is_student():
        return JsonResponse({"ok": False}, status=403)

    student = user.student_profile
    module = get_object_or_404(Module, code=code)
    if not student.modules.filter(pk=module.pk).exists():
        return JsonResponse({"ok": False}, status=404)

    quiz = get_object_or_404(Quiz, pk=quiz_id, module=module)

    attempt = (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )
    if attempt is None:
        return JsonResponse({"ok": False, "message": "No active attempt found."}, status=404)

    if attempt.is_expired():
        _grade_attempt(attempt, auto_submitted=True)
        return JsonResponse({"ok": False, "expired": True}, status=409)

    _upsert_attempt_answers(attempt, request.POST)
    return JsonResponse({"ok": True})


@login_required
@require_http_methods(["POST"])
def submit_quiz_attempt(request, code, quiz_id):
    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    module = get_object_or_404(Module, code=code)
    if not student.modules.filter(pk=module.pk).exists():
        raise Http404("Not found")

    quiz = get_object_or_404(Quiz, pk=quiz_id, module=module)

    attempt = (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )
    if attempt is None:
        messages.error(request, "No active quiz attempt was found.")
        return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)

    _upsert_attempt_answers(attempt, request.POST)
    _grade_attempt(attempt, auto_submitted=attempt.is_expired())

    messages.success(request, "Quiz submitted successfully.")
    return redirect("accounts:quiz_detail", code=module.code, quiz_id=quiz.id)

@login_required  # Ensure only authenticated users can view assignment details
def assignment_detail(request, code, assignment_id):  # View that displays details for a particular assignment within a module

    user: User = request.user  # Get the current authenticated user

    module = get_object_or_404(Module, code=code)  # Fetch module by code, or return 404 if not found

    # Fetch assignment from this module
    assignment = get_object_or_404(  # Fetch assignment ensuring that it belongs to the specified module
        Assignment.objects.select_related("module").prefetch_related("files__parsed_document"),
        pk=assignment_id,  # Filter by primary key of the assignment
        module=module,  # Ensure the assignment is tied to the current module
    )

    if user.is_student():  # If the user is a student, show student-specific assignment view
        student = user.student_profile  # Retrieve the Student profile associated with the user
        # must be enrolled in this module
        if not student.modules.filter(pk=module.pk).exists():  # Ensure student is actually enrolled in this module
            raise Http404("Assignment not found")  # Hide existence of assignment if not enrolled

        # student's own submission (if any)
        submission = (  # Query for a single AssignmentSubmission object for this student and assignment
            AssignmentSubmission.objects
            .filter(assignment=assignment, student=student)  # Filter by current assignment and student
            .select_related("grade")  # Include related grade if it exists
            .prefetch_related("files")  # Prefetch any attached submission files
            .first()  # Return first result or None if there is no submission yet
        )

        context = {  # Context for rendering the student assignment detail template
            "user": user,  # Current user object
            "nav_items": _shared_nav_items(),  # Shared navigation links
            "module": module,  # Module that the assignment belongs to
            "assignment": assignment,  # The assignment being viewed
            "role": "student",  # Role string used by template to branch behavior
            "submission": submission,  # Student’s existing submission, if present
        }
        template = "accounts/assignment_detail.html"  # Template used for both student and lecturer assignment detail views

    elif user.is_lecturer():  # If the user is a lecturer, show lecturer-specific assignment view
        lecturer = user.lecturer_profile  # Retrieve Lecturer profile for the user
        # must teach this module
        if not lecturer.modules.filter(pk=module.pk).exists():  # Ensure this lecturer teaches the module
            raise Http404("Assignment not found")  # Hide assignment if lecturer has no relation to the module

        # all submissions for this assignment
        submissions = (  # Build queryset of all submissions for this assignment
            AssignmentSubmission.objects
            .filter(assignment=assignment)  # Filter submissions by current assignment
            .select_related("student__user", "grade")  # Prefetch student’s user object and attached grade
            .prefetch_related("files")  # Prefetch any files uploaded with each submission
            .order_by("-submitted_at")  # Sort submissions with the most recent at the top
        )

        context = {  # Context for lecturer assignment detail template
            "user": user,  # Current user
            "nav_items": _shared_nav_items(),  # Navigation items
            "module": module,  # Module object
            "assignment": assignment,  # Assignment object
            "role": "lecturer",  # Role string used for template branching
            "submissions": submissions,  # All submissions for this assignment
        }
        template = "accounts/assignment_detail.html"  # Use the assignment detail template for lecturer view as well

    else:  # If user is not recognized as student or lecturer
        return redirect("accounts:login")  # Send them back to the login page

    return render(request, template, context)  # Render the chosen template with the computed context


@login_required  # Require authentication to submit assignments
@require_http_methods(["POST"])  # This view only accepts POST requests (submissions)
def submit_assignment(request, code, assignment_id):  # View that handles submission of assignment files by a student

    user: User = request.user  # Get the authenticated user
    if not user.is_student():  # Ensure that only students can submit assignments
        raise Http404("Not found")  # Return 404 if a non-student tries this endpoint

    student = user.student_profile  # Retrieve Student profile linked to this user
    module = get_object_or_404(Module, code=code)  # Fetch the module by its code or raise 404 if missing

    # must be enrolled
    if not student.modules.filter(pk=module.pk).exists():  # Confirm that the student is enrolled in this module
        raise Http404("Not found")  # If not enrolled, hide the endpoint with a 404

    assignment = get_object_or_404(  # Fetch assignment linked to module and given ID or 404 if not found
        Assignment,
        pk=assignment_id,  # Primary key of the assignment
        module=module,  # Enforce that the assignment belongs to this module
    )

    # create or get submission
    submission, created = AssignmentSubmission.objects.get_or_create(  # Retrieve existing submission or create a new one for student+assignment
        assignment=assignment,  # Link submission to the chosen assignment
        student=student,  # Link submission to the current student
        defaults={"status": AssignmentSubmission.Status.SUBMITTED},  # Initial default status if a new submission is created
    )

    # update status (handle late)
    now = timezone.now()  # Capture the current time for comparison with due datetime
    if assignment.due_datetime and now > assignment.due_datetime:  # Check if the current time is later than assignment due time
        submission.status = AssignmentSubmission.Status.LATE  # Mark submission as late if submitted after due date
    else:
        submission.status = AssignmentSubmission.Status.SUBMITTED  # Otherwise mark as a normal submitted status
    submission.submitted_at = now  # Record the timestamp at which the submission was made or updated
    submission.save()  # Persist submission changes to the database

    # attach uploaded files
    for uploaded in request.FILES.getlist("files"):  # Iterate over each uploaded file from the submission form
        SubmissionFile.objects.create(  # Create a new SubmissionFile record for each uploaded file
            submission=submission,  # Attach the file to the existing submission object
            file=uploaded,  # Save file binary data through Django’s file storage
            original_name=uploaded.name,  # Keep original filename for display to user
            uploaded_by=user,  # Track which user uploaded the file (the student)
        )

    return redirect("accounts:assignment_detail", code=module.code, assignment_id=assignment.id)  # Redirect back to the assignment detail page after submission


@login_required  # Ensure user is logged in to grade submissions
@require_http_methods(["GET", "POST"])  # Allow both GET (display form) and POST (submit form) on this view
def grade_submission(request, code, assignment_id, submission_id):  # View for lecturers to create or update a grade for a submission

    user: User = request.user  # Get the current authenticated user
    if not user.is_lecturer():  # Make sure only lecturers can access grading functionality
        raise Http404("Not found")  # Return 404 for unauthorized roles to conceal endpoint

    lecturer = user.lecturer_profile  # Retrieve Lecturer profile instance
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Confirm module exists and is taught by this lecturer
    assignment = get_object_or_404(Assignment, pk=assignment_id, module=module)  # Fetch assignment belonging to this module or 404
    submission = get_object_or_404(  # Fetch the specific submission to be graded
        AssignmentSubmission.objects.select_related("student__user"),  # Prefetch related student and user for display
        pk=submission_id,  # Primary key of submission
        assignment=assignment,  # Ensure submission belongs to this assignment
    )

    errors = []  # Initialize list to hold validation error messages
    grade_obj = getattr(submission, "grade", None)  # Retrieve the associated grade object if it exists, else None
    initial_value = ""  # Default initial value for mark input
    initial_feedback = ""  # Default initial feedback text

    if grade_obj:  # If a grade already exists
        initial_value = grade_obj.value  # Use existing grade value as initial form value
        initial_feedback = grade_obj.feedback_text or ""  # Use existing feedback text or empty string if None

    if request.method == "POST":  # When form is submitted to create or update a grade
        value_str = request.POST.get("value", "").strip()  # Extract mark (as string) from POST data
        feedback = request.POST.get("feedback", "").strip()  # Extract feedback text from POST data

        if not value_str:  # Ensure that a mark value has been provided
            errors.append("A mark is required.")  # Add validation error for missing mark
        else:
            try:
                value_float = float(value_str)  # Attempt to convert mark to float
            except ValueError:  # If conversion fails, mark input is invalid
                errors.append("Mark must be a number.")  # Notify user of invalid mark
                value_float = None  # Reset parsed value

        if not errors and value_float is not None:  # Only proceed when there are no validation errors and mark is numeric
            if grade_obj is None:  # If no grade record exists yet, create a new one
                grade_obj = AssignmentGrade.objects.create(
                    submission=submission,  # Link grade to this submission
                    marker=lecturer,  # Set the marker as the current lecturer
                    value=value_float,  # Store the numeric grade value
                    feedback_text=feedback,  # Store textual feedback
                )
            else:  # If a grade already exists, update it in place
                grade_obj.value = value_float  # Update the numeric grade
                grade_obj.feedback_text = feedback  # Update the feedback text
                grade_obj.marker = lecturer  # Update marker to reflect who last updated the grade
                grade_obj.save()  # Save updated grade information to the database

            return redirect("accounts:assignment_detail", code=module.code, assignment_id=assignment.id)  # After saving, redirect back to the assignment detail page

    context = {  # Build context for the grade submission template
        "user": user,  # Current user
        # Shared nav items for header + footer
        "nav_items": _shared_nav_items(),
        "module": module,  # Current module context
        "assignment": assignment,  # Current assignment context
        "submission": submission,  # Submission being graded
        "errors": errors,  # List of any validation error messages
        "initial": {  # Initial values to pre-populate the grading form
            "value": request.POST.get("value", initial_value) if request.method == "POST" else initial_value,  # Mark value
            "feedback": request.POST.get("feedback", initial_feedback) if request.method == "POST" else initial_feedback,  # Feedback text
        },
    }

    return render(request, "accounts/grade_submission.html", context)  # Render the grade submission template with provided context

@login_required
@require_http_methods(["GET"])
def parsed_document_modal(request, parsed_id):
    user: User = request.user
    parsed_document, module = _get_authorised_parsed_document(parsed_id, user)
    source_file = parsed_document.get_source_file()

    context = {
        "parsed_document": parsed_document,
        "module": module,
        "source_file": source_file,
        "document_title": parsed_document.get_source_name(),
        "can_edit_images": user.is_lecturer(),
    }
    return render(request, "accounts/partials/parsed_document_modal.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def edit_parsed_document_images(request, parsed_id):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    parsed_document, module = _get_authorised_parsed_document(parsed_id, user)

    if request.method == "POST":
        for image in parsed_document.images.all():
            image.alt_text = request.POST.get(f"alt_{image.id}", "").strip()
            image.save(update_fields=["alt_text"])

        _rebuild_parsed_document_html(parsed_document, save=True)
        messages.success(request, "Image descriptions updated successfully.")

        return redirect("accounts:edit_parsed_document_images", parsed_id=parsed_document.id)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "parsed_document": parsed_document,
    }
    return render(request, "accounts/edit_parsed_document_images.html", context)

def _validate_password_strength(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number.")
    if not re.search(r"[^\w\s]", password):
        errors.append("Password must contain at least one special character (e.g. !, @, #).")
    return errors

def _get_all_valid_courses() -> list[str]:
    """
    Aggregate all allowed course codes from Module.allowed_courses.
    Returns a sorted unique list of normalized codes (3–10 chars, A–Z/0–9).
    """
    courses_set = set()
    for allowed in Module.objects.values_list("allowed_courses", flat=True):
        if isinstance(allowed, list):
            for c in allowed:
                code = _normalize_course_code(str(c))
                if COURSE_CODE_RE.match(code):
                    courses_set.add(code)
    return sorted(courses_set)

COURSE_CODE_RE = re.compile(r"^[A-Z0-9]{3,10}$")

def _normalize_course_code(raw: str) -> str:
    """
    Normalize user-entered course code:
    - strip whitespace
    - remove internal spaces
    - uppercase
    """
    raw = (raw or "").strip().upper()
    raw = raw.replace(" ", "")
    return raw
