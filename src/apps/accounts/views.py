import re  # Regular expressions module, used for validating input
import json # Standard library for working with JSON data, used in some views for parsing or returning JSON payloads
import calendar as pycalendar  # Standard library for calendar-related functions, used in some views for date calculations
import os # Standard library for operating system interactions, used in file handling and path manipulations
from django.contrib.auth.decorators import login_required  # Imports decorator to ensure some views are only accessible to authenticated users
from django.contrib.auth.views import LoginView  # Imports Django’s built-in class-based login view for handling authentication
from django.shortcuts import redirect, render, get_object_or_404  # Common shortcuts for redirects, rendering templates, and fetching objects or returning 404
from django.urls import reverse  # Used to dynamically resolve URL patterns by their name
from django.utils import timezone  # Provides timezone-aware datetime utilities compatible with Django settings
from django.http import Http404, JsonResponse  # Exception used to immediately return a 404 Not Found response / Class for returning JSON responses in views
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit # Standard library utilities for parsing and constructing URLs, used in some views for handling redirect URLs and query parameters
from django.db.models import Count, Q, Max  # ORM helpers: Count for aggregation and Q for complex query filters
from django.views.decorators.http import require_http_methods  # Decorator to restrict allowed HTTP methods per view
from datetime import datetime, timedelta, date  # Standard library datetime class used for parsing date and time input / timedelta for date arithmetic
from collections import defaultdict  # Standard library class for creating dictionaries with default value types, used in some views for grouping data
from decimal import Decimal, InvalidOperation  # Standard library Decimal class for precise decimal arithmetic / InvalidOperation for handling invalid decimal operations
from django.contrib import messages  # Django's messaging framework for passing one-time messages to templates
from django.core.files.base import ContentFile  # Utility for creating file objects from raw content, used in file handling
from django.db import transaction  # Provides atomic transaction management for database operations, ensuring data integrity
from .document_parsing import build_rendered_html_from_blocks, parse_uploaded_office_file
from .models import User, StudentProfile, LecturerProfile, Course, AcademicYear, Module, ModulePlacement, ModuleOffering, ModuleOfferingEnrollmentLecturer, ModuleOfferingEnrollmentStudent, Assignment, AssignmentSubmission, AssignmentGrade, AssignmentFile, SubmissionFile, ModuleWeek, ModuleWeekFile, ParsedDocument, ParsedDocumentImage, Quiz, QuizQuestion, QuizOption, QuizAttempt, QuizAnswer, Notification, GlobalAnnouncement, ModuleAnnouncement  # Imports all custom models referenced by these views
from .notifications import create_notification, notify_offering_students, notify_offering_lecturers # Imports notification helper functions for creating notifications and sending them to students or lecturers of a module
from django.utils.http import url_has_allowed_host_and_scheme # Utility to validate that a URL is safe for redirects, preventing open redirect vulnerabilities
from django.contrib.auth.forms import AuthenticationForm # Django's built-in authentication form, used in the login view for handling user login input and validation - used in this case to format input in checks.
from django.contrib.auth.password_validation import validate_password # Django's built-in password validation function, used to validate password strength and compliance with configured validators
from django.core.exceptions import ValidationError as DjangoValidationError # Exception class for handling validation errors, used in password validation and other input checks

# Temporary
# import traceback
# from django.http import HttpResponse
# from django.utils.html import escape

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


def _ensure_primary_lecturer(offering: ModuleOffering):
    if offering.lecturer_enrolments.filter(is_primary=True).exists():
        return

    first_enrolment = offering.lecturer_enrolments.order_by("id").first()
    if first_enrolment:
        first_enrolment.is_primary = True
        first_enrolment.save(update_fields=["is_primary"])

def _get_available_course_codes() -> list[str]:
    return list(
        Course.objects.filter(
            is_active=True,
            module_placements__available_now=True,
            module_placements__module__is_active=True,
        )
        .order_by("code")
        .values_list("code", flat=True)
        .distinct()
    )


def _get_course_by_code(course_code: str):
    if not course_code:
        return None
    return Course.objects.filter(code__iexact=course_code, is_active=True).first()

def _build_module_selector_rows(course_code: str | None = None) -> list[dict]:
    placements = (
        ModulePlacement.objects.select_related("module", "course")
        .filter(
            available_now=True,
            module__is_active=True,
            course__is_active=True,
        )
        .order_by("module__code", "module__title", "course__code")
    )

    if course_code:
        placements = placements.filter(
            course__code__iexact=_normalize_course_code(course_code)
        )

    rows_by_module_id: dict[int, dict] = {}

    for placement in placements:
        module = placement.module
        row = rows_by_module_id.setdefault(
            module.id,
            {
                "id": module.id,
                "code": module.code,
                "title": module.title,
                "label": f"{module.code} – {module.title}",
                "course_codes": [],
            },
        )

        if placement.course.code not in row["course_codes"]:
            row["course_codes"].append(placement.course.code)

    rows = list(rows_by_module_id.values())
    for row in rows:
        row["course_codes"] = sorted(row["course_codes"])

    return rows

def _parse_module_course_lines(raw_value: str, errors: list[str]) -> list[Course]:
    courses: list[Course] = []
    seen: set[int] = set()

    lines = [line.strip() for line in (raw_value or "").splitlines() if line.strip()]
    if not lines:
        errors.append("At least one course placement is required.")
        return courses

    for line in lines:
        course_code = _normalize_course_code(line)

        if not COURSE_CODE_RE.match(course_code):
            errors.append(f"Invalid course code '{course_code}'.")
            continue

        course = _get_course_by_code(course_code)
        if not course:
            errors.append(f"Course '{course_code}' does not exist or is inactive.")
            continue

        if course.id in seen:
            continue

        seen.add(course.id)
        courses.append(course)

    return courses

def _get_student_by_username(username: str):
    username = (username or "").strip().lower()
    if not username:
        return None
    return (
        StudentProfile.objects.select_related("user")
        .filter(user__username__iexact=username)
        .first()
    )


def _get_lecturer_by_username(username: str):
    username = (username or "").strip().lower()
    if not username:
        return None
    return (
        LecturerProfile.objects.select_related("user")
        .filter(user__username__iexact=username)
        .first()
    )

def _derived_student_status_after_unlock(student: StudentProfile):
    return StudentProfile.Status.ACTIVE

def _current_module_ids_for_student(student: StudentProfile):
    current_year = _get_current_academic_year()
    if not current_year:
        return set()

    return set(
        ModuleOfferingEnrollmentStudent.objects.filter(
            student=student,
            offering__academic_year=current_year,
            offering__is_current=True,
        ).values_list("offering__module_id", flat=True)
    )


def _current_module_ids_for_lecturer(lecturer: LecturerProfile):
    current_year = _get_current_academic_year()
    if not current_year:
        return set()

    return set(
        ModuleOfferingEnrollmentLecturer.objects.filter(
            lecturer=lecturer,
            offering__academic_year=current_year,
            offering__is_current=True,
        ).values_list("offering__module_id", flat=True)
    )

def _build_addable_modules_for_student(student: StudentProfile):
    course_code = _normalize_course_code(student.course or "")
    if not course_code or student.status != StudentProfile.Status.ACTIVE:
        return Module.objects.none()

    existing_module_ids = _current_module_ids_for_student(student)

    return (
        Module.objects.filter(
            is_active=True,
            placements__course__code__iexact=course_code,
            placements__available_now=True,
            placements__course__is_active=True,
        )
        .exclude(pk__in=existing_module_ids)
        .distinct()
        .order_by("code", "title")
    )

def _build_removable_modules_for_student(student: StudentProfile):
    existing_module_ids = _current_module_ids_for_student(student)

    return (
        Module.objects.filter(
            is_active=True,
            pk__in=existing_module_ids,
        )
        .distinct()
        .order_by("code", "title")
    )


def _build_addable_modules_for_lecturer(lecturer: LecturerProfile):
    current_year = _get_current_academic_year()
    if not current_year:
        return Module.objects.none()

    existing_module_ids = _current_module_ids_for_lecturer(lecturer)

    return (
        Module.objects.filter(
            is_active=True,
            placements__available_now=True,
            placements__course__is_active=True,
            offerings__academic_year=current_year,
            offerings__is_current=True,
        )
        .exclude(pk__in=existing_module_ids)
        .distinct()
        .order_by("code", "title")
    )

def _build_removable_modules_for_lecturer(lecturer: LecturerProfile):
    existing_module_ids = _current_module_ids_for_lecturer(lecturer)

    return (
        Module.objects.filter(
            is_active=True,
            pk__in=existing_module_ids,
        )
        .distinct()
        .order_by("code", "title")
    )

def _redirect_with_query(url_name: str, **params):
    filtered = {key: value for key, value in params.items() if value}
    base_url = reverse(url_name)
    if not filtered:
        return redirect(base_url)
    return redirect(f"{base_url}?{urlencode(filtered)}")

def _search_modules_for_admin(query: str):
    query = (query or "").strip()
    if not query:
        return Module.objects.none()

    return (
        Module.objects.filter(
            Q(code__icontains=query) | Q(title__icontains=query)
        )
        .order_by("code", "title")[:20]
    )


def _build_module_retire_summary(module: Module):
    current_year = _get_current_academic_year()

    placements = list(
        module.placements
        .select_related("course")
        .order_by("course__code")
    )

    current_offerings = []
    if current_year:
        current_offerings = list(
            ModuleOffering.objects.filter(
                module=module,
                academic_year=current_year,
            )
            .select_related("module", "academic_year")
            .annotate(
                student_count=Count("student_enrolments", distinct=True),
                lecturer_count=Count("lecturer_enrolments", distinct=True),
            )
            .order_by("module__code")
        )

    return {
        "placements": placements,
        "current_offerings": current_offerings,
        "current_year": current_year,
    }

def _get_current_academic_year():
    return AcademicYear.objects.filter(is_current=True).order_by("-start_date").first()


def _build_academic_year_label(start_date: date, end_date: date) -> str:
    return f"{start_date.year}/{str(end_date.year)[-2:]}"


def _ensure_module_offering_for_module(module: Module, academic_year: AcademicYear):
    offering, created = ModuleOffering.objects.get_or_create(
        module=module,
        academic_year=academic_year,
        defaults={
            "is_current": academic_year.is_current,
            "is_read_only": False,
        },
    )

    changed_fields = []
    if offering.is_current != academic_year.is_current:
        offering.is_current = academic_year.is_current
        changed_fields.append("is_current")

    if offering.is_read_only:
        offering.is_read_only = False
        changed_fields.append("is_read_only")

    if changed_fields:
        offering.save(update_fields=changed_fields)

    return offering, created

def _sync_current_module_offerings(academic_year: AcademicYear) -> int:
    created_count = 0

    modules = (
        Module.objects.filter(
            is_active=True,
            placements__available_now=True,
            placements__course__is_active=True,
        )
        .distinct()
        .order_by("code")
    )

    for module in modules:
        _, created = _ensure_module_offering_for_module(module, academic_year)
        if created:
            created_count += 1

    return created_count

def _find_current_student_offering(student: StudentProfile, module: Module, academic_year: AcademicYear | None = None):
    academic_year = academic_year or _get_current_academic_year()
    if not academic_year:
        return None

    course_code = _normalize_course_code(student.course or "")
    if not course_code:
        return None

    allowed = ModulePlacement.objects.filter(
        module=module,
        course__code__iexact=course_code,
        available_now=True,
        module__is_active=True,
        course__is_active=True,
    ).exists()

    if not allowed:
        return None

    offering, _ = _ensure_module_offering_for_module(module, academic_year)
    return offering

def _get_current_offering_for_lecturer_module(module: Module, academic_year: AcademicYear | None = None):
    academic_year = academic_year or _get_current_academic_year()
    if not academic_year:
        return None

    allowed = ModulePlacement.objects.filter(
        module=module,
        available_now=True,
        module__is_active=True,
        course__is_active=True,
    ).exists()

    if not allowed:
        return None

    offering, _ = _ensure_module_offering_for_module(module, academic_year)
    return offering

def _sync_student_current_offering_enrolment(student: StudentProfile, module: Module, academic_year: AcademicYear | None = None):
    offering = _find_current_student_offering(student, module, academic_year=academic_year)
    if not offering:
        return False

    _, created = ModuleOfferingEnrollmentStudent.objects.get_or_create(
        offering=offering,
        student=student,
    )
    return created


def _remove_student_current_offering_enrolment(student: StudentProfile, module: Module, academic_year: AcademicYear | None = None):
    offering = _find_current_student_offering(student, module, academic_year=academic_year)
    if not offering:
        return 0

    deleted, _ = ModuleOfferingEnrollmentStudent.objects.filter(
        offering=offering,
        student=student,
    ).delete()
    return deleted


def _sync_lecturer_current_offering_enrolment(lecturer: LecturerProfile, module: Module, academic_year: AcademicYear | None = None):
    offering = _get_current_offering_for_lecturer_module(module, academic_year=academic_year)
    if not offering:
        return 0

    offering_has_primary = offering.lecturer_enrolments.filter(is_primary=True).exists()

    enrolment, created = ModuleOfferingEnrollmentLecturer.objects.get_or_create(
        offering=offering,
        lecturer=lecturer,
        defaults={"is_primary": not offering_has_primary},
    )

    if not created and not offering_has_primary and not enrolment.is_primary:
        enrolment.is_primary = True
        enrolment.save(update_fields=["is_primary"])

    return 1 if created else 0

def _remove_lecturer_current_offering_enrolment(lecturer: LecturerProfile, module: Module, academic_year: AcademicYear | None = None):
    offering = _get_current_offering_for_lecturer_module(module, academic_year=academic_year)
    if not offering:
        return 0

    deleted, _ = ModuleOfferingEnrollmentLecturer.objects.filter(
        offering=offering,
        lecturer=lecturer,
    ).delete()
    return deleted

def _safe_add_years(date_value: date, years: int = 1) -> date:
    try:
        return date_value.replace(year=date_value.year + years)
    except ValueError:
        if date_value.month == 2 and date_value.day == 29:
            return date_value.replace(year=date_value.year + years, month=2, day=28)
        raise


def _build_next_academic_year_window(current_year: AcademicYear):
    next_start = _safe_add_years(current_year.start_date, 1)
    next_end = _safe_add_years(current_year.end_date, 1)

    return {
        "start_date": next_start,
        "end_date": next_end,
        "label": _build_academic_year_label(next_start, next_end),
    }


def _roll_forward_module_placement_availability():
    updated_count = 0

    for placement in ModulePlacement.objects.all():
        new_available_now = placement.available_next_rollover
        if placement.available_now != new_available_now:
            placement.available_now = new_available_now
            placement.save(update_fields=["available_now"])
            updated_count += 1

    return updated_count


def _create_next_current_module_offerings(academic_year: AcademicYear):
    created_count = 0

    modules = (
        Module.objects.filter(
            is_active=True,
            placements__available_next_rollover=True,
            placements__course__is_active=True,
        )
        .distinct()
        .order_by("code")
    )

    for module in modules:
        offering, created = ModuleOffering.objects.get_or_create(
            module=module,
            academic_year=academic_year,
            defaults={
                "is_current": True,
                "is_read_only": False,
            },
        )

        changed_fields = []
        if not offering.is_current:
            offering.is_current = True
            changed_fields.append("is_current")

        if offering.is_read_only:
            offering.is_read_only = False
            changed_fields.append("is_read_only")

        if changed_fields:
            offering.save(update_fields=changed_fields)

        if created:
            created_count += 1

    return created_count


def _copy_lecturers_to_next_current_offerings(previous_current_year: AcademicYear, next_current_year: AcademicYear):
    created_count = 0

    previous_offerings = (
        ModuleOffering.objects.filter(
            academic_year=previous_current_year,
        )
        .select_related("module")
        .prefetch_related("lecturer_enrolments")
    )

    for previous_offering in previous_offerings:
        next_offering = ModuleOffering.objects.filter(
            module=previous_offering.module,
            academic_year=next_current_year,
        ).first()

        if not next_offering:
            continue

        for lecturer_enrolment in previous_offering.lecturer_enrolments.all():
            new_enrolment, created = ModuleOfferingEnrollmentLecturer.objects.get_or_create(
                offering=next_offering,
                lecturer=lecturer_enrolment.lecturer,
                defaults={"is_primary": lecturer_enrolment.is_primary},
            )

            if not created and lecturer_enrolment.is_primary and not new_enrolment.is_primary:
                new_enrolment.is_primary = True
                new_enrolment.save(update_fields=["is_primary"])

            if created:
                created_count += 1

    return created_count

def _start_new_academic_year_transition(current_year: AcademicYear):
    next_window = _build_next_academic_year_window(current_year)

    with transaction.atomic():
        _sync_current_module_offerings(current_year)

        current_year.is_current = False
        current_year.save(update_fields=["is_current"])

        ModuleOffering.objects.filter(
            academic_year=current_year,
        ).update(
            is_current=False,
            is_read_only=True,
        )

        next_year, created = AcademicYear.objects.get_or_create(
            label=next_window["label"],
            defaults={
                "start_date": next_window["start_date"],
                "end_date": next_window["end_date"],
                "is_current": True,
            },
        )

        if not created:
            next_year.start_date = next_window["start_date"]
            next_year.end_date = next_window["end_date"]
            next_year.is_current = True
            next_year.save(update_fields=["start_date", "end_date", "is_current"])

        placement_updates = _roll_forward_module_placement_availability()
        created_offerings = _create_next_current_module_offerings(next_year)
        copied_lecturers = _copy_lecturers_to_next_current_offerings(current_year, next_year)

    return {
        "next_year": next_year,
        "placement_updates": placement_updates,
        "created_offerings": created_offerings,
        "copied_lecturers": copied_lecturers,
    }

def _get_accessible_offering_for_user(user: User, offering_id: int):
    offering = get_object_or_404(
        ModuleOffering.objects.select_related(
            "module",
            "academic_year",
        ),
        pk=offering_id,
    )

    if user.is_student():
        if not ModuleOfferingEnrollmentStudent.objects.filter(
            offering=offering,
            student=user.student_profile,
        ).exists():
            raise Http404("Offering not found")
    elif user.is_lecturer():
        if not ModuleOfferingEnrollmentLecturer.objects.filter(
            offering=offering,
            lecturer=user.lecturer_profile,
        ).exists():
            raise Http404("Offering not found")
    else:
        raise Http404("Offering not found")

    return offering

def _get_writable_lecturer_offering_by_id(user: User, offering_id: int):
    if not user.is_lecturer():
        raise Http404("Offering not found")

    offering = _get_accessible_offering_for_user(user, offering_id)

    if _is_read_only_offering(offering):
        raise Http404("Offering not found")

    return offering

def _is_read_only_offering(offering: ModuleOffering) -> bool:
    return offering.is_read_only or not offering.is_current

def _current_offering_queryset_for_student(student: StudentProfile):
    current_year = _get_current_academic_year()
    if not current_year:
        return ModuleOffering.objects.none()

    return (
        ModuleOffering.objects.filter(
            academic_year=current_year,
            is_current=True,
            student_enrolments__student=student,
        )
        .select_related("module", "academic_year")
        .prefetch_related("lecturer_enrolments__lecturer__user")
        .annotate(student_count=Count("student_enrolments", distinct=True))
        .distinct()
        .order_by("module__code")
    )


def _current_offering_queryset_for_lecturer(lecturer: LecturerProfile):
    current_year = _get_current_academic_year()
    if not current_year:
        return ModuleOffering.objects.none()

    return (
        ModuleOffering.objects.filter(
            academic_year=current_year,
            is_current=True,
            lecturer_enrolments__lecturer=lecturer,
        )
        .select_related("module", "academic_year")
        .annotate(student_count=Count("student_enrolments", distinct=True))
        .distinct()
        .order_by("module__code")
    )

def _previous_offering_queryset_for_student(student: StudentProfile):
    current_year = _get_current_academic_year()

    qs = (
        ModuleOffering.objects.filter(
            student_enrolments__student=student,
        )
        .select_related("module", "academic_year")
        .prefetch_related("lecturer_enrolments__lecturer__user")
        .annotate(student_count=Count("student_enrolments", distinct=True))
        .distinct()
        .order_by("-academic_year__start_date", "module__code")
    )

    if current_year:
        qs = qs.exclude(academic_year=current_year, is_current=True)

    return qs


def _previous_offering_queryset_for_lecturer(lecturer: LecturerProfile):
    current_year = _get_current_academic_year()

    qs = (
        ModuleOffering.objects.filter(
            lecturer_enrolments__lecturer=lecturer,
        )
        .select_related("module", "academic_year")
        .annotate(student_count=Count("student_enrolments", distinct=True))
        .distinct()
        .order_by("-academic_year__start_date", "module__code")
    )

    if current_year:
        qs = qs.exclude(academic_year=current_year, is_current=True)

    return qs


def _group_offerings_by_academic_year(offerings):
    grouped = defaultdict(list)
    ordered_year_ids = []

    for offering in offerings:
        academic_year_id = offering.academic_year_id
        if academic_year_id not in grouped:
            ordered_year_ids.append(academic_year_id)
        grouped[academic_year_id].append(offering)

    return [
        {
            "academic_year_label": grouped[academic_year_id][0].academic_year.label,
            "offerings": grouped[academic_year_id],
        }
        for academic_year_id in ordered_year_ids
    ]


def _build_previous_student_dashboard_year_groups(student: StudentProfile, next_url=None):
    previous_offerings = list(_previous_offering_queryset_for_student(student))

    return [
        {
            "academic_year_label": group["academic_year_label"],
            "rows": _build_student_dashboard_module_rows(group["offerings"], next_url),
        }
        for group in _group_offerings_by_academic_year(previous_offerings)
    ]


def _build_previous_lecturer_dashboard_year_groups(lecturer: LecturerProfile, next_url=None):
    previous_offerings = list(_previous_offering_queryset_for_lecturer(lecturer))

    return [
        {
            "academic_year_label": group["academic_year_label"],
            "rows": _build_lecturer_dashboard_module_rows(group["offerings"], next_url),
        }
        for group in _group_offerings_by_academic_year(previous_offerings)
    ]


def _build_previous_student_profile_year_groups(student: StudentProfile, next_url=None):
    previous_offerings = list(_previous_offering_queryset_for_student(student))

    return [
        {
            "academic_year_label": group["academic_year_label"],
            "module_rows": _build_student_profile_modules(group["offerings"], student, next_url),
        }
        for group in _group_offerings_by_academic_year(previous_offerings)
    ]


def _build_previous_lecturer_profile_year_groups(lecturer: LecturerProfile, next_url=None):
    previous_offerings = list(_previous_offering_queryset_for_lecturer(lecturer))

    return [
        {
            "academic_year_label": group["academic_year_label"],
            "module_rows": _build_lecturer_profile_modules(group["offerings"], lecturer, next_url),
        }
        for group in _group_offerings_by_academic_year(previous_offerings)
    ]

def _primary_offering_lecturer_name(offering: ModuleOffering) -> str:
    enrolments = list(offering.lecturer_enrolments.all())
    primary = next((enrolment for enrolment in enrolments if enrolment.is_primary), None)
    chosen = primary or (enrolments[0] if enrolments else None)

    if not chosen:
        return "TBA"

    return chosen.lecturer.user.get_full_name() or chosen.lecturer.user.username


def _build_student_dashboard_module_rows(offerings_qs, next_url=None):
    rows = []

    for offering in offerings_qs:
        rows.append(
            {
                "code": offering.module.code,
                "title": offering.module.title,
                "url": _append_next_param(
                    reverse("accounts:offering_detail", args=[offering.id]),
                    next_url,
                ),
                "lecturer_name": _primary_offering_lecturer_name(offering),
                "academic_year_label": offering.academic_year.label,
            }
        )

    return rows


def _build_lecturer_dashboard_module_rows(offerings_qs, next_url=None):
    rows = []

    for offering in offerings_qs:
        rows.append(
            {
                "code": offering.module.code,
                "title": offering.module.title,
                "url": _append_next_param(
                    reverse("accounts:offering_detail", args=[offering.id]),
                    next_url,
                ),
                "student_count": getattr(offering, "student_count", 0),
                "academic_year_label": offering.academic_year.label,
            }
        )

    return rows

def _get_accessible_offering_assignment_for_user(user: User, offering_id: int, assignment_id: int):
    offering = _get_accessible_offering_for_user(user, offering_id)
    assignment = get_object_or_404(
        Assignment.objects.select_related("offering__module").prefetch_related("files__parsed_document"),
        pk=assignment_id,
        offering=offering,
    )
    return offering, assignment


def _get_accessible_offering_quiz_for_user(user: User, offering_id: int, quiz_id: int):
    offering = _get_accessible_offering_for_user(user, offering_id)
    quiz = get_object_or_404(
        Quiz.objects.select_related("offering__module").prefetch_related("questions__options"),
        pk=quiz_id,
        offering=offering,
    )
    return offering, quiz

def _recent_offering_module_announcements(offering):
    return (
        offering.module_announcements
        .select_related("created_by")
        .order_by("-created_at", "-id")[:3]
    )

def _portal_office_tiles():
    primary_tiles = [
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
    ]

    more_tile = {
        "label": "More",
        "url": "https://www.microsoft365.com/apps",
        "image": "accounts/images/more.png",
    }

    return primary_tiles, more_tile

def _portal_offering_queryset_for_user(user: User):
    current_year = _get_current_academic_year()
    if not current_year:
        return ModuleOffering.objects.none()

    if user.is_student():
        return (
            ModuleOffering.objects.filter(
                academic_year=current_year,
                is_current=True,
                student_enrolments__student=user.student_profile,
            )
            .select_related("module", "academic_year")
            .distinct()
            .order_by("module__code")
        )

    if user.is_lecturer():
        return (
            ModuleOffering.objects.filter(
                academic_year=current_year,
                is_current=True,
                lecturer_enrolments__lecturer=user.lecturer_profile,
            )
            .select_related("module", "academic_year")
            .distinct()
            .order_by("module__code")
        )

    return ModuleOffering.objects.none()

def _portal_file_links(file_objects):
    links = []
    for file_obj in file_objects:
        links.append(
            {
                "name": file_obj.original_name or os.path.basename(file_obj.file.name),
                "url": file_obj.file.url,
            }
        )
    return links

def _build_portal_week_context(user, today=None, next_url=None):
    today = today or timezone.localdate()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    offerings = list(_portal_offering_queryset_for_user(user))
    rows = []

    student_profile = user.student_profile if user.is_student() else None
    lecturer_profile = user.lecturer_profile if user.is_lecturer() else None

    for offering in offerings:
        module = offering.module
        module_url = _append_next_param(
            reverse("accounts:offering_detail", args=[offering.id]),
            next_url,
        )

        assessment_items = []
        learning_items = []
        grade_items = []

        new_assignments = (
            Assignment.objects.filter(
                offering=offering,
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            )
            .prefetch_related("files")
            .order_by("-created_at")
        )

        for assignment in new_assignments:
            assessment_items.append(
                {
                    "title": assignment.title,
                    "url": _append_next_param(
                        reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                        next_url,
                    ),
                    "files": _portal_file_links(assignment.files.all()),
                }
            )

        new_quizzes = (
            Quiz.objects.filter(
                offering=offering,
                created_at__date__gte=week_start,
                created_at__date__lte=week_end,
            )
            .order_by("-created_at")
        )

        if user.is_student():
            new_quizzes = new_quizzes.filter(is_published=True)

        for quiz in new_quizzes:
            assessment_items.append(
                {
                    "title": quiz.title,
                    "url": _append_next_param(
                        reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),
                        next_url,
                    ),
                    "files": [],
                }
            )

        learning_weeks = (
            ModuleWeek.objects
            .filter(
                offering=offering,
                files__uploaded_at__date__gte=week_start,
                files__uploaded_at__date__lte=week_end,
            )
            .prefetch_related("files")
            .distinct()
            .order_by("week_number")
        )

        for week in learning_weeks:
            learning_items.append(
                {
                    "title": (week.description or f"Week {week.week_number}").strip(),
                    "url": module_url,
                    "files": _portal_file_links(week.files.all()),
                }
            )

        if student_profile:
            assignment_grades = (
                AssignmentGrade.objects
                .filter(
                    submission__student=student_profile,
                    submission__assignment__offering=offering,
                    graded_at__date__gte=week_start,
                    graded_at__date__lte=week_end,
                )
                .select_related("submission__assignment")
                .order_by("-graded_at")
            )

            for grade in assignment_grades:
                assignment = grade.submission.assignment
                grade_items.append(
                    {
                        "title": assignment.title,
                        "url": _append_next_param(
                            reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                            next_url,
                        ),
                        "summary": f"{grade.value}/{assignment.max_mark} · released {grade.graded_at.strftime('%Y-%m-%d %H:%M')}",
                    }
                )

            quiz_attempts = (
                QuizAttempt.objects
                .filter(
                    student=student_profile,
                    quiz__offering=offering,
                    submitted_at__isnull=False,
                    submitted_at__date__gte=week_start,
                    submitted_at__date__lte=week_end,
                )
                .exclude(status=QuizAttempt.Status.IN_PROGRESS)
                .select_related("quiz")
                .order_by("-submitted_at")
            )

            for attempt in quiz_attempts:
                grade_items.append(
                    {
                        "title": attempt.quiz.title,
                        "url": _append_next_param(
                            reverse("accounts:offering_quiz_detail", args=[offering.id, attempt.quiz.id]),
                            next_url,
                        ),
                        "summary": f"{attempt.weighted_score}/{attempt.quiz.max_mark} · released {attempt.submitted_at.strftime('%Y-%m-%d %H:%M')}",
                    }
                )

        elif lecturer_profile:
            assignment_grades = (
                AssignmentGrade.objects
                .filter(
                    marker=lecturer_profile,
                    submission__assignment__offering=offering,
                    graded_at__date__gte=week_start,
                    graded_at__date__lte=week_end,
                )
                .select_related("submission__assignment", "submission__student__user")
                .order_by("-graded_at")
            )

            for grade in assignment_grades:
                assignment = grade.submission.assignment
                student_name = grade.submission.student.user.get_full_name() or grade.submission.student.user.username
                grade_items.append(
                    {
                        "title": assignment.title,
                        "url": _append_next_param(
                            reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                            next_url,
                        ),
                        "summary": f"{student_name} · {grade.value}/{assignment.max_mark} · graded {grade.graded_at.strftime('%Y-%m-%d %H:%M')}",
                    }
                )

            quiz_attempts = (
                QuizAttempt.objects
                .filter(
                    quiz__offering=offering,
                    submitted_at__isnull=False,
                    submitted_at__date__gte=week_start,
                    submitted_at__date__lte=week_end,
                )
                .exclude(status=QuizAttempt.Status.IN_PROGRESS)
                .select_related("quiz", "student__user")
                .order_by("-submitted_at")
            )

            for attempt in quiz_attempts:
                student_name = attempt.student.user.get_full_name() or attempt.student.user.username
                grade_items.append(
                    {
                        "title": attempt.quiz.title,
                        "url": _append_next_param(
                            reverse("accounts:offering_quiz_detail", args=[offering.id, attempt.quiz.id]),
                            next_url,
                        ),
                        "summary": f"{student_name} · {attempt.weighted_score}/{attempt.quiz.max_mark} · submitted {attempt.submitted_at.strftime('%Y-%m-%d %H:%M')}",
                    }
                )

        if assessment_items or learning_items or grade_items:
            rows.append(
                {
                    "module_code": module.code,
                    "module_title": module.title,
                    "module_url": module_url,
                    "assessment_items": assessment_items,
                    "learning_items": learning_items,
                    "grade_items": grade_items,
                }
            )

    return {
        "week_start": week_start,
        "week_end": week_end,
        "portal_week_rows": rows,
    }

def _build_portal_calendar_context(user, year, month, next_url=None):
    today = timezone.localdate()

    first_of_month = date(year, month, 1)
    _, last_day = pycalendar.monthrange(year, month)
    last_of_month = date(year, month, last_day)

    current_offerings = _portal_offering_queryset_for_user(user)

    assignment_qs = (
        Assignment.objects
        .filter(
            offering__in=current_offerings,
            due_datetime__date__gte=first_of_month,
            due_datetime__date__lte=last_of_month,
        )
        .select_related("offering__module")
        .order_by("due_datetime", "title")
    )

    quiz_qs = (
        Quiz.objects
        .filter(
            offering__in=current_offerings,
            close_datetime__date__gte=first_of_month,
            close_datetime__date__lte=last_of_month,
        )
        .select_related("offering__module")
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
                "url": _append_next_param(
                    reverse("accounts:offering_assignment_detail", args=[assignment.offering.id, assignment.id]),
                    next_url,
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
                "url": _append_next_param(
                    reverse("accounts:offering_quiz_detail", args=[quiz.offering.id, quiz.id]),
                    next_url,
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
    notify_offering_students(
        assignment.offering,
        title=f"New assignment: {assignment.title}",
        redirect_url=reverse(
            "accounts:offering_assignment_detail",
            args=[assignment.offering.id, assignment.id],
        ),
        notification_type=Notification.Type.ASSIGNMENT_NEW,
        event_key=f"assignment-new:{assignment.id}",
    )


def _notify_student_assignment_submitted(submission):
    create_notification(
        recipient=submission.student.user,
        offering=submission.assignment.offering,
        title=f"Assignment submitted: {submission.assignment.title}",
        redirect_url=reverse(
            "accounts:offering_assignment_detail",
            args=[submission.assignment.offering.id, submission.assignment.id],
        ),
        notification_type=Notification.Type.ASSIGNMENT_SUBMITTED,
        event_key=f"assignment-submitted:{submission.id}",
    )


def _notify_student_assignment_graded(grade_obj):
    create_notification(
        recipient=grade_obj.submission.student.user,
        offering=grade_obj.submission.assignment.offering,
        title=f"Assignment graded: {grade_obj.submission.assignment.title}",
        redirect_url=reverse(
            "accounts:offering_assignment_detail",
            args=[grade_obj.submission.assignment.offering.id, grade_obj.submission.assignment.id],
        ),
        notification_type=Notification.Type.ASSIGNMENT_GRADED,
    )


def _notify_students_new_quiz(quiz):
    if not quiz.is_published:
        return

    notify_offering_students(
        quiz.offering,
        title=f"New quiz: {quiz.title}",
        redirect_url=reverse(
            "accounts:offering_quiz_detail",
            args=[quiz.offering.id, quiz.id],
        ),
        notification_type=Notification.Type.QUIZ_NEW,
        event_key=f"quiz-new:{quiz.id}",
    )


def _notify_student_quiz_submitted(attempt):
    create_notification(
        recipient=attempt.student.user,
        offering=attempt.quiz.offering,
        title=f"Quiz submitted: {attempt.quiz.title}",
        redirect_url=reverse(
            "accounts:offering_quiz_detail",
            args=[attempt.quiz.offering.id, attempt.quiz.id],
        ),
        notification_type=Notification.Type.QUIZ_SUBMITTED,
        event_key=f"quiz-submitted:{attempt.id}",
    )


def _notify_students_if_week_now_viewable(week):
    if not _week_is_viewable(week):
        return

    notify_offering_students(
        week.offering,
        title=f"New week available: Week {week.week_number}",
        redirect_url=reverse("accounts:offering_detail", args=[week.offering.id]),
        notification_type=Notification.Type.WEEK_AVAILABLE,
        event_key=f"week-available:{week.offering.id}:{week.week_number}",
    )


def _notify_lecturers_parser_success(offering, document_name, redirect_url):
    notify_offering_lecturers(
        offering,
        title=f"Document parsed successfully: {document_name}",
        redirect_url=redirect_url,
        notification_type=Notification.Type.PARSER_SUCCESS,
    )


def _notify_lecturers_parser_failure(offering, document_name, redirect_url):
    notify_offering_lecturers(
        offering,
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
def _get_authorised_parsed_document(parsed_id: int, user: User):
    parsed_document = get_object_or_404(
        ParsedDocument.objects.select_related(
            "week_file__week__offering__module",
            "assignment_file__assignment__offering__module",
        ).prefetch_related("images"),
        pk=parsed_id,
    )

    if parsed_document.week_file_id:
        source_offering = parsed_document.week_file.week.offering
    elif parsed_document.assignment_file_id:
        source_offering = parsed_document.assignment_file.assignment.offering
    else:
        raise Http404("Parsed document not found")

    module = source_offering.module

    if user.is_student():
        if not ModuleOfferingEnrollmentStudent.objects.filter(
            offering=source_offering,
            student=user.student_profile,
        ).exists():
            raise Http404("Parsed document not found")
    elif user.is_lecturer():
        if not ModuleOfferingEnrollmentLecturer.objects.filter(
            offering=source_offering,
            lecturer=user.lecturer_profile,
        ).exists():
            raise Http404("Parsed document not found")
    else:
        raise Http404("Parsed document not found")

    return parsed_document, source_offering, module

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

def _build_student_module_assessment_items(offering, student, now, next_url=None):
    submitted_assignment_ids = set(
        AssignmentSubmission.objects.filter(
            assignment__offering=offering,
            student=student,
        ).values_list("assignment_id", flat=True)
    )

    items = []

    for assignment in offering.assignments.prefetch_related("files__parsed_document").all():
        items.append(
            {
                "kind": "assignment",
                "label": "Assignment",
                "title": assignment.title,
                "description": assignment.description,
                "url": _append_next_param(
                    reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                    next_url,
                ),
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

    for quiz in offering.quizzes.filter(is_published=True).all():
        state = _get_student_quiz_state(quiz, student, now=now)
        items.append(
            {
                "kind": "quiz",
                "label": "Quiz",
                "title": quiz.title,
                "description": quiz.description,
                "url": _append_next_param(
                    reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),
                    next_url,
                ),
                "is_clickable": state["is_clickable"] if not _is_read_only_offering(offering) else True,
                "date_label": "Closes",
                "date_value": quiz.close_datetime,
                "max_mark": quiz.max_mark,
                "status_label": state["status_label"] if not _is_read_only_offering(offering) else "Closed",
                "detail_line": f"Time limit: {quiz.time_limit_minutes} mins · Attempts: {state['attempts_used']}/{quiz.max_attempts}",
                "file_names": [],
                "sort_at": quiz.close_datetime,
            }
        )

    return sorted(items, key=lambda item: item["sort_at"])

def _build_lecturer_module_assessment_items(offering, next_url=None):
    items = []

    assignments = (
        offering.assignments
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
                "url": _append_next_param(
                    reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                    next_url,
                ),
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
        offering.quizzes
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
                "url": _append_next_param(
                    reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),
                    next_url,
                ),
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

def _build_student_dashboard_items(student, offerings_qs, now, next_url=None):
    items = []

    upcoming_assignments = (
        Assignment.objects.filter(
            offering__in=offerings_qs,
            due_datetime__gte=now,
        )
        .exclude(submissions__student=student)
        .select_related("offering__module")
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
                "url": _append_next_param(
                    reverse("accounts:offering_assignment_detail", args=[assignment.offering.id, assignment.id]),
                    next_url,
                ),
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
            offering__in=offerings_qs,
            is_published=True,
            close_datetime__gte=now,
        )
        .select_related("offering__module")
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
                "url": _append_next_param(
                    reverse("accounts:offering_quiz_detail", args=[quiz.offering.id, quiz.id]),
                    next_url,
                ),
                "is_clickable": state["is_clickable"],
                "date_label": "Closes",
                "date_value": quiz.close_datetime,
                "max_mark": quiz.max_mark,
                "status_label": state["status_label"],
                "detail_line": f"Time limit: {quiz.time_limit_minutes} mins · Attempts: {state['attempts_used']}/{quiz.max_attempts}",
                "sort_at": quiz.close_datetime,
            }
        )

    return sorted(items, key=lambda item: item["sort_at"])

def _format_mark_display(value):
    decimal_value = Decimal(str(value or 0))
    rendered = f"{decimal_value:.2f}"
    return rendered.rstrip("0").rstrip(".") or "0"


def _build_student_profile_modules(offerings_qs, student, next_url=None):
    offerings = list(offerings_qs)

    if not offerings:
        return []

    submitted_assignment_ids = set(
        AssignmentSubmission.objects.filter(
            student=student,
            assignment__offering__in=offerings_qs,
        ).values_list("assignment_id", flat=True)
    )

    graded_assignment_marks = dict(
        AssignmentGrade.objects.filter(
            submission__student=student,
            submission__assignment__offering__in=offerings_qs,
        ).values_list("submission__assignment_id", "value")
    )

    best_quiz_attempt_by_quiz = {}
    submitted_quiz_attempts = (
        QuizAttempt.objects.filter(
            student=student,
            quiz__offering__in=offerings_qs,
            quiz__is_published=True,
            submitted_at__isnull=False,
        )
        .select_related("quiz", "quiz__offering__module")
        .order_by("quiz_id", "-weighted_score", "-submitted_at", "-id")
    )

    for attempt in submitted_quiz_attempts:
        best_quiz_attempt_by_quiz.setdefault(attempt.quiz_id, attempt)

    module_rows = []

    for offering in offerings:
        items = []

        assignments = offering.assignments.all().order_by("due_datetime", "title")

        for assignment in assignments:
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
                    "url": _append_next_param(
                        reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                        next_url,
                    ),
                    "metric": metric,
                    "metric_class": metric_class,
                    "sort_at": assignment.due_datetime,
                }
            )

        quizzes = offering.quizzes.filter(is_published=True).order_by("close_datetime", "title")

        for quiz in quizzes:
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
                    "url": _append_next_param(
                        reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),
                        next_url,
                    ),
                    "metric": metric,
                    "metric_class": metric_class,
                    "sort_at": quiz.close_datetime,
                }
            )

        items.sort(key=lambda item: (item["sort_at"], item["title"]))

        module_rows.append(
            {
                "code": offering.module.code,
                "title": offering.module.title,
                "url": _append_next_param(
                    reverse("accounts:offering_detail", args=[offering.id]),
                    next_url,
                ),
                "academic_year_label": offering.academic_year.label,
                "items": items,
            }
        )

    return module_rows

def _build_lecturer_profile_modules(offerings_qs, lecturer, next_url=None):
    offerings = list(offerings_qs)

    if not offerings:
        return []

    assignment_submitted_counts = dict(
        AssignmentSubmission.objects.filter(
            assignment__offering__in=offerings_qs,
        )
        .values("assignment_id")
        .annotate(submitted_count=Count("student", distinct=True))
        .values_list("assignment_id", "submitted_count")
    )

    quiz_attempted_counts = dict(
        QuizAttempt.objects.filter(
            quiz__offering__in=offerings_qs,
            submitted_at__isnull=False,
        )
        .values("quiz_id")
        .annotate(attempted_count=Count("student", distinct=True))
        .values_list("quiz_id", "attempted_count")
    )

    module_rows = []

    for offering in offerings:
        total_students = getattr(offering, "student_count", 0) or 0
        items = []

        assignments = offering.assignments.all().order_by("due_datetime", "title")

        for assignment in assignments:
            submitted = assignment_submitted_counts.get(assignment.id, 0)
            unsubmitted = max(total_students - submitted, 0)

            if total_students > 0 and submitted == total_students:
                metric_class = "profile-metric--complete"
            elif submitted > 0:
                metric_class = "profile-metric--pending"
            else:
                metric_class = "profile-metric--empty"

            items.append(
                {
                    "kind_label": "Assignment",
                    "kind_class": "assignment",
                    "title": assignment.title,
                    "url": _append_next_param(
                        reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),
                        next_url,
                    ),
                    "metric": f"{submitted} Submitted / {unsubmitted} Unsubmitted",
                    "metric_class": metric_class,
                    "sort_at": assignment.due_datetime,
                }
            )

        quizzes = offering.quizzes.all().order_by("close_datetime", "title")

        for quiz in quizzes:
            attempted = quiz_attempted_counts.get(quiz.id, 0)
            not_attempted = max(total_students - attempted, 0)

            if total_students > 0 and attempted == total_students:
                metric_class = "profile-metric--complete"
            elif attempted > 0:
                metric_class = "profile-metric--pending"
            else:
                metric_class = "profile-metric--empty"

            items.append(
                {
                    "kind_label": "Quiz",
                    "kind_class": "quiz",
                    "title": quiz.title,
                    "url": _append_next_param(
                        reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),
                        next_url,
                    ),
                    "metric": f"{attempted} Attempted / {not_attempted} Not Attempted",
                    "metric_class": metric_class,
                    "sort_at": quiz.close_datetime,
                }
            )

        items.sort(key=lambda item: (item["sort_at"], item["title"]))

        module_rows.append(
            {
                "code": offering.module.code,
                "title": offering.module.title,
                "url": _append_next_param(
                    reverse("accounts:offering_detail", args=[offering.id]),
                    next_url,
                ),
                "academic_year_label": offering.academic_year.label,
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

# File Upload Validation for Student Submissions
STUDENT_SUBMISSION_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".zip",
    ".7z",
    ".rar",
    ".jpg",
    ".jpeg",
    ".png",
}

# To protect against potential security risks - block certain file types that could be executed on the server or cause issues when opened, including common web file formats and scripts that could be used for malicious purposes.
STUDENT_SUBMISSION_BLOCKED_EXTENSIONS = {
    ".html",
    ".htm",
    ".xhtml",
    ".svg",
    ".svgz",
    ".xml",
    ".js",
    ".mjs",
}

# Set a maximum file size for student submissions to prevent excessively large uploads that could strain server resources or cause timeouts. 
MAX_STUDENT_SUBMISSION_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

def _validate_student_submission_upload(uploaded_file) -> str | None:
    name = getattr(uploaded_file, "name", "") or ""
    _, ext = os.path.splitext(name)
    ext = ext.lower()

    size = getattr(uploaded_file, "size", 0) or 0

    if not name:
        return "One of the uploaded files is missing a filename."

    if not ext:
        return f"{name}: File uploads must have a valid extension."

    if ext in STUDENT_SUBMISSION_BLOCKED_EXTENSIONS:
        return f"{name}: This file type is not allowed."

    if ext not in STUDENT_SUBMISSION_ALLOWED_EXTENSIONS:
        return f"{name}: This file type is not allowed."

    if size <= 0:
        return f"{name}: The file is empty."

    if size > MAX_STUDENT_SUBMISSION_FILE_BYTES:
        return f"{name}: The file exceeds the 20 MB upload limit."

    return None

def _safe_back_url(request, fallback_name, *fallback_args):
    fallback_url = reverse(fallback_name, args=fallback_args)

    candidate = request.GET.get("next")
    if not candidate:
        return fallback_url

    if not url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return fallback_url

    return candidate

def _append_next_param(url, next_url):
    if not next_url:
        return url

    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["next"] = next_url

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query, doseq=True),
            parsed.fragment,
        )
    )

# Classes

class LowercaseUsernameAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Please enter a valid email address and password. Please note that passwords are case-sensitive.",
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        if username:
            self.cleaned_data["username"] = username.strip().lower()
        return super().clean()

class RoleBasedLoginView(LoginView):  # Custom login view that extends Django’s built-in LoginView to add role-based redirects
    template_name = "accounts/login.html"  # Specifies the template to use when displaying the login form
    redirect_authenticated_user = True  # If a user is already authenticated, they will be redirected to the success URL instead of seeing the login form again
    authentication_form = LowercaseUsernameAuthenticationForm

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
    
# Views

def register_student(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    valid_courses = _get_available_course_codes()
    module_rows = _build_registration_module_rows()

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""
        course_raw = request.POST.get("course") or ""
        course = _normalize_course_code(course_raw)
        module_ids = request.POST.getlist("module_ids")

        errors: dict[str, list[str]] = {}

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

        if email and not email.endswith("@mytudublin.ie"):
            errors.setdefault("email", []).append(
                "Student email must end with @mytudublin.ie."
            )

        if email and User.objects.filter(username__iexact=email).exists():
            errors.setdefault("email", []).append(
                "An account already exists for this email address."
            )

        if password1 and password2 and password1 != password2:
            errors.setdefault("password", []).append("Passwords do not match.")

        candidate_user = User(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        pw_errors = _validate_password_strength(password1, user=candidate_user)
        if pw_errors:
            errors.setdefault("password", []).extend(pw_errors)

        selected_course = _get_course_by_code(course)

        if not selected_course or course not in valid_courses:
            errors.setdefault("course", []).append(
                "Selected course is not recognised for module registration."
            )

        valid_module_ids = set(
            ModulePlacement.objects.filter(
                course__code__iexact=course,
                available_now=True,
                module__is_active=True,
            ).values_list("module_id", flat=True)
        )

        selected_modules = []
        submitted_module_ids: list[int] = []

        if module_ids:
            submitted_module_ids = [
                int(module_id)
                for module_id in module_ids
                if str(module_id).isdigit()
            ]

            invalid_ids = set(submitted_module_ids) - valid_module_ids
            if invalid_ids or len(submitted_module_ids) != len(module_ids):
                errors.setdefault("modules", []).append(
                    "One or more selected modules are invalid for the chosen course."
                )
            else:
                selected_modules = list(
                    Module.objects.filter(
                        pk__in=submitted_module_ids,
                        is_active=True,
                    ).order_by("code")
                )

        if errors:
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
                "module_rows": module_rows,
            }
            return render(request, "accounts/registration.html", context)

        user = User.objects.create_user(
            username=email,
            email=email,
            password=password1,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.STUDENT,
        )

        student_number = email.split("@")[0]

        student_profile = StudentProfile.objects.create(
            user=user,
            student_number=student_number,
            course=course,
            status=StudentProfile.Status.ACTIVE,
        )

        current_academic_year = _get_current_academic_year()
        if current_academic_year:
            for module in selected_modules:
                _sync_student_current_offering_enrolment(
                    student_profile,
                    module,
                    academic_year=current_academic_year,
                )

        messages.success(
            request,
            "Registration Successful. You can now log in with your student email and password!",
        )
        return redirect("accounts:login")

    context = {
        "errors": {},
        "form_data": {},
        "valid_courses": valid_courses,
        "module_rows": module_rows,
    }
    return render(request, "accounts/registration.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def student_join_modules(request):
    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    if student.status != StudentProfile.Status.ACTIVE:
        messages.info(request, "Only active students can join current academic year modules.")
        return redirect("accounts:dashboard")

    course_code = _normalize_course_code(student.course or "")

    if not _get_course_by_code(course_code):
        messages.error(request, "Your course is not configured yet. Please contact an administrator.")
        return redirect("accounts:dashboard")

    module_rows = _build_module_selector_rows(course_code=course_code)
    valid_module_ids = {row["id"] for row in module_rows}
    existing_current_ids = _current_module_ids_for_student(student)

    if request.method == "POST":
        submitted_ids = {
            int(module_id)
            for module_id in request.POST.getlist("module_ids")
            if str(module_id).isdigit()
        }

        invalid_ids = submitted_ids - valid_module_ids
        if invalid_ids:
            messages.error(request, "One or more selected modules are not valid for your course.")
            submitted_ids = existing_current_ids
        else:
            current_academic_year = _get_current_academic_year()

            for module_id in submitted_ids:
                module = Module.objects.filter(pk=module_id).first()
                if module and current_academic_year:
                    _sync_student_current_offering_enrolment(
                        student,
                        module,
                        academic_year=current_academic_year,
                    )

            newly_added = len(submitted_ids - existing_current_ids)
            if newly_added:
                messages.success(request, f"{newly_added} module(s) added successfully.")
            else:
                messages.info(request, "No new modules were added.")

            return redirect("accounts:student_join_modules")
    else:
        submitted_ids = existing_current_ids

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "student": student,
        "course_code": course_code,
        "module_rows": module_rows,
        "selected_module_ids": {str(module_id) for module_id in submitted_ids},
    }
    return render(request, "accounts/student_join_modules.html", context)

@login_required
def dashboard(request):

    user: User = request.user

    if user.is_admin():
        return redirect("accounts:admin_dashboard")

    nav_items = _shared_nav_items()
    now = timezone.now()

    if user.is_student():
        template = "accounts/student_dashboard.html"
        student = user.student_profile

        current_offerings = _current_offering_queryset_for_student(student)

        upcoming_items = _build_student_dashboard_items(
            student,
            current_offerings,
            now,
            request.get_full_path(),
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "current_module_rows": _build_student_dashboard_module_rows(
                current_offerings,
                request.get_full_path(),
            ),
            "previous_year_groups": _build_previous_student_dashboard_year_groups(
                student,
                request.get_full_path(),
            ),
            "upcoming_items": upcoming_items,
            "global_announcements": _recent_global_announcements(),
        }

    elif user.is_lecturer():
        template = "accounts/lecturer_dashboard.html"
        lecturer = user.lecturer_profile

        current_offerings = _current_offering_queryset_for_lecturer(lecturer)

        ungraded_submissions_qs = (
            AssignmentSubmission.objects.filter(
                assignment__offering__in=current_offerings,
                grade__isnull=True,
            )
            .select_related(
                "assignment",
                "assignment__offering__module",
                "student",
                "student__user",
            )
            .order_by("-submitted_at")[:10]
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "current_module_rows": _build_lecturer_dashboard_module_rows(
                current_offerings,
                request.get_full_path(),
            ),
            "previous_year_groups": _build_previous_lecturer_dashboard_year_groups(
                lecturer,
                request.get_full_path(),
            ),
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

    current_academic_year = _get_current_academic_year()

    context = _admin_page_context(user, "Admin Dashboard")
    context.update(
        {
            "total_students": StudentProfile.objects.count(),
            "total_lecturers": LecturerProfile.objects.count(),
            "total_modules": Module.objects.count(),
            "total_courses": Course.objects.count(),
            "current_academic_year": current_academic_year,
            "recent_global_announcements": _recent_global_announcements(),
            "monitoring_url": os.environ.get("EAGNA_MONITORING_URL", "").strip(),
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
        email = (request.POST.get("email") or "").strip().lower()
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

        candidate_user = User(
            username=email,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        password_errors = _validate_password_strength(password1, user=candidate_user)
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
def admin_manage_student_account(request):
    user: User = request.user
    _require_admin_user(user)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        student = get_object_or_404(
            StudentProfile.objects.select_related("user"),
            pk=request.POST.get("student_id"),
        )

        if action == "lock_student":
            student.status = StudentProfile.Status.LOCKED
            student.save(update_fields=["status"])

            student.user.is_active = False
            student.user.save(update_fields=["is_active"])

            messages.success(
                request,
                f"Locked {student.user.get_full_name() or student.user.username}.",
            )

        elif action == "unlock_student":
            restored_status = _derived_student_status_after_unlock(student)
            student.status = restored_status
            student.save(update_fields=["status"])

            student.user.is_active = True
            student.user.save(update_fields=["is_active"])

            messages.success(
                request,
                f"Unlocked {student.user.get_full_name() or student.user.username} and restored status to {student.get_status_display()}.",
            )

        else:
            messages.error(request, "Unknown student account action.")

        return _redirect_with_query(
            "accounts:admin_manage_student_account",
            username=student.user.username,
        )

    username = (request.GET.get("username") or "").strip()
    student = _get_student_by_username(username) if username else None
    search_error = ""
    if username and not student:
        search_error = "No student account was found for that username."

    context = _admin_page_context(user, "Manage Student Account")
    context.update(
        {
            "username_query": username,
            "student_result": student,
            "search_error": search_error,
        }
    )
    return render(request, "accounts/admin_manage_student_account.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_manage_lecturer_account(request):
    user: User = request.user
    _require_admin_user(user)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        lecturer = get_object_or_404(
            LecturerProfile.objects.select_related("user"),
            pk=request.POST.get("lecturer_id"),
        )

        if action == "lock_lecturer":
            lecturer.user.is_active = False
            lecturer.user.save(update_fields=["is_active"])
            messages.success(
                request,
                f"Locked {lecturer.user.get_full_name() or lecturer.user.username}.",
            )

        elif action == "unlock_lecturer":
            lecturer.user.is_active = True
            lecturer.user.save(update_fields=["is_active"])
            messages.success(
                request,
                f"Unlocked {lecturer.user.get_full_name() or lecturer.user.username}.",
            )

        else:
            messages.error(request, "Unknown lecturer account action.")

        return _redirect_with_query(
            "accounts:admin_manage_lecturer_account",
            username=lecturer.user.username,
        )

    username = (request.GET.get("username") or "").strip()
    lecturer = _get_lecturer_by_username(username) if username else None
    search_error = ""
    if username and not lecturer:
        search_error = "No lecturer account was found for that username."

    context = _admin_page_context(user, "Manage Lecturer Account")
    context.update(
        {
            "username_query": username,
            "lecturer_result": lecturer,
            "search_error": search_error,
        }
    )
    return render(request, "accounts/admin_manage_lecturer_account.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_add_course(request):
    user: User = request.user
    _require_admin_user(user)

    errors = []

    if request.method == "POST":
        code = _normalize_course_code(request.POST.get("code", ""))
        title = (request.POST.get("title") or "").strip()
        length_years_raw = (request.POST.get("length_years") or "").strip()
        is_active = request.POST.get("is_active") == "on"

        if not code:
            errors.append("Course code is required.")
        elif not COURSE_CODE_RE.match(code):
            errors.append("Course code must be 3–10 characters and contain only letters / numbers.")
        elif Course.objects.filter(code__iexact=code).exists():
            errors.append("A course with this code already exists.")

        if not title:
            errors.append("Course title is required.")

        try:
            length_years = int(length_years_raw or "0")
        except ValueError:
            length_years = 0

        if length_years < 1:
            errors.append("Course length must be at least 1 year.")

        if not errors:
            Course.objects.create(
                code=code,
                title=title,
                length_years=length_years,
                is_active=is_active,
            )
            messages.success(request, "Course created successfully.")
            return redirect("accounts:admin_dashboard")

    context = _admin_page_context(user, "Add Course")
    context.update(
        {
            "errors": errors,
            "initial": {
                "code": request.POST.get("code", ""),
                "title": request.POST.get("title", ""),
                "length_years": request.POST.get("length_years", "4"),
                "is_active": (request.POST.get("is_active") == "on") if request.method == "POST" else True,
            },
        }
    )
    return render(request, "accounts/admin_add_course.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_manage_academic_year(request):
    user: User = request.user
    _require_admin_user(user)

    current_year = _get_current_academic_year()
    errors = []
    confirm_rollover = request.GET.get("confirm_rollover") == "1"
    next_year_preview = _build_next_academic_year_window(current_year) if current_year else None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "set_current_year":
            start_date_raw = (request.POST.get("start_date") or "").strip()
            end_date_raw = (request.POST.get("end_date") or "").strip()

            start_date_value = None
            end_date_value = None

            try:
                start_date_value = date.fromisoformat(start_date_raw)
            except ValueError:
                errors.append("Start date is invalid.")

            try:
                end_date_value = date.fromisoformat(end_date_raw)
            except ValueError:
                errors.append("End date is invalid.")

            if start_date_value and end_date_value and start_date_value >= end_date_value:
                errors.append("End date must be after the start date.")

            if not errors:
                label = _build_academic_year_label(start_date_value, end_date_value)

                AcademicYear.objects.filter(is_current=True).update(is_current=False)

                academic_year, created = AcademicYear.objects.get_or_create(
                    label=label,
                    defaults={
                        "start_date": start_date_value,
                        "end_date": end_date_value,
                        "is_current": True,
                    },
                )

                if not created:
                    academic_year.start_date = start_date_value
                    academic_year.end_date = end_date_value
                    academic_year.is_current = True
                    academic_year.save(update_fields=["start_date", "end_date", "is_current"])

                created_offerings = _sync_current_module_offerings(academic_year)
                messages.success(
                    request,
                    f"Current academic year set to {academic_year.label}. "
                    f"Offerings created: {created_offerings}."
                )
                return redirect("accounts:admin_manage_academic_year")

        elif action == "sync_current_year":
            if not current_year:
                messages.error(request, "There is no current academic year to sync.")
                return redirect("accounts:admin_manage_academic_year")

            created_offerings = _sync_current_module_offerings(current_year)

            messages.success(
                request,
                f"Synchronized {current_year.label}. "
                f"Offerings created: {created_offerings}."
            )
            return redirect("accounts:admin_manage_academic_year")

        elif action == "start_new_academic_year":
            if not current_year:
                messages.error(request, "You must set a current academic year before starting a new one.")
                return redirect("accounts:admin_manage_academic_year")

            summary = _start_new_academic_year_transition(current_year)

            messages.success(
                request,
                f"Started New Academic Year {summary['next_year'].label}. "
                f"Placement Availability Updated: {summary['placement_updates']}. "
                f"Offerings Created: {summary['created_offerings']}. "
                f"Lecturers Re-Enrolled: {summary['copied_lecturers']}."
            )
            return redirect("accounts:admin_manage_academic_year")

        else:
            messages.error(request, "Unknown academic year action.")
            return redirect("accounts:admin_manage_academic_year")

    current_year = _get_current_academic_year()

    offering_count = (
        ModuleOffering.objects.filter(academic_year=current_year).count()
        if current_year else 0
    )
    student_enrolment_count = (
        ModuleOfferingEnrollmentStudent.objects.filter(offering__academic_year=current_year).count()
        if current_year else 0
    )
    lecturer_enrolment_count = (
        ModuleOfferingEnrollmentLecturer.objects.filter(offering__academic_year=current_year).count()
        if current_year else 0
    )

    context = _admin_page_context(user, "Manage Academic Year")
    context.update(
        {
            "errors": errors,
            "current_academic_year": current_year,
            "offering_count": offering_count,
            "student_offering_enrolment_count": student_enrolment_count,
            "lecturer_offering_enrolment_count": lecturer_enrolment_count,
            "confirm_rollover": confirm_rollover,
            "next_year_preview": next_year_preview,
            "initial": {
                "start_date": request.POST.get("start_date", ""),
                "end_date": request.POST.get("end_date", ""),
            },
        }
    )
    return render(request, "accounts/admin_manage_academic_year.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_add_module(request):
    user: User = request.user
    _require_admin_user(user)

    errors = []

    if request.method == "POST":
        code = _normalize_course_code(request.POST.get("code", ""))
        title = (request.POST.get("title") or "").strip()
        placements_raw = request.POST.get("placements", "")
        is_active = request.POST.get("is_active") == "on"
        available_now = request.POST.get("available_now") == "on"
        available_next_rollover = request.POST.get("available_next_rollover") == "on"

        if not code:
            errors.append("Module code is required.")
        elif Module.objects.filter(code__iexact=code).exists():
            errors.append("A module with this code already exists.")

        if not title:
            errors.append("Module title is required.")

        parsed_courses = _parse_module_course_lines(placements_raw, errors)

        if not errors:
            module = Module.objects.create(
                code=code,
                title=title,
                is_active=is_active,
            )

            for course in parsed_courses:
                ModulePlacement.objects.create(
                    module=module,
                    course=course,
                    available_now=available_now,
                    available_next_rollover=available_next_rollover,
                )

            current_academic_year = _get_current_academic_year()
            if current_academic_year and available_now:
                _ensure_module_offering_for_module(module, current_academic_year)

            messages.success(request, "Module created successfully.")
            return redirect("accounts:admin_dashboard")

    context = _admin_page_context(user, "Add Module")
    context.update(
        {
            "errors": errors,
            "initial": {
                "code": request.POST.get("code", ""),
                "title": request.POST.get("title", ""),
                "placements": request.POST.get("placements", ""),
                "is_active": (request.POST.get("is_active") == "on") if request.method == "POST" else True,
                "available_now": (request.POST.get("available_now") == "on") if request.method == "POST" else True,
                "available_next_rollover": (request.POST.get("available_next_rollover") == "on") if request.method == "POST" else True,
            },
        }
    )
    return render(request, "accounts/admin_add_module.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_retire_module(request):
    user: User = request.user
    _require_admin_user(user)

    module_query = (request.GET.get("module_query") or request.POST.get("module_query") or "").strip()
    selected_module_id = request.GET.get("module_id") or request.POST.get("module_id") or ""

    search_results = _search_modules_for_admin(module_query) if module_query else Module.objects.none()
    selected_module = None
    selected_summary = None
    errors = []

    if selected_module_id and str(selected_module_id).isdigit():
        selected_module = Module.objects.filter(pk=selected_module_id).first()
        if selected_module:
            selected_summary = _build_module_retire_summary(selected_module)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "retire_module":
            if not selected_module:
                errors.append("Please select a valid module first.")
            else:
                retire_now = request.POST.get("retire_now") == "on"
                retire_next_rollover = request.POST.get("retire_next_rollover") == "on"

                if not retire_now and not retire_next_rollover:
                    errors.append("Choose at least one retirement option.")

                if not errors:
                    placements_qs = ModulePlacement.objects.filter(module=selected_module)
                    current_year = _get_current_academic_year()

                    placements_now_updated = 0
                    placements_next_updated = 0
                    archived_offerings = 0

                    with transaction.atomic():
                        if retire_now:
                            placements_now_updated = placements_qs.filter(available_now=True).update(
                                available_now=False
                            )

                            if current_year:
                                _sync_current_module_offerings(current_year)

                                archived_offerings = ModuleOffering.objects.filter(
                                    module=selected_module,
                                    academic_year=current_year,
                                    is_current=True,
                                ).update(
                                    is_current=False,
                                    is_read_only=True,
                                )

                        if retire_next_rollover:
                            placements_next_updated = placements_qs.filter(
                                available_next_rollover=True
                            ).update(available_next_rollover=False)

                    messages.success(
                        request,
                        f"Updated {selected_module.code}. "
                        f"Placements unavailable now: {placements_now_updated}. "
                        f"Placements unavailable next rollover: {placements_next_updated}. "
                        f"Current offerings archived: {archived_offerings}."
                    )

                    return _redirect_with_query(
                        "accounts:admin_retire_module",
                        module_query=module_query,
                        module_id=selected_module.id,
                    )

    context = _admin_page_context(user, "Retire Module")
    context.update(
        {
            "module_query": module_query,
            "search_results": search_results,
            "selected_module": selected_module,
            "selected_summary": selected_summary,
            "errors": errors,
        }
    )
    return render(request, "accounts/admin_retire_module.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def admin_edit_enrollment(request):
    user: User = request.user
    _require_admin_user(user)

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "add_student":
            student = get_object_or_404(StudentProfile, pk=request.POST.get("student_id"))
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))

            valid_ids = set(_build_addable_modules_for_student(student).values_list("id", flat=True))
            if module.id not in valid_ids:
                messages.error(request, "That module cannot be added for this student.")
            else:
                current_academic_year = _get_current_academic_year()
                created = False

                if current_academic_year:
                    created = _sync_student_current_offering_enrolment(
                        student,
                        module,
                        academic_year=current_academic_year,
                    )

                if created:
                    messages.success(
                        request,
                        f"Added {student.user.get_full_name() or student.user.username} to {module.code}.",
                    )
                else:
                    messages.info(request, "That student is already enrolled in this module.")

            return _redirect_with_query(
                "accounts:admin_edit_enrollment",
                add_student_username=student.user.username,
            )

        elif action == "remove_student":
            student = get_object_or_404(StudentProfile, pk=request.POST.get("student_id"))
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))

            valid_ids = set(_build_removable_modules_for_student(student).values_list("id", flat=True))
            if module.id not in valid_ids:
                messages.error(request, "That module is not currently enrolled for this student.")
            else:
                current_academic_year = _get_current_academic_year()
                deleted = 0

                if current_academic_year:
                    deleted = _remove_student_current_offering_enrolment(
                        student,
                        module,
                        academic_year=current_academic_year,
                    )

                if deleted:
                    messages.success(
                        request,
                        f"Removed {student.user.get_full_name() or student.user.username} from {module.code}.",
                    )
                else:
                    messages.info(request, "That student was not enrolled in this module.")

            return _redirect_with_query(
                "accounts:admin_edit_enrollment",
                remove_student_username=student.user.username,
            )

        elif action == "add_lecturer":
            lecturer = get_object_or_404(LecturerProfile, pk=request.POST.get("lecturer_id"))
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))

            valid_ids = set(_build_addable_modules_for_lecturer(lecturer).values_list("id", flat=True))
            if module.id not in valid_ids:
                messages.error(request, "That module cannot be added for this lecturer.")
            else:
                current_academic_year = _get_current_academic_year()
                created_count = 0

                if current_academic_year:
                    created_count = _sync_lecturer_current_offering_enrolment(
                        lecturer,
                        module,
                        academic_year=current_academic_year,
                    )

                if created_count:
                    messages.success(
                        request,
                        f"Added {lecturer.user.get_full_name() or lecturer.user.username} to {module.code}.",
                    )
                else:
                    messages.info(request, "That lecturer is already enrolled in this module.")

            return _redirect_with_query(
                "accounts:admin_edit_enrollment",
                add_lecturer_username=lecturer.user.username,
            )

        elif action == "remove_lecturer":
            lecturer = get_object_or_404(LecturerProfile, pk=request.POST.get("lecturer_id"))
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))

            valid_ids = set(_build_removable_modules_for_lecturer(lecturer).values_list("id", flat=True))
            if module.id not in valid_ids:
                messages.error(request, "That module is not currently assigned to this lecturer.")
            else:
                current_academic_year = _get_current_academic_year()
                deleted = 0

                if current_academic_year:
                    deleted = _remove_lecturer_current_offering_enrolment(
                        lecturer,
                        module,
                        academic_year=current_academic_year,
                    )

                if deleted:
                    current_offering = _get_current_offering_for_lecturer_module(
                        module,
                        academic_year=current_academic_year,
                    )
                    if current_offering:
                        _ensure_primary_lecturer(current_offering)

                    messages.success(
                        request,
                        f"Removed {lecturer.user.get_full_name() or lecturer.user.username} from {module.code}.",
                    )

                else:
                    messages.info(request, "That lecturer was not enrolled in this module.")

            return _redirect_with_query(
                "accounts:admin_edit_enrollment",
                remove_lecturer_username=lecturer.user.username,
            )

        else:
            messages.error(request, "Unknown admin enrollment action.")
            return redirect("accounts:admin_edit_enrollment")

    add_student_username = (request.GET.get("add_student_username") or "").strip()
    remove_student_username = (request.GET.get("remove_student_username") or "").strip()
    add_lecturer_username = (request.GET.get("add_lecturer_username") or "").strip()
    remove_lecturer_username = (request.GET.get("remove_lecturer_username") or "").strip()

    add_student_profile = _get_student_by_username(add_student_username) if add_student_username else None
    remove_student_profile = _get_student_by_username(remove_student_username) if remove_student_username else None
    add_lecturer_profile = _get_lecturer_by_username(add_lecturer_username) if add_lecturer_username else None
    remove_lecturer_profile = _get_lecturer_by_username(remove_lecturer_username) if remove_lecturer_username else None

    context = _admin_page_context(user, "Edit Enrollment")
    context.update(
        {
            "add_student_username": add_student_username,
            "remove_student_username": remove_student_username,
            "add_lecturer_username": add_lecturer_username,
            "remove_lecturer_username": remove_lecturer_username,
            "add_student_profile": add_student_profile,
            "remove_student_profile": remove_student_profile,
            "add_lecturer_profile": add_lecturer_profile,
            "remove_lecturer_profile": remove_lecturer_profile,
            "add_student_modules": _build_addable_modules_for_student(add_student_profile) if add_student_profile else [],
            "remove_student_modules": _build_removable_modules_for_student(remove_student_profile) if remove_student_profile else [],
            "add_lecturer_modules": _build_addable_modules_for_lecturer(add_lecturer_profile) if add_lecturer_profile else [],
            "remove_lecturer_modules": _build_removable_modules_for_lecturer(remove_lecturer_profile) if remove_lecturer_profile else [],
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

        current_offerings = _current_offering_queryset_for_student(student)

        context.update(
            {
                "profile_role": "student",
                "course": student.course or "N/A",
                "module_rows": _build_student_profile_modules(
                    current_offerings,
                    student,
                    request.get_full_path(),
                ),
                "previous_year_groups": _build_previous_student_profile_year_groups(
                    student,
                    request.get_full_path(),
                ),
            }
        )

    elif user.is_lecturer():
        lecturer = get_object_or_404(
            LecturerProfile.objects.select_related("user"),
            user=user,
        )

        current_offerings = _current_offering_queryset_for_lecturer(lecturer)

        context.update(
            {
                "profile_role": "lecturer",
                "module_rows": _build_lecturer_profile_modules(
                    current_offerings,
                    lecturer,
                    request.get_full_path(),
                ),
                "previous_year_groups": _build_previous_lecturer_profile_year_groups(
                    lecturer,
                    request.get_full_path(),
                ),
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

    target_url = notification.redirect_url or reverse("accounts:dashboard")

    if not url_has_allowed_host_and_scheme(
        target_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        target_url = reverse("accounts:dashboard")

    return redirect(target_url)

@login_required
@require_http_methods(["POST"])
def read_all_notifications(request):
    Notification.objects.filter(
        recipient=request.user,
        is_read=False,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )

    next_url = request.POST.get("next") or reverse("accounts:dashboard")

    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("accounts:dashboard")

    return redirect(next_url)

@login_required
def portal(request):

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

    office_tiles_primary, office_tile_more = _portal_office_tiles()

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "office_tiles_primary": office_tiles_primary,
        "office_tile_more": office_tile_more,
        "timetable_url": f"https://timetables.tudublin.ie/timetables?date={today.isoformat()}&view=week",
    }

    context.update(
        _build_portal_calendar_context(
            user=user,
            year=selected_year,
            month=selected_month,
            next_url=request.get_full_path(),
        )
    )
    
    context.update(
        _build_portal_week_context(
            user=user,
            today=today,
            next_url=request.get_full_path(),
        )
    )

    return render(request, "accounts/portal.html", context)

@login_required
def offering_detail(request, offering_id):
    user: User = request.user
    nav_items = _shared_nav_items()

    offering = _get_accessible_offering_for_user(user, offering_id)
    module = offering.module
    read_only = _is_read_only_offering(offering)
    now = timezone.now()
    module_announcements = _recent_offering_module_announcements(offering)

    if user.is_student():
        student = user.student_profile

        assessment_items = _build_student_module_assessment_items(
            offering,
            student,
            now,
            request.get_full_path(),
        )

        weeks = (
            offering.weeks
            .filter(files__isnull=False)
            .prefetch_related("files__parsed_document")
            .order_by("week_number")
            .distinct()
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "offering": offering,
            "module": module,
            "role": "student",
            "read_only": read_only,
            "assessment_items": assessment_items,
            "module_announcements": module_announcements,
            "weeks": weeks,
            "run_start": offering.academic_year.start_date,
            "run_end": offering.academic_year.end_date,
            "back_url": _safe_back_url(request, "accounts:dashboard"),
        }

    elif user.is_lecturer():
        assessment_items = _build_lecturer_module_assessment_items(
            offering,
            request.get_full_path(),
        )

        requested_week_number = request.GET.get("week")
        try:
            requested_week_number = int(requested_week_number) if requested_week_number else None
        except (TypeError, ValueError):
            requested_week_number = None

        all_weeks = list(
            offering.weeks
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
            offering.student_enrolments.select_related("student__user"),
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
            "offering": offering,
            "module": module,
            "role": "lecturer",
            "read_only": read_only,
            "assessment_items": assessment_items,
            "module_announcements": module_announcements,
            "weeks": weeks,
            "enrolled_students": enrolled_students,
            "enrolled_student_count": len(enrolled_students),
            "run_start": offering.academic_year.start_date,
            "run_end": offering.academic_year.end_date,
            "back_url": _safe_back_url(request, "accounts:dashboard"),
        }

    else:
        return redirect("accounts:login")

    return render(request, "accounts/module_detail.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def offering_create_module_announcement(request, offering_id):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    module = offering.module
    errors = []

    if request.method == "POST":
        title, content, errors = _validate_announcement_form(request)

        if not errors:
            ModuleAnnouncement.objects.create(
                offering=offering,
                title=title,
                content=content,
                created_by=user,
            )
            ModuleAnnouncement.trim_to_latest_three_for_offering(offering)

            messages.success(request, "Module announcement created successfully.")
            return redirect("accounts:offering_detail", offering_id=offering.id)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "offering": offering,
        "module": module,
        "errors": errors,
        "initial": {
            "title": request.POST.get("title", ""),
            "content": request.POST.get("content", ""),
        },
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
    }
    return render(request, "accounts/module_announcement_form.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def offering_edit_module_announcement(request, offering_id, announcement_id):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    module = offering.module
    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, offering=offering)

    errors = []

    if request.method == "POST":
        title, content, errors = _validate_announcement_form(request)

        if not errors:
            announcement.title = title
            announcement.content = content
            announcement.save(update_fields=["title", "content", "updated_at"])

            messages.success(request, "Module announcement updated successfully.")
            return redirect("accounts:offering_detail", offering_id=offering.id)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "offering": offering,
        "module": module,
        "announcement": announcement,
        "errors": errors,
        "initial": {
            "title": request.POST.get("title", announcement.title) if request.method == "POST" else announcement.title,
            "content": request.POST.get("content", announcement.content) if request.method == "POST" else announcement.content,
        },
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
    }
    return render(request, "accounts/module_announcement_form.html", context)

@login_required
@require_http_methods(["POST"])
def offering_delete_module_announcement(request, offering_id, announcement_id):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, offering=offering)

    announcement.delete()
    messages.success(request, "Module announcement deleted successfully.")
    return redirect("accounts:offering_detail", offering_id=offering.id)

@login_required
def offering_upload_week_file(request, offering_id, week_number):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    module = offering.module

    week, _ = ModuleWeek.objects.get_or_create(
        offering=offering,
        week_number=week_number,
        defaults={"title": f"Week {week_number}"},
    )

    if request.method == "POST":
        was_visible = _week_is_viewable(week)
        module_detail_url = reverse("accounts:offering_detail", args=[offering.id])

        if "file" not in request.FILES:
            messages.error(request, "Please choose a .docx or .pptx file to upload.")
            return redirect("accounts:offering_detail", offering_id=offering.id)

        uploaded = request.FILES["file"]

        try:
            parsed_payload = parse_uploaded_office_file(uploaded)
        except ValueError as exc:
            _notify_lecturers_parser_failure(offering, uploaded.name, module_detail_url)
            messages.error(request, str(exc))
            return redirect("accounts:offering_detail", offering_id=offering.id)

        except Exception:
            _notify_lecturers_parser_failure(offering, uploaded.name, module_detail_url)
            messages.error(
                request,
                "The file could not be translated into accessible HTML. "
                "Please upload a readable .docx or .pptx containing text, tables, and images.",
            )
            return redirect("accounts:offering_detail", offering_id=offering.id)

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

            _notify_lecturers_parser_failure(offering, uploaded.name, module_detail_url)
            messages.error(
                request,
                "The file was not published because parsing/storage failed.",
            )
            return redirect("accounts:offering_detail", offering_id=offering.id)

        _notify_lecturers_parser_success(offering, uploaded.name, module_detail_url)

        if not was_visible:
            _notify_students_if_week_now_viewable(week)

        messages.success(request, "Weekly file uploaded and parsed successfully.")

    return redirect("accounts:offering_detail", offering_id=offering.id)

@login_required
@require_http_methods(["POST"])
def offering_save_module_week(request, offering_id, week_number):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    week, _ = ModuleWeek.objects.get_or_create(
        offering=offering,
        week_number=week_number,
        defaults={"title": f"Week {week_number}"},
    )

    description = request.POST.get("description", "").strip()
    uploaded_files = request.FILES.getlist("files")
    module_detail_url = reverse("accounts:offering_detail", args=[offering.id])
    was_visible = _week_is_viewable(week)

    if not description:
        messages.error(request, "A week description is required before saving.")
        return redirect("accounts:offering_detail", offering_id=offering.id)

    if not week.files.exists() and not uploaded_files:
        messages.error(request, "Please add at least one .docx or .pptx file before saving this week.")
        return redirect("accounts:offering_detail", offering_id=offering.id)

    week.description = description
    week.save(update_fields=["description"])

    for uploaded in uploaded_files:
        try:
            parsed_payload = parse_uploaded_office_file(uploaded)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("accounts:offering_detail", offering_id=offering.id)
        except Exception:
            messages.error(
                request,
                "The file could not be translated into accessible HTML. "
                "Please upload a readable .docx or .pptx containing text, tables, and images.",
            )
            return redirect("accounts:offering_detail", offering_id=offering.id)

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
                "One of the uploaded files failed during parsing/storage, so the save was cancelled.",
            )
            return redirect("accounts:offering_detail", offering_id=offering.id)

        _notify_lecturers_parser_success(
            offering,
            uploaded.name,
            module_detail_url,
        )

    if not was_visible:
        _notify_students_if_week_now_viewable(week)

    messages.success(request, f"Week {week.week_number} saved successfully.")
    return redirect(f"{reverse('accounts:offering_detail', args=[offering.id])}?week={week.week_number}")

@login_required
@require_http_methods(["POST"])
def offering_add_module_week(request, offering_id):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    next_week_number = (
        offering.weeks.aggregate(max_week=Max("week_number")).get("max_week") or 0
    ) + 1

    week, created = ModuleWeek.objects.get_or_create(
        offering=offering,
        week_number=next_week_number,
        defaults={"title": f"Week {next_week_number}"},
    )

    return redirect(f"{reverse('accounts:offering_detail', args=[offering.id])}?week={week.week_number}")

@login_required
@require_http_methods(["GET", "POST"])
def offering_create_assignment(request, offering_id):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    module = offering.module
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
            errors.append("% of Module must be a number.")
            max_mark_val = 100.0

        uploaded_files = request.FILES.getlist("files")
        parsed_file_payloads: list[tuple] = []
        create_assignment_url = reverse("accounts:offering_create_assignment", args=[offering.id])

        if not errors and uploaded_files:
            for uploaded in uploaded_files:
                try:
                    parsed_payload = parse_uploaded_office_file(uploaded)
                    parsed_file_payloads.append((uploaded, parsed_payload))
                except ValueError as exc:
                    _notify_lecturers_parser_failure(offering, uploaded.name, create_assignment_url)
                    errors.append(f"{uploaded.name}: {exc}")
                except Exception:
                    _notify_lecturers_parser_failure(offering, uploaded.name, create_assignment_url)
                    errors.append(
                        f"{uploaded.name}: The file could not be translated into accessible HTML."
                    )

        if not errors and due_dt is not None:
            assignment = None
            created_assignment_files: list[AssignmentFile] = []

            try:
                with transaction.atomic():
                    assignment = Assignment.objects.create(
                        offering=offering,
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

                _notify_lecturers_parser_failure(offering, "assignment materials", create_assignment_url)
                errors.append(
                    "The assignment was not published because one or more uploaded files "
                    "failed during parsing/storage."
                )
            else:
                assignment_detail_url = reverse(
                    "accounts:offering_assignment_detail",
                    args=[offering.id, assignment.id],
                )

                for assignment_file in created_assignment_files:
                    _notify_lecturers_parser_success(
                        offering,
                        assignment_file.original_name or assignment_file.file.name,
                        assignment_detail_url,
                    )

                _notify_students_new_assignment(assignment)

                messages.success(request, "Assignment created successfully.")
                return redirect(
                    "accounts:offering_assignment_detail",
                    offering_id=offering.id,
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
        "offering": offering,
        "module": module,
        "errors": errors,
        "initial": {
            "title": title,
            "description": description,
            "due_date": due_date_str,
            "due_time": due_time_str,
            "max_mark": max_mark_str,
        },
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
    }
    return render(request, "accounts/create_assignment.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def offering_create_quiz(request, offering_id):
    user: User = request.user
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)

    module = offering.module
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
            "% of Module",
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
                    offering=offering,
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
            return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

    else:
        initial_questions = []

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "offering": offering,
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
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
    }
    return render(request, "accounts/create_quiz.html", context)

@login_required
def offering_quiz_detail(request, offering_id, quiz_id):
    user: User = request.user
    nav_items = _shared_nav_items()
    now = timezone.now()

    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)
    module = offering.module
    read_only = _is_read_only_offering(offering)

    if user.is_lecturer():
        question_rows = _build_question_rows(quiz)
        attempts = (
            quiz.attempts
            .select_related("student__user")
            .order_by("-started_at")
        )

        context = {
            "user": user,
            "nav_items": nav_items,
            "offering": offering,
            "module": module,
            "quiz": quiz,
            "role": "lecturer",
            "read_only": read_only,
            "question_rows": question_rows,
            "attempts": attempts,
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
        }
        return render(request, "accounts/quiz_detail.html", context)

    if user.is_student():
        student = user.student_profile

        if not quiz.is_published:
            raise Http404("Quiz not found")

        if not read_only:
            _auto_submit_expired_attempt_if_needed(quiz, student)

        state = _get_student_quiz_state(quiz, student, now=timezone.now())
        active_attempt = state["active_attempt"] if not read_only else None
        latest_submitted_attempt = state["latest_submitted_attempt"]

        can_start_attempt = (
            not read_only
            and quiz.is_published
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
            "offering": offering,
            "module": module,
            "quiz": quiz,
            "role": "student",
            "read_only": read_only,
            "state": state,
            "active_attempt": active_attempt,
            "submitted_attempt": latest_submitted_attempt,
            "can_start_attempt": can_start_attempt,
            "question_rows": question_rows,
            "remaining_seconds": remaining_seconds,
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
        }
        return render(request, "accounts/quiz_detail.html", context)

    return redirect("accounts:login")


@login_required
def offering_assignment_detail(request, offering_id, assignment_id):
    user: User = request.user

    offering, assignment = _get_accessible_offering_assignment_for_user(user, offering_id, assignment_id)
    module = offering.module
    read_only = _is_read_only_offering(offering)

    if user.is_student():
        student = user.student_profile

        submission = (
            AssignmentSubmission.objects
            .filter(assignment=assignment, student=student)
            .select_related("grade")
            .prefetch_related("files")
            .first()
        )

        context = {
            "user": user,
            "nav_items": _shared_nav_items(),
            "offering": offering,
            "module": module,
            "assignment": assignment,
            "role": "student",
            "read_only": read_only,
            "submission": submission,
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
        }
        template = "accounts/assignment_detail.html"

    elif user.is_lecturer():
        submissions = (
            AssignmentSubmission.objects
            .filter(assignment=assignment)
            .select_related("student__user", "grade")
            .prefetch_related("files")
            .order_by("-submitted_at")
        )

        context = {
            "user": user,
            "nav_items": _shared_nav_items(),
            "offering": offering,
            "module": module,
            "assignment": assignment,
            "role": "lecturer",
            "read_only": read_only,
            "submissions": submissions,
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
        }
        template = "accounts/assignment_detail.html"

    else:
        return redirect("accounts:login")

    return render(request, template, context)

@login_required
@require_http_methods(["POST"])
def offering_start_quiz_attempt(request, offering_id, quiz_id):
    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)

    if _is_read_only_offering(offering):
        raise Http404("Not found")

    now = timezone.now()
    if now < quiz.open_datetime or now > quiz.close_datetime:
        messages.error(request, "This quiz is not currently open.")
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

    existing_active_attempt = (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )
    if existing_active_attempt:
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

    attempts_used = quiz.attempts.filter(student=student).count()
    if attempts_used >= quiz.max_attempts:
        messages.error(request, "You have used all available attempts for this quiz.")
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

    requested_expiry = now + timedelta(minutes=quiz.time_limit_minutes)
    expires_at = min(requested_expiry, quiz.close_datetime)

    QuizAttempt.objects.create(
        quiz=quiz,
        student=student,
        attempt_number=attempts_used + 1,
        expires_at=expires_at,
        status=QuizAttempt.Status.IN_PROGRESS,
    )

    return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

@login_required
@require_http_methods(["POST"])
def offering_save_quiz_progress(request, offering_id, quiz_id):
    user: User = request.user
    if not user.is_student():
        return JsonResponse({"ok": False}, status=403)

    student = user.student_profile
    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)

    if _is_read_only_offering(offering):
        return JsonResponse({"ok": False}, status=404)

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
def offering_submit_quiz_attempt(request, offering_id, quiz_id):
    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)

    if _is_read_only_offering(offering):
        raise Http404("Not found")

    attempt = (
        quiz.attempts
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)
        .order_by("-attempt_number")
        .first()
    )
    if attempt is None:
        messages.error(request, "No active quiz attempt was found.")
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

    _upsert_attempt_answers(attempt, request.POST)
    _grade_attempt(attempt, auto_submitted=attempt.is_expired())

    messages.success(request, "Quiz submitted successfully.")
    return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)

@login_required
@require_http_methods(["POST"])
def offering_submit_assignment(request, offering_id, assignment_id):
    user: User = request.user
    if not user.is_student():
        raise Http404("Not found")

    student = user.student_profile
    offering, assignment = _get_accessible_offering_assignment_for_user(user, offering_id, assignment_id)

    if _is_read_only_offering(offering):
        raise Http404("Not found")

    uploaded_files = request.FILES.getlist("files")

    validation_errors = [
        error
        for uploaded in uploaded_files
        if (error := _validate_student_submission_upload(uploaded))
    ]

    if validation_errors:
        for error in validation_errors:
            messages.error(request, error)

        return redirect(
            "accounts:offering_assignment_detail",
            offering_id=offering.id,
            assignment_id=assignment.id,
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

    for uploaded in uploaded_files:
        SubmissionFile.objects.create(
            submission=submission,
            file=uploaded,
            original_name=uploaded.name,
            uploaded_by=user,
        )

    _notify_student_assignment_submitted(submission)

    return redirect("accounts:offering_assignment_detail", offering_id=offering.id, assignment_id=assignment.id)

@login_required
@require_http_methods(["GET", "POST"])
def offering_grade_submission(request, offering_id, assignment_id, submission_id):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    offering, assignment = _get_accessible_offering_assignment_for_user(user, offering_id, assignment_id)

    if _is_read_only_offering(offering):
        raise Http404("Not found")

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

            return redirect(
                "accounts:offering_assignment_detail",
                offering_id=offering.id,
                assignment_id=assignment.id,
            )

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "offering": offering,
        "module": offering.module,
        "assignment": assignment,
        "submission": submission,
        "errors": errors,
        "initial": {
            "value": request.POST.get("value", initial_value) if request.method == "POST" else initial_value,
            "feedback": request.POST.get("feedback", initial_feedback) if request.method == "POST" else initial_feedback,
        },
        "back_url": _safe_back_url(request, "accounts:offering_assignment_detail", offering.id, assignment.id),
    }

    return render(request, "accounts/grade_submission.html", context)

@login_required
@require_http_methods(["GET"])
def parsed_document_modal(request, parsed_id):
    user: User = request.user
    parsed_document, offering, module = _get_authorised_parsed_document(parsed_id, user)
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
@require_http_methods(["GET"])
def global_announcement_modal(request, announcement_id):
    announcement = get_object_or_404(GlobalAnnouncement, pk=announcement_id)

    if request.user.is_admin():
        raise Http404("Not found")

    context = {
        "announcement": announcement,
        "scope_label": "Global Announcement",
    }
    return render(request, "accounts/partials/announcement_modal.html", context)

@login_required
@require_http_methods(["GET"])
def offering_module_announcement_modal(request, offering_id, announcement_id):
    offering = _get_accessible_offering_for_user(request.user, offering_id)
    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, offering=offering)

    context = {
        "announcement": announcement,
        "scope_label": f"{offering.module.code} Announcement",
    }
    return render(request, "accounts/partials/announcement_modal.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def edit_parsed_document_images(request, parsed_id):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    parsed_document, offering, module = _get_authorised_parsed_document(parsed_id, user)

    if _is_read_only_offering(offering):
        raise Http404("Not found")

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
        "offering": offering,
        "parsed_document": parsed_document,
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),
    }
    return render(request, "accounts/edit_parsed_document_images.html", context)

def _validate_password_strength(password: str, user: User | None = None) -> list[str]:
    errors: list[str] = []

    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number.")
    if not re.search(r"[^\w\s]", password):
        errors.append("Password must contain at least one special character (e.g. !, @, #).")

    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        errors.extend(exc.messages)

    return errors

def _get_all_valid_courses() -> list[str]:
    return list(
        Course.objects.filter(is_active=True)
        .order_by("code")
        .values_list("code", flat=True)
    )

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

def _build_registration_module_rows() -> list[dict]:
    return _build_module_selector_rows()
