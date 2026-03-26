from django.contrib.auth.decorators import login_required  # Imports decorator to ensure some views are only accessible to authenticated users
from django.contrib.auth.views import LoginView  # Imports Django’s built-in class-based login view for handling authentication
from django.shortcuts import redirect, render, get_object_or_404  # Common shortcuts for redirects, rendering templates, and fetching objects or returning 404
from django.urls import reverse  # Used to dynamically resolve URL patterns by their name
from django.utils import timezone  # Provides timezone-aware datetime utilities compatible with Django settings
from django.http import Http404, JsonResponse  # Exception used to immediately return a 404 Not Found response / Class for returning JSON responses in views
from django.db.models import Count, Q, Max  # ORM helpers: Count for aggregation and Q for complex query filters
from django.views.decorators.http import require_http_methods  # Decorator to restrict allowed HTTP methods per view
from datetime import datetime, timedelta, date  # Standard library datetime class used for parsing date and time input / timedelta for date arithmetic
from collections import defaultdict  # Standard library class for creating dictionaries with default value types, used in some views for grouping data
from decimal import Decimal, InvalidOperation  # Standard library Decimal class for precise decimal arithmetic / InvalidOperation for handling invalid decimal operations
from django.contrib import messages  # Django's messaging framework for passing one-time messages to templates
from django.core.files.base import ContentFile  # Utility for creating file objects from raw content, used in file handling
from django.db import transaction  # Provides atomic transaction management for database operations, ensuring data integrity
from .document_parsing import build_rendered_html_from_blocks, parse_uploaded_office_file
from .models import User, StudentProfile, LecturerProfile, Module, ModuleEnrollmentStudent, ModuleEnrollmentLecturer, Assignment, AssignmentSubmission, AssignmentGrade, AssignmentFile, SubmissionFile, ModuleWeek, ModuleWeekFile, ParsedDocument, ParsedDocumentImage, Quiz, QuizQuestion, QuizOption, QuizAttempt, QuizAnswer, Notification, GlobalAnnouncement, ModuleAnnouncement  # Imports all custom models referenced by these views
from .notifications import create_notification, notify_module_students, notify_module_lecturers
import re  # Regular expressions module, used for validating input
import json # Standard library for working with JSON data, used in some views for parsing or returning JSON payloads
import calendar as pycalendar  # Standard library for calendar-related functions, used in some views for date calculations
from django.utils.http import url_has_allowed_host_and_scheme
# Temporary
import traceback
from django.http import HttpResponse
from django.utils.html import escape

# Shared Navigation Menu Items (used in multiple views for consistent header/footer links)
def _shared_nav_items():
    return [
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},
        {"label": "Portal", "url": reverse("accounts:portal")},
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},
        {"label": "Website", "url": "https://www.tudublin.ie/"},
    ]

def _require_admin_user(user):
    if not user.is_admin():
        raise Http404("Not found")


def _admin_page_context(user, page_title):
    return {
        "user": user,
        "page_title": page_title,
        "dashboard_url": reverse("accounts:admin_dashboard"),
    }


def _ensure_primary_lecturer(module):
    if module.lecturer_enrolments.filter(is_primary=True).exists():
        return

    first_enrolment = module.lecturer_enrolments.order_by("id").first()
    if first_enrolment:
        first_enrolment.is_primary = True
        first_enrolment.save(update_fields=["is_primary"])


def _build_admin_enrollment_rows():
    modules = (
        Module.objects
        .filter(is_active=True)
        .prefetch_related(
            "student_enrolments__student__user",
            "lecturer_enrolments__lecturer__user",
        )
        .order_by("code", "title")
    )

    rows = []

    for module in modules:
        student_rows = []
        for enrolment in sorted(
            module.student_enrolments.all(),
            key=lambda e: (
                (e.student.user.get_full_name() or e.student.user.username).lower(),
                e.student.student_number.lower(),
            ),
        ):
            student = enrolment.student
            student_rows.append(
                {
                    "id": student.id,
                    "name": student.user.get_full_name() or student.user.username,
                    "email": student.user.username,
                    "student_number": student.student_number,
                    "course": student.course or "",
                }
            )

        lecturer_rows = []
        for enrolment in sorted(
            module.lecturer_enrolments.all(),
            key=lambda e: (
                (e.lecturer.user.get_full_name() or e.lecturer.user.username).lower(),
                e.lecturer.staff_id.lower(),
            ),
        ):
            lecturer = enrolment.lecturer
            lecturer_rows.append(
                {
                    "id": lecturer.id,
                    "name": lecturer.user.get_full_name() or lecturer.user.username,
                    "email": lecturer.user.username,
                    "staff_id": lecturer.staff_id,
                    "is_primary": enrolment.is_primary,
                }
            )

        rows.append(
            {
                "module": module,
                "students": student_rows,
                "lecturers": lecturer_rows,
            }
        )

    return rows

def _portal_office_tiles():
    """
    Starter launch URLs for Office365 links.
    Replace any of these later if TU Dublin uses tenant-specific entry points.
    """
    return [
        {
            "label": "Teams",
            "url": "https://teams.microsoft.com/",
            "image": "accounts/images/teams.png",
        },
        {
            "label": "OneDrive",
            "url": "https://www.microsoft365.com/launch/onedrive",
            "image": "accounts/images/onedrive.png",
        },
        {
            "label": "SharePoint",
            "url": "https://www.microsoft365.com/launch/sharepoint",
            "image": "accounts/images/sharepoint.png",
        },
        {
            "label": "OneNote",
            "url": "https://www.microsoft365.com/launch/onenote",
            "image": "accounts/images/onenote.png",
        },
        {
            "label": "Word",
            "url": "https://www.microsoft365.com/launch/word",
            "image": "accounts/images/word.png",
        },
        {
            "label": "Excel",
            "url": "https://www.microsoft365.com/launch/excel",
            "image": "accounts/images/excel.png",
        },
        {
            "label": "PowerPoint",
            "url": "https://www.microsoft365.com/launch/powerpoint",
            "image": "accounts/images/powerpoint.png",
        },
        {
            "label": "More",
            "url": "https://www.microsoft365.com/apps",
            "image": "accounts/images/more.png",
        },
    ]


def _portal_module_queryset_for_user(user):
    if user.is_student():
        return (
            user.student_profile.modules
            .filter(is_active=True)
            .order_by("code")
        )

    if user.is_lecturer():
        return (
            user.lecturer_profile.modules
            .filter(is_active=True)
            .order_by("code")
        )

    return Module.objects.none()


def _build_portal_calendar_context(user, year, month):
    today = timezone.localdate()

    first_of_month = date(year, month, 1)
    _, last_day = pycalendar.monthrange(year, month)
    last_of_month = date(year, month, last_day)

    current_modules = _portal_module_queryset_for_user(user)

    assignment_qs = (
        Assignment.objects
        .filter(
            module__in=current_modules,
            due_datetime__date__gte=first_of_month,
            due_datetime__date__lte=last_of_month,
        )
        .select_related("module")
        .order_by("due_datetime", "title")
    )

    quiz_qs = (
        Quiz.objects
        .filter(
            module__in=current_modules,
            close_datetime__date__gte=first_of_month,
            close_datetime__date__lte=last_of_month,
        )
        .select_related("module")
        .order_by("close_datetime", "title")
    )

    if user.is_student():
        quiz_qs = quiz_qs.filter(is_published=True)

    month_items = []

    for assignment in assignment_qs:
        month_items.append(
            {
                "kind_label": "Assignment",
                "kind_class": "assignment",
                "title": assignment.title,
                "module_code": assignment.module.code,
                "module_title": assignment.module.title,
                "timestamp": assignment.due_datetime,
                "date_value": assignment.due_datetime.date(),
                "url": reverse(
                    "accounts:assignment_detail",
                    args=[assignment.module.code, assignment.id],
                ),
                "date_text": "Due",
            }
        )

    for quiz in quiz_qs:
        month_items.append(
            {
                "kind_label": "Quiz",
                "kind_class": "quiz",
                "title": quiz.title,
                "module_code": quiz.module.code,
                "module_title": quiz.module.title,
                "timestamp": quiz.close_datetime,
                "date_value": quiz.close_datetime.date(),
                "url": reverse(
                    "accounts:quiz_detail",
                    args=[quiz.module.code, quiz.id],
                ),
                "date_text": "Closes",
            }
        )

    month_items.sort(key=lambda item: (item["timestamp"], item["kind_label"], item["title"]))

    items_by_day = defaultdict(list)
    for item in month_items:
        items_by_day[item["date_value"]].append(item)

    calendar_weeks = []
    calendar_builder = pycalendar.Calendar(firstweekday=0)

    for week in calendar_builder.monthdatescalendar(year, month):
        week_cells = []
        for day in week:
            day_items = items_by_day.get(day, [])
            week_cells.append(
                {
                    "date": day,
                    "day_number": day.day,
                    "in_month": day.month == month,
                    "is_today": day == today,
                    "items": day_items[:3],
                    "extra_count": max(len(day_items) - 3, 0),
                }
            )
        calendar_weeks.append(week_cells)

    prev_month_anchor = first_of_month - timedelta(days=1)
    next_month_anchor = (first_of_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    return {
        "calendar_weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "calendar_weeks": calendar_weeks,
        "calendar_items": month_items,
        "calendar_month_label": first_of_month.strftime("%B %Y"),
        "prev_year": prev_month_anchor.year,
        "prev_month": prev_month_anchor.month,
        "next_year": next_month_anchor.year,
        "next_month": next_month_anchor.month,
    }

def _week_is_viewable(week):
    return bool((week.description or "").strip()) or week.files.exists()


def _notify_students_new_assignment(assignment):
    notify_module_students(
        assignment.module,
        title=f"New assignment: {assignment.title}",
        redirect_url=reverse("accounts:assignment_detail", args=[assignment.module.code, assignment.id]),
        notification_type=Notification.Type.ASSIGNMENT_NEW,
        event_key=f"assignment-new:{assignment.id}",
    )


def _notify_student_assignment_submitted(submission):
    create_notification(
        recipient=submission.student.user,
        module=submission.assignment.module,
        title=f"Assignment submitted: {submission.assignment.title}",
        redirect_url=reverse(
            "accounts:assignment_detail",
            args=[submission.assignment.module.code, submission.assignment.id],
        ),
        notification_type=Notification.Type.ASSIGNMENT_SUBMITTED,
        event_key=f"assignment-submitted:{submission.id}",
    )


def _notify_student_assignment_graded(grade_obj):
    create_notification(
        recipient=grade_obj.submission.student.user,
        module=grade_obj.submission.assignment.module,
        title=f"Assignment graded: {grade_obj.submission.assignment.title}",
        redirect_url=reverse(
            "accounts:assignment_detail",
            args=[grade_obj.submission.assignment.module.code, grade_obj.submission.assignment.id],
        ),
        notification_type=Notification.Type.ASSIGNMENT_GRADED,
    )


def _notify_students_new_quiz(quiz):
    if not quiz.is_published:
        return

    notify_module_students(
        quiz.module,
        title=f"New quiz: {quiz.title}",
        redirect_url=reverse("accounts:quiz_detail", args=[quiz.module.code, quiz.id]),
        notification_type=Notification.Type.QUIZ_NEW,
        event_key=f"quiz-new:{quiz.id}",
    )


def _notify_student_quiz_submitted(attempt):
    create_notification(
        recipient=attempt.student.user,
        module=attempt.quiz.module,
        title=f"Quiz submitted: {attempt.quiz.title}",
        redirect_url=reverse("accounts:quiz_detail", args=[attempt.quiz.module.code, attempt.quiz.id]),
        notification_type=Notification.Type.QUIZ_SUBMITTED,
        event_key=f"quiz-submitted:{attempt.id}",
    )


def _notify_students_if_week_now_viewable(week):
    if not _week_is_viewable(week):
        return

    notify_module_students(
        week.module,
        title=f"New week available: Week {week.week_number}",
        redirect_url=reverse("accounts:module_detail", args=[week.module.code]),
        notification_type=Notification.Type.WEEK_AVAILABLE,
        event_key=f"week-available:{week.module_id}:{week.week_number}",
    )


def _notify_lecturers_parser_success(module, document_name, redirect_url):
    notify_module_lecturers(
        module,
        title=f"Document parsed successfully: {document_name}",
        redirect_url=redirect_url,
        notification_type=Notification.Type.PARSER_SUCCESS,
    )


def _notify_lecturers_parser_failure(module, document_name, redirect_url):
    notify_module_lecturers(
        module,
        title=f"Document parse failed: {document_name}",
        redirect_url=redirect_url,
        notification_type=Notification.Type.PARSER_FAILURE,
    )

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

    valid_types = {
        QuizQuestion.Type.MULTIPLE_CHOICE,
        QuizQuestion.Type.MULTIPLE_SELECT,
        QuizQuestion.Type.TRUE_FALSE,
    }
    parsed_questions = []

    for index, item in enumerate(payload, start=1):
        prompt = (item.get("prompt") or "").strip()
        question_type = (item.get("question_type") or "").strip()
        marks = _parse_decimal_value(
            item.get("marks", "1"),
            f"Question {index} marks",
            errors,
            minimum=Decimal("0.25"),
        )

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

        if question_type == QuizQuestion.Type.TRUE_FALSE:
            correct_true_false = (item.get("correct_true_false") or "").strip().lower()
            if correct_true_false not in {"true", "false"}:
                errors.append(f"Question {index} must choose either True or False as the correct answer.")

            normalized["options"] = [
                {"text": "True", "is_correct": correct_true_false == "true"},
                {"text": "False", "is_correct": correct_true_false == "false"},
            ]
            parsed_questions.append(normalized)
            continue

        raw_options = item.get("options")
        options = []

        if isinstance(raw_options, list):
            for option_index, option in enumerate(raw_options, start=1):
                text = (option.get("text") or "").strip()
                if not text:
                    errors.append(f"Question {index} option {option_index} cannot be empty.")
                    continue

                options.append(
                    {
                        "text": text,
                        "is_correct": bool(option.get("is_correct")),
                    }
                )
        else:

            legacy_options = [
                line.strip()
                for line in (item.get("options_text") or "").splitlines()
                if line.strip()
            ]

            if question_type == QuizQuestion.Type.MULTIPLE_CHOICE:
                try:
                    correct_number = int(str(item.get("correct_option") or "").strip())
                except ValueError:
                    correct_number = None

                options = [
                    {
                        "text": option_text,
                        "is_correct": (position == (correct_number - 1)) if correct_number is not None else False,
                    }
                    for position, option_text in enumerate(legacy_options)
                ]

            elif question_type == QuizQuestion.Type.MULTIPLE_SELECT:
                parsed_numbers = []
                for part in str(item.get("correct_options") or "").split(","):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        parsed_numbers.append(int(part))
                    except ValueError:
                        errors.append(
                            f"Question {index} multiple-select correct answers must be comma-separated numbers."
                        )
                        parsed_numbers = []
                        break

                parsed_numbers = sorted(set(parsed_numbers))
                options = [
                    {
                        "text": option_text,
                        "is_correct": ((position + 1) in parsed_numbers),
                    }
                    for position, option_text in enumerate(legacy_options)
                ]

        if len(options) < 2:
            errors.append(f"Question {index} must have at least two options.")

        if question_type == QuizQuestion.Type.MULTIPLE_CHOICE:
            correct_count = sum(1 for option in options if option["is_correct"])
            if correct_count != 1:
                errors.append(f"Question {index} must have exactly one correct answer.")

        if question_type == QuizQuestion.Type.MULTIPLE_SELECT:
            if not any(option["is_correct"] for option in options):
                errors.append(f"Question {index} must have at least one correct answer.")

        normalized["options"] = options
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

    was_unsubmitted = attempt.submitted_at is None
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

    if was_unsubmitted:
        _notify_student_quiz_submitted(attempt)

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

def _format_mark_display(value):
    decimal_value = Decimal(str(value or 0))
    rendered = f"{decimal_value:.2f}"
    return rendered.rstrip("0").rstrip(".") or "0"


def _build_student_profile_modules(student):
    modules = list(
        student.modules
        .filter(is_active=True)
        .prefetch_related("assignments", "quizzes")
        .order_by("code")
    )

    if not modules:
        return []

    submitted_assignment_ids = set(
        AssignmentSubmission.objects.filter(
            student=student,
            assignment__module__in=modules,
        ).values_list("assignment_id", flat=True)
    )

    graded_assignment_marks = dict(
        AssignmentGrade.objects.filter(
            submission__student=student,
            submission__assignment__module__in=modules,
        ).values_list("submission__assignment_id", "value")
    )

    best_quiz_attempt_by_quiz = {}
    submitted_quiz_attempts = (
        QuizAttempt.objects.filter(
            student=student,
            quiz__module__in=modules,
            quiz__is_published=True,
            submitted_at__isnull=False,
        )
        .select_related("quiz", "quiz__module")
        .order_by("quiz_id", "-weighted_score", "-submitted_at", "-id")
    )

    for attempt in submitted_quiz_attempts:
        best_quiz_attempt_by_quiz.setdefault(attempt.quiz_id, attempt)

    module_rows = []

    for module in modules:
        items = []

        for assignment in module.assignments.all().order_by("due_datetime", "title"):
            if assignment.id in graded_assignment_marks:
                metric = (
                    f"{_format_mark_display(graded_assignment_marks[assignment.id])}"
                    f"/{_format_mark_display(assignment.max_mark)}"
                )
                metric_class = "profile-metric--complete"
            elif assignment.id in submitted_assignment_ids:
                metric = "Pending"
                metric_class = "profile-metric--pending"
            else:
                metric = "Not submitted"
                metric_class = "profile-metric--empty"

            items.append(
                {
                    "kind_label": "Assignment",
                    "kind_class": "assignment",
                    "title": assignment.title,
                    "url": reverse("accounts:assignment_detail", args=[module.code, assignment.id]),
                    "metric": metric,
                    "metric_class": metric_class,
                    "sort_at": assignment.due_datetime,
                }
            )

        for quiz in module.quizzes.filter(is_published=True).order_by("close_datetime", "title"):
            best_attempt = best_quiz_attempt_by_quiz.get(quiz.id)

            if best_attempt:
                metric = (
                    f"{_format_mark_display(best_attempt.weighted_score)}"
                    f"/{_format_mark_display(quiz.max_mark)}"
                )
                metric_class = "profile-metric--complete"
            else:
                metric = "Not attempted"
                metric_class = "profile-metric--empty"

            items.append(
                {
                    "kind_label": "Quiz",
                    "kind_class": "quiz",
                    "title": quiz.title,
                    "url": reverse("accounts:quiz_detail", args=[module.code, quiz.id]),
                    "metric": metric,
                    "metric_class": metric_class,
                    "sort_at": quiz.close_datetime,
                }
            )

        items.sort(key=lambda item: (item["sort_at"], item["title"]))

        module_rows.append(
            {
                "code": module.code,
                "title": module.title,
                "items": items,
            }
        )

    return module_rows


def _build_lecturer_profile_modules(lecturer):
    modules = list(
        lecturer.modules
        .filter(is_active=True)
        .annotate(total_students=Count("students", distinct=True))
        .prefetch_related("assignments", "quizzes")
        .order_by("code")
    )

    if not modules:
        return []

    assignment_marked_counts = dict(
        AssignmentGrade.objects.filter(
            submission__assignment__module__in=modules,
        )
        .values("submission__assignment_id")
        .annotate(marked_count=Count("submission__student", distinct=True))
        .values_list("submission__assignment_id", "marked_count")
    )

    quiz_marked_counts = dict(
        QuizAttempt.objects.filter(
            quiz__module__in=modules,
            submitted_at__isnull=False,
        )
        .values("quiz_id")
        .annotate(marked_count=Count("student", distinct=True))
        .values_list("quiz_id", "marked_count")
    )

    module_rows = []

    for module in modules:
        total_students = getattr(module, "total_students", 0) or 0
        items = []

        for assignment in module.assignments.all().order_by("due_datetime", "title"):
            marked = assignment_marked_counts.get(assignment.id, 0)
            unmarked = max(total_students - marked, 0)

            if total_students > 0 and marked == total_students:
                metric_class = "profile-metric--complete"
            elif marked > 0:
                metric_class = "profile-metric--pending"
            else:
                metric_class = "profile-metric--empty"

            items.append(
                {
                    "kind_label": "Assignment",
                    "kind_class": "assignment",
                    "title": assignment.title,
                    "url": reverse("accounts:assignment_detail", args=[module.code, assignment.id]),
                    "metric": f"{marked} marked / {unmarked} unmarked",
                    "metric_class": metric_class,
                    "sort_at": assignment.due_datetime,
                }
            )

        for quiz in module.quizzes.all().order_by("close_datetime", "title"):
            marked = quiz_marked_counts.get(quiz.id, 0)
            unmarked = max(total_students - marked, 0)

            if total_students > 0 and marked == total_students:
                metric_class = "profile-metric--complete"
            elif marked > 0:
                metric_class = "profile-metric--pending"
            else:
                metric_class = "profile-metric--empty"

            items.append(
                {
                    "kind_label": "Quiz",
                    "kind_class": "quiz",
                    "title": quiz.title,
                    "url": reverse("accounts:quiz_detail", args=[module.code, quiz.id]),
                    "metric": f"{marked} marked / {unmarked} unmarked",
                    "metric_class": metric_class,
                    "sort_at": quiz.close_datetime,
                }
            )

        items.sort(key=lambda item: (item["sort_at"], item["title"]))

        module_rows.append(
            {
                "code": module.code,
                "title": module.title,
                "student_count": total_students,
                "items": items,
            }
        )

    return module_rows

def _recent_global_announcements():
    return (
        GlobalAnnouncement.objects
        .select_related("created_by")
        .order_by("-created_at", "-id")[:3]
    )


def _recent_module_announcements(module):
    return (
        module.module_announcements
        .select_related("created_by")
        .order_by("-created_at", "-id")[:3]
    )


def _validate_announcement_form(request):
    title = (request.POST.get("title") or "").strip()
    content = (request.POST.get("content") or "").strip()
    errors = []

    if not title:
        errors.append("Title is required.")
    if not content:
        errors.append("Content is required.")

    return title, content, errors

class RoleBasedLoginView(LoginView):  # Custom login view that extends Django’s built-in LoginView to add role-based redirects
    template_name = "accounts/login.html"  # Specifies the template to use when displaying the login form
    redirect_authenticated_user = True  # If a user is already authenticated, they will be redirected to the success URL instead of seeing the login form again

    def get_success_url(self):  # Overrides method to control where a user is redirected after successful login
        # Redirect based on role
        user: User = self.request.user  # Grabs the authenticated user object from the current request
        if user.is_student():  # If the user has the student role, send them to the student dashboard
            return "/student-dashboard/"
        if user.is_lecturer():  # If the user has the lecturer role, send them to the lecturer dashboard
            return "/lecturer-dashboard/"
        if user.is_admin():  # If the user has the admin role, send them to the admin dashboard
            return "/admin-dashboard/"
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

    if user.is_admin():
        return redirect("accounts:admin_dashboard")

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
            "global_announcements": _recent_global_announcements(),
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
            "global_announcements": _recent_global_announcements(),
        }

    else:
        return redirect("accounts:login")

    return render(request, template, context)

@login_required
def admin_dashboard(request):
    user: User = request.user
    _require_admin_user(user)

    context = _admin_page_context(user, "Admin Dashboard")
    context.update(
        {
            "total_students": StudentProfile.objects.count(),
            "total_lecturers": LecturerProfile.objects.count(),
            "total_modules": Module.objects.count(),
            "total_student_enrolments": ModuleEnrollmentStudent.objects.count(),
            "total_lecturer_enrolments": ModuleEnrollmentLecturer.objects.count(),
            "recent_global_announcements": _recent_global_announcements(),
        }
    )
    return render(request, "accounts/admin_dashboard.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def admin_add_lecturer(request):
    user: User = request.user
    _require_admin_user(user)

    errors = []

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip()
        staff_id = (request.POST.get("staff_id") or "").strip()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""

        if not first_name:
            errors.append("First name is required.")
        if not last_name:
            errors.append("Surname is required.")
        if not email or "@" not in email:
            errors.append("A valid email is required.")
        if not staff_id:
            errors.append("Staff ID is required.")
        if not password1 or not password2:
            errors.append("Both password fields are required.")
        if password1 and password2 and password1 != password2:
            errors.append("Passwords do not match.")

        password_errors = _validate_password_strength(password1)
        if password_errors:
            errors.extend(password_errors)

        if email and User.objects.filter(username__iexact=email).exists():
            errors.append("A user already exists with this email address.")

        if staff_id and LecturerProfile.objects.filter(staff_id__iexact=staff_id).exists():
            errors.append("A lecturer already exists with this staff ID.")

        if not errors:
            lecturer_user = User.objects.create_user(
                username=email,
                email=email,
                password=password1,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.LECTURER,
            )

            LecturerProfile.objects.create(
                user=lecturer_user,
                staff_id=staff_id,
            )

            messages.success(request, "Lecturer account created successfully.")
            return redirect("accounts:admin_dashboard")

    context = _admin_page_context(user, "Add Lecturer")
    context.update(
        {
            "errors": errors,
            "initial": {
                "first_name": request.POST.get("first_name", ""),
                "last_name": request.POST.get("last_name", ""),
                "email": request.POST.get("email", ""),
                "staff_id": request.POST.get("staff_id", ""),
            },
        }
    )
    return render(request, "accounts/admin_add_lecturer.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def admin_add_module(request):
    user: User = request.user
    _require_admin_user(user)

    errors = []

    if request.method == "POST":
        code = _normalize_course_code(request.POST.get("code", ""))
        title = (request.POST.get("title") or "").strip()
        start_date_str = (request.POST.get("start_date") or "").strip()
        end_date_str = (request.POST.get("end_date") or "").strip()
        allowed_courses_raw = request.POST.get("allowed_courses", "")
        is_active = request.POST.get("is_active") == "on"

        start_date_value = None
        end_date_value = None

        if not code:
            errors.append("Module code is required.")
        elif Module.objects.filter(code__iexact=code).exists():
            errors.append("A module with this code already exists.")

        if not title:
            errors.append("Module title is required.")

        if start_date_str:
            try:
                start_date_value = date.fromisoformat(start_date_str)
            except ValueError:
                errors.append("Start date is invalid.")

        if end_date_str:
            try:
                end_date_value = date.fromisoformat(end_date_str)
            except ValueError:
                errors.append("End date is invalid.")

        parsed_allowed_courses = []
        if allowed_courses_raw.strip():
            raw_tokens = re.split(r"[\n,]+", allowed_courses_raw)
            invalid_codes = []

            for token in raw_tokens:
                normalized = _normalize_course_code(token)
                if not normalized:
                    continue
                if not COURSE_CODE_RE.match(normalized):
                    invalid_codes.append(normalized)
                else:
                    parsed_allowed_courses.append(normalized)

            parsed_allowed_courses = sorted(set(parsed_allowed_courses))

            if invalid_codes:
                errors.append(
                    "Allowed course codes must be 3–10 characters and contain only letters/numbers."
                )

        if not errors:
            Module.objects.create(
                code=code,
                title=title,
                start_date=start_date_value,
                end_date=end_date_value,
                last_rollover_year=timezone.localdate().year,
                is_active=is_active,
                allowed_courses=parsed_allowed_courses,
            )

            messages.success(request, "Module created successfully.")
            return redirect("accounts:admin_dashboard")

    context = _admin_page_context(user, "Add Module")
    context.update(
        {
            "errors": errors,
            "initial": {
                "code": request.POST.get("code", ""),
                "title": request.POST.get("title", ""),
                "start_date": request.POST.get("start_date", ""),
                "end_date": request.POST.get("end_date", ""),
                "allowed_courses": request.POST.get("allowed_courses", ""),
                "is_active": (request.POST.get("is_active") == "on") if request.method == "POST" else True,
            },
        }
    )
    return render(request, "accounts/admin_add_module.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def admin_edit_enrollment(request):
    user: User = request.user
    _require_admin_user(user)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "add_student":
            module = get_object_or_404(Module, pk=request.POST.get("student_module_id"))
            student = get_object_or_404(StudentProfile, pk=request.POST.get("student_id"))

            _, created = ModuleEnrollmentStudent.objects.get_or_create(
                module=module,
                student=student,
            )

            if created:
                messages.success(request, f"Added {student.user.get_full_name() or student.user.username} to {module.code}.")
            else:
                messages.info(request, "That student is already enrolled in this module.")

        elif action == "remove_student":
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))
            student = get_object_or_404(StudentProfile, pk=request.POST.get("student_id"))

            deleted, _ = ModuleEnrollmentStudent.objects.filter(
                module=module,
                student=student,
            ).delete()

            if deleted:
                messages.success(request, f"Removed {student.user.get_full_name() or student.user.username} from {module.code}.")
            else:
                messages.info(request, "That student was not enrolled in this module.")

        elif action == "add_lecturer":
            module = get_object_or_404(Module, pk=request.POST.get("lecturer_module_id"))
            lecturer = get_object_or_404(LecturerProfile, pk=request.POST.get("lecturer_id"))

            should_be_primary = not module.lecturer_enrolments.exists()

            _, created = ModuleEnrollmentLecturer.objects.get_or_create(
                module=module,
                lecturer=lecturer,
                defaults={"is_primary": should_be_primary},
            )

            if created:
                messages.success(request, f"Added {lecturer.user.get_full_name() or lecturer.user.username} to {module.code}.")
            else:
                messages.info(request, "That lecturer is already enrolled in this module.")

        elif action == "remove_lecturer":
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))
            lecturer = get_object_or_404(LecturerProfile, pk=request.POST.get("lecturer_id"))

            was_primary = ModuleEnrollmentLecturer.objects.filter(
                module=module,
                lecturer=lecturer,
                is_primary=True,
            ).exists()

            deleted, _ = ModuleEnrollmentLecturer.objects.filter(
                module=module,
                lecturer=lecturer,
            ).delete()

            if deleted:
                if was_primary:
                    _ensure_primary_lecturer(module)
                messages.success(request, f"Removed {lecturer.user.get_full_name() or lecturer.user.username} from {module.code}.")
            else:
                messages.info(request, "That lecturer was not enrolled in this module.")

        else:
            messages.error(request, "Unknown admin enrollment action.")

        return redirect("accounts:admin_edit_enrollment")

    modules = Module.objects.filter(is_active=True).order_by("code", "title")
    students = StudentProfile.objects.select_related("user").order_by("user__last_name", "user__first_name", "student_number")
    lecturers = LecturerProfile.objects.select_related("user").order_by("user__last_name", "user__first_name", "staff_id")

    context = _admin_page_context(user, "Edit Enrollment")
    context.update(
        {
            "modules": modules,
            "students": students,
            "lecturers": lecturers,
            "enrollment_rows": _build_admin_enrollment_rows(),
        }
    )
    return render(request, "accounts/admin_edit_enrollment.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_create_global_announcement(request):
    user: User = request.user
    _require_admin_user(user)

    errors = []

    if request.method == "POST":
        title, content, errors = _validate_announcement_form(request)

        if not errors:
            GlobalAnnouncement.objects.create(
                title=title,
                content=content,
                created_by=user,
            )
            GlobalAnnouncement.trim_to_latest_three()

            messages.success(request, "Global announcement created successfully.")
            return redirect("accounts:admin_dashboard")

    context = _admin_page_context(user, "Create Global Announcement")
    context.update(
        {
            "errors": errors,
            "initial": {
                "title": request.POST.get("title", ""),
                "content": request.POST.get("content", ""),
            },
        }
    )
    return render(request, "accounts/admin_global_announcement_form.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def admin_edit_global_announcement(request, announcement_id):
    user: User = request.user
    _require_admin_user(user)

    announcement = get_object_or_404(GlobalAnnouncement, pk=announcement_id)
    errors = []

    if request.method == "POST":
        title, content, errors = _validate_announcement_form(request)

        if not errors:
            announcement.title = title
            announcement.content = content
            announcement.save(update_fields=["title", "content", "updated_at"])

            messages.success(request, "Global announcement updated successfully.")
            return redirect("accounts:admin_dashboard")

    context = _admin_page_context(user, "Edit Global Announcement")
    context.update(
        {
            "errors": errors,
            "announcement": announcement,
            "initial": {
                "title": request.POST.get("title", announcement.title) if request.method == "POST" else announcement.title,
                "content": request.POST.get("content", announcement.content) if request.method == "POST" else announcement.content,
            },
        }
    )
    return render(request, "accounts/admin_global_announcement_form.html", context)


@login_required
@require_http_methods(["POST"])
def admin_delete_global_announcement(request, announcement_id):
    user: User = request.user
    _require_admin_user(user)

    announcement = get_object_or_404(GlobalAnnouncement, pk=announcement_id)
    announcement.delete()

    messages.success(request, "Global announcement deleted successfully.")
    return redirect("accounts:admin_dashboard")

@login_required
@require_http_methods(["POST"])
def update_accessibility_preferences(request):
    user = request.user

    colour_scheme = (request.POST.get("colour_scheme") or user.colour_scheme).strip()
    font_scheme = (request.POST.get("font_scheme") or user.font_scheme).strip()

    valid_colour_schemes = {choice[0] for choice in User.ColourScheme.choices}
    valid_font_schemes = {choice[0] for choice in User.FontScheme.choices}

    if colour_scheme not in valid_colour_schemes:
        colour_scheme = User.ColourScheme.DEFAULT

    if font_scheme not in valid_font_schemes:
        font_scheme = User.FontScheme.DEFAULT

    user.colour_scheme = colour_scheme
    user.font_scheme = font_scheme
    user.save(update_fields=["colour_scheme", "font_scheme"])

    next_url = request.POST.get("next") or reverse("accounts:dashboard")
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("accounts:dashboard")

    return redirect(next_url)

@login_required
def user_profile(request):
    _rollover_modules_if_due()
    user: User = request.user

    if user.is_admin():
        return redirect("accounts:admin_dashboard")

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "display_name": user.get_full_name() or user.username,
        "profile_email": user.username,
    }

    if user.is_student():
        student = get_object_or_404(
            StudentProfile.objects.select_related("user"),
            user=user,
        )

        context.update(
            {
                "profile_role": "student",
                "course": student.course or "N/A",
                "module_rows": _build_student_profile_modules(student),
            }
        )

    elif user.is_lecturer():
        lecturer = get_object_or_404(
            LecturerProfile.objects.select_related("user"),
            user=user,
        )

        context.update(
            {
                "profile_role": "lecturer",
                "module_rows": _build_lecturer_profile_modules(lecturer),
            }
        )

    else:
        raise Http404("Profile not found")

    return render(request, "accounts/profile.html", context)

@login_required
def open_notification(request, notification_id):
    notification = get_object_or_404(
        Notification,
        pk=notification_id,
        recipient=request.user,
    )

    notification.mark_as_read()

    if notification.redirect_url:
        return redirect(notification.redirect_url)

    return redirect("accounts:dashboard")

@login_required
def portal(request):
    _rollover_modules_if_due()
    user: User = request.user

    if user.is_admin():
        return redirect("accounts:admin_dashboard")

    today = timezone.localdate()

    try:
        selected_year = int(request.GET.get("year", today.year))
        selected_month = int(request.GET.get("month", today.month))
        if selected_month < 1 or selected_month > 12:
            raise ValueError
    except (TypeError, ValueError):
        selected_year = today.year
        selected_month = today.month

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "office_tiles": _portal_office_tiles(),
        "timetable_url": "https://timetables.tudublin.ie/",
    }

    context.update(
        _build_portal_calendar_context(
            user=user,
            year=selected_year,
            month=selected_month,
        )
    )

    return render(request, "accounts/portal.html", context)

@login_required
def module_detail(request, code):
    user: User = request.user
    nav_items = _shared_nav_items()

    try:
        module = (
            Module.objects
            .prefetch_related(
                "assignments__files",
                "quizzes",
                "module_announcements__created_by",
            )
            .get(code=code)
        )
    except Module.DoesNotExist:
        raise Http404("Module not found")

    run_start, run_end = module.current_cycle_window()
    now = timezone.now()
    module_announcements = _recent_module_announcements(module)

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
            "module_announcements": module_announcements,
            "weeks": weeks,
            "run_start": run_start,
            "run_end": run_end,
        }

    elif user.is_lecturer():
        lecturer = user.lecturer_profile
        if not lecturer.modules.filter(pk=module.pk).exists():
            raise Http404("Module not found")

        role = "lecturer"
        assessment_items = _build_lecturer_module_assessment_items(module)

        requested_week_number = request.GET.get("week")
        try:
            requested_week_number = int(requested_week_number) if requested_week_number else None
        except (TypeError, ValueError):
            requested_week_number = None

        all_weeks = list(
            module.weeks
            .all()
            .prefetch_related("files__parsed_document")
            .order_by("week_number")
        )

        weeks = []
        for week in all_weeks:
            has_description = bool((week.description or "").strip())
            has_files = bool(week.files.all())
            if has_description or has_files:
                weeks.append(week)

        if requested_week_number is not None:
            requested_week = next(
                (week for week in all_weeks if week.week_number == requested_week_number),
                None,
            )
            if requested_week and requested_week not in weeks:
                weeks.append(requested_week)
                weeks.sort(key=lambda week: week.week_number)

        student_enrolments = sorted(
            module.student_enrolments.select_related("student__user"),
            key=lambda enrolment: (
                (enrolment.student.user.get_full_name() or enrolment.student.user.username).lower(),
                enrolment.student.user.username.lower(),
            ),
        )

        enrolled_students = [
            {
                "name": enrolment.student.user.get_full_name() or enrolment.student.user.username,
                "email": enrolment.student.user.username,
            }
            for enrolment in student_enrolments
        ]

        context = {
            "user": user,
            "nav_items": nav_items,
            "module": module,
            "role": role,
            "assessment_items": assessment_items,
            "module_announcements": module_announcements,
            "weeks": weeks,
            "run_start": run_start,
            "run_end": run_end,
            "enrolled_students": enrolled_students,
            "enrolled_student_count": len(enrolled_students),
        }

    else:
        return redirect("accounts:login")

    return render(request, "accounts/module_detail.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def create_module_announcement(request, code):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    errors = []

    if request.method == "POST":
        title, content, errors = _validate_announcement_form(request)

        if not errors:
            ModuleAnnouncement.objects.create(
                module=module,
                title=title,
                content=content,
                created_by=user,
            )
            ModuleAnnouncement.trim_to_latest_three_for_module(module)

            messages.success(request, "Module announcement created successfully.")
            return redirect("accounts:module_detail", code=module.code)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "errors": errors,
        "initial": {
            "title": request.POST.get("title", ""),
            "content": request.POST.get("content", ""),
        },
    }
    return render(request, "accounts/module_announcement_form.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def edit_module_announcement(request, code, announcement_id):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)
    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, module=module)

    errors = []

    if request.method == "POST":
        title, content, errors = _validate_announcement_form(request)

        if not errors:
            announcement.title = title
            announcement.content = content
            announcement.save(update_fields=["title", "content", "updated_at"])

            messages.success(request, "Module announcement updated successfully.")
            return redirect("accounts:module_detail", code=module.code)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "announcement": announcement,
        "errors": errors,
        "initial": {
            "title": request.POST.get("title", announcement.title) if request.method == "POST" else announcement.title,
            "content": request.POST.get("content", announcement.content) if request.method == "POST" else announcement.content,
        },
    }
    return render(request, "accounts/module_announcement_form.html", context)

@login_required
@require_http_methods(["POST"])
def delete_module_announcement(request, code, announcement_id):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)
    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, module=module)

    announcement.delete()
    messages.success(request, "Module announcement deleted successfully.")
    return redirect("accounts:module_detail", code=module.code)

@login_required
def upload_week_file(request, code, week_number):

    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    week, _ = ModuleWeek.objects.get_or_create(
        module=module,
        week_number=week_number,
        defaults={"title": f"Week {week_number}"},
    )

    if request.method == "POST":
        was_visible = _week_is_viewable(week)
        module_detail_url = reverse("accounts:module_detail", args=[module.code])

        if "file" not in request.FILES:
            messages.error(request, "Please choose a .docx or .pptx file to upload.")
            return redirect("accounts:module_detail", code=module.code)

        uploaded = request.FILES["file"]

        try:
            parsed_payload = parse_uploaded_office_file(uploaded)
        except ValueError as exc:
            _notify_lecturers_parser_failure(module, uploaded.name, module_detail_url)
            messages.error(request, str(exc))
            return redirect("accounts:module_detail", code=module.code)

        except Exception:
            _notify_lecturers_parser_failure(module, uploaded.name, module_detail_url)
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

            _notify_lecturers_parser_failure(module, uploaded.name, module_detail_url)
            messages.error(
                request,
                "The file was not published because parsing/storage failed.",
            )
            return redirect("accounts:module_detail", code=module.code)

        _notify_lecturers_parser_success(module, uploaded.name, module_detail_url)

        if not was_visible:
            _notify_students_if_week_now_viewable(week)

        messages.success(request, "Weekly file uploaded and parsed successfully.")

    return redirect("accounts:module_detail", code=module.code)


@login_required
def edit_week_description(request, code, week_number):

    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    week, _ = ModuleWeek.objects.get_or_create(
        module=module,
        week_number=week_number,
        defaults={"title": f"Week {week_number}"},
    )

    if request.method == "POST":
        was_visible = _week_is_viewable(week)
        description = request.POST.get("description", "").strip()
        week.description = description
        week.save()

        if not was_visible:
            _notify_students_if_week_now_viewable(week)

    return redirect("accounts:module_detail", code=module.code)

@login_required
@require_http_methods(["POST"])
def add_module_week(request, code):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    next_week_number = (
        module.weeks.aggregate(max_week=Max("week_number")).get("max_week") or 0
    ) + 1

    week, _ = ModuleWeek.objects.get_or_create(
        module=module,
        week_number=next_week_number,
        defaults={"title": f"Week {next_week_number}"},
    )

    return redirect(f"{reverse('accounts:module_detail', args=[module.code])}?week={week.week_number}")

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
        create_assignment_url = reverse("accounts:create_assignment", args=[module.code])

        if not errors and uploaded_files:
            for uploaded in uploaded_files:
                try:
                    parsed_payload = parse_uploaded_office_file(uploaded)
                    parsed_file_payloads.append((uploaded, parsed_payload))
                except ValueError as exc:
                    _notify_lecturers_parser_failure(module, uploaded.name, create_assignment_url)
                    errors.append(f"{uploaded.name}: {exc}")
                except Exception:
                    _notify_lecturers_parser_failure(module, uploaded.name, create_assignment_url)
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

                _notify_lecturers_parser_failure(module, "assignment materials", create_assignment_url)
                errors.append(
                    "The assignment was not published because one or more uploaded files "
                    "failed during parsing/storage."
                )
            else:
                assignment_detail_url = reverse(
                    "accounts:assignment_detail",
                    args=[module.code, assignment.id],
                )

                for assignment_file in created_assignment_files:
                    _notify_lecturers_parser_success(
                        module,
                        assignment_file.original_name or assignment_file.file.name,
                        assignment_detail_url,
                    )

                _notify_students_new_assignment(assignment)

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

            _notify_students_new_quiz(quiz)

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


@login_required
@require_http_methods(["POST"])
def submit_assignment(request, code, assignment_id):

    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    module = get_object_or_404(Module, code=code)

    if not student.modules.filter(pk=module.pk).exists():
        raise Http404("Not found")

    assignment = get_object_or_404(
        Assignment,
        pk=assignment_id,
        module=module,
    )

    submission, created = AssignmentSubmission.objects.get_or_create(
        assignment=assignment,
        student=student,
        defaults={"status": AssignmentSubmission.Status.SUBMITTED},
    )

    now = timezone.now()
    if assignment.due_datetime and now > assignment.due_datetime:
        submission.status = AssignmentSubmission.Status.LATE
    else:
        submission.status = AssignmentSubmission.Status.SUBMITTED
    submission.submitted_at = now
    submission.save()

    for uploaded in request.FILES.getlist("files"):
        SubmissionFile.objects.create(
            submission=submission,
            file=uploaded,
            original_name=uploaded.name,
            uploaded_by=user,
        )

    _notify_student_assignment_submitted(submission)

    return redirect("accounts:assignment_detail", code=module.code, assignment_id=assignment.id)

@login_required
@require_http_methods(["GET", "POST"])
def grade_submission(request, code, assignment_id, submission_id):

    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)
    assignment = get_object_or_404(Assignment, pk=assignment_id, module=module)
    submission = get_object_or_404(
        AssignmentSubmission.objects.select_related("student__user"),
        pk=submission_id,
        assignment=assignment,
    )

    errors = []
    grade_obj = getattr(submission, "grade", None)
    initial_value = ""
    initial_feedback = ""

    if grade_obj:
        initial_value = grade_obj.value
        initial_feedback = grade_obj.feedback_text or ""

    if request.method == "POST":
        value_str = request.POST.get("value", "").strip()
        feedback = request.POST.get("feedback", "").strip()

        if not value_str:
            errors.append("A mark is required.")
        else:
            try:
                value_float = float(value_str)
            except ValueError:
                errors.append("Mark must be a number.")
                value_float = None

        if not errors and value_float is not None:
            if grade_obj is None:
                grade_obj = AssignmentGrade.objects.create(
                    submission=submission,
                    marker=lecturer,
                    value=value_float,
                    feedback_text=feedback,
                )
            else:
                grade_obj.value = value_float
                grade_obj.feedback_text = feedback
                grade_obj.marker = lecturer
                grade_obj.save()

            _notify_student_assignment_graded(grade_obj)

            return redirect("accounts:assignment_detail", code=module.code, assignment_id=assignment.id)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "assignment": assignment,
        "submission": submission,
        "errors": errors,
        "initial": {
            "value": request.POST.get("value", initial_value) if request.method == "POST" else initial_value,
            "feedback": request.POST.get("feedback", initial_feedback) if request.method == "POST" else initial_feedback,
        },
    }

    return render(request, "accounts/grade_submission.html", context)

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
