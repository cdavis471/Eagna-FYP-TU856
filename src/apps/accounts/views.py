# =======
# Imports
# =======
import re  # Regex helpers.
import json  # JSON helpers.
import calendar as pycalendar  # Calendar helpers.
import os  # Path utilities.
from django.contrib.auth.decorators import login_required  # Require login.
from django.contrib.auth.views import LoginView  # Login view base.
from django.shortcuts import redirect, render, get_object_or_404  # Common view shortcuts.
from django.urls import reverse  # Reverse named URLs.
from django.utils import timezone  # Timezone utilities.
from django.http import Http404, JsonResponse  # HTTP response helpers.
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit  # URL query helpers.
from django.db.models import Count, Q, Max  # Query helpers.
from django.views.decorators.http import require_http_methods  # Limit HTTP methods.
from datetime import datetime, timedelta, date  # Date and time helpers.
from collections import defaultdict  # Default dictionary helper.
from decimal import Decimal, InvalidOperation  # Decimal helpers.
from django.contrib import messages  # Flash messages.
from django.core.files.base import ContentFile  # In-memory file wrapper.
from django.db import transaction  # Database transactions.
from .document_parsing import build_rendered_html_from_blocks, parse_uploaded_office_file  # Document parsing helpers.
from .models import User, StudentProfile, LecturerProfile, Course, AcademicYear, Module, ModulePlacement, ModuleOffering, ModuleOfferingEnrollmentLecturer, ModuleOfferingEnrollmentStudent, Assignment, AssignmentSubmission, AssignmentGrade, AssignmentFile, SubmissionFile, ModuleWeek, ModuleWeekFile, ParsedDocument, ParsedDocumentImage, Quiz, QuizQuestion, QuizOption, QuizAttempt, QuizAnswer, Notification, GlobalAnnouncement, ModuleAnnouncement  # Application models.
from .notifications import create_notification, notify_offering_students, notify_offering_lecturers  # Notification helpers.
from django.utils.http import url_has_allowed_host_and_scheme  # Safe redirect helper.
from django.contrib.auth.forms import AuthenticationForm  # Authentication form.
from django.contrib.auth.password_validation import validate_password  # Password validators.
from django.core.exceptions import ValidationError as DjangoValidationError  # Validation exception alias.

# Temporary
# import traceback
# from django.http import HttpResponse
# from django.utils.html import escape

# ==============
# Shared Helpers
# ==============
def _shared_nav_items():  # Define _shared_nav_items.
    """Return shared navigation items."""
    return [  # Return the computed value.
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},  # Add this mapping item.
        {"label": "Portal", "url": reverse("accounts:portal")},  # Add this mapping item.
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},  # Add this mapping item.
        {"label": "Website", "url": "https://www.tudublin.ie/"},  # Add this mapping item.
    ]  # Close the current list.

# =============
# Admin Helpers
# =============
def _require_admin_user(user):  # Define _require_admin_user.
    """Ensure the user is an admin."""
    if not user.is_admin():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.


def _admin_page_context(user, page_title):  # Define _admin_page_context.
    """Build shared admin page context."""
    return {  # Return the computed value.
        "user": user,  # Set user.
        "page_title": page_title,  # Set page title.
        "dashboard_url": reverse("accounts:admin_dashboard"),  # Set dashboard url.
    }  # Close the current mapping.


def _ensure_primary_lecturer(offering: ModuleOffering):  # Define _ensure_primary_lecturer.
    """Ensure primary lecturer."""
    if offering.lecturer_enrolments.filter(is_primary=True).exists():  # Check the current condition.
        return  # Return early.

    first_enrolment = offering.lecturer_enrolments.order_by("id").first()  # Order queryset results.
    if first_enrolment:  # Check the current condition.
        first_enrolment.is_primary = True  # Store the boolean state.
        first_enrolment.save(update_fields=["is_primary"])  # Save model changes.

# ========================
# Module Selection Helpers
# ========================
def _get_available_course_codes() -> list[str]:  # Define _get_available_course_codes.
    """Return available course codes."""
    return list(  # Return the computed value.
        Course.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            module_placements__available_now=True,  # Store the computed value.
            module_placements__module__is_active=True,  # Store the computed value.
        )  # Close the current call.
        .order_by("code")  # Order queryset results.
        .values_list("code", flat=True)  # Select field values.
        .distinct()  # Remove duplicate rows.
    )  # Close the current call.


def _get_course_by_code(course_code: str):  # Define _get_course_by_code.
    """Return an active course by code."""
    if not course_code:  # Check the current condition.
        return None  # Return the computed value.
    return Course.objects.filter(code__iexact=course_code, is_active=True).first()  # Return the computed value.

def _build_module_selector_rows(course_code: str | None = None) -> list[dict]:  # Define _build_module_selector_rows.
    """Build module selector rows."""
    placements = (  # Store the computed value.
        ModulePlacement.objects.select_related("module", "course")  # Follow related objects.
        .filter(  # Filter queryset records.
            available_now=True,  # Store the computed value.
            module__is_active=True,  # Store the computed value.
            course__is_active=True,  # Store the computed value.
        )  # Close the current call.
        .order_by("module__code", "module__title", "course__code")  # Order queryset results.
    )  # Close the current call.

    if course_code:  # Check the current condition.
        placements = placements.filter(  # Filter queryset records.
            course__code__iexact=_normalize_course_code(course_code)  # Store the computed value.
        )  # Close the current call.

    rows_by_module_id: dict[int, dict] = {}  # Build the value mapping.

    for placement in placements:  # Iterate through the collection.
        module = placement.module  # Store the computed value.
        row = rows_by_module_id.setdefault(  # Create the default mapping.
            module.id,  # Continue the current value.
            {  # Start the current mapping.
                "id": module.id,  # Set id.
                "code": module.code,  # Set code.
                "title": module.title,  # Set title.
                "label": f"{module.code} – {module.title}",  # Set label.
                "course_codes": [],  # Set course codes.
            },  # Close the current mapping.
        )  # Close the current call.

        if placement.course.code not in row["course_codes"]:  # Check the current condition.
            row["course_codes"].append(placement.course.code)  # Append to the list.

    rows = list(rows_by_module_id.values())  # Select dictionary fields.
    for row in rows:  # Iterate through the collection.
        row["course_codes"] = sorted(row["course_codes"])  # Continue the current block.

    return rows  # Return the computed value.

def _parse_module_course_lines(raw_value: str, errors: list[str]) -> list[Course]:  # Define _parse_module_course_lines.
    """Parse module course lines."""
    courses: list[Course] = []  # Build the list values.
    seen: set[int] = set()  # Initialise the value set.

    lines = [line.strip() for line in (raw_value or "").splitlines() if line.strip()]  # Split lines from the value.
    if not lines:  # Check the current condition.
        errors.append("At least one course placement is required.")  # Append to the list.
        return courses  # Return the computed value.

    for line in lines:  # Iterate through the collection.
        course_code = _normalize_course_code(line)  # Store the computed value.

        if not COURSE_CODE_RE.match(course_code):  # Check the current condition.
            errors.append(f"Invalid course code '{course_code}'.")  # Append to the list.
            continue  # Continue to the next item.

        course = _get_course_by_code(course_code)  # Store the computed value.
        if not course:  # Check the current condition.
            errors.append(f"Course '{course_code}' does not exist or is inactive.")  # Append to the list.
            continue  # Continue to the next item.

        if course.id in seen:  # Check the current condition.
            continue  # Continue to the next item.

        seen.add(course.id)  # Call the helper function.
        courses.append(course)  # Append to the list.

    return courses  # Return the computed value.

def _get_student_by_username(username: str):  # Define _get_student_by_username.
    """Return student by username."""
    username = (username or "").strip().lower()  # Trim surrounding whitespace.
    if not username:  # Check the current condition.
        return None  # Return the computed value.
    return (  # Return the computed value.
        StudentProfile.objects.select_related("user")  # Follow related objects.
        .filter(user__username__iexact=username)  # Filter queryset records.
        .first()  # Return the first result.
    )  # Close the current call.


def _get_lecturer_by_username(username: str):  # Define _get_lecturer_by_username.
    """Return lecturer by username."""
    username = (username or "").strip().lower()  # Trim surrounding whitespace.
    if not username:  # Check the current condition.
        return None  # Return the computed value.
    return (  # Return the computed value.
        LecturerProfile.objects.select_related("user")  # Follow related objects.
        .filter(user__username__iexact=username)  # Filter queryset records.
        .first()  # Return the first result.
    )  # Close the current call.

def _derived_student_status_after_unlock(student: StudentProfile):  # Define _derived_student_status_after_unlock.
    """Return the status after unlocking a student."""
    return StudentProfile.Status.ACTIVE  # Return the computed value.

def _current_module_ids_for_student(student: StudentProfile):  # Define _current_module_ids_for_student.
    """Return current module ids for student."""
    current_year = _get_current_academic_year()  # Store the computed value.
    if not current_year:  # Check the current condition.
        return set()  # Return the computed value.

    return set(  # Return the computed value.
        ModuleOfferingEnrollmentStudent.objects.filter(  # Filter queryset records.
            student=student,  # Store the computed value.
            offering__academic_year=current_year,  # Store the computed value.
            offering__is_current=True,  # Store the computed value.
        ).values_list("offering__module_id", flat=True)  # Select field values.
    )  # Close the current call.


def _current_module_ids_for_lecturer(lecturer: LecturerProfile):  # Define _current_module_ids_for_lecturer.
    """Return current module ids for lecturer."""
    current_year = _get_current_academic_year()  # Store the computed value.
    if not current_year:  # Check the current condition.
        return set()  # Return the computed value.

    return set(  # Return the computed value.
        ModuleOfferingEnrollmentLecturer.objects.filter(  # Filter queryset records.
            lecturer=lecturer,  # Store the computed value.
            offering__academic_year=current_year,  # Store the computed value.
            offering__is_current=True,  # Store the computed value.
        ).values_list("offering__module_id", flat=True)  # Select field values.
    )  # Close the current call.

def _build_addable_modules_for_student(student: StudentProfile):  # Define _build_addable_modules_for_student.
    """Build addable modules for student."""
    course_code = _normalize_course_code(student.course or "")  # Store the computed value.
    if not course_code or student.status != StudentProfile.Status.ACTIVE:  # Check the current condition.
        return Module.objects.none()  # Return the computed value.

    existing_module_ids = _current_module_ids_for_student(student)  # Store matching ids.

    return (  # Return the computed value.
        Module.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            placements__course__code__iexact=course_code,  # Store the computed value.
            placements__available_now=True,  # Store the computed value.
            placements__course__is_active=True,  # Store the computed value.
        )  # Close the current call.
        .exclude(pk__in=existing_module_ids)  # Exclude matching records.
        .distinct()  # Remove duplicate rows.
        .order_by("code", "title")  # Order queryset results.
    )  # Close the current call.

def _build_removable_modules_for_student(student: StudentProfile):  # Define _build_removable_modules_for_student.
    """Build removable modules for student."""
    existing_module_ids = _current_module_ids_for_student(student)  # Store matching ids.

    return (  # Return the computed value.
        Module.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            pk__in=existing_module_ids,  # Store the computed value.
        )  # Close the current call.
        .distinct()  # Remove duplicate rows.
        .order_by("code", "title")  # Order queryset results.
    )  # Close the current call.


def _build_addable_modules_for_lecturer(lecturer: LecturerProfile):  # Define _build_addable_modules_for_lecturer.
    """Build addable modules for lecturer."""
    current_year = _get_current_academic_year()  # Store the computed value.
    if not current_year:  # Check the current condition.
        return Module.objects.none()  # Return the computed value.

    existing_module_ids = _current_module_ids_for_lecturer(lecturer)  # Store matching ids.

    return (  # Return the computed value.
        Module.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            placements__available_now=True,  # Store the computed value.
            placements__course__is_active=True,  # Store the computed value.
            offerings__academic_year=current_year,  # Store the computed value.
            offerings__is_current=True,  # Store the computed value.
        )  # Close the current call.
        .exclude(pk__in=existing_module_ids)  # Exclude matching records.
        .distinct()  # Remove duplicate rows.
        .order_by("code", "title")  # Order queryset results.
    )  # Close the current call.

def _build_removable_modules_for_lecturer(lecturer: LecturerProfile):  # Define _build_removable_modules_for_lecturer.
    """Build removable modules for lecturer."""
    existing_module_ids = _current_module_ids_for_lecturer(lecturer)  # Store matching ids.

    return (  # Return the computed value.
        Module.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            pk__in=existing_module_ids,  # Store the computed value.
        )  # Close the current call.
        .distinct()  # Remove duplicate rows.
        .order_by("code", "title")  # Order queryset results.
    )  # Close the current call.

def _redirect_with_query(url_name: str, **params):  # Define _redirect_with_query.
    """Append query parameters to a redirect URL."""
    filtered = {key: value for key, value in params.items() if value}  # Iterate key-value pairs.
    base_url = reverse(url_name)  # Store the resolved URL.
    if not filtered:  # Check the current condition.
        return redirect(base_url)  # Return the redirect response.
    return redirect(f"{base_url}?{urlencode(filtered)}")  # Return the redirect response.

def _search_modules_for_admin(query: str):  # Define _search_modules_for_admin.
    """Handle search modules for admin."""
    query = (query or "").strip()  # Trim surrounding whitespace.
    if not query:  # Check the current condition.
        return Module.objects.none()  # Return the computed value.

    return (  # Return the computed value.
        Module.objects.filter(  # Filter queryset records.
            Q(code__icontains=query) | Q(title__icontains=query)  # Call the helper function.
        )  # Close the current call.
        .order_by("code", "title")[:20]  # Order queryset results.
    )  # Close the current call.


def _build_module_retire_summary(module: Module):  # Define _build_module_retire_summary.
    """Build module retire summary."""
    current_year = _get_current_academic_year()  # Store the computed value.

    placements = list(  # Store the computed value.
        module.placements  # Continue the current block.
        .select_related("course")  # Follow related objects.
        .order_by("course__code")  # Order queryset results.
    )  # Close the current call.

    current_offerings = []  # Store the computed value.
    if current_year:  # Check the current condition.
        current_offerings = list(  # Store the computed value.
            ModuleOffering.objects.filter(  # Filter queryset records.
                module=module,  # Store the computed value.
                academic_year=current_year,  # Store the computed value.
            )  # Close the current call.
            .select_related("module", "academic_year")  # Follow related objects.
            .annotate(  # Add queryset annotations.
                student_count=Count("student_enrolments", distinct=True),  # Store the item count.
                lecturer_count=Count("lecturer_enrolments", distinct=True),  # Store the item count.
            )  # Close the current call.
            .order_by("module__code")  # Order queryset results.
        )  # Close the current call.

    return {  # Return the computed value.
        "placements": placements,  # Set placements.
        "current_offerings": current_offerings,  # Set current offerings.
        "current_year": current_year,  # Set current year.
    }  # Close the current mapping.

# =====================
# Academic Year Helpers
# =====================
def _get_current_academic_year():  # Define _get_current_academic_year.
    """Return the current academic year."""
    return AcademicYear.objects.filter(is_current=True).order_by("-start_date").first()  # Return the computed value.


def _build_academic_year_label(start_date: date, end_date: date) -> str:  # Define _build_academic_year_label.
    """Build an academic year label."""
    return f"{start_date.year}/{str(end_date.year)[-2:]}"  # Return the computed value.


def _ensure_module_offering_for_module(module: Module, academic_year: AcademicYear):  # Define _ensure_module_offering_for_module.
    """Ensure module offering for module."""
    offering, created = ModuleOffering.objects.get_or_create(  # Unpack returned values.
        module=module,  # Store the computed value.
        academic_year=academic_year,  # Store the computed value.
        defaults={  # Store the computed value.
            "is_current": academic_year.is_current,  # Set is current.
            "is_read_only": False,  # Set is read only.
        },  # Close the current mapping.
    )  # Close the current call.

    changed_fields = []  # Store the computed value.
    if offering.is_current != academic_year.is_current:  # Check the current condition.
        offering.is_current = academic_year.is_current  # Store the boolean state.
        changed_fields.append("is_current")  # Append to the list.

    if offering.is_read_only:  # Check the current condition.
        offering.is_read_only = False  # Store the boolean state.
        changed_fields.append("is_read_only")  # Append to the list.

    if changed_fields:  # Check the current condition.
        offering.save(update_fields=changed_fields)  # Save model changes.

    return offering, created  # Return the computed value.

def _sync_current_module_offerings(academic_year: AcademicYear) -> int:  # Define _sync_current_module_offerings.
    """Synchronise current module offerings."""
    created_count = 0  # Store the item count.

    modules = (  # Store the computed value.
        Module.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            placements__available_now=True,  # Store the computed value.
            placements__course__is_active=True,  # Store the computed value.
        )  # Close the current call.
        .distinct()  # Remove duplicate rows.
        .order_by("code")  # Order queryset results.
    )  # Close the current call.

    for module in modules:  # Iterate through the collection.
        _, created = _ensure_module_offering_for_module(module, academic_year)  # Unpack returned values.
        if created:  # Check the current condition.
            created_count += 1  # Continue the current block.

    return created_count  # Return the computed value.

def _find_current_student_offering(student: StudentProfile, module: Module, academic_year: AcademicYear | None = None):  # Define _find_current_student_offering.
    """Find current student offering."""
    academic_year = academic_year or _get_current_academic_year()  # Store the computed value.
    if not academic_year:  # Check the current condition.
        return None  # Return the computed value.

    course_code = _normalize_course_code(student.course or "")  # Store the computed value.
    if not course_code:  # Check the current condition.
        return None  # Return the computed value.

    allowed = ModulePlacement.objects.filter(  # Filter queryset records.
        module=module,  # Store the computed value.
        course__code__iexact=course_code,  # Store the computed value.
        available_now=True,  # Store the computed value.
        module__is_active=True,  # Store the computed value.
        course__is_active=True,  # Store the computed value.
    ).exists()  # Check for any result.

    if not allowed:  # Check the current condition.
        return None  # Return the computed value.

    offering, _ = _ensure_module_offering_for_module(module, academic_year)  # Unpack returned values.
    return offering  # Return the computed value.

def _get_current_offering_for_lecturer_module(module: Module, academic_year: AcademicYear | None = None):  # Define _get_current_offering_for_lecturer_module.
    """Return current offering for lecturer module."""
    academic_year = academic_year or _get_current_academic_year()  # Store the computed value.
    if not academic_year:  # Check the current condition.
        return None  # Return the computed value.

    allowed = ModulePlacement.objects.filter(  # Filter queryset records.
        module=module,  # Store the computed value.
        available_now=True,  # Store the computed value.
        module__is_active=True,  # Store the computed value.
        course__is_active=True,  # Store the computed value.
    ).exists()  # Check for any result.

    if not allowed:  # Check the current condition.
        return None  # Return the computed value.

    offering, _ = _ensure_module_offering_for_module(module, academic_year)  # Unpack returned values.
    return offering  # Return the computed value.

def _sync_student_current_offering_enrolment(student: StudentProfile, module: Module, academic_year: AcademicYear | None = None):  # Define _sync_student_current_offering_enrolment.
    """Synchronise student current offering enrolment."""
    offering = _find_current_student_offering(student, module, academic_year=academic_year)  # Store the computed value.
    if not offering:  # Check the current condition.
        return False  # Return the computed value.

    _, created = ModuleOfferingEnrollmentStudent.objects.get_or_create(  # Unpack returned values.
        offering=offering,  # Store the computed value.
        student=student,  # Store the computed value.
    )  # Close the current call.
    return created  # Return the computed value.


def _remove_student_current_offering_enrolment(student: StudentProfile, module: Module, academic_year: AcademicYear | None = None):  # Define _remove_student_current_offering_enrolment.
    """Remove student current offering enrolment."""
    offering = _find_current_student_offering(student, module, academic_year=academic_year)  # Store the computed value.
    if not offering:  # Check the current condition.
        return 0  # Return the computed value.

    deleted, _ = ModuleOfferingEnrollmentStudent.objects.filter(  # Filter queryset records.
        offering=offering,  # Store the computed value.
        student=student,  # Store the computed value.
    ).delete()  # Delete the record.
    return deleted  # Return the computed value.


def _sync_lecturer_current_offering_enrolment(lecturer: LecturerProfile, module: Module, academic_year: AcademicYear | None = None):  # Define _sync_lecturer_current_offering_enrolment.
    """Synchronise lecturer current offering enrolment."""
    offering = _get_current_offering_for_lecturer_module(module, academic_year=academic_year)  # Store the computed value.
    if not offering:  # Check the current condition.
        return 0  # Return the computed value.

    offering_has_primary = offering.lecturer_enrolments.filter(is_primary=True).exists()  # Filter queryset records.

    enrolment, created = ModuleOfferingEnrollmentLecturer.objects.get_or_create(  # Unpack returned values.
        offering=offering,  # Store the computed value.
        lecturer=lecturer,  # Store the computed value.
        defaults={"is_primary": not offering_has_primary},  # Store the computed value.
    )  # Close the current call.

    if not created and not offering_has_primary and not enrolment.is_primary:  # Check the current condition.
        enrolment.is_primary = True  # Store the boolean state.
        enrolment.save(update_fields=["is_primary"])  # Save model changes.

    return 1 if created else 0  # Return the computed value.

def _remove_lecturer_current_offering_enrolment(lecturer: LecturerProfile, module: Module, academic_year: AcademicYear | None = None):  # Define _remove_lecturer_current_offering_enrolment.
    """Remove lecturer current offering enrolment."""
    offering = _get_current_offering_for_lecturer_module(module, academic_year=academic_year)  # Store the computed value.
    if not offering:  # Check the current condition.
        return 0  # Return the computed value.

    deleted, _ = ModuleOfferingEnrollmentLecturer.objects.filter(  # Filter queryset records.
        offering=offering,  # Store the computed value.
        lecturer=lecturer,  # Store the computed value.
    ).delete()  # Delete the record.
    return deleted  # Return the computed value.

def _safe_add_years(date_value: date, years: int = 1) -> date:  # Define _safe_add_years.
    """Safely add years to a date."""
    try:  # Start guarded parsing.
        return date_value.replace(year=date_value.year + years)  # Return the computed value.
    except ValueError:  # Handle the raised exception.
        if date_value.month == 2 and date_value.day == 29:  # Check the current condition.
            return date_value.replace(year=date_value.year + years, month=2, day=28)  # Return the computed value.
        raise  # Continue the current block.


def _build_next_academic_year_window(current_year: AcademicYear):  # Define _build_next_academic_year_window.
    """Build the next academic year window."""
    next_start = _safe_add_years(current_year.start_date, 1)  # Store the computed value.
    next_end = _safe_add_years(current_year.end_date, 1)  # Store the computed value.

    return {  # Return the computed value.
        "start_date": next_start,  # Set start date.
        "end_date": next_end,  # Set end date.
        "label": _build_academic_year_label(next_start, next_end),  # Set label.
    }  # Close the current mapping.


def _roll_forward_module_placement_availability():  # Define _roll_forward_module_placement_availability.
    """Roll forward module placement availability."""
    updated_count = 0  # Store the item count.

    for placement in ModulePlacement.objects.all():  # Iterate through the collection.
        new_available_now = placement.available_next_rollover  # Store the computed value.
        if placement.available_now != new_available_now:  # Check the current condition.
            placement.available_now = new_available_now  # Store the computed value.
            placement.save(update_fields=["available_now"])  # Save model changes.
            updated_count += 1  # Continue the current block.

    return updated_count  # Return the computed value.


def _create_next_current_module_offerings(academic_year: AcademicYear):  # Define _create_next_current_module_offerings.
    """Create next current module offerings."""
    created_count = 0  # Store the item count.

    modules = (  # Store the computed value.
        Module.objects.filter(  # Filter queryset records.
            is_active=True,  # Store the boolean state.
            placements__available_next_rollover=True,  # Store the computed value.
            placements__course__is_active=True,  # Store the computed value.
        )  # Close the current call.
        .distinct()  # Remove duplicate rows.
        .order_by("code")  # Order queryset results.
    )  # Close the current call.

    for module in modules:  # Iterate through the collection.
        offering, created = ModuleOffering.objects.get_or_create(  # Unpack returned values.
            module=module,  # Store the computed value.
            academic_year=academic_year,  # Store the computed value.
            defaults={  # Store the computed value.
                "is_current": True,  # Set is current.
                "is_read_only": False,  # Set is read only.
            },  # Close the current mapping.
        )  # Close the current call.

        changed_fields = []  # Store the computed value.
        if not offering.is_current:  # Check the current condition.
            offering.is_current = True  # Store the boolean state.
            changed_fields.append("is_current")  # Append to the list.

        if offering.is_read_only:  # Check the current condition.
            offering.is_read_only = False  # Store the boolean state.
            changed_fields.append("is_read_only")  # Append to the list.

        if changed_fields:  # Check the current condition.
            offering.save(update_fields=changed_fields)  # Save model changes.

        if created:  # Check the current condition.
            created_count += 1  # Continue the current block.

    return created_count  # Return the computed value.


def _copy_lecturers_to_next_current_offerings(previous_current_year: AcademicYear, next_current_year: AcademicYear):  # Define _copy_lecturers_to_next_current_offerings.
    """Handle copy lecturers to next current offerings."""
    created_count = 0  # Store the item count.

    previous_offerings = (  # Store the computed value.
        ModuleOffering.objects.filter(  # Filter queryset records.
            academic_year=previous_current_year,  # Store the computed value.
        )  # Close the current call.
        .select_related("module")  # Follow related objects.
        .prefetch_related("lecturer_enrolments")  # Prefetch related objects.
    )  # Close the current call.

    for previous_offering in previous_offerings:  # Iterate through the collection.
        next_offering = ModuleOffering.objects.filter(  # Filter queryset records.
            module=previous_offering.module,  # Store the computed value.
            academic_year=next_current_year,  # Store the computed value.
        ).first()  # Return the first result.

        if not next_offering:  # Check the current condition.
            continue  # Continue to the next item.

        for lecturer_enrolment in previous_offering.lecturer_enrolments.all():  # Iterate through the collection.
            new_enrolment, created = ModuleOfferingEnrollmentLecturer.objects.get_or_create(  # Unpack returned values.
                offering=next_offering,  # Store the computed value.
                lecturer=lecturer_enrolment.lecturer,  # Store the computed value.
                defaults={"is_primary": lecturer_enrolment.is_primary},  # Store the computed value.
            )  # Close the current call.

            if not created and lecturer_enrolment.is_primary and not new_enrolment.is_primary:  # Check the current condition.
                new_enrolment.is_primary = True  # Store the boolean state.
                new_enrolment.save(update_fields=["is_primary"])  # Save model changes.

            if created:  # Check the current condition.
                created_count += 1  # Continue the current block.

    return created_count  # Return the computed value.

def _start_new_academic_year_transition(current_year: AcademicYear):  # Define _start_new_academic_year_transition.
    # Calculate the label, start date, and end date for the next academic year
    """Start new academic year transition."""
    next_window = _build_next_academic_year_window(current_year)  # Store the computed value.
    # Run the whole rollover as one database transaction.
    with transaction.atomic():  # Open the resource safely.
        # Make sure the current year has all required offerings before rollover starts
        _sync_current_module_offerings(current_year)  # Call the helper function.
        # Mark the old year as no longer current
        current_year.is_current = False  # Store the boolean state.
        # Save that change to the database
        current_year.save(update_fields=["is_current"])  # Save model changes.

        # Select all module offerings belonging to the old current year
        # Mark those offerings as no longer current
        # Lock them so they become historical / read-only records
        ModuleOffering.objects.filter(  # Filter queryset records.
            academic_year=current_year,  # Store the computed value.
        ).update(  # Bulk update matching records.
            is_current=False,  # Store the boolean state.
            is_read_only=True,  # Store the boolean state.
        )  # Close the current call.

        next_year, created = AcademicYear.objects.get_or_create(  # Unpack returned values.
            # Try to find or create the next academic year by label
            label=next_window["label"],  # Store the computed value.
            defaults={  # Store the computed value.
                # Default start date for the new year
                "start_date": next_window["start_date"],  # Set start date.
                # Default end date for the new year
                "end_date": next_window["end_date"],  # Set end date.
                # Make the new year the active current year
                "is_current": True,  # Set is current.
            },  # Close the current mapping.
        )  # Close the current call.

        # If the year already existed, refresh its dates and current status
        if not created:  # Check the current condition.
            # Update the start date
            next_year.start_date = next_window["start_date"]  # Store the parsed date.
            # Ensure the existing year becomes current
            next_year.end_date = next_window["end_date"]  # Store the parsed date.
            # Save only the updated fields
            next_year.is_current = True  # Store the boolean state.
            next_year.save(update_fields=["start_date", "end_date", "is_current"])  # Save model changes.

        placement_updates = _roll_forward_module_placement_availability() # Update module placement availability for the new cycle
        created_offerings = _create_next_current_module_offerings(next_year) # Create the new current module offerings for the next academic year
        copied_lecturers = _copy_lecturers_to_next_current_offerings(current_year, next_year) # Carry lecturer enrolments forward into the new offerings where appropriate

    # Return a summary of the rollover results
    return {  # Return the computed value.
        "next_year": next_year,  # Set next year.
        "placement_updates": placement_updates,  # Set placement updates.
        "created_offerings": created_offerings,  # Set created offerings.
        "copied_lecturers": copied_lecturers,  # Set copied lecturers.
    }  # Close the current mapping.

# =======================
# Offering Access Helpers
# =======================
def _get_accessible_offering_for_user(user: User, offering_id: int):  # Define _get_accessible_offering_for_user.
    """Return accessible offering for user."""
    offering = get_object_or_404(  # Store the computed value.
        ModuleOffering.objects.select_related(  # Follow related objects.
            "module",  # Continue the current value.
            "academic_year",  # Continue the current value.
        ),  # Close the current call.
        pk=offering_id,  # Store the computed value.
    )  # Close the current call.

    if user.is_student():  # Check the current condition.
        if not ModuleOfferingEnrollmentStudent.objects.filter(  # Check the current condition.
            offering=offering,  # Store the computed value.
            student=user.student_profile,  # Store the computed value.
        ).exists():  # Check for any result.
            raise Http404("Offering not found")  # Raise a not found error.
    elif user.is_lecturer():  # Check the alternate condition.
        if not ModuleOfferingEnrollmentLecturer.objects.filter(  # Check the current condition.
            offering=offering,  # Store the computed value.
            lecturer=user.lecturer_profile,  # Store the computed value.
        ).exists():  # Check for any result.
            raise Http404("Offering not found")  # Raise a not found error.
    else:  # Handle the fallback case.
        raise Http404("Offering not found")  # Raise a not found error.

    return offering  # Return the computed value.

def _get_writable_lecturer_offering_by_id(user: User, offering_id: int):  # Define _get_writable_lecturer_offering_by_id.
    """Return writable lecturer offering by id."""
    if not user.is_lecturer():  # Check the current condition.
        raise Http404("Offering not found")  # Raise a not found error.

    offering = _get_accessible_offering_for_user(user, offering_id)  # Store the computed value.

    if _is_read_only_offering(offering):  # Check the current condition.
        raise Http404("Offering not found")  # Raise a not found error.

    return offering  # Return the computed value.

def _is_read_only_offering(offering: ModuleOffering) -> bool:  # Define _is_read_only_offering.
    """Handle is read only offering."""
    return offering.is_read_only or not offering.is_current  # Return the computed value.

def _current_offering_queryset_for_student(student: StudentProfile):  # Define _current_offering_queryset_for_student.
    """Return current offering queryset for student."""
    current_year = _get_current_academic_year()  # Store the computed value.
    if not current_year:  # Check the current condition.
        return ModuleOffering.objects.none()  # Return the computed value.

    return (  # Return the computed value.
        ModuleOffering.objects.filter(  # Filter queryset records.
            academic_year=current_year,  # Store the computed value.
            is_current=True,  # Store the boolean state.
            student_enrolments__student=student,  # Store the computed value.
        )  # Close the current call.
        .select_related("module", "academic_year")  # Follow related objects.
        .prefetch_related("lecturer_enrolments__lecturer__user")  # Prefetch related objects.
        .annotate(student_count=Count("student_enrolments", distinct=True))  # Add queryset annotations.
        .distinct()  # Remove duplicate rows.
        .order_by("module__code")  # Order queryset results.
    )  # Close the current call.


def _current_offering_queryset_for_lecturer(lecturer: LecturerProfile):  # Define _current_offering_queryset_for_lecturer.
    """Return current offering queryset for lecturer."""
    current_year = _get_current_academic_year()  # Store the computed value.
    if not current_year:  # Check the current condition.
        return ModuleOffering.objects.none()  # Return the computed value.

    return (  # Return the computed value.
        ModuleOffering.objects.filter(  # Filter queryset records.
            academic_year=current_year,  # Store the computed value.
            is_current=True,  # Store the boolean state.
            lecturer_enrolments__lecturer=lecturer,  # Store the computed value.
        )  # Close the current call.
        .select_related("module", "academic_year")  # Follow related objects.
        .annotate(student_count=Count("student_enrolments", distinct=True))  # Add queryset annotations.
        .distinct()  # Remove duplicate rows.
        .order_by("module__code")  # Order queryset results.
    )  # Close the current call.

def _previous_offering_queryset_for_student(student: StudentProfile):  # Define _previous_offering_queryset_for_student.
    """Return previous offering queryset for student."""
    current_year = _get_current_academic_year()  # Store the computed value.

    qs = (  # Initialise the queryset.
        ModuleOffering.objects.filter(  # Filter queryset records.
            student_enrolments__student=student,  # Store the computed value.
        )  # Close the current call.
        .select_related("module", "academic_year")  # Follow related objects.
        .prefetch_related("lecturer_enrolments__lecturer__user")  # Prefetch related objects.
        .annotate(student_count=Count("student_enrolments", distinct=True))  # Add queryset annotations.
        .distinct()  # Remove duplicate rows.
        .order_by("-academic_year__start_date", "module__code")  # Order queryset results.
    )  # Close the current call.

    if current_year:  # Check the current condition.
        qs = qs.exclude(academic_year=current_year, is_current=True)  # Exclude matching records.

    return qs  # Return the computed value.


def _previous_offering_queryset_for_lecturer(lecturer: LecturerProfile):  # Define _previous_offering_queryset_for_lecturer.
    """Return previous offering queryset for lecturer."""
    current_year = _get_current_academic_year()  # Store the computed value.

    qs = (  # Initialise the queryset.
        ModuleOffering.objects.filter(  # Filter queryset records.
            lecturer_enrolments__lecturer=lecturer,  # Store the computed value.
        )  # Close the current call.
        .select_related("module", "academic_year")  # Follow related objects.
        .annotate(student_count=Count("student_enrolments", distinct=True))  # Add queryset annotations.
        .distinct()  # Remove duplicate rows.
        .order_by("-academic_year__start_date", "module__code")  # Order queryset results.
    )  # Close the current call.

    if current_year:  # Check the current condition.
        qs = qs.exclude(academic_year=current_year, is_current=True)  # Exclude matching records.

    return qs  # Return the computed value.


# ==================
# Dashboard Builders
# ==================
def _group_offerings_by_academic_year(offerings):  # Define _group_offerings_by_academic_year.
    """Group offerings by academic year."""
    grouped = defaultdict(list)  # Store the computed value.
    ordered_year_ids = []  # Store matching ids.

    for offering in offerings:  # Iterate through the collection.
        academic_year_id = offering.academic_year_id  # Store the related id.
        if academic_year_id not in grouped:  # Check the current condition.
            ordered_year_ids.append(academic_year_id)  # Append to the list.
        grouped[academic_year_id].append(offering)  # Append to the list.

    return [  # Return the computed value.
        {  # Start the current mapping.
            "academic_year_label": grouped[academic_year_id][0].academic_year.label,  # Set this mapping value.
            "offerings": grouped[academic_year_id],  # Set offerings.
        }  # Close the current mapping.
        for academic_year_id in ordered_year_ids  # Iterate through the collection.
    ]  # Close the current list.


def _build_previous_student_dashboard_year_groups(student: StudentProfile, next_url=None):  # Define _build_previous_student_dashboard_year_groups.
    """Build previous student dashboard year groups."""
    previous_offerings = list(_previous_offering_queryset_for_student(student))  # Store the computed value.

    return [  # Return the computed value.
        {  # Start the current mapping.
            "academic_year_label": group["academic_year_label"],  # Set this mapping value.
            "rows": _build_student_dashboard_module_rows(group["offerings"], next_url),  # Set rows.
        }  # Close the current mapping.
        for group in _group_offerings_by_academic_year(previous_offerings)  # Iterate through the collection.
    ]  # Close the current list.


def _build_previous_lecturer_dashboard_year_groups(lecturer: LecturerProfile, next_url=None):  # Define _build_previous_lecturer_dashboard_year_groups.
    """Build previous lecturer dashboard year groups."""
    previous_offerings = list(_previous_offering_queryset_for_lecturer(lecturer))  # Store the computed value.

    return [  # Return the computed value.
        {  # Start the current mapping.
            "academic_year_label": group["academic_year_label"],  # Set this mapping value.
            "rows": _build_lecturer_dashboard_module_rows(group["offerings"], next_url),  # Set rows.
        }  # Close the current mapping.
        for group in _group_offerings_by_academic_year(previous_offerings)  # Iterate through the collection.
    ]  # Close the current list.


def _build_previous_student_profile_year_groups(student: StudentProfile, next_url=None):  # Define _build_previous_student_profile_year_groups.
    """Build previous student profile year groups."""
    previous_offerings = list(_previous_offering_queryset_for_student(student))  # Store the computed value.

    return [  # Return the computed value.
        {  # Start the current mapping.
            "academic_year_label": group["academic_year_label"],  # Set this mapping value.
            "module_rows": _build_student_profile_modules(group["offerings"], student, next_url),  # Set module rows.
        }  # Close the current mapping.
        for group in _group_offerings_by_academic_year(previous_offerings)  # Iterate through the collection.
    ]  # Close the current list.


def _build_previous_lecturer_profile_year_groups(lecturer: LecturerProfile, next_url=None):  # Define _build_previous_lecturer_profile_year_groups.
    """Build previous lecturer profile year groups."""
    previous_offerings = list(_previous_offering_queryset_for_lecturer(lecturer))  # Store the computed value.

    return [  # Return the computed value.
        {  # Start the current mapping.
            "academic_year_label": group["academic_year_label"],  # Set this mapping value.
            "module_rows": _build_lecturer_profile_modules(group["offerings"], lecturer, next_url),  # Set module rows.
        }  # Close the current mapping.
        for group in _group_offerings_by_academic_year(previous_offerings)  # Iterate through the collection.
    ]  # Close the current list.

def _primary_offering_lecturer_name(offering: ModuleOffering) -> str:  # Define _primary_offering_lecturer_name.
    """Return the primary lecturer name."""
    enrolments = list(offering.lecturer_enrolments.all())  # Return all records.
    primary = next((enrolment for enrolment in enrolments if enrolment.is_primary), None)  # Store the computed value.
    chosen = primary or (enrolments[0] if enrolments else None)  # Store the computed value.

    if not chosen:  # Check the current condition.
        return "TBA"  # Return the computed value.

    return chosen.lecturer.user.get_full_name() or chosen.lecturer.user.username  # Return the computed value.


def _build_student_dashboard_module_rows(offerings_qs, next_url=None):  # Define _build_student_dashboard_module_rows.
    """Build student dashboard module rows."""
    rows = []  # Build the list values.

    for offering in offerings_qs:  # Iterate through the collection.
        rows.append(  # Append to the list.
            {  # Start the current mapping.
                "code": offering.module.code,  # Set code.
                "title": offering.module.title,  # Set title.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_detail", args=[offering.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "lecturer_name": _primary_offering_lecturer_name(offering),  # Set lecturer name.
                "academic_year_label": offering.academic_year.label,  # Set this mapping value.
            }  # Close the current mapping.
        )  # Close the current call.

    return rows  # Return the computed value.


def _build_lecturer_dashboard_module_rows(offerings_qs, next_url=None):  # Define _build_lecturer_dashboard_module_rows.
    """Build lecturer dashboard module rows."""
    rows = []  # Build the list values.

    for offering in offerings_qs:  # Iterate through the collection.
        rows.append(  # Append to the list.
            {  # Start the current mapping.
                "code": offering.module.code,  # Set code.
                "title": offering.module.title,  # Set title.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_detail", args=[offering.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "student_count": getattr(offering, "student_count", 0),  # Set student count.
                "academic_year_label": offering.academic_year.label,  # Set this mapping value.
            }  # Close the current mapping.
        )  # Close the current call.

    return rows  # Return the computed value.

def _get_accessible_offering_assignment_for_user(user: User, offering_id: int, assignment_id: int):  # Define _get_accessible_offering_assignment_for_user.
    """Return accessible offering assignment for user."""
    offering = _get_accessible_offering_for_user(user, offering_id)  # Store the computed value.
    assignment = get_object_or_404(  # Store the computed value.
        Assignment.objects.select_related("offering__module").prefetch_related("files__parsed_document"),  # Follow related objects.
        pk=assignment_id,  # Store the computed value.
        offering=offering,  # Store the computed value.
    )  # Close the current call.
    return offering, assignment  # Return the computed value.


def _get_accessible_offering_quiz_for_user(user: User, offering_id: int, quiz_id: int):  # Define _get_accessible_offering_quiz_for_user.
    """Return accessible offering quiz for user."""
    offering = _get_accessible_offering_for_user(user, offering_id)  # Store the computed value.
    quiz = get_object_or_404(  # Store the computed value.
        Quiz.objects.select_related("offering__module").prefetch_related("questions__options"),  # Follow related objects.
        pk=quiz_id,  # Store the computed value.
        offering=offering,  # Store the computed value.
    )  # Close the current call.
    return offering, quiz  # Return the computed value.

def _recent_offering_module_announcements(offering):  # Define _recent_offering_module_announcements.
    """Return recent offering module announcements."""
    return (  # Return the computed value.
        offering.module_announcements  # Continue the current block.
        .select_related("created_by")  # Follow related objects.
        .order_by("-created_at", "-id")[:3]  # Order queryset results.
    )  # Close the current call.

# ==============
# Portal Helpers
# ==============
def _portal_office_tiles():  # Define _portal_office_tiles.
    """Return portal office tiles."""
    primary_tiles = [  # Store the computed value.
        {  # Start the current mapping.
            "label": "Teams",  # Set label.
            "url": "https://teams.microsoft.com/",  # Set url.
            "image": "accounts/images/teams.png",  # Set image.
        },  # Close the current mapping.
        {  # Start the current mapping.
            "label": "OneDrive",  # Set label.
            "url": "https://www.microsoft365.com/launch/onedrive",  # Set url.
            "image": "accounts/images/onedrive.png",  # Set image.
        },  # Close the current mapping.
        {  # Start the current mapping.
            "label": "OneNote",  # Set label.
            "url": "https://www.microsoft365.com/launch/onenote",  # Set url.
            "image": "accounts/images/onenote.png",  # Set image.
        },  # Close the current mapping.
        {  # Start the current mapping.
            "label": "Word",  # Set label.
            "url": "https://www.microsoft365.com/launch/word",  # Set url.
            "image": "accounts/images/word.png",  # Set image.
        },  # Close the current mapping.
        {  # Start the current mapping.
            "label": "Excel",  # Set label.
            "url": "https://www.microsoft365.com/launch/excel",  # Set url.
            "image": "accounts/images/excel.png",  # Set image.
        },  # Close the current mapping.
        {  # Start the current mapping.
            "label": "PowerPoint",  # Set label.
            "url": "https://www.microsoft365.com/launch/powerpoint",  # Set url.
            "image": "accounts/images/powerpoint.png",  # Set image.
        },  # Close the current mapping.
    ]  # Close the current list.

    more_tile = {  # Store the computed value.
        "label": "More",  # Set label.
        "url": "https://www.microsoft365.com/apps",  # Set url.
        "image": "accounts/images/more.png",  # Set image.
    }  # Close the current mapping.

    return primary_tiles, more_tile  # Return the computed value.

def _portal_offering_queryset_for_user(user: User):  # Define _portal_offering_queryset_for_user.
    """Return portal offerings for a user."""
    current_year = _get_current_academic_year()  # Store the computed value.
    if not current_year:  # Check the current condition.
        return ModuleOffering.objects.none()  # Return the computed value.

    if user.is_student():  # Check the current condition.
        return (  # Return the computed value.
            ModuleOffering.objects.filter(  # Filter queryset records.
                academic_year=current_year,  # Store the computed value.
                is_current=True,  # Store the boolean state.
                student_enrolments__student=user.student_profile,  # Store the computed value.
            )  # Close the current call.
            .select_related("module", "academic_year")  # Follow related objects.
            .distinct()  # Remove duplicate rows.
            .order_by("module__code")  # Order queryset results.
        )  # Close the current call.

    if user.is_lecturer():  # Check the current condition.
        return (  # Return the computed value.
            ModuleOffering.objects.filter(  # Filter queryset records.
                academic_year=current_year,  # Store the computed value.
                is_current=True,  # Store the boolean state.
                lecturer_enrolments__lecturer=user.lecturer_profile,  # Store the computed value.
            )  # Close the current call.
            .select_related("module", "academic_year")  # Follow related objects.
            .distinct()  # Remove duplicate rows.
            .order_by("module__code")  # Order queryset results.
        )  # Close the current call.

    return ModuleOffering.objects.none()  # Return the computed value.

def _portal_file_links(file_objects):  # Define _portal_file_links.
    """Build portal file links."""
    links = []  # Store the computed value.
    for file_obj in file_objects:  # Iterate through the collection.
        links.append(  # Append to the list.
            {  # Start the current mapping.
                "name": file_obj.original_name or os.path.basename(file_obj.file.name),  # Set name.
                "url": file_obj.file.url,  # Set url.
            }  # Close the current mapping.
        )  # Close the current call.
    return links  # Return the computed value.

def _build_portal_week_context(user, today=None, next_url=None):  # Define _build_portal_week_context.
    """Build portal week context."""
    today = today or timezone.localdate()  # Store the computed value.
    week_start = today - timedelta(days=today.weekday())  # Store the computed value.
    week_end = week_start + timedelta(days=6)  # Store the computed value.

    offerings = list(_portal_offering_queryset_for_user(user))  # Store the computed value.
    rows = []  # Build the list values.

    student_profile = user.student_profile if user.is_student() else None  # Store the computed value.
    lecturer_profile = user.lecturer_profile if user.is_lecturer() else None  # Store the computed value.

    for offering in offerings:  # Iterate through the collection.
        module = offering.module  # Store the computed value.
        module_url = _append_next_param(  # Store the resolved URL.
            reverse("accounts:offering_detail", args=[offering.id]),  # Resolve the named URL.
            next_url,  # Continue the current value.
        )  # Close the current call.

        assessment_items = []  # Build the list values.
        learning_items = []  # Build the list values.
        grade_items = []  # Build the list values.

        new_assignments = (  # Store the computed value.
            Assignment.objects.filter(  # Filter queryset records.
                offering=offering,  # Store the computed value.
                created_at__date__gte=week_start,  # Store the computed value.
                created_at__date__lte=week_end,  # Store the computed value.
            )  # Close the current call.
            .prefetch_related("files")  # Prefetch related objects.
            .order_by("-created_at")  # Order queryset results.
        )  # Close the current call.

        for assignment in new_assignments:  # Iterate through the collection.
            assessment_items.append(  # Append to the list.
                {  # Start the current mapping.
                    "title": assignment.title,  # Set title.
                    "url": _append_next_param(  # Set url.
                        reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                        next_url,  # Continue the current value.
                    ),  # Close the current call.
                    "files": _portal_file_links(assignment.files.all()),  # Return all records.
                }  # Close the current mapping.
            )  # Close the current call.

        new_quizzes = (  # Store the computed value.
            Quiz.objects.filter(  # Filter queryset records.
                offering=offering,  # Store the computed value.
                created_at__date__gte=week_start,  # Store the computed value.
                created_at__date__lte=week_end,  # Store the computed value.
            )  # Close the current call.
            .order_by("-created_at")  # Order queryset results.
        )  # Close the current call.

        if user.is_student():  # Check the current condition.
            new_quizzes = new_quizzes.filter(is_published=True)  # Filter queryset records.

        for quiz in new_quizzes:  # Iterate through the collection.
            assessment_items.append(  # Append to the list.
                {  # Start the current mapping.
                    "title": quiz.title,  # Set title.
                    "url": _append_next_param(  # Set url.
                        reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),  # Resolve the named URL.
                        next_url,  # Continue the current value.
                    ),  # Close the current call.
                    "files": [],  # Set files.
                }  # Close the current mapping.
            )  # Close the current call.

        learning_weeks = (  # Store the computed value.
            ModuleWeek.objects  # Continue the current block.
            .filter(  # Filter queryset records.
                offering=offering,  # Store the computed value.
                files__uploaded_at__date__gte=week_start,  # Store the computed value.
                files__uploaded_at__date__lte=week_end,  # Store the computed value.
            )  # Close the current call.
            .prefetch_related("files")  # Prefetch related objects.
            .distinct()  # Remove duplicate rows.
            .order_by("week_number")  # Order queryset results.
        )  # Close the current call.

        for week in learning_weeks:  # Iterate through the collection.
            learning_items.append(  # Append to the list.
                {  # Start the current mapping.
                    "title": (week.description or f"Week {week.week_number}").strip(),  # Trim surrounding whitespace.
                    "url": module_url,  # Set url.
                    "files": _portal_file_links(week.files.all()),  # Return all records.
                }  # Close the current mapping.
            )  # Close the current call.

        if student_profile:  # Check the current condition.
            assignment_grades = (  # Store the computed value.
                AssignmentGrade.objects  # Continue the current block.
                .filter(  # Filter queryset records.
                    submission__student=student_profile,  # Store the computed value.
                    submission__assignment__offering=offering,  # Store the computed value.
                    graded_at__date__gte=week_start,  # Store the computed value.
                    graded_at__date__lte=week_end,  # Store the computed value.
                )  # Close the current call.
                .select_related("submission__assignment")  # Follow related objects.
                .order_by("-graded_at")  # Order queryset results.
            )  # Close the current call.

            for grade in assignment_grades:  # Iterate through the collection.
                assignment = grade.submission.assignment  # Store the computed value.
                grade_items.append(  # Append to the list.
                    {  # Start the current mapping.
                        "title": assignment.title,  # Set title.
                        "url": _append_next_param(  # Set url.
                            reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                            next_url,  # Continue the current value.
                        ),  # Close the current call.
                        "summary": f"{grade.value}/{assignment.max_mark} · released {grade.graded_at.strftime('%Y-%m-%d %H:%M')}",  # Set summary.
                    }  # Close the current mapping.
                )  # Close the current call.

            quiz_attempts = (  # Store the computed value.
                QuizAttempt.objects  # Continue the current block.
                .filter(  # Filter queryset records.
                    student=student_profile,  # Store the computed value.
                    quiz__offering=offering,  # Store the computed value.
                    submitted_at__isnull=False,  # Store the computed value.
                    submitted_at__date__gte=week_start,  # Store the computed value.
                    submitted_at__date__lte=week_end,  # Store the computed value.
                )  # Close the current call.
                .exclude(status=QuizAttempt.Status.IN_PROGRESS)  # Exclude matching records.
                .select_related("quiz")  # Follow related objects.
                .order_by("-submitted_at")  # Order queryset results.
            )  # Close the current call.

            for attempt in quiz_attempts:  # Iterate through the collection.
                summary = (  # Store the computed value.
                    f"{attempt.weighted_score}/{attempt.quiz.max_mark} · released {attempt.submitted_at.strftime('%Y-%m-%d %H:%M')}"  # Continue the current block.
                    if _quiz_results_released(attempt.quiz)  # Check the current condition.
                    else f"Submitted {attempt.submitted_at.strftime('%Y-%m-%d %H:%M')} · results release when the quiz closes"  # Continue the current block.
                )  # Close the current call.

                grade_items.append(  # Append to the list.
                    {  # Start the current mapping.
                        "title": attempt.quiz.title,  # Set title.
                        "url": _append_next_param(  # Set url.
                            reverse("accounts:offering_quiz_detail", args=[offering.id, attempt.quiz.id]),  # Resolve the named URL.
                            next_url,  # Continue the current value.
                        ),  # Close the current call.
                        "summary": summary,  # Set summary.
                    }  # Close the current mapping.
                )  # Close the current call.

        elif lecturer_profile:  # Check the alternate condition.
            assignment_grades = (  # Store the computed value.
                AssignmentGrade.objects  # Continue the current block.
                .filter(  # Filter queryset records.
                    marker=lecturer_profile,  # Store the computed value.
                    submission__assignment__offering=offering,  # Store the computed value.
                    graded_at__date__gte=week_start,  # Store the computed value.
                    graded_at__date__lte=week_end,  # Store the computed value.
                )  # Close the current call.
                .select_related("submission__assignment", "submission__student__user")  # Follow related objects.
                .order_by("-graded_at")  # Order queryset results.
            )  # Close the current call.

            for grade in assignment_grades:  # Iterate through the collection.
                assignment = grade.submission.assignment  # Store the computed value.
                student_name = grade.submission.student.user.get_full_name() or grade.submission.student.user.username  # Store the computed value.
                grade_items.append(  # Append to the list.
                    {  # Start the current mapping.
                        "title": assignment.title,  # Set title.
                        "url": _append_next_param(  # Set url.
                            reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                            next_url,  # Continue the current value.
                        ),  # Close the current call.
                        "summary": f"{student_name} · {grade.value}/{assignment.max_mark} · graded {grade.graded_at.strftime('%Y-%m-%d %H:%M')}",  # Set summary.
                    }  # Close the current mapping.
                )  # Close the current call.

            quiz_attempts = (  # Store the computed value.
                QuizAttempt.objects  # Continue the current block.
                .filter(  # Filter queryset records.
                    quiz__offering=offering,  # Store the computed value.
                    submitted_at__isnull=False,  # Store the computed value.
                    submitted_at__date__gte=week_start,  # Store the computed value.
                    submitted_at__date__lte=week_end,  # Store the computed value.
                )  # Close the current call.
                .exclude(status=QuizAttempt.Status.IN_PROGRESS)  # Exclude matching records.
                .select_related("quiz", "student__user")  # Follow related objects.
                .order_by("-submitted_at")  # Order queryset results.
            )  # Close the current call.

            for attempt in quiz_attempts:  # Iterate through the collection.
                student_name = attempt.student.user.get_full_name() or attempt.student.user.username  # Store the computed value.
                grade_items.append(  # Append to the list.
                    {  # Start the current mapping.
                        "title": attempt.quiz.title,  # Set title.
                        "url": _append_next_param(  # Set url.
                            reverse("accounts:offering_quiz_detail", args=[offering.id, attempt.quiz.id]),  # Resolve the named URL.
                            next_url,  # Continue the current value.
                        ),  # Close the current call.
                        "summary": f"{student_name} · {attempt.weighted_score}/{attempt.quiz.max_mark} · submitted {attempt.submitted_at.strftime('%Y-%m-%d %H:%M')}",  # Set summary.
                    }  # Close the current mapping.
                )  # Close the current call.

        if assessment_items or learning_items or grade_items:  # Check the current condition.
            rows.append(  # Append to the list.
                {  # Start the current mapping.
                    "module_code": module.code,  # Set module code.
                    "module_title": module.title,  # Set module title.
                    "module_url": module_url,  # Set module url.
                    "assessment_items": assessment_items,  # Set assessment items.
                    "learning_items": learning_items,  # Set learning items.
                    "grade_items": grade_items,  # Set grade items.
                }  # Close the current mapping.
            )  # Close the current call.

    return {  # Return the computed value.
        "week_start": week_start,  # Set week start.
        "week_end": week_end,  # Set week end.
        "portal_week_rows": rows,  # Set portal week rows.
    }  # Close the current mapping.

def _build_portal_calendar_context(user, year, month, next_url=None):  # Define _build_portal_calendar_context.
    """Build portal calendar context."""
    today = timezone.localdate()  # Store the computed value.

    first_of_month = date(year, month, 1)  # Store the computed value.
    _, last_day = pycalendar.monthrange(year, month)  # Unpack returned values.
    last_of_month = date(year, month, last_day)  # Store the computed value.

    current_offerings = _portal_offering_queryset_for_user(user)  # Store the computed value.

    assignment_qs = (  # Initialise the queryset.
        Assignment.objects  # Continue the current block.
        .filter(  # Filter queryset records.
            offering__in=current_offerings,  # Store the computed value.
            due_datetime__date__gte=first_of_month,  # Store the computed value.
            due_datetime__date__lte=last_of_month,  # Store the computed value.
        )  # Close the current call.
        .select_related("offering__module")  # Follow related objects.
        .order_by("due_datetime", "title")  # Order queryset results.
    )  # Close the current call.

    quiz_qs = (  # Initialise the queryset.
        Quiz.objects  # Continue the current block.
        .filter(  # Filter queryset records.
            offering__in=current_offerings,  # Store the computed value.
            close_datetime__date__gte=first_of_month,  # Store the computed value.
            close_datetime__date__lte=last_of_month,  # Store the computed value.
        )  # Close the current call.
        .select_related("offering__module")  # Follow related objects.
        .order_by("close_datetime", "title")  # Order queryset results.
    )  # Close the current call.

    if user.is_student():  # Check the current condition.
        quiz_qs = quiz_qs.filter(is_published=True)  # Filter queryset records.

    month_items = []  # Build the list values.

    for assignment in assignment_qs:  # Iterate through the collection.
        month_items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind_label": "Assignment",  # Set kind label.
                "kind_class": "assignment",  # Set kind class.
                "title": assignment.title,  # Set title.
                "module_code": assignment.module.code,  # Set module code.
                "module_title": assignment.module.title,  # Set module title.
                "timestamp": assignment.due_datetime,  # Set timestamp.
                "date_value": assignment.due_datetime.date(),  # Set date value.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_assignment_detail", args=[assignment.offering.id, assignment.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "date_text": "Due",  # Set date text.
            }  # Close the current mapping.
        )  # Close the current call.

    for quiz in quiz_qs:  # Iterate through the collection.
        month_items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind_label": "Quiz",  # Set kind label.
                "kind_class": "quiz",  # Set kind class.
                "title": quiz.title,  # Set title.
                "module_code": quiz.module.code,  # Set module code.
                "module_title": quiz.module.title,  # Set module title.
                "timestamp": quiz.close_datetime,  # Set timestamp.
                "date_value": quiz.close_datetime.date(),  # Set date value.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_quiz_detail", args=[quiz.offering.id, quiz.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "date_text": "Closes",  # Set date text.
            }  # Close the current mapping.
        )  # Close the current call.

    month_items.sort(key=lambda item: (item["timestamp"], item["kind_label"], item["title"]))  # Call the helper function.

    items_by_day = defaultdict(list)  # Store the computed value.
    for item in month_items:  # Iterate through the collection.
        items_by_day[item["date_value"]].append(item)  # Append to the list.

    calendar_weeks = []  # Store the computed value.
    calendar_builder = pycalendar.Calendar(firstweekday=0)  # Store the computed value.

    for week in calendar_builder.monthdatescalendar(year, month):  # Iterate through the collection.
        week_cells = []  # Store the computed value.
        for day in week:  # Iterate through the collection.
            day_items = items_by_day.get(day, [])  # Fetch a single record.
            week_cells.append(  # Append to the list.
                {  # Start the current mapping.
                    "date": day,  # Set date.
                    "day_number": day.day,  # Set day number.
                    "in_month": day.month == month,  # Set in month.
                    "is_today": day == today,  # Set is today.
                    "items": day_items[:3],  # Set items.
                    "extra_count": max(len(day_items) - 3, 0),  # Set extra count.
                }  # Close the current mapping.
            )  # Close the current call.
        calendar_weeks.append(week_cells)  # Append to the list.

    prev_month_anchor = first_of_month - timedelta(days=1)  # Store the computed value.
    next_month_anchor = (first_of_month.replace(day=28) + timedelta(days=4)).replace(day=1)  # Store the computed value.

    return {  # Return the computed value.
        "calendar_weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],  # Set calendar weekdays.
        "calendar_weeks": calendar_weeks,  # Set calendar weeks.
        "calendar_items": month_items,  # Set calendar items.
        "calendar_month_label": first_of_month.strftime("%B %Y"),  # Set this mapping value.
        "prev_year": prev_month_anchor.year,  # Set prev year.
        "prev_month": prev_month_anchor.month,  # Set prev month.
        "next_year": next_month_anchor.year,  # Set next year.
        "next_month": next_month_anchor.month,  # Set next month.
    }  # Close the current mapping.

def _week_is_viewable(week):  # Define _week_is_viewable.
    """Return whether a week is viewable."""
    return bool((week.description or "").strip()) or week.files.exists()  # Return the computed value.

# ====================
# Notification Helpers
# ====================
def _notify_students_new_assignment(assignment):  # Define _notify_students_new_assignment.
    """Notify students new assignment."""
    notify_offering_students(  # Notify enrolled students.
        assignment.offering,  # Continue the current value.
        title=f"New assignment: {assignment.title}",  # Store the computed value.
        redirect_url=reverse(  # Store the resolved URL.
            "accounts:offering_assignment_detail",  # Continue the current value.
            args=[assignment.offering.id, assignment.id],  # Store the computed value.
        ),  # Close the current call.
        notification_type=Notification.Type.ASSIGNMENT_NEW,  # Store the computed value.
        event_key=f"assignment-new:{assignment.id}",  # Store the computed value.
    )  # Close the current call.


def _notify_student_assignment_submitted(submission):  # Define _notify_student_assignment_submitted.
    """Notify student assignment submitted."""
    create_notification(  # Create the notification record.
        recipient=submission.student.user,  # Store the computed value.
        offering=submission.assignment.offering,  # Store the computed value.
        title=f"Assignment submitted: {submission.assignment.title}",  # Store the computed value.
        redirect_url=reverse(  # Store the resolved URL.
            "accounts:offering_assignment_detail",  # Continue the current value.
            args=[submission.assignment.offering.id, submission.assignment.id],  # Store the computed value.
        ),  # Close the current call.
        notification_type=Notification.Type.ASSIGNMENT_SUBMITTED,  # Store the computed value.
        event_key=f"assignment-submitted:{submission.id}",  # Store the computed value.
    )  # Close the current call.


def _notify_student_assignment_graded(grade_obj):  # Define _notify_student_assignment_graded.
    """Notify student assignment graded."""
    create_notification(  # Create the notification record.
        recipient=grade_obj.submission.student.user,  # Store the computed value.
        offering=grade_obj.submission.assignment.offering,  # Store the computed value.
        title=f"Assignment graded: {grade_obj.submission.assignment.title}",  # Store the computed value.
        redirect_url=reverse(  # Store the resolved URL.
            "accounts:offering_assignment_detail",  # Continue the current value.
            args=[grade_obj.submission.assignment.offering.id, grade_obj.submission.assignment.id],  # Store the computed value.
        ),  # Close the current call.
        notification_type=Notification.Type.ASSIGNMENT_GRADED,  # Store the computed value.
    )  # Close the current call.


def _notify_students_new_quiz(quiz):  # Define _notify_students_new_quiz.
    """Notify students new quiz."""
    if not quiz.is_published:  # Check the current condition.
        return  # Return early.

    notify_offering_students(  # Notify enrolled students.
        quiz.offering,  # Continue the current value.
        title=f"New quiz: {quiz.title}",  # Store the computed value.
        redirect_url=reverse(  # Store the resolved URL.
            "accounts:offering_quiz_detail",  # Continue the current value.
            args=[quiz.offering.id, quiz.id],  # Store the computed value.
        ),  # Close the current call.
        notification_type=Notification.Type.QUIZ_NEW,  # Store the computed value.
        event_key=f"quiz-new:{quiz.id}",  # Store the computed value.
    )  # Close the current call.


def _notify_student_quiz_submitted(attempt):  # Define _notify_student_quiz_submitted.
    """Notify student quiz submitted."""
    create_notification(  # Create the notification record.
        recipient=attempt.student.user,  # Store the computed value.
        offering=attempt.quiz.offering,  # Store the computed value.
        title=f"Quiz submitted: {attempt.quiz.title}",  # Store the computed value.
        redirect_url=reverse(  # Store the resolved URL.
            "accounts:offering_quiz_detail",  # Continue the current value.
            args=[attempt.quiz.offering.id, attempt.quiz.id],  # Store the computed value.
        ),  # Close the current call.
        notification_type=Notification.Type.QUIZ_SUBMITTED,  # Store the computed value.
        event_key=f"quiz-submitted:{attempt.id}",  # Store the computed value.
    )  # Close the current call.


def _notify_students_if_week_now_viewable(week):  # Define _notify_students_if_week_now_viewable.
    """Notify students if week now viewable."""
    if not _week_is_viewable(week):  # Check the current condition.
        return  # Return early.

    notify_offering_students(  # Notify enrolled students.
        week.offering,  # Continue the current value.
        title=f"New week available: Week {week.week_number}",  # Store the computed value.
        redirect_url=reverse("accounts:offering_detail", args=[week.offering.id]),  # Store the resolved URL.
        notification_type=Notification.Type.WEEK_AVAILABLE,  # Store the computed value.
        event_key=f"week-available:{week.offering.id}:{week.week_number}",  # Store the computed value.
    )  # Close the current call.


def _notify_lecturers_parser_success(offering, document_name, redirect_url):  # Define _notify_lecturers_parser_success.
    """Notify lecturers parser success."""
    notify_offering_lecturers(  # Notify enrolled lecturers.
        offering,  # Continue the current value.
        title=f"Document parsed successfully: {document_name}",  # Store the computed value.
        redirect_url=redirect_url,  # Store the resolved URL.
        notification_type=Notification.Type.PARSER_SUCCESS,  # Store the computed value.
    )  # Close the current call.


def _notify_lecturers_parser_failure(offering, document_name, redirect_url):  # Define _notify_lecturers_parser_failure.
    """Notify lecturers parser failure."""
    notify_offering_lecturers(  # Notify enrolled lecturers.
        offering,  # Continue the current value.
        title=f"Document parse failed: {document_name}",  # Store the computed value.
        redirect_url=redirect_url,  # Store the resolved URL.
        notification_type=Notification.Type.PARSER_FAILURE,  # Store the computed value.
    )  # Close the current call.

# ================
# Parsed Documents
# ================
def _rebuild_parsed_document_html(parsed_document: ParsedDocument, save: bool = True) -> str:  # Define _rebuild_parsed_document_html.
    """Rebuild rendered HTML for a parsed document."""
    image_lookup = {  # Store the computed value.
        image.token: {  # Start the current mapping.
            "src": image.image.url,  # Set src.
            "alt_text": image.alt_text or "",  # Set alt text.
        }  # Close the current mapping.
        for image in parsed_document.images.all()  # Iterate through the collection.
    }  # Close the current mapping.

    parsed_document.rendered_html = build_rendered_html_from_blocks(  # Store rendered HTML.
        parsed_document.parsed_blocks or [],  # Continue the current value.
        image_lookup=image_lookup,  # Store the computed value.
    )  # Close the current call.

    if save:  # Check the current condition.
        parsed_document.save(update_fields=["rendered_html", "updated_at"])  # Save model changes.

    return parsed_document.rendered_html  # Return the computed value.

def _persist_parsed_document(  # Define _persist_parsed_document.
    *,  # Continue the current value.
    parsed_payload: dict,  # Continue the current value.
    week_file: ModuleWeekFile | None = None,  # Store the uploaded file.
    assignment_file: AssignmentFile | None = None,  # Store the uploaded file.
) -> ParsedDocument:  # Continue the current block.
    """Persist a parsed document and its images."""
    parsed_document = ParsedDocument.objects.create(  # Create a database record.
        week_file=week_file,  # Store the uploaded file.
        assignment_file=assignment_file,  # Store the uploaded file.
        source_extension=parsed_payload["extension"],  # Store the computed value.
        parser_status=ParsedDocument.Status.PROCESSING,  # Store the computed value.
        parsed_blocks=parsed_payload["blocks"],  # Store the computed value.
        page_count=parsed_payload["page_count"],  # Store the item count.
    )  # Close the current call.

    created_images: list[ParsedDocumentImage] = []  # Store the computed value.

    try:  # Start guarded parsing.
        for image_data in parsed_payload.get("images", []):  # Iterate through the collection.
            image_obj = ParsedDocumentImage(  # Store the computed value.
                parsed_document=parsed_document,  # Store the computed value.
                token=image_data["token"],  # Store the computed value.
                display_order=image_data.get("display_order") or 0,  # Fetch a single record.
                page_number=image_data.get("page_number"),  # Fetch a single record.
                original_name=image_data.get("filename", ""),  # Fetch a single record.
                alt_text=image_data.get("alt_text", ""),  # Fetch a single record.
            )  # Close the current call.
            image_obj.image.save(  # Save model changes.
                image_data["filename"],  # Continue the current value.
                ContentFile(image_data["content"]),  # Call the helper function.
                save=True,  # Store the computed value.
            )  # Close the current call.
            created_images.append(image_obj)  # Append to the list.

        _rebuild_parsed_document_html(parsed_document, save=False)  # Call the helper function.

        parsed_document.parser_status = ParsedDocument.Status.READY  # Store the computed value.
        parsed_document.parse_error = ""  # Store the computed value.
        parsed_document.save(update_fields=["rendered_html", "parser_status", "parse_error", "updated_at"])  # Save model changes.
        return parsed_document  # Return the computed value.

    except Exception:  # Handle the raised exception.
        for image in created_images:  # Iterate through the collection.
            if image.image:  # Check the current condition.
                image.image.delete(save=False)  # Delete the record.

        ParsedDocumentImage.objects.filter(parsed_document=parsed_document).delete()  # Filter queryset records.
        parsed_document.delete()  # Delete the record.
        raise  # Continue the current block.

def _get_authorised_parsed_document(parsed_id: int, user: User):  # Define _get_authorised_parsed_document.
    """Return an authorised parsed document."""
    parsed_document = get_object_or_404(  # Store the computed value.
        ParsedDocument.objects.select_related(  # Follow related objects.
            "week_file__week__offering__module",  # Continue the current value.
            "assignment_file__assignment__offering__module",  # Continue the current value.
        ).prefetch_related("images"),  # Prefetch related objects.
        pk=parsed_id,  # Store the computed value.
    )  # Close the current call.

    if parsed_document.week_file_id:  # Check the current condition.
        source_offering = parsed_document.week_file.week.offering  # Store the computed value.
    elif parsed_document.assignment_file_id:  # Check the alternate condition.
        source_offering = parsed_document.assignment_file.assignment.offering  # Store the computed value.
    else:  # Handle the fallback case.
        raise Http404("Parsed document not found")  # Raise a not found error.

    module = source_offering.module  # Store the computed value.

    if user.is_student():  # Check the current condition.
        if not ModuleOfferingEnrollmentStudent.objects.filter(  # Check the current condition.
            offering=source_offering,  # Store the computed value.
            student=user.student_profile,  # Store the computed value.
        ).exists():  # Check for any result.
            raise Http404("Parsed document not found")  # Raise a not found error.
    elif user.is_lecturer():  # Check the alternate condition.
        if not ModuleOfferingEnrollmentLecturer.objects.filter(  # Check the current condition.
            offering=source_offering,  # Store the computed value.
            lecturer=user.lecturer_profile,  # Store the computed value.
        ).exists():  # Check for any result.
            raise Http404("Parsed document not found")  # Raise a not found error.
    else:  # Handle the fallback case.
        raise Http404("Parsed document not found")  # Raise a not found error.

    return parsed_document, source_offering, module  # Return the computed value.

# ============
# Quiz Helpers
# ============
def _parse_form_datetime(date_str, time_str, label, errors):  # Define _parse_form_datetime.
    """Parse a form datetime value."""
    if not date_str:  # Check the current condition.
        errors.append(f"{label} date is required.")  # Append to the list.
        return None  # Return the computed value.
    if not time_str:  # Check the current condition.
        errors.append(f"{label} time is required.")  # Append to the list.
        return None  # Return the computed value.

    try:  # Start guarded parsing.
        dt = datetime.fromisoformat(f"{date_str} {time_str}")  # Store the computed value.
    except ValueError:  # Handle the raised exception.
        errors.append(f"Invalid {label.lower()} date/time format.")  # Append to the list.
        return None  # Return the computed value.

    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt  # Return the computed value.


def _parse_decimal_value(raw_value, label, errors, minimum=None):  # Define _parse_decimal_value.
    """Parse a decimal form value."""
    try:  # Start guarded parsing.
        value = Decimal(str(raw_value).strip())  # Trim surrounding whitespace.
    except (InvalidOperation, TypeError, ValueError):  # Handle the decimal parsing error.
        errors.append(f"{label} must be a valid number.")  # Append to the list.
        return None  # Return the computed value.

    if minimum is not None and value < Decimal(str(minimum)):  # Check the current condition.
        errors.append(f"{label} must be at least {minimum}.")  # Append to the list.
        return None  # Return the computed value.

    return value.quantize(Decimal("0.01"))  # Return the computed value.


def _parse_positive_int(raw_value, label, errors, minimum=1):  # Define _parse_positive_int.
    """Parse a positive integer value."""
    try:  # Start guarded parsing.
        value = int(str(raw_value).strip())  # Trim surrounding whitespace.
    except (TypeError, ValueError):  # Handle the raised exception.
        errors.append(f"{label} must be a whole number.")  # Append to the list.
        return None  # Return the computed value.

    if value < minimum:  # Check the current condition.
        errors.append(f"{label} must be at least {minimum}.")  # Append to the list.
        return None  # Return the computed value.

    return value  # Return the computed value.


def _parse_questions_payload(raw_payload, errors):  # Define _parse_questions_payload.
    """Parse quiz questions from the request."""
    try:  # Start guarded parsing.
        payload = json.loads(raw_payload or "[]")  # Store the computed value.
    except json.JSONDecodeError:  # Handle the raised exception.
        errors.append("Question data could not be read. Please rebuild the quiz form and try again.")  # Append to the list.
        return []  # Return the computed value.

    if not isinstance(payload, list) or not payload:  # Check the current condition.
        errors.append("At least one question is required.")  # Append to the list.
        return []  # Return the computed value.

    valid_types = {  # Store the computed value.
        QuizQuestion.Type.MULTIPLE_CHOICE,  # Continue the current value.
        QuizQuestion.Type.MULTIPLE_SELECT,  # Continue the current value.
        QuizQuestion.Type.TRUE_FALSE,  # Continue the current value.
    }  # Close the current mapping.
    parsed_questions = []  # Store the computed value.

    for index, item in enumerate(payload, start=1):  # Iterate through the collection.
        prompt = (item.get("prompt") or "").strip()  # Fetch a single record.
        question_type = (item.get("question_type") or "").strip()  # Fetch a single record.
        marks = _parse_decimal_value(  # Store the computed value.
            item.get("marks", "1"),  # Fetch a single record.
            f"Question {index} marks",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=Decimal("0.25"),  # Store the computed value.
        )  # Close the current call.

        if not prompt:  # Check the current condition.
            errors.append(f"Question {index} prompt is required.")  # Append to the list.

        if question_type not in valid_types:  # Check the current condition.
            errors.append(f"Question {index} has an invalid question type.")  # Append to the list.

        normalized = {  # Store the computed value.
            "prompt": prompt,  # Set prompt.
            "question_type": question_type,  # Set question type.
            "marks": marks or Decimal("1.00"),  # Set marks.
            "options": [],  # Set options.
        }  # Close the current mapping.

        if question_type == QuizQuestion.Type.TRUE_FALSE:  # Check the current condition.
            correct_true_false = (item.get("correct_true_false") or "").strip().lower()  # Fetch a single record.
            if correct_true_false not in {"true", "false"}:  # Check the current condition.
                errors.append(f"Question {index} must choose either True or False as the correct answer.")  # Append to the list.

            normalized["options"] = [  # Start the current list.
                {"text": "True", "is_correct": correct_true_false == "true"},  # Add this mapping item.
                {"text": "False", "is_correct": correct_true_false == "false"},  # Add this mapping item.
            ]  # Close the current list.
            parsed_questions.append(normalized)  # Append to the list.
            continue  # Continue to the next item.

        raw_options = item.get("options")  # Fetch a single record.
        options = []  # Store the computed value.

        if isinstance(raw_options, list):  # Check the current condition.
            for option_index, option in enumerate(raw_options, start=1):  # Iterate through the collection.
                text = (option.get("text") or "").strip()  # Fetch a single record.
                if not text:  # Check the current condition.
                    errors.append(f"Question {index} option {option_index} cannot be empty.")  # Append to the list.
                    continue  # Continue to the next item.

                options.append(  # Append to the list.
                    {  # Start the current mapping.
                        "text": text,  # Set text.
                        "is_correct": bool(option.get("is_correct")),  # Fetch a single record.
                    }  # Close the current mapping.
                )  # Close the current call.
        else:  # Handle the fallback case.

            legacy_options = [  # Build the list values.
                line.strip()  # Trim surrounding whitespace.
                for line in (item.get("options_text") or "").splitlines()  # Iterate through the collection.
                if line.strip()  # Check the current condition.
            ]  # Close the current list.

            if question_type == QuizQuestion.Type.MULTIPLE_CHOICE:  # Check the current condition.
                try:  # Start guarded parsing.
                    correct_number = int(str(item.get("correct_option") or "").strip())  # Fetch a single record.
                except ValueError:  # Handle the raised exception.
                    correct_number = None  # Store the computed value.

                options = [  # Store the computed value.
                    {  # Start the current mapping.
                        "text": option_text,  # Set text.
                        "is_correct": (position == (correct_number - 1)) if correct_number is not None else False,  # Set is correct.
                    }  # Close the current mapping.
                    for position, option_text in enumerate(legacy_options)  # Iterate through the collection.
                ]  # Close the current list.

            elif question_type == QuizQuestion.Type.MULTIPLE_SELECT:  # Check the alternate condition.
                parsed_numbers = []  # Store the computed value.
                for part in str(item.get("correct_options") or "").split(","):  # Iterate through the collection.
                    part = part.strip()  # Trim surrounding whitespace.
                    if not part:  # Check the current condition.
                        continue  # Continue to the next item.
                    try:  # Start guarded parsing.
                        parsed_numbers.append(int(part))  # Append to the list.
                    except ValueError:  # Handle the raised exception.
                        errors.append(  # Append to the list.
                            f"Question {index} multiple-select correct answers must be comma-separated numbers."  # Continue the current block.
                        )  # Close the current call.
                        parsed_numbers = []  # Store the computed value.
                        break  # Stop the current loop.

                parsed_numbers = sorted(set(parsed_numbers))  # Store the computed value.
                options = [  # Store the computed value.
                    {  # Start the current mapping.
                        "text": option_text,  # Set text.
                        "is_correct": ((position + 1) in parsed_numbers),  # Set is correct.
                    }  # Close the current mapping.
                    for position, option_text in enumerate(legacy_options)  # Iterate through the collection.
                ]  # Close the current list.

        if len(options) < 2:  # Check the current condition.
            errors.append(f"Question {index} must have at least two options.")  # Append to the list.

        if question_type == QuizQuestion.Type.MULTIPLE_CHOICE:  # Check the current condition.
            correct_count = sum(1 for option in options if option["is_correct"])  # Store the item count.
            if correct_count != 1:  # Check the current condition.
                errors.append(f"Question {index} must have exactly one correct answer.")  # Append to the list.

        if question_type == QuizQuestion.Type.MULTIPLE_SELECT:  # Check the current condition.
            if not any(option["is_correct"] for option in options):  # Check the current condition.
                errors.append(f"Question {index} must have at least one correct answer.")  # Append to the list.

        normalized["options"] = options  # Continue the current block.
        parsed_questions.append(normalized)  # Append to the list.

    return parsed_questions  # Return the computed value.


def _create_quiz_questions(quiz, question_payloads):  # Define _create_quiz_questions.
    """Create quiz questions and options."""
    for question_index, question_data in enumerate(question_payloads, start=1):  # Iterate through the collection.
        question = QuizQuestion.objects.create(  # Create a database record.
            quiz=quiz,  # Store the computed value.
            prompt=question_data["prompt"],  # Store the computed value.
            question_type=question_data["question_type"],  # Store the computed value.
            marks=question_data["marks"],  # Store the computed value.
            display_order=question_index,  # Store the computed value.
        )  # Close the current call.

        for option_index, option_data in enumerate(question_data["options"], start=1):  # Iterate through the collection.
            QuizOption.objects.create(  # Create a database record.
                question=question,  # Store the computed value.
                text=option_data["text"],  # Store the computed value.
                is_correct=option_data["is_correct"],  # Store the boolean state.
                display_order=option_index,  # Store the computed value.
            )  # Close the current call.

def _can_edit_assignment(assignment, now=None):  # Define _can_edit_assignment.
    """Return whether the assignment can still be edited."""
    now = now or timezone.now()  # Store the computed value.
    return now < assignment.due_datetime  # Return the computed value.


def _can_edit_quiz(quiz, now=None):  # Define _can_edit_quiz.
    """Return whether the quiz can still be edited."""
    now = now or timezone.now()  # Store the computed value.
    return now < quiz.open_datetime  # Return the computed value.


def _quiz_has_active_attempts(quiz):  # Define _quiz_has_active_attempts.
    """Return whether the quiz currently has an active attempt."""
    return quiz.attempts.filter(  # Return the computed value.
        status=QuizAttempt.Status.IN_PROGRESS,  # Store the computed value.
        submitted_at__isnull=True,  # Store the computed value.
    ).exists()  # Check for any result.


def _can_delete_quiz(quiz):  # Define _can_delete_quiz.
    """Return whether the quiz can be deleted."""
    return not _quiz_has_active_attempts(quiz)  # Return the computed value.


def _build_quiz_editor_initial_questions(quiz):  # Define _build_quiz_editor_initial_questions.
    """Build quiz editor initial question data."""
    initial_questions = []  # Store the computed value.

    for question in quiz.questions.prefetch_related("options").all():  # Iterate through the collection.
        question_data = {  # Store the computed value.
            "prompt": question.prompt,  # Set prompt.
            "question_type": question.question_type,  # Set question type.
            "marks": str(question.marks),  # Set marks.
        }  # Close the current mapping.

        options = list(question.options.all())  # Store the computed value.

        if question.question_type == QuizQuestion.Type.TRUE_FALSE:  # Check the current condition.
            correct_option = next((option for option in options if option.is_correct), None)  # Store the computed value.
            correct_value = (correct_option.text if correct_option else "True").strip().lower()  # Store the computed value.
            question_data["correct_true_false"] = "false" if correct_value == "false" else "true"  # Set correct value.
        else:  # Handle the fallback case.
            question_data["options"] = [  # Set options.
                {  # Start the current mapping.
                    "text": option.text,  # Set text.
                    "is_correct": option.is_correct,  # Set is correct.
                }  # Close the current mapping.
                for option in options  # Iterate through the collection.
            ]  # Close the current list.

        initial_questions.append(question_data)  # Append to the list.

    return initial_questions  # Return the computed value.


def _delete_parsed_document_assets(parsed_document):  # Define _delete_parsed_document_assets.
    """Delete parsed document database and storage assets."""
    for image in parsed_document.images.all():  # Iterate through the collection.
        if image.image:  # Check the current condition.
            image.image.delete(save=False)  # Delete the record.

    ParsedDocumentImage.objects.filter(parsed_document=parsed_document).delete()  # Filter queryset records.
    parsed_document.delete()  # Delete the record.


def _delete_assignment_file_assets(assignment_file):  # Define _delete_assignment_file_assets.
    """Delete an assignment file and any parsed document assets."""
    parsed_document = assignment_file.parsed_document_safe  # Store the computed value.
    if parsed_document:  # Check the current condition.
        _delete_parsed_document_assets(parsed_document)  # Call the helper function.

    if assignment_file.file:  # Check the current condition.
        assignment_file.file.delete(save=False)  # Delete the record.

    assignment_file.delete()  # Delete the record.


def _delete_submission_file_assets(submission_file):  # Define _delete_submission_file_assets.
    """Delete a submission file from storage and the database."""
    if submission_file.file:  # Check the current condition.
        submission_file.file.delete(save=False)  # Delete the record.

    submission_file.delete()  # Delete the record.


def _delete_assignment_with_assets(assignment):  # Define _delete_assignment_with_assets.
    """Delete an assignment and all uploaded storage assets."""
    assignment_files = list(  # Store the computed value.
        assignment.files.select_related("parsed_document").prefetch_related("parsed_document__images")  # Follow related objects.
    )  # Close the current call.
    submission_files = list(  # Store the computed value.
        SubmissionFile.objects.filter(submission__assignment=assignment)  # Filter queryset records.
    )  # Close the current call.

    for assignment_file in assignment_files:  # Iterate through the collection.
        _delete_assignment_file_assets(assignment_file)  # Call the helper function.

    for submission_file in submission_files:  # Iterate through the collection.
        _delete_submission_file_assets(submission_file)  # Call the helper function.

    assignment.delete()  # Delete the record.

def _quiz_results_released(quiz, now=None):  # Define _quiz_results_released.
    """Return whether quiz results should be visible to students."""
    now = now or timezone.now()  # Store the computed value.
    return now >= quiz.close_datetime  # Return the computed value.

def _get_student_quiz_state(quiz, student, now=None):  # Define _get_student_quiz_state.
    """Return the student's quiz state."""
    now = now or timezone.now()  # Store the computed value.

    attempts = list(  # Store the computed value.
        quiz.attempts.filter(student=student).order_by("-attempt_number", "-started_at")  # Filter queryset records.
    )  # Close the current call.
    active_attempt = next((attempt for attempt in attempts if attempt.is_active()), None)  # Store the computed value.
    latest_submitted_attempt = next((attempt for attempt in attempts if attempt.submitted_at), None)  # Store the computed value.

    attempts_used = len(attempts)  # Store the computed value.
    remaining_attempts = max(quiz.max_attempts - attempts_used, 0)  # Store the computed value.

    if active_attempt:  # Check the current condition.
        status_label = "Attempt in progress"  # Store the computed value.
        is_clickable = True  # Store the boolean state.
    elif not quiz.is_published:  # Check the alternate condition.
        status_label = "Draft"  # Store the computed value.
        is_clickable = False  # Store the boolean state.
    elif now < quiz.open_datetime:  # Check the alternate condition.
        status_label = "Not open yet"  # Store the computed value.
        is_clickable = False  # Store the boolean state.
    elif now > quiz.close_datetime:  # Check the alternate condition.
        status_label = "Closed"  # Store the computed value.
        is_clickable = bool(latest_submitted_attempt)  # Store the boolean state.
    elif remaining_attempts > 0:  # Check the alternate condition.
        status_label = "Open"  # Store the computed value.
        is_clickable = True  # Store the boolean state.
    else:  # Handle the fallback case.
        status_label = "Attempts used"  # Store the computed value.
        is_clickable = bool(latest_submitted_attempt)  # Store the boolean state.

    return {  # Return the computed value.
        "active_attempt": active_attempt,  # Set active attempt.
        "latest_submitted_attempt": latest_submitted_attempt,  # Set this mapping value.
        "attempts_used": attempts_used,  # Set attempts used.
        "remaining_attempts": remaining_attempts,  # Set remaining attempts.
        "status_label": status_label,  # Set status label.
        "is_clickable": is_clickable,  # Set is clickable.
    }  # Close the current mapping.


def _build_question_rows(quiz, attempt=None):  # Define _build_question_rows.
    """Build quiz question rows."""
    answer_lookup = {}  # Store the computed value.
    if attempt is not None:  # Check the current condition.
        answer_lookup = {  # Store the computed value.
            answer.question_id: answer  # Continue the current block.
            for answer in attempt.answers.all()  # Iterate through the collection.
        }  # Close the current mapping.

    rows = []  # Build the list values.
    for question_number, question in enumerate(  # Iterate through the collection.
        quiz.questions.prefetch_related("options").all(),  # Prefetch related objects.
        start=1,  # Store the computed value.
    ):  # Continue the current block.
        answer = answer_lookup.get(question.id)  # Fetch a single record.
        selected_option_id = answer.selected_option_id if answer else None  # Store the related id.
        selected_option_ids = set(answer.selected_option_ids or []) if answer else set()  # Store matching ids.

        options = []  # Store the computed value.
        for option in question.options.all():  # Iterate through the collection.
            option_is_selected = (  # Store the computed value.
                option.id == selected_option_id  # Continue the current block.
                or option.id in selected_option_ids  # Continue the current block.
            )  # Close the current call.
            options.append(  # Append to the list.
                {  # Start the current mapping.
                    "id": option.id,  # Set id.
                    "text": option.text,  # Set text.
                    "is_correct": option.is_correct,  # Set is correct.
                    "selected": option_is_selected,  # Set selected.
                }  # Close the current mapping.
            )  # Close the current call.

        selected_texts = [option["text"] for option in options if option["selected"]]  # Store the computed value.
        correct_texts = [option["text"] for option in options if option["is_correct"]]  # Store the computed value.

        rows.append(  # Append to the list.
            {  # Start the current mapping.
                "id": question.id,  # Set id.
                "number": question_number,  # Set number.
                "prompt": question.prompt,  # Set prompt.
                "question_type": question.question_type,  # Set question type.
                "question_type_label": question.get_question_type_display(),  # Set the human-friendly question type label.
                "marks": question.marks,  # Set marks.
                "awarded_marks": answer.awarded_marks if answer else Decimal("0.00"),  # Set awarded marks.
                "options": options,  # Set options.
                "selected_answer_text": ", ".join(selected_texts) if selected_texts else "No answer selected",  # Set this mapping value.
                "correct_answer_text": ", ".join(correct_texts) if correct_texts else "",  # Set this mapping value.
            }  # Close the current mapping.
        )  # Close the current call.

    return rows  # Return the computed value.


def _upsert_attempt_answers(attempt, post_data):  # Define _upsert_attempt_answers.
    """Upsert quiz attempt answers."""
    quiz = attempt.quiz  # Store the computed value.
    questions = quiz.questions.prefetch_related("options").all()  # Prefetch related objects.

    for question in questions:  # Iterate through the collection.
        answer, _ = QuizAnswer.objects.get_or_create(  # Unpack returned values.
            attempt=attempt,  # Store the computed value.
            question=question,  # Store the computed value.
        )  # Close the current call.

        valid_option_ids = {option.id for option in question.options.all()}  # Return all records.

        if question.question_type == QuizQuestion.Type.MULTIPLE_SELECT:  # Check the current condition.
            raw_ids = post_data.getlist(f"question_{question.id}")  # Read repeated form values.
            cleaned_ids = []  # Store matching ids.
            for raw_id in raw_ids:  # Iterate through the collection.
                try:  # Start guarded parsing.
                    option_id = int(raw_id)  # Store the related id.
                except (TypeError, ValueError):  # Handle the raised exception.
                    continue  # Continue to the next item.
                if option_id in valid_option_ids and option_id not in cleaned_ids:  # Check the current condition.
                    cleaned_ids.append(option_id)  # Append to the list.

            answer.selected_option = None  # Store the computed value.
            answer.selected_option_ids = cleaned_ids  # Store matching ids.
            answer.save(update_fields=["selected_option", "selected_option_ids"])  # Save model changes.

        else:  # Handle the fallback case.
            raw_id = (post_data.get(f"question_{question.id}") or "").strip()  # Fetch a single record.
            selected_option = None  # Store the computed value.
            if raw_id:  # Check the current condition.
                try:  # Start guarded parsing.
                    option_id = int(raw_id)  # Store the related id.
                except ValueError:  # Handle the raised exception.
                    option_id = None  # Store the related id.
                if option_id in valid_option_ids:  # Check the current condition.
                    selected_option = question.options.get(pk=option_id)  # Fetch a single record.

            answer.selected_option = selected_option  # Store the computed value.
            answer.selected_option_ids = []  # Store matching ids.
            answer.save(update_fields=["selected_option", "selected_option_ids"])  # Save model changes.


def _grade_attempt(attempt, auto_submitted=False):  # Define _grade_attempt.
    """Grade a quiz attempt."""
    quiz = attempt.quiz  # Store the computed value.
    questions = quiz.questions.prefetch_related("options").all()  # Prefetch related objects.

    was_unsubmitted = attempt.submitted_at is None  # Store the computed value.
    total_raw = Decimal("0.00")  # Store the computed value.
    total_possible = Decimal("0.00")  # Store the computed value.

    for question in questions:  # Iterate through the collection.
        total_possible += question.marks  # Continue the current block.

        answer, _ = QuizAnswer.objects.get_or_create(  # Unpack returned values.
            attempt=attempt,  # Store the computed value.
            question=question,  # Store the computed value.
        )  # Close the current call.

        awarded = Decimal("0.00")  # Store the computed value.
        is_correct = False  # Store the boolean state.
        correct_options = [option for option in question.options.all() if option.is_correct]  # Return all records.

        if question.question_type in {  # Check the current condition.
            QuizQuestion.Type.MULTIPLE_CHOICE,  # Continue the current value.
            QuizQuestion.Type.TRUE_FALSE,  # Continue the current value.
            QuizQuestion.Type.FILL_BLANK,  # Continue the current value.
        }:  # Continue the current block.
            correct_option = correct_options[0] if correct_options else None  # Store the computed value.
            if correct_option and answer.selected_option_id == correct_option.id:  # Check the current condition.
                awarded = question.marks  # Store the computed value.
                is_correct = True  # Store the boolean state.

        elif question.question_type == QuizQuestion.Type.MULTIPLE_SELECT:  # Check the alternate condition.
            correct_ids = {option.id for option in correct_options}  # Store matching ids.
            selected_ids = set(answer.selected_option_ids or [])  # Store matching ids.

            if correct_ids:  # Check the current condition.
                unit_value = question.marks / Decimal(len(correct_ids))  # Store the computed value.
                positives = unit_value * Decimal(len(selected_ids & correct_ids))  # Store the computed value.
                negatives = unit_value * Decimal(len(selected_ids - correct_ids))  # Store the computed value.
                awarded = positives - negatives  # Store the computed value.

                if awarded < Decimal("0.00"):  # Check the current condition.
                    awarded = Decimal("0.00")  # Store the computed value.
                if awarded > question.marks:  # Check the current condition.
                    awarded = question.marks  # Store the computed value.

                is_correct = selected_ids == correct_ids  # Store the boolean state.

        awarded = awarded.quantize(Decimal("0.01"))  # Store the computed value.
        answer.awarded_marks = awarded  # Store the computed value.
        answer.is_correct = is_correct  # Store the boolean state.
        answer.save(update_fields=["awarded_marks", "is_correct"])  # Save model changes.

        total_raw += awarded  # Continue the current block.

    if total_possible > Decimal("0.00"):  # Check the current condition.
        weighted_score = (total_raw / total_possible) * quiz.max_mark  # Store the calculated score.
    else:  # Handle the fallback case.
        weighted_score = Decimal("0.00")  # Store the calculated score.

    attempt.raw_score = total_raw.quantize(Decimal("0.01"))  # Store the calculated score.
    attempt.weighted_score = weighted_score.quantize(Decimal("0.01"))  # Store the calculated score.
    attempt.submitted_at = timezone.now()  # Store the computed value.
    attempt.status = (  # Store the computed value.
        QuizAttempt.Status.AUTO_SUBMITTED  # Continue the current block.
        if auto_submitted  # Check the current condition.
        else QuizAttempt.Status.SUBMITTED  # Continue the current block.
    )  # Close the current call.
    attempt.save(update_fields=["raw_score", "weighted_score", "submitted_at", "status"])  # Save model changes.

    if was_unsubmitted:  # Check the current condition.
        _notify_student_quiz_submitted(attempt)  # Call the helper function.

    return attempt  # Return the computed value.

def _auto_submit_expired_attempt_if_needed(quiz, student):  # Define _auto_submit_expired_attempt_if_needed.
    """Auto-submit an expired attempt when needed."""
    active_attempt = (  # Store the computed value.
        quiz.attempts  # Continue the current block.
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)  # Filter queryset records.
        .order_by("-attempt_number")  # Order queryset results.
        .first()  # Return the first result.
    )  # Close the current call.

    if active_attempt and active_attempt.is_expired():  # Check the current condition.
        _grade_attempt(active_attempt, auto_submitted=True)  # Call the helper function.

    return (  # Return the computed value.
        quiz.attempts  # Continue the current block.
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)  # Filter queryset records.
        .order_by("-attempt_number")  # Order queryset results.
        .first()  # Return the first result.
    )  # Close the current call.

# ===================
# Assessment Builders
# ===================
def _build_student_module_assessment_items(offering, student, now, next_url=None):  # Define _build_student_module_assessment_items.
    """Build student module assessment items."""
    submitted_assignment_ids = set(  # Store matching ids.
        AssignmentSubmission.objects.filter(  # Filter queryset records.
            assignment__offering=offering,  # Store the computed value.
            student=student,  # Store the computed value.
        ).values_list("assignment_id", flat=True)  # Select field values.
    )  # Close the current call.

    items = []  # Store the computed value.

    for assignment in offering.assignments.prefetch_related("files__parsed_document").all():  # Iterate through the collection.
        items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind": "assignment",  # Set kind.
                "label": "Assignment",  # Set label.
                "title": assignment.title,  # Set title.
                "description": assignment.description,  # Set description.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "is_clickable": True,  # Set is clickable.
                "date_label": "Due",  # Set date label.
                "date_value": assignment.due_datetime,  # Set date value.
                "max_mark": assignment.max_mark,  # Set max mark.
                "status_label": "Submitted" if assignment.id in submitted_assignment_ids else "",  # Set status label.
                "detail_line": "",  # Set detail line.
                "file_names": [f.original_name or f.file.name for f in assignment.files.all()],  # Return all records.
                "sort_at": assignment.due_datetime,  # Set sort at.
            }  # Close the current mapping.
        )  # Close the current call.

    for quiz in offering.quizzes.filter(is_published=True).all():  # Iterate through the collection.
        state = _get_student_quiz_state(quiz, student, now=now)  # Store the computed value.
        items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind": "quiz",  # Set kind.
                "label": "Quiz",  # Set label.
                "title": quiz.title,  # Set title.
                "description": quiz.description,  # Set description.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "is_clickable": state["is_clickable"] if not _is_read_only_offering(offering) else True,  # Set is clickable.
                "date_label": "Closes",  # Set date label.
                "date_value": quiz.close_datetime,  # Set date value.
                "max_mark": quiz.max_mark,  # Set max mark.
                "status_label": state["status_label"] if not _is_read_only_offering(offering) else "Closed",  # Set status label.
                "detail_line": f"Time limit: {quiz.time_limit_minutes} mins · Attempts: {state['attempts_used']}/{quiz.max_attempts}",  # Set detail line.
                "file_names": [],  # Set file names.
                "sort_at": quiz.close_datetime,  # Set sort at.
            }  # Close the current mapping.
        )  # Close the current call.

    return sorted(items, key=lambda item: item["sort_at"])  # Return the computed value.

def _build_lecturer_module_assessment_items(offering, next_url=None):  # Define _build_lecturer_module_assessment_items.
    """Build lecturer module assessment items."""
    items = []  # Store the computed value.

    assignments = (  # Store the computed value.
        offering.assignments  # Continue the current block.
        .all()  # Return all records.
        .annotate(  # Add queryset annotations.
            total_submissions=Count("submissions", distinct=True),  # Store the computed value.
            ungraded_submissions=Count(  # Store the computed value.
                "submissions",  # Continue the current value.
                filter=Q(submissions__grade__isnull=True),  # Store the computed value.
                distinct=True,  # Store the computed value.
            ),  # Close the current call.
        )  # Close the current call.
        .prefetch_related("files__parsed_document")  # Prefetch related objects.
    )  # Close the current call.

    for assignment in assignments:  # Iterate through the collection.
        items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind": "assignment",  # Set kind.
                "label": "Assignment",  # Set label.
                "title": assignment.title,  # Set title.
                "description": assignment.description,  # Set description.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "is_clickable": True,  # Set is clickable.
                "date_label": "Due",  # Set date label.
                "date_value": assignment.due_datetime,  # Set date value.
                "max_mark": assignment.max_mark,  # Set max mark.
                "status_label": "",  # Set status label.
                "detail_line": f"Submissions: {assignment.total_submissions} ({assignment.ungraded_submissions} ungraded)",  # Set detail line.
                "file_names": [f.original_name or f.file.name for f in assignment.files.all()],  # Return all records.
                "sort_at": assignment.due_datetime,  # Set sort at.
            }  # Close the current mapping.
        )  # Close the current call.

    quizzes = (  # Store the computed value.
        offering.quizzes  # Continue the current block.
        .all()  # Return all records.
        .annotate(  # Add queryset annotations.
            total_attempts=Count("attempts", distinct=True),  # Store the computed value.
            submitted_attempts=Count(  # Store the computed value.
                "attempts",  # Continue the current value.
                filter=Q(attempts__submitted_at__isnull=False),  # Store the computed value.
                distinct=True,  # Store the computed value.
            ),  # Close the current call.
        )  # Close the current call.
    )  # Close the current call.

    for quiz in quizzes:  # Iterate through the collection.
        items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind": "quiz",  # Set kind.
                "label": "Quiz",  # Set label.
                "title": quiz.title,  # Set title.
                "description": quiz.description,  # Set description.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "is_clickable": True,  # Set is clickable.
                "date_label": "Closes",  # Set date label.
                "date_value": quiz.close_datetime,  # Set date value.
                "max_mark": quiz.max_mark,  # Set max mark.
                "status_label": "Published" if quiz.is_published else "Draft",  # Set status label.
                "detail_line": f"Attempts started: {quiz.total_attempts} · Submitted: {quiz.submitted_attempts}",  # Set detail line.
                "file_names": [],  # Set file names.
                "sort_at": quiz.close_datetime,  # Set sort at.
            }  # Close the current mapping.
        )  # Close the current call.

    return sorted(items, key=lambda item: item["sort_at"])  # Return the computed value.

def _build_student_dashboard_items(student, offerings_qs, now, next_url=None):  # Define _build_student_dashboard_items.
    """Build student dashboard items."""
    items = []  # Store the computed value.

    upcoming_assignments = (  # Store the computed value.
        Assignment.objects.filter(  # Filter queryset records.
            offering__in=offerings_qs,  # Store the computed value.
            due_datetime__gte=now,  # Store the computed value.
        )  # Close the current call.
        .exclude(submissions__student=student)  # Exclude matching records.
        .select_related("offering__module")  # Follow related objects.
        .order_by("due_datetime")  # Order queryset results.
    )  # Close the current call.

    for assignment in upcoming_assignments:  # Iterate through the collection.
        items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind": "assignment",  # Set kind.
                "label": "Assignment",  # Set label.
                "title": assignment.title,  # Set title.
                "description": assignment.description,  # Set description.
                "module_title": assignment.module.title,  # Set module title.
                "module_code": assignment.module.code,  # Set module code.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_assignment_detail", args=[assignment.offering.id, assignment.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "is_clickable": True,  # Set is clickable.
                "date_label": "Due",  # Set date label.
                "date_value": assignment.due_datetime,  # Set date value.
                "max_mark": assignment.max_mark,  # Set max mark.
                "status_label": "",  # Set status label.
                "detail_line": "",  # Set detail line.
                "sort_at": assignment.due_datetime,  # Set sort at.
            }  # Close the current mapping.
        )  # Close the current call.

    candidate_quizzes = (  # Store the computed value.
        Quiz.objects.filter(  # Filter queryset records.
            offering__in=offerings_qs,  # Store the computed value.
            is_published=True,  # Store the boolean state.
            close_datetime__gte=now,  # Store the computed value.
        )  # Close the current call.
        .select_related("offering__module")  # Follow related objects.
        .order_by("close_datetime")  # Order queryset results.
    )  # Close the current call.

    for quiz in candidate_quizzes:  # Iterate through the collection.
        state = _get_student_quiz_state(quiz, student, now=now)  # Store the computed value.

        if state["remaining_attempts"] <= 0 and not state["active_attempt"]:  # Check the current condition.
            continue  # Continue to the next item.

        items.append(  # Append to the list.
            {  # Start the current mapping.
                "kind": "quiz",  # Set kind.
                "label": "Quiz",  # Set label.
                "title": quiz.title,  # Set title.
                "description": quiz.description,  # Set description.
                "module_title": quiz.module.title,  # Set module title.
                "module_code": quiz.module.code,  # Set module code.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_quiz_detail", args=[quiz.offering.id, quiz.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "is_clickable": state["is_clickable"],  # Set is clickable.
                "date_label": "Closes",  # Set date label.
                "date_value": quiz.close_datetime,  # Set date value.
                "max_mark": quiz.max_mark,  # Set max mark.
                "status_label": state["status_label"],  # Set status label.
                "detail_line": f"Time limit: {quiz.time_limit_minutes} mins · Attempts: {state['attempts_used']}/{quiz.max_attempts}",  # Set detail line.
                "sort_at": quiz.close_datetime,  # Set sort at.
            }  # Close the current mapping.
        )  # Close the current call.

    return sorted(items, key=lambda item: item["sort_at"])  # Return the computed value.

def _format_mark_display(value):  # Define _format_mark_display.
    """Format mark display."""
    decimal_value = Decimal(str(value or 0))  # Store the computed value.
    rendered = f"{decimal_value:.2f}"  # Store the computed value.
    return rendered.rstrip("0").rstrip(".") or "0"  # Return the computed value.


def _build_student_profile_modules(offerings_qs, student, next_url=None):  # Define _build_student_profile_modules.
    """Build student profile modules."""
    offerings = list(offerings_qs)  # Store the computed value.

    if not offerings:  # Check the current condition.
        return []  # Return the computed value.

    submitted_assignment_ids = set(  # Store matching ids.
        AssignmentSubmission.objects.filter(  # Filter queryset records.
            student=student,  # Store the computed value.
            assignment__offering__in=offerings_qs,  # Store the computed value.
        ).values_list("assignment_id", flat=True)  # Select field values.
    )  # Close the current call.

    graded_assignment_marks = dict(  # Store the computed value.
        AssignmentGrade.objects.filter(  # Filter queryset records.
            submission__student=student,  # Store the computed value.
            submission__assignment__offering__in=offerings_qs,  # Store the computed value.
        ).values_list("submission__assignment_id", "value")  # Select field values.
    )  # Close the current call.

    best_quiz_attempt_by_quiz = {}  # Store the computed value.
    submitted_quiz_attempts = (  # Store the computed value.
        QuizAttempt.objects.filter(  # Filter queryset records.
            student=student,  # Store the computed value.
            quiz__offering__in=offerings_qs,  # Store the computed value.
            quiz__is_published=True,  # Store the computed value.
            submitted_at__isnull=False,  # Store the computed value.
        )  # Close the current call.
        .select_related("quiz", "quiz__offering__module")  # Follow related objects.
        .order_by("quiz_id", "-weighted_score", "-submitted_at", "-id")  # Order queryset results.
    )  # Close the current call.

    for attempt in submitted_quiz_attempts:  # Iterate through the collection.
        best_quiz_attempt_by_quiz.setdefault(attempt.quiz_id, attempt)  # Create the default mapping.

    module_rows = []  # Build the list values.

    for offering in offerings:  # Iterate through the collection.
        items = []  # Store the computed value.

        assignments = offering.assignments.all().order_by("due_datetime", "title")  # Order queryset results.

        for assignment in assignments:  # Iterate through the collection.
            if assignment.id in graded_assignment_marks:  # Check the current condition.
                metric = (  # Store the computed value.
                    f"{_format_mark_display(graded_assignment_marks[assignment.id])}"  # Continue the current block.
                    f"/{_format_mark_display(assignment.max_mark)}"  # Continue the current block.
                )  # Close the current call.
                metric_class = "profile-metric--complete"  # Store the computed value.
            elif assignment.id in submitted_assignment_ids:  # Check the alternate condition.
                metric = "Pending"  # Store the computed value.
                metric_class = "profile-metric--pending"  # Store the computed value.
            else:  # Handle the fallback case.
                metric = "Not submitted"  # Store the computed value.
                metric_class = "profile-metric--empty"  # Store the computed value.

            items.append(  # Append to the list.
                {  # Start the current mapping.
                    "kind_label": "Assignment",  # Set kind label.
                    "kind_class": "assignment",  # Set kind class.
                    "title": assignment.title,  # Set title.
                    "url": _append_next_param(  # Set url.
                        reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                        next_url,  # Continue the current value.
                    ),  # Close the current call.
                    "metric": metric,  # Set metric.
                    "metric_class": metric_class,  # Set metric class.
                    "sort_at": assignment.due_datetime,  # Set sort at.
                }  # Close the current mapping.
            )  # Close the current call.

        quizzes = offering.quizzes.filter(is_published=True).order_by("close_datetime", "title")  # Filter queryset records.

        for quiz in quizzes:  # Iterate through the collection.
            best_attempt = best_quiz_attempt_by_quiz.get(quiz.id)  # Fetch a single record.

            if best_attempt and _quiz_results_released(quiz):  # Check the current condition.
                metric = (  # Store the computed value.
                    f"{_format_mark_display(best_attempt.weighted_score)}"  # Continue the current block.
                    f"/{_format_mark_display(quiz.max_mark)}"  # Continue the current block.
                )  # Close the current call.
                metric_class = "profile-metric--complete"  # Store the computed value.
            elif best_attempt:  # Check the alternate condition.
                metric = "Awaiting release"  # Store the computed value.
                metric_class = "profile-metric--pending"  # Store the computed value.
            else:  # Handle the fallback case.
                metric = "Not attempted"  # Store the computed value.
                metric_class = "profile-metric--empty"  # Store the computed value.

            items.append(  # Append to the list.
                {  # Start the current mapping.
                    "kind_label": "Quiz",  # Set kind label.
                    "kind_class": "quiz",  # Set kind class.
                    "title": quiz.title,  # Set title.
                    "url": _append_next_param(  # Set url.
                        reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),  # Resolve the named URL.
                        next_url,  # Continue the current value.
                    ),  # Close the current call.
                    "metric": metric,  # Set metric.
                    "metric_class": metric_class,  # Set metric class.
                    "sort_at": quiz.close_datetime,  # Set sort at.
                }  # Close the current mapping.
            )  # Close the current call.

        items.sort(key=lambda item: (item["sort_at"], item["title"]))  # Call the helper function.

        module_rows.append(  # Append to the list.
            {  # Start the current mapping.
                "code": offering.module.code,  # Set code.
                "title": offering.module.title,  # Set title.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_detail", args=[offering.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "academic_year_label": offering.academic_year.label,  # Set this mapping value.
                "items": items,  # Set items.
            }  # Close the current mapping.
        )  # Close the current call.

    return module_rows  # Return the computed value.

def _build_lecturer_profile_modules(offerings_qs, lecturer, next_url=None):  # Define _build_lecturer_profile_modules.
    """Build lecturer profile modules."""
    offerings = list(offerings_qs)  # Store the computed value.

    if not offerings:  # Check the current condition.
        return []  # Return the computed value.

    assignment_submitted_counts = dict(  # Store the computed value.
        AssignmentSubmission.objects.filter(  # Filter queryset records.
            assignment__offering__in=offerings_qs,  # Store the computed value.
        )  # Close the current call.
        .values("assignment_id")  # Select dictionary fields.
        .annotate(submitted_count=Count("student", distinct=True))  # Add queryset annotations.
        .values_list("assignment_id", "submitted_count")  # Select field values.
    )  # Close the current call.

    quiz_attempted_counts = dict(  # Store the computed value.
        QuizAttempt.objects.filter(  # Filter queryset records.
            quiz__offering__in=offerings_qs,  # Store the computed value.
            submitted_at__isnull=False,  # Store the computed value.
        )  # Close the current call.
        .values("quiz_id")  # Select dictionary fields.
        .annotate(attempted_count=Count("student", distinct=True))  # Add queryset annotations.
        .values_list("quiz_id", "attempted_count")  # Select field values.
    )  # Close the current call.

    module_rows = []  # Build the list values.

    for offering in offerings:  # Iterate through the collection.
        total_students = getattr(offering, "student_count", 0) or 0  # Store the computed value.
        items = []  # Store the computed value.

        assignments = offering.assignments.all().order_by("due_datetime", "title")  # Order queryset results.

        for assignment in assignments:  # Iterate through the collection.
            submitted = assignment_submitted_counts.get(assignment.id, 0)  # Fetch a single record.
            unsubmitted = max(total_students - submitted, 0)  # Store the computed value.

            if total_students > 0 and submitted == total_students:  # Check the current condition.
                metric_class = "profile-metric--complete"  # Store the computed value.
            elif submitted > 0:  # Check the alternate condition.
                metric_class = "profile-metric--pending"  # Store the computed value.
            else:  # Handle the fallback case.
                metric_class = "profile-metric--empty"  # Store the computed value.

            items.append(  # Append to the list.
                {  # Start the current mapping.
                    "kind_label": "Assignment",  # Set kind label.
                    "kind_class": "assignment",  # Set kind class.
                    "title": assignment.title,  # Set title.
                    "url": _append_next_param(  # Set url.
                        reverse("accounts:offering_assignment_detail", args=[offering.id, assignment.id]),  # Resolve the named URL.
                        next_url,  # Continue the current value.
                    ),  # Close the current call.
                    "metric": f"{submitted} Submitted / {unsubmitted} Unsubmitted",  # Set metric.
                    "metric_class": metric_class,  # Set metric class.
                    "sort_at": assignment.due_datetime,  # Set sort at.
                }  # Close the current mapping.
            )  # Close the current call.

        quizzes = offering.quizzes.all().order_by("close_datetime", "title")  # Order queryset results.

        for quiz in quizzes:  # Iterate through the collection.
            attempted = quiz_attempted_counts.get(quiz.id, 0)  # Fetch a single record.
            not_attempted = max(total_students - attempted, 0)  # Store the computed value.

            if total_students > 0 and attempted == total_students:  # Check the current condition.
                metric_class = "profile-metric--complete"  # Store the computed value.
            elif attempted > 0:  # Check the alternate condition.
                metric_class = "profile-metric--pending"  # Store the computed value.
            else:  # Handle the fallback case.
                metric_class = "profile-metric--empty"  # Store the computed value.

            items.append(  # Append to the list.
                {  # Start the current mapping.
                    "kind_label": "Quiz",  # Set kind label.
                    "kind_class": "quiz",  # Set kind class.
                    "title": quiz.title,  # Set title.
                    "url": _append_next_param(  # Set url.
                        reverse("accounts:offering_quiz_detail", args=[offering.id, quiz.id]),  # Resolve the named URL.
                        next_url,  # Continue the current value.
                    ),  # Close the current call.
                    "metric": f"{attempted} Attempted / {not_attempted} Not Attempted",  # Set metric.
                    "metric_class": metric_class,  # Set metric class.
                    "sort_at": quiz.close_datetime,  # Set sort at.
                }  # Close the current mapping.
            )  # Close the current call.

        items.sort(key=lambda item: (item["sort_at"], item["title"]))  # Call the helper function.

        module_rows.append(  # Append to the list.
            {  # Start the current mapping.
                "code": offering.module.code,  # Set code.
                "title": offering.module.title,  # Set title.
                "url": _append_next_param(  # Set url.
                    reverse("accounts:offering_detail", args=[offering.id]),  # Resolve the named URL.
                    next_url,  # Continue the current value.
                ),  # Close the current call.
                "academic_year_label": offering.academic_year.label,  # Set this mapping value.
                "student_count": total_students,  # Set student count.
                "items": items,  # Set items.
            }  # Close the current mapping.
        )  # Close the current call.

    return module_rows  # Return the computed value.

# ====================
# Announcement Helpers
# ====================
def _recent_global_announcements():  # Define _recent_global_announcements.
    """Return recent global announcements."""
    return (  # Return the computed value.
        GlobalAnnouncement.objects  # Continue the current block.
        .select_related("created_by")  # Follow related objects.
        .order_by("-created_at", "-id")[:3]  # Order queryset results.
    )  # Close the current call.


def _recent_module_announcements(module):  # Define _recent_module_announcements.
    """Return recent module announcements."""
    return (  # Return the computed value.
        module.module_announcements  # Continue the current block.
        .select_related("created_by")  # Follow related objects.
        .order_by("-created_at", "-id")[:3]  # Order queryset results.
    )  # Close the current call.


def _validate_announcement_form(request):  # Define _validate_announcement_form.
    """Validate announcement form data."""
    title = (request.POST.get("title") or "").strip()  # Fetch a single record.
    content = (request.POST.get("content") or "").strip()  # Fetch a single record.
    errors = []  # Initialise error messages.

    if not title:  # Check the current condition.
        errors.append("Title is required.")  # Append to the list.
    if not content:  # Check the current condition.
        errors.append("Content is required.")  # Append to the list.

    return title, content, errors  # Return the computed value.

# =================
# Upload Validation
# =================
STUDENT_SUBMISSION_ALLOWED_EXTENSIONS = {  # Store the computed value.
    ".pdf",  # Continue the current value.
    ".doc",  # Continue the current value.
    ".docx",  # Continue the current value.
    ".ppt",  # Continue the current value.
    ".pptx",  # Continue the current value.
    ".xls",  # Continue the current value.
    ".xlsx",  # Continue the current value.
    ".csv",  # Continue the current value.
    ".txt",  # Continue the current value.
    ".zip",  # Continue the current value.
    ".7z",  # Continue the current value.
    ".rar",  # Continue the current value.
    ".jpg",  # Continue the current value.
    ".jpeg",  # Continue the current value.
    ".png",  # Continue the current value.
}  # Close the current mapping.

STUDENT_SUBMISSION_BLOCKED_EXTENSIONS = {  # Store the computed value.
    ".html",  # Continue the current value.
    ".htm",  # Continue the current value.
    ".xhtml",  # Continue the current value.
    ".svg",  # Continue the current value.
    ".svgz",  # Continue the current value.
    ".xml",  # Continue the current value.
    ".js",  # Continue the current value.
    ".mjs",  # Continue the current value.
}  # Close the current mapping.

MAX_STUDENT_SUBMISSION_FILE_BYTES = 50 * 1024 * 1024  # 50 MB

def _validate_student_submission_upload(uploaded_file) -> str | None:  # Define _validate_student_submission_upload.
    """Validate a student submission upload."""
    name = getattr(uploaded_file, "name", "") or ""  # Store the computed value.
    _, ext = os.path.splitext(name)  # Unpack returned values.
    ext = ext.lower()  # Normalise text to lowercase.

    size = getattr(uploaded_file, "size", 0) or 0  # Store the computed value.

    if not name:  # Check the current condition.
        return "One of the uploaded files is missing a filename."  # Return the computed value.

    if not ext:  # Check the current condition.
        return f"{name}: File uploads must have a valid extension."  # Return the computed value.

    if ext in STUDENT_SUBMISSION_BLOCKED_EXTENSIONS:  # Check the current condition.
        return f"{name}: This file type is not allowed."  # Return the computed value.

    if ext not in STUDENT_SUBMISSION_ALLOWED_EXTENSIONS:  # Check the current condition.
        return f"{name}: This file type is not allowed."  # Return the computed value.

    if size <= 0:  # Check the current condition.
        return f"{name}: The file is empty."  # Return the computed value.

    if size > MAX_STUDENT_SUBMISSION_FILE_BYTES:  # Check the current condition.
        return f"{name}: The file exceeds the 20 MB upload limit."  # Return the computed value.

    return None  # Return the computed value.

def _safe_back_url(request, fallback_name, *fallback_args):  # Define _safe_back_url.
    """Return a safe back URL."""
    fallback_url = reverse(fallback_name, args=fallback_args)  # Store the resolved URL.

    candidate = request.GET.get("next")  # Fetch a single record.
    if not candidate:  # Check the current condition.
        return fallback_url  # Return the computed value.

    if not url_has_allowed_host_and_scheme(  # Check the current condition.
        candidate,  # Continue the current value.
        allowed_hosts={request.get_host()},  # Store the computed value.
        require_https=request.is_secure(),  # Store the computed value.
    ):  # Continue the current block.
        return fallback_url  # Return the computed value.

    return candidate  # Return the computed value.

def _append_next_param(url, next_url):  # Define _append_next_param.
    """Append a next parameter to a URL."""
    if not next_url:  # Check the current condition.
        return url  # Return the computed value.

    parsed = urlsplit(url)  # Store the computed value.
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))  # Store the computed value.
    query["next"] = next_url  # Continue the current block.

    return urlunsplit(  # Return the computed value.
        (  # Open the current call.
            parsed.scheme,  # Continue the current value.
            parsed.netloc,  # Continue the current value.
            parsed.path,  # Continue the current value.
            urlencode(query, doseq=True),  # Call the helper function.
            parsed.fragment,  # Continue the current value.
        )  # Close the current call.
    )  # Close the current call.


# ==============
# Authentication
# ==============
class LowercaseUsernameAuthenticationForm(AuthenticationForm):  # Define LowercaseUsernameAuthenticationForm.
    """Normalise login usernames to lowercase."""
    error_messages = {  # Store the computed value.
        **AuthenticationForm.error_messages,  # Continue the current value.
        "invalid_login": "Please enter a valid email address and password. Please note that passwords are case-sensitive.",  # Set invalid login.
    }  # Close the current mapping.

    def clean(self):  # Define clean.
        """Validate the model state."""
        username = self.cleaned_data.get("username")  # Fetch a single record.
        if username:  # Check the current condition.
            self.cleaned_data["username"] = username.strip().lower()  # Trim surrounding whitespace.
        return super().clean()  # Return the computed value.

class RoleBasedLoginView(LoginView):  # Role-based login view.
    """Redirect users after login by role."""
    template_name = "accounts/login.html"  # Login template.
    redirect_authenticated_user = True  # Redirect signed-in users.
    authentication_form = LowercaseUsernameAuthenticationForm  # Store the computed value.

    def get_success_url(self):  # Define get_success_url.
        """Return the post-login redirect URL."""
        user: User = self.request.user  # Store the current user.
        if user.is_student():  # Check the current condition.
            return "/student-dashboard/"  # Return the computed value.
        if user.is_lecturer():  # Check the current condition.
            return "/lecturer-dashboard/"  # Return the computed value.
        if user.is_admin():  # Check the current condition.
            return "/admin-dashboard/"  # Return the computed value.
        return "/"  # Fallback URL.


# ============
# Public Views
# ============
def register_student(request):  # Define register_student.
    """Handle student registration."""
    if request.user.is_authenticated:  # Check the current condition.
        return redirect("accounts:dashboard")  # Return the redirect response.

    valid_courses = _get_available_course_codes()  # Store the computed value.
    module_rows = _build_registration_module_rows()  # Build the list values.

    if request.method == "POST":  # Check the current condition.
        first_name = (request.POST.get("first_name") or "").strip()  # Fetch a single record.
        last_name = (request.POST.get("last_name") or "").strip()  # Fetch a single record.
        email = (request.POST.get("email") or "").strip().lower()  # Fetch a single record.
        password1 = request.POST.get("password1") or ""  # Fetch a single record.
        password2 = request.POST.get("password2") or ""  # Fetch a single record.
        course_raw = request.POST.get("course") or ""  # Fetch a single record.
        course = _normalize_course_code(course_raw)  # Store the computed value.
        module_ids = request.POST.getlist("module_ids")  # Read repeated form values.

        errors: dict[str, list[str]] = {}  # Initialise error messages.

        if not first_name:  # Check the current condition.
            errors.setdefault("first_name", []).append("First name is required.")  # Append to the list.
        if not last_name:  # Check the current condition.
            errors.setdefault("last_name", []).append("Surname is required.")  # Append to the list.
        if not email:  # Check the current condition.
            errors.setdefault("email", []).append("Student email is required.")  # Append to the list.
        if not password1 or not password2:  # Check the current condition.
            errors.setdefault("password", []).append("Both password fields are required.")  # Append to the list.
        if not course:  # Check the current condition.
            errors.setdefault("course", []).append("Course code is required.")  # Append to the list.
        elif not COURSE_CODE_RE.match(course):  # Check the alternate condition.
            errors.setdefault("course", []).append(  # Append to the list.
                "Course code must be 3–10 characters and contain only letters / numbers."  # Continue the current block.
            )  # Close the current call.
        if not module_ids:  # Check the current condition.
            errors.setdefault("modules", []).append("Please select at least one module.")  # Append to the list.

        if email and not email.endswith("@mytudublin.ie"):  # Check the current condition.
            errors.setdefault("email", []).append(  # Append to the list.
                "Student email must end with @mytudublin.ie."  # Continue the current block.
            )  # Close the current call.

        if email and User.objects.filter(username__iexact=email).exists():  # Check the current condition.
            errors.setdefault("email", []).append(  # Append to the list.
                "An account already exists for this email address."  # Continue the current block.
            )  # Close the current call.

        if password1 and password2 and password1 != password2:  # Check the current condition.
            errors.setdefault("password", []).append("Passwords do not match.")  # Append to the list.

        candidate_user = User(  # Store the computed value.
            username=email,  # Store the computed value.
            email=email,  # Store the computed value.
            first_name=first_name,  # Store the computed value.
            last_name=last_name,  # Store the computed value.
        )  # Close the current call.

        pw_errors = _validate_password_strength(password1, user=candidate_user)  # Initialise error messages.
        if pw_errors:  # Check the current condition.
            errors.setdefault("password", []).extend(pw_errors)  # Extend the list.

        selected_course = _get_course_by_code(course)  # Store the computed value.

        if not selected_course or course not in valid_courses:  # Check the current condition.
            errors.setdefault("course", []).append(  # Append to the list.
                "Selected course is not recognised for module registration."  # Continue the current block.
            )  # Close the current call.

        valid_module_ids = set(  # Store matching ids.
            ModulePlacement.objects.filter(  # Filter queryset records.
                course__code__iexact=course,  # Store the computed value.
                available_now=True,  # Store the computed value.
                module__is_active=True,  # Store the computed value.
            ).values_list("module_id", flat=True)  # Select field values.
        )  # Close the current call.

        selected_modules = []  # Store the computed value.
        submitted_module_ids: list[int] = []  # Store matching ids.

        if module_ids:  # Check the current condition.
            submitted_module_ids = [  # Store matching ids.
                int(module_id)  # Call the helper function.
                for module_id in module_ids  # Iterate through the collection.
                if str(module_id).isdigit()  # Check the current condition.
            ]  # Close the current list.

            invalid_ids = set(submitted_module_ids) - valid_module_ids  # Store matching ids.
            if invalid_ids or len(submitted_module_ids) != len(module_ids):  # Check the current condition.
                errors.setdefault("modules", []).append(  # Append to the list.
                    "One or more selected modules are invalid for the chosen course."  # Continue the current block.
                )  # Close the current call.
            else:  # Handle the fallback case.
                selected_modules = list(  # Store the computed value.
                    Module.objects.filter(  # Filter queryset records.
                        pk__in=submitted_module_ids,  # Store the computed value.
                        is_active=True,  # Store the boolean state.
                    ).order_by("code")  # Order queryset results.
                )  # Close the current call.

        if errors:  # Check the current condition.
            context = {  # Build template context.
                "errors": errors,  # Set errors.
                "form_data": {  # Set form data.
                    "first_name": first_name,  # Set first name.
                    "last_name": last_name,  # Set last name.
                    "email": email,  # Set email.
                    "course": course,  # Set course.
                    "module_ids": module_ids,  # Set module ids.
                },  # Close the current mapping.
                "valid_courses": valid_courses,  # Set valid courses.
                "module_rows": module_rows,  # Set module rows.
            }  # Close the current mapping.
            return render(request, "accounts/registration.html", context)  # Return the rendered template.

        user = User.objects.create_user(  # Store the current user.
            username=email,  # Store the computed value.
            email=email,  # Store the computed value.
            password=password1,  # Store the computed value.
            first_name=first_name,  # Store the computed value.
            last_name=last_name,  # Store the computed value.
            role=User.Role.STUDENT,  # Store the computed value.
        )  # Close the current call.

        student_number = email.split("@")[0]  # Split the current value.

        student_profile = StudentProfile.objects.create(  # Create a database record.
            user=user,  # Store the current user.
            student_number=student_number,  # Store the computed value.
            course=course,  # Store the computed value.
            status=StudentProfile.Status.ACTIVE,  # Store the computed value.
        )  # Close the current call.

        current_academic_year = _get_current_academic_year()  # Store the computed value.
        if current_academic_year:  # Check the current condition.
            for module in selected_modules:  # Iterate through the collection.
                _sync_student_current_offering_enrolment(  # Open the current call.
                    student_profile,  # Continue the current value.
                    module,  # Continue the current value.
                    academic_year=current_academic_year,  # Store the computed value.
                )  # Close the current call.

        messages.success(  # Queue a success message.
            request,  # Continue the current value.
            "Registration Successful. You can now log in with your student email and password!",  # Continue the current value.
        )  # Close the current call.
        return redirect("accounts:login")  # Return the redirect response.

    context = {  # Build template context.
        "errors": {},  # Set errors.
        "form_data": {},  # Set form data.
        "valid_courses": valid_courses,  # Set valid courses.
        "module_rows": module_rows,  # Set module rows.
    }  # Close the current mapping.
    return render(request, "accounts/registration.html", context)  # Return the rendered template.

@login_required  # Require login.
def student_join_modules(request):  # Define student_join_modules.
    """Handle student module joining."""
    user: User = request.user  # Store the current user.
    if not user.is_student():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    student = user.student_profile  # Store the computed value.
    if student.status != StudentProfile.Status.ACTIVE:  # Check the current condition.
        messages.info(request, "Only active students can join current academic year modules.")  # Queue an info message.
        return redirect("accounts:dashboard")  # Return the redirect response.

    course_code = _normalize_course_code(student.course or "")  # Store the computed value.

    if not _get_course_by_code(course_code):  # Check the current condition.
        messages.error(request, "Your course is not configured yet. Please contact an administrator.")  # Queue an error message.
        return redirect("accounts:dashboard")  # Return the redirect response.

    module_rows = _build_module_selector_rows(course_code=course_code)  # Build the list values.
    module_rows_by_id = {row["id"]: row for row in module_rows}  # Build the value mapping.
    valid_module_ids = {row["id"] for row in module_rows}  # Store matching ids.
    existing_current_ids = _current_module_ids_for_student(student)  # Store matching ids.

    current_module_rows = [  # Build the list values.
        module_rows_by_id[module_id]  # Continue the current value.
        for module_id in sorted(  # Sort the current ids by label.
            existing_current_ids,  # Continue the current value.
            key=lambda module_id: module_rows_by_id.get(module_id, {}).get("label", ""),  # Continue the current value.
        )  # Close the current call.
        if module_id in module_rows_by_id  # Check the current condition.
    ]  # Close the current list.

    if request.method == "POST":  # Check the current condition.
        submitted_ids = {  # Store matching ids.
            int(module_id)  # Call the helper function.
            for module_id in request.POST.getlist("module_ids")  # Iterate through the collection.
            if str(module_id).isdigit()  # Check the current condition.
        }  # Close the current mapping.

        submitted_ids -= existing_current_ids  # Remove already joined modules from the submitted set.

        invalid_ids = submitted_ids - valid_module_ids  # Store matching ids.
        if invalid_ids:  # Check the current condition.
            messages.error(request, "One or more selected modules are not valid for your course.")  # Queue an error message.
            submitted_ids = {  # Store matching ids.
                module_id  # Continue the current value.
                for module_id in submitted_ids  # Iterate through the collection.
                if module_id in valid_module_ids  # Check the current condition.
            }  # Close the current mapping.
        else:  # Handle the fallback case.
            current_academic_year = _get_current_academic_year()  # Store the computed value.

            for module_id in submitted_ids:  # Iterate through the collection.
                module = Module.objects.filter(pk=module_id).first()  # Filter queryset records.
                if module and current_academic_year:  # Check the current condition.
                    _sync_student_current_offering_enrolment(  # Open the current call.
                        student,  # Continue the current value.
                        module,  # Continue the current value.
                        academic_year=current_academic_year,  # Store the computed value.
                    )  # Close the current call.

            newly_added = len(submitted_ids)  # Store the computed value.
            if newly_added:  # Check the current condition.
                messages.success(request, f"{newly_added} module(s) added successfully.")  # Queue a success message.
            else:  # Handle the fallback case.
                messages.info(request, "No new modules were added.")  # Queue an info message.

            return redirect("accounts:student_join_modules")  # Return the redirect response.
    else:  # Handle the fallback case.
        submitted_ids = set()  # Store the computed value.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "student": student,  # Set student.
        "course_code": course_code,  # Set course code.
        "module_rows": module_rows,  # Set module rows.
        "current_module_rows": current_module_rows,  # Set current module rows.
        "current_module_ids": {str(module_id) for module_id in existing_current_ids},  # Set this mapping value.
        "selected_module_ids": {str(module_id) for module_id in submitted_ids},  # Set this mapping value.
    }  # Close the current mapping.
    return render(request, "accounts/student_join_modules.html", context)  # Return the rendered template.

@login_required  # Require login.
def dashboard(request):  # Define dashboard.
    """Handle the dashboard view."""
    user: User = request.user  # Store the current user.

    if user.is_admin():  # Check the current condition.
        return redirect("accounts:admin_dashboard")  # Return the redirect response.

    nav_items = _shared_nav_items()  # Build the list values.
    now = timezone.now()  # Store the computed value.

    if user.is_student():  # Check the current condition.
        template = "accounts/student_dashboard.html"  # Store the computed value.
        student = user.student_profile  # Store the computed value.

        current_offerings = _current_offering_queryset_for_student(student)  # Store the computed value.

        upcoming_items = _build_student_dashboard_items(  # Build the list values.
            student,  # Continue the current value.
            current_offerings,  # Continue the current value.
            now,  # Continue the current value.
            request.get_full_path(),  # Call the helper function.
        )  # Close the current call.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": nav_items,  # Set nav items.
            "current_module_rows": _build_student_dashboard_module_rows(  # Set this mapping value.
                current_offerings,  # Continue the current value.
                request.get_full_path(),  # Call the helper function.
            ),  # Close the current call.
            "previous_year_groups": _build_previous_student_dashboard_year_groups(  # Set this mapping value.
                student,  # Continue the current value.
                request.get_full_path(),  # Call the helper function.
            ),  # Close the current call.
            "upcoming_items": upcoming_items,  # Set upcoming items.
            "global_announcements": _recent_global_announcements(),  # Set this mapping value.
        }  # Close the current mapping.

    elif user.is_lecturer():  # Check the alternate condition.
        template = "accounts/lecturer_dashboard.html"  # Store the computed value.
        lecturer = user.lecturer_profile  # Store the computed value.

        current_offerings = _current_offering_queryset_for_lecturer(lecturer)  # Store the computed value.

        ungraded_submissions_qs = (  # Initialise the queryset.
            AssignmentSubmission.objects.filter(  # Filter queryset records.
                assignment__offering__in=current_offerings,  # Store the computed value.
                grade__isnull=True,  # Store the computed value.
            )  # Close the current call.
            .select_related(  # Follow related objects.
                "assignment",  # Continue the current value.
                "assignment__offering__module",  # Continue the current value.
                "student",  # Continue the current value.
                "student__user",  # Continue the current value.
            )  # Close the current call.
            .order_by("-submitted_at")[:10]  # Order queryset results.
        )  # Close the current call.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": nav_items,  # Set nav items.
            "current_module_rows": _build_lecturer_dashboard_module_rows(  # Set this mapping value.
                current_offerings,  # Continue the current value.
                request.get_full_path(),  # Call the helper function.
            ),  # Close the current call.
            "previous_year_groups": _build_previous_lecturer_dashboard_year_groups(  # Set this mapping value.
                lecturer,  # Continue the current value.
                request.get_full_path(),  # Call the helper function.
            ),  # Close the current call.
            "ungraded_submissions": ungraded_submissions_qs,  # Set this mapping value.
            "global_announcements": _recent_global_announcements(),  # Set this mapping value.
        }  # Close the current mapping.

    else:  # Handle the fallback case.
        return redirect("accounts:login")  # Return the redirect response.

    return render(request, template, context)  # Return the rendered template.

# ===========
# Admin Views
# ===========
@login_required  # Require login.
def admin_dashboard(request):  # Define admin_dashboard.
    """Handle the admin dashboard view."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    current_academic_year = _get_current_academic_year()  # Store the computed value.

    context = _admin_page_context(user, "Admin Dashboard")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "total_students": StudentProfile.objects.count(),  # Count matching records.
            "total_lecturers": LecturerProfile.objects.count(),  # Count matching records.
            "total_modules": Module.objects.count(),  # Count matching records.
            "total_courses": Course.objects.count(),  # Count matching records.
            "current_academic_year": current_academic_year,  # Set this mapping value.
            "recent_global_announcements": _recent_global_announcements(),  # Set this mapping value.
            "monitoring_url": os.environ.get("EAGNA_MONITORING_URL", "").strip(),  # Fetch a single record.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_dashboard.html", context)  # Return the rendered template.


@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_add_lecturer(request):  # Define admin_add_lecturer.
    """Handle admin add lecturer."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        first_name = (request.POST.get("first_name") or "").strip()  # Fetch a single record.
        last_name = (request.POST.get("last_name") or "").strip()  # Fetch a single record.
        email = (request.POST.get("email") or "").strip().lower()  # Fetch a single record.
        staff_id = (request.POST.get("staff_id") or "").strip()  # Fetch a single record.
        password1 = request.POST.get("password1") or ""  # Fetch a single record.
        password2 = request.POST.get("password2") or ""  # Fetch a single record.

        if not first_name:  # Check the current condition.
            errors.append("First name is required.")  # Append to the list.
        if not last_name:  # Check the current condition.
            errors.append("Surname is required.")  # Append to the list.
        if not email or "@" not in email:  # Check the current condition.
            errors.append("A valid email is required.")  # Append to the list.
        if not staff_id:  # Check the current condition.
            errors.append("Staff ID is required.")  # Append to the list.
        if not password1 or not password2:  # Check the current condition.
            errors.append("Both password fields are required.")  # Append to the list.
        if password1 and password2 and password1 != password2:  # Check the current condition.
            errors.append("Passwords do not match.")  # Append to the list.

        candidate_user = User(  # Store the computed value.
            username=email,  # Store the computed value.
            email=email,  # Store the computed value.
            first_name=first_name,  # Store the computed value.
            last_name=last_name,  # Store the computed value.
        )  # Close the current call.

        password_errors = _validate_password_strength(password1, user=candidate_user)  # Initialise error messages.
        if password_errors:  # Check the current condition.
            errors.extend(password_errors)  # Extend the list.

        if email and User.objects.filter(username__iexact=email).exists():  # Check the current condition.
            errors.append("A user already exists with this email address.")  # Append to the list.

        if staff_id and LecturerProfile.objects.filter(staff_id__iexact=staff_id).exists():  # Check the current condition.
            errors.append("A lecturer already exists with this staff ID.")  # Append to the list.

        if not errors:  # Check the current condition.
            lecturer_user = User.objects.create_user(  # Store the computed value.
                username=email,  # Store the computed value.
                email=email,  # Store the computed value.
                password=password1,  # Store the computed value.
                first_name=first_name,  # Store the computed value.
                last_name=last_name,  # Store the computed value.
                role=User.Role.LECTURER,  # Store the computed value.
            )  # Close the current call.

            LecturerProfile.objects.create(  # Create a database record.
                user=lecturer_user,  # Store the current user.
                staff_id=staff_id,  # Store the related id.
            )  # Close the current call.

            messages.success(request, "Lecturer account created successfully.")  # Queue a success message.
            return redirect("accounts:admin_dashboard")  # Return the redirect response.

    context = _admin_page_context(user, "Add Lecturer")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "errors": errors,  # Set errors.
            "initial": {  # Set initial.
                "first_name": request.POST.get("first_name", ""),  # Fetch a single record.
                "last_name": request.POST.get("last_name", ""),  # Fetch a single record.
                "email": request.POST.get("email", ""),  # Fetch a single record.
                "staff_id": request.POST.get("staff_id", ""),  # Fetch a single record.
            },  # Close the current mapping.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_add_lecturer.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_manage_student_account(request):  # Define admin_manage_student_account.
    """Handle admin manage student account."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    if request.method == "POST":  # Check the current condition.
        action = (request.POST.get("action") or "").strip()  # Fetch a single record.
        student = get_object_or_404(  # Store the computed value.
            StudentProfile.objects.select_related("user"),  # Follow related objects.
            pk=request.POST.get("student_id"),  # Fetch a single record.
        )  # Close the current call.

        if action == "lock_student":  # Check the current condition.
            student.status = StudentProfile.Status.LOCKED  # Store the computed value.
            student.save(update_fields=["status"])  # Save model changes.

            student.user.is_active = False  # Store the boolean state.
            student.user.save(update_fields=["is_active"])  # Save model changes.

            messages.success(  # Queue a success message.
                request,  # Continue the current value.
                f"Locked {student.user.get_full_name() or student.user.username}.",  # Continue the current value.
            )  # Close the current call.

        elif action == "unlock_student":  # Check the alternate condition.
            restored_status = _derived_student_status_after_unlock(student)  # Store the computed value.
            student.status = restored_status  # Store the computed value.
            student.save(update_fields=["status"])  # Save model changes.

            student.user.is_active = True  # Store the boolean state.
            student.user.save(update_fields=["is_active"])  # Save model changes.

            messages.success(  # Queue a success message.
                request,  # Continue the current value.
                f"Unlocked {student.user.get_full_name() or student.user.username} and restored status to {student.get_status_display()}.",  # Continue the current value.
            )  # Close the current call.

        else:  # Handle the fallback case.
            messages.error(request, "Unknown student account action.")  # Queue an error message.

        return _redirect_with_query(  # Return the computed value.
            "accounts:admin_manage_student_account",  # Continue the current value.
            username=student.user.username,  # Store the computed value.
        )  # Close the current call.

    username = (request.GET.get("username") or "").strip()  # Fetch a single record.
    student = _get_student_by_username(username) if username else None  # Store the computed value.
    search_error = ""  # Store the computed value.
    if username and not student:  # Check the current condition.
        search_error = "No student account was found for that username."  # Store the computed value.

    context = _admin_page_context(user, "Manage Student Account")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "username_query": username,  # Set username query.
            "student_result": student,  # Set student result.
            "search_error": search_error,  # Set search error.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_manage_student_account.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_manage_lecturer_account(request):  # Define admin_manage_lecturer_account.
    """Handle admin manage lecturer account."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    if request.method == "POST":  # Check the current condition.
        action = (request.POST.get("action") or "").strip()  # Fetch a single record.
        lecturer = get_object_or_404(  # Store the computed value.
            LecturerProfile.objects.select_related("user"),  # Follow related objects.
            pk=request.POST.get("lecturer_id"),  # Fetch a single record.
        )  # Close the current call.

        if action == "lock_lecturer":  # Check the current condition.
            lecturer.user.is_active = False  # Store the boolean state.
            lecturer.user.save(update_fields=["is_active"])  # Save model changes.
            messages.success(  # Queue a success message.
                request,  # Continue the current value.
                f"Locked {lecturer.user.get_full_name() or lecturer.user.username}.",  # Continue the current value.
            )  # Close the current call.

        elif action == "unlock_lecturer":  # Check the alternate condition.
            lecturer.user.is_active = True  # Store the boolean state.
            lecturer.user.save(update_fields=["is_active"])  # Save model changes.
            messages.success(  # Queue a success message.
                request,  # Continue the current value.
                f"Unlocked {lecturer.user.get_full_name() or lecturer.user.username}.",  # Continue the current value.
            )  # Close the current call.

        else:  # Handle the fallback case.
            messages.error(request, "Unknown lecturer account action.")  # Queue an error message.

        return _redirect_with_query(  # Return the computed value.
            "accounts:admin_manage_lecturer_account",  # Continue the current value.
            username=lecturer.user.username,  # Store the computed value.
        )  # Close the current call.

    username = (request.GET.get("username") or "").strip()  # Fetch a single record.
    lecturer = _get_lecturer_by_username(username) if username else None  # Store the computed value.
    search_error = ""  # Store the computed value.
    if username and not lecturer:  # Check the current condition.
        search_error = "No lecturer account was found for that username."  # Store the computed value.

    context = _admin_page_context(user, "Manage Lecturer Account")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "username_query": username,  # Set username query.
            "lecturer_result": lecturer,  # Set lecturer result.
            "search_error": search_error,  # Set search error.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_manage_lecturer_account.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_add_course(request):  # Define admin_add_course.
    """Handle admin add course."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        code = _normalize_course_code(request.POST.get("code", ""))  # Fetch a single record.
        title = (request.POST.get("title") or "").strip()  # Fetch a single record.
        length_years_raw = (request.POST.get("length_years") or "").strip()  # Fetch a single record.
        is_active = request.POST.get("is_active") == "on"  # Fetch a single record.

        if not code:  # Check the current condition.
            errors.append("Course code is required.")  # Append to the list.
        elif not COURSE_CODE_RE.match(code):  # Check the alternate condition.
            errors.append("Course code must be 3–10 characters and contain only letters / numbers.")  # Append to the list.
        elif Course.objects.filter(code__iexact=code).exists():  # Check the alternate condition.
            errors.append("A course with this code already exists.")  # Append to the list.

        if not title:  # Check the current condition.
            errors.append("Course title is required.")  # Append to the list.

        try:  # Start guarded parsing.
            length_years = int(length_years_raw or "0")  # Store the computed value.
        except ValueError:  # Handle the raised exception.
            length_years = 0  # Store the computed value.

        if length_years < 1:  # Check the current condition.
            errors.append("Course length must be at least 1 year.")  # Append to the list.

        if not errors:  # Check the current condition.
            Course.objects.create(  # Create a database record.
                code=code,  # Store the computed value.
                title=title,  # Store the computed value.
                length_years=length_years,  # Store the computed value.
                is_active=is_active,  # Store the boolean state.
            )  # Close the current call.
            messages.success(request, "Course created successfully.")  # Queue a success message.
            return redirect("accounts:admin_dashboard")  # Return the redirect response.

    context = _admin_page_context(user, "Add Course")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "errors": errors,  # Set errors.
            "initial": {  # Set initial.
                "code": request.POST.get("code", ""),  # Fetch a single record.
                "title": request.POST.get("title", ""),  # Fetch a single record.
                "length_years": request.POST.get("length_years", "4"),  # Fetch a single record.
                "is_active": (request.POST.get("is_active") == "on") if request.method == "POST" else True,  # Fetch a single record.
            },  # Close the current mapping.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_add_course.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_manage_academic_year(request):  # Define admin_manage_academic_year.

    # Get the currently logged-in user
    """Handle admin manage academic year."""
    user: User = request.user  # Store the current user.
    # Stop access unless the user is an administrator
    _require_admin_user(user)  # Call the helper function.

    current_year = _get_current_academic_year() # Fetch the current academic year if one exists
    errors = [] # Collect validation errors for display
    confirm_rollover = request.GET.get("confirm_rollover") == "1" # Check whether the rollover confirmation flag was passed in the query string
    next_year_preview = _build_next_academic_year_window(current_year) if current_year else None  # Build a preview of the next academic year if a current year exists

    # Handle submitted admin actions
    if request.method == "POST":  # Check the current condition.

        # Read which action the admin requested from the submitted form data
        action = (request.POST.get("action") or "").strip()  # Fetch a single record.

        if action == "set_current_year":  # Check the current condition.
            start_date_raw = (request.POST.get("start_date") or "").strip()  # Fetch a single record.
            end_date_raw = (request.POST.get("end_date") or "").strip()  # Fetch a single record.

            start_date_value = None  # Store the computed value.
            end_date_value = None  # Store the computed value.

            try:  # Start guarded parsing.
                start_date_value = date.fromisoformat(start_date_raw)  # Store the computed value.
            except ValueError:  # Handle the raised exception.
                errors.append("Start date is invalid.")  # Append to the list.

            try:  # Start guarded parsing.
                end_date_value = date.fromisoformat(end_date_raw)  # Store the computed value.
            except ValueError:  # Handle the raised exception.
                errors.append("End date is invalid.")  # Append to the list.

            if start_date_value and end_date_value and start_date_value >= end_date_value:  # Check the current condition.
                errors.append("End date must be after the start date.")  # Append to the list.

            if not errors:  # Check the current condition.
                label = _build_academic_year_label(start_date_value, end_date_value)  # Store the computed value.

                AcademicYear.objects.filter(is_current=True).update(is_current=False)  # Filter queryset records.

                academic_year, created = AcademicYear.objects.get_or_create(  # Unpack returned values.
                    label=label,  # Store the computed value.
                    defaults={  # Store the computed value.
                        "start_date": start_date_value,  # Set start date.
                        "end_date": end_date_value,  # Set end date.
                        "is_current": True,  # Set is current.
                    },  # Close the current mapping.
                )  # Close the current call.

                if not created:  # Check the current condition.
                    academic_year.start_date = start_date_value  # Store the parsed date.
                    academic_year.end_date = end_date_value  # Store the parsed date.
                    academic_year.is_current = True  # Store the boolean state.
                    academic_year.save(update_fields=["start_date", "end_date", "is_current"])  # Save model changes.

                created_offerings = _sync_current_module_offerings(academic_year)  # Store the computed value.
                messages.success(  # Queue a success message.
                    request,  # Continue the current value.
                    f"Current academic year set to {academic_year.label}. "  # Continue the current block.
                    f"Offerings created: {created_offerings}."  # Continue the current block.
                )  # Close the current call.
                return redirect("accounts:admin_manage_academic_year")  # Return the redirect response.

        elif action == "sync_current_year":  # Check the alternate condition.
            if not current_year:  # Check the current condition.
                messages.error(request, "There is no current academic year to sync.")  # Queue an error message.
                return redirect("accounts:admin_manage_academic_year")  # Return the redirect response.

            created_offerings = _sync_current_module_offerings(current_year)  # Store the computed value.

            messages.success(  # Queue a success message.
                request,  # Continue the current value.
                f"Synchronized {current_year.label}. "  # Continue the current block.
                f"Offerings created: {created_offerings}."  # Continue the current block.
            )  # Close the current call.
            return redirect("accounts:admin_manage_academic_year")  # Return the redirect response.

        # Admin wants to perform the full rollover into a new year
        elif action == "start_new_academic_year":  # Check the alternate condition.

            # Prevent rollover if there is no active current year
            if not current_year:  # Check the current condition.
                messages.error(request, "You must set a current academic year before starting a new one.")  # Queue an error message.
                return redirect("accounts:admin_manage_academic_year")  # Return the redirect response.

            # Run the rollover process and collect summary counts
            summary = _start_new_academic_year_transition(current_year)  # Store the computed value.

            # Show the rollover outcome in one success message
            messages.success(  # Queue a success message.
                request,  # Continue the current value.
                f"Started New Academic Year {summary['next_year'].label}. "  # Continue the current block.
                f"Placement Availability Updated: {summary['placement_updates']}. "  # Continue the current block.
                f"Offerings Created: {summary['created_offerings']}. "  # Continue the current block.
                f"Lecturers Re-Enrolled: {summary['copied_lecturers']}."  # Continue the current block.
            )  # Close the current call.
            return redirect("accounts:admin_manage_academic_year")  # Redirect back to the admin management page

        else:  # Handle the fallback case.
            messages.error(request, "Unknown academic year action.")  # Queue an error message.
            return redirect("accounts:admin_manage_academic_year")  # Return the redirect response.

    current_year = _get_current_academic_year()  # Store the computed value.

    offering_count = (  # Store the item count.
        ModuleOffering.objects.filter(academic_year=current_year).count()  # Filter queryset records.
        if current_year else 0  # Check the current condition.
    )  # Close the current call.
    student_enrolment_count = (  # Store the item count.
        ModuleOfferingEnrollmentStudent.objects.filter(offering__academic_year=current_year).count()  # Filter queryset records.
        if current_year else 0  # Check the current condition.
    )  # Close the current call.
    lecturer_enrolment_count = (  # Store the item count.
        ModuleOfferingEnrollmentLecturer.objects.filter(offering__academic_year=current_year).count()  # Filter queryset records.
        if current_year else 0  # Check the current condition.
    )  # Close the current call.

    context = _admin_page_context(user, "Manage Academic Year")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "errors": errors,  # Set errors.
            "current_academic_year": current_year,  # Set this mapping value.
            "offering_count": offering_count,  # Set offering count.
            "student_offering_enrolment_count": student_enrolment_count,  # Set this mapping value.
            "lecturer_offering_enrolment_count": lecturer_enrolment_count,  # Set this mapping value.
            "confirm_rollover": confirm_rollover,  # Set confirm rollover.
            "next_year_preview": next_year_preview,  # Set next year preview.
            "initial": {  # Set initial.
                "start_date": request.POST.get("start_date", ""),  # Fetch a single record.
                "end_date": request.POST.get("end_date", ""),  # Fetch a single record.
            },  # Close the current mapping.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_manage_academic_year.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_add_module(request):  # Define admin_add_module.
    """Handle admin add module."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        code = _normalize_course_code(request.POST.get("code", ""))  # Fetch a single record.
        title = (request.POST.get("title") or "").strip()  # Fetch a single record.
        placements_raw = request.POST.get("placements", "")  # Fetch a single record.
        is_active = request.POST.get("is_active") == "on"  # Fetch a single record.
        available_now = request.POST.get("available_now") == "on"  # Fetch a single record.
        available_next_rollover = request.POST.get("available_next_rollover") == "on"  # Fetch a single record.

        if not code:  # Check the current condition.
            errors.append("Module code is required.")  # Append to the list.
        elif Module.objects.filter(code__iexact=code).exists():  # Check the alternate condition.
            errors.append("A module with this code already exists.")  # Append to the list.

        if not title:  # Check the current condition.
            errors.append("Module title is required.")  # Append to the list.

        parsed_courses = _parse_module_course_lines(placements_raw, errors)  # Store the computed value.

        if not errors:  # Check the current condition.
            module = Module.objects.create(  # Create a database record.
                code=code,  # Store the computed value.
                title=title,  # Store the computed value.
                is_active=is_active,  # Store the boolean state.
            )  # Close the current call.

            for course in parsed_courses:  # Iterate through the collection.
                ModulePlacement.objects.create(  # Create a database record.
                    module=module,  # Store the computed value.
                    course=course,  # Store the computed value.
                    available_now=available_now,  # Store the computed value.
                    available_next_rollover=available_next_rollover,  # Store the computed value.
                )  # Close the current call.

            current_academic_year = _get_current_academic_year()  # Store the computed value.
            if current_academic_year and available_now:  # Check the current condition.
                _ensure_module_offering_for_module(module, current_academic_year)  # Call the helper function.

            messages.success(request, "Module created successfully.")  # Queue a success message.
            return redirect("accounts:admin_dashboard")  # Return the redirect response.

    context = _admin_page_context(user, "Add Module")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "errors": errors,  # Set errors.
            "initial": {  # Set initial.
                "code": request.POST.get("code", ""),  # Fetch a single record.
                "title": request.POST.get("title", ""),  # Fetch a single record.
                "placements": request.POST.get("placements", ""),  # Fetch a single record.
                "is_active": (request.POST.get("is_active") == "on") if request.method == "POST" else True,  # Fetch a single record.
                "available_now": (request.POST.get("available_now") == "on") if request.method == "POST" else True,  # Fetch a single record.
                "available_next_rollover": (request.POST.get("available_next_rollover") == "on") if request.method == "POST" else True,  # Fetch a single record.
            },  # Close the current mapping.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_add_module.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_retire_module(request):  # Define admin_retire_module.
    """Handle admin retire module."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    module_query = (request.GET.get("module_query") or request.POST.get("module_query") or "").strip()  # Fetch a single record.
    selected_module_id = request.GET.get("module_id") or request.POST.get("module_id") or ""  # Fetch a single record.

    search_results = _search_modules_for_admin(module_query) if module_query else Module.objects.none()  # Return no records.
    selected_module = None  # Store the computed value.
    selected_summary = None  # Store the computed value.
    errors = []  # Initialise error messages.

    if selected_module_id and str(selected_module_id).isdigit():  # Check the current condition.
        selected_module = Module.objects.filter(pk=selected_module_id).first()  # Filter queryset records.
        if selected_module:  # Check the current condition.
            selected_summary = _build_module_retire_summary(selected_module)  # Store the computed value.

    if request.method == "POST":  # Check the current condition.
        action = (request.POST.get("action") or "").strip()  # Fetch a single record.

        if action == "retire_module":  # Check the current condition.
            if not selected_module:  # Check the current condition.
                errors.append("Please select a valid module first.")  # Append to the list.
            else:  # Handle the fallback case.
                retire_now = request.POST.get("retire_now") == "on"  # Fetch a single record.
                retire_next_rollover = request.POST.get("retire_next_rollover") == "on"  # Fetch a single record.

                if not retire_now and not retire_next_rollover:  # Check the current condition.
                    errors.append("Choose at least one retirement option.")  # Append to the list.

                if not errors:  # Check the current condition.
                    placements_qs = ModulePlacement.objects.filter(module=selected_module)  # Filter queryset records.
                    current_year = _get_current_academic_year()  # Store the computed value.

                    placements_now_updated = 0  # Store the computed value.
                    placements_next_updated = 0  # Store the computed value.
                    archived_offerings = 0  # Store the computed value.

                    with transaction.atomic():  # Open the resource safely.
                        if retire_now:  # Check the current condition.
                            placements_now_updated = placements_qs.filter(available_now=True).update(  # Filter queryset records.
                                available_now=False  # Store the computed value.
                            )  # Close the current call.

                            if current_year:  # Check the current condition.
                                _sync_current_module_offerings(current_year)  # Call the helper function.

                                archived_offerings = ModuleOffering.objects.filter(  # Filter queryset records.
                                    module=selected_module,  # Store the computed value.
                                    academic_year=current_year,  # Store the computed value.
                                    is_current=True,  # Store the boolean state.
                                ).update(  # Bulk update matching records.
                                    is_current=False,  # Store the boolean state.
                                    is_read_only=True,  # Store the boolean state.
                                )  # Close the current call.

                        if retire_next_rollover:  # Check the current condition.
                            placements_next_updated = placements_qs.filter(  # Filter queryset records.
                                available_next_rollover=True  # Store the computed value.
                            ).update(available_next_rollover=False)  # Bulk update matching records.

                    messages.success(  # Queue a success message.
                        request,  # Continue the current value.
                        f"Updated {selected_module.code}. "  # Continue the current block.
                        f"Placements unavailable now: {placements_now_updated}. "  # Continue the current block.
                        f"Placements unavailable next rollover: {placements_next_updated}. "  # Continue the current block.
                        f"Current offerings archived: {archived_offerings}."  # Continue the current block.
                    )  # Close the current call.

                    return _redirect_with_query(  # Return the computed value.
                        "accounts:admin_retire_module",  # Continue the current value.
                        module_query=module_query,  # Store the computed value.
                        module_id=selected_module.id,  # Store the related id.
                    )  # Close the current call.

    context = _admin_page_context(user, "Retire Module")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "module_query": module_query,  # Set module query.
            "search_results": search_results,  # Set search results.
            "selected_module": selected_module,  # Set selected module.
            "selected_summary": selected_summary,  # Set selected summary.
            "errors": errors,  # Set errors.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_retire_module.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_edit_enrollment(request):  # Define admin_edit_enrollment.
    """Handle admin edit enrollment."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    if request.method == "POST":  # Check the current condition.
        action = (request.POST.get("action") or "").strip()  # Fetch a single record.

        if action == "add_student":  # Check the current condition.
            student = get_object_or_404(StudentProfile, pk=request.POST.get("student_id"))  # Fetch a single record.
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))  # Fetch a single record.

            valid_ids = set(_build_addable_modules_for_student(student).values_list("id", flat=True))  # Select field values.
            if module.id not in valid_ids:  # Check the current condition.
                messages.error(request, "That module cannot be added for this student.")  # Queue an error message.
            else:  # Handle the fallback case.
                current_academic_year = _get_current_academic_year()  # Store the computed value.
                created = False  # Store the computed value.

                if current_academic_year:  # Check the current condition.
                    created = _sync_student_current_offering_enrolment(  # Store the computed value.
                        student,  # Continue the current value.
                        module,  # Continue the current value.
                        academic_year=current_academic_year,  # Store the computed value.
                    )  # Close the current call.

                if created:  # Check the current condition.
                    messages.success(  # Queue a success message.
                        request,  # Continue the current value.
                        f"Added {student.user.get_full_name() or student.user.username} to {module.code}.",  # Continue the current value.
                    )  # Close the current call.
                else:  # Handle the fallback case.
                    messages.info(request, "That student is already enrolled in this module.")  # Queue an info message.

            return _redirect_with_query(  # Return the computed value.
                "accounts:admin_edit_enrollment",  # Continue the current value.
                add_student_username=student.user.username,  # Store the computed value.
            )  # Close the current call.

        elif action == "remove_student":  # Check the alternate condition.
            student = get_object_or_404(StudentProfile, pk=request.POST.get("student_id"))  # Fetch a single record.
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))  # Fetch a single record.

            valid_ids = set(_build_removable_modules_for_student(student).values_list("id", flat=True))  # Select field values.
            if module.id not in valid_ids:  # Check the current condition.
                messages.error(request, "That module is not currently enrolled for this student.")  # Queue an error message.
            else:  # Handle the fallback case.
                current_academic_year = _get_current_academic_year()  # Store the computed value.
                deleted = 0  # Store the computed value.

                if current_academic_year:  # Check the current condition.
                    deleted = _remove_student_current_offering_enrolment(  # Store the computed value.
                        student,  # Continue the current value.
                        module,  # Continue the current value.
                        academic_year=current_academic_year,  # Store the computed value.
                    )  # Close the current call.

                if deleted:  # Check the current condition.
                    messages.success(  # Queue a success message.
                        request,  # Continue the current value.
                        f"Removed {student.user.get_full_name() or student.user.username} from {module.code}.",  # Continue the current value.
                    )  # Close the current call.
                else:  # Handle the fallback case.
                    messages.info(request, "That student was not enrolled in this module.")  # Queue an info message.

            return _redirect_with_query(  # Return the computed value.
                "accounts:admin_edit_enrollment",  # Continue the current value.
                remove_student_username=student.user.username,  # Store the computed value.
            )  # Close the current call.

        elif action == "add_lecturer":  # Check the alternate condition.
            lecturer = get_object_or_404(LecturerProfile, pk=request.POST.get("lecturer_id"))  # Fetch a single record.
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))  # Fetch a single record.

            valid_ids = set(_build_addable_modules_for_lecturer(lecturer).values_list("id", flat=True))  # Select field values.
            if module.id not in valid_ids:  # Check the current condition.
                messages.error(request, "That module cannot be added for this lecturer.")  # Queue an error message.
            else:  # Handle the fallback case.
                current_academic_year = _get_current_academic_year()  # Store the computed value.
                created_count = 0  # Store the item count.

                if current_academic_year:  # Check the current condition.
                    created_count = _sync_lecturer_current_offering_enrolment(  # Store the item count.
                        lecturer,  # Continue the current value.
                        module,  # Continue the current value.
                        academic_year=current_academic_year,  # Store the computed value.
                    )  # Close the current call.

                if created_count:  # Check the current condition.
                    messages.success(  # Queue a success message.
                        request,  # Continue the current value.
                        f"Added {lecturer.user.get_full_name() or lecturer.user.username} to {module.code}.",  # Continue the current value.
                    )  # Close the current call.
                else:  # Handle the fallback case.
                    messages.info(request, "That lecturer is already enrolled in this module.")  # Queue an info message.

            return _redirect_with_query(  # Return the computed value.
                "accounts:admin_edit_enrollment",  # Continue the current value.
                add_lecturer_username=lecturer.user.username,  # Store the computed value.
            )  # Close the current call.

        elif action == "remove_lecturer":  # Check the alternate condition.
            lecturer = get_object_or_404(LecturerProfile, pk=request.POST.get("lecturer_id"))  # Fetch a single record.
            module = get_object_or_404(Module, pk=request.POST.get("module_id"))  # Fetch a single record.

            valid_ids = set(_build_removable_modules_for_lecturer(lecturer).values_list("id", flat=True))  # Select field values.
            if module.id not in valid_ids:  # Check the current condition.
                messages.error(request, "That module is not currently assigned to this lecturer.")  # Queue an error message.
            else:  # Handle the fallback case.
                current_academic_year = _get_current_academic_year()  # Store the computed value.
                deleted = 0  # Store the computed value.

                if current_academic_year:  # Check the current condition.
                    deleted = _remove_lecturer_current_offering_enrolment(  # Store the computed value.
                        lecturer,  # Continue the current value.
                        module,  # Continue the current value.
                        academic_year=current_academic_year,  # Store the computed value.
                    )  # Close the current call.

                if deleted:  # Check the current condition.
                    current_offering = _get_current_offering_for_lecturer_module(  # Store the computed value.
                        module,  # Continue the current value.
                        academic_year=current_academic_year,  # Store the computed value.
                    )  # Close the current call.
                    if current_offering:  # Check the current condition.
                        _ensure_primary_lecturer(current_offering)  # Call the helper function.

                    messages.success(  # Queue a success message.
                        request,  # Continue the current value.
                        f"Removed {lecturer.user.get_full_name() or lecturer.user.username} from {module.code}.",  # Continue the current value.
                    )  # Close the current call.

                else:  # Handle the fallback case.
                    messages.info(request, "That lecturer was not enrolled in this module.")  # Queue an info message.

            return _redirect_with_query(  # Return the computed value.
                "accounts:admin_edit_enrollment",  # Continue the current value.
                remove_lecturer_username=lecturer.user.username,  # Store the computed value.
            )  # Close the current call.

        else:  # Handle the fallback case.
            messages.error(request, "Unknown admin enrollment action.")  # Queue an error message.
            return redirect("accounts:admin_edit_enrollment")  # Return the redirect response.

    add_student_username = (request.GET.get("add_student_username") or "").strip()  # Fetch a single record.
    remove_student_username = (request.GET.get("remove_student_username") or "").strip()  # Fetch a single record.
    add_lecturer_username = (request.GET.get("add_lecturer_username") or "").strip()  # Fetch a single record.
    remove_lecturer_username = (request.GET.get("remove_lecturer_username") or "").strip()  # Fetch a single record.

    add_student_profile = _get_student_by_username(add_student_username) if add_student_username else None  # Store the computed value.
    remove_student_profile = _get_student_by_username(remove_student_username) if remove_student_username else None  # Store the computed value.
    add_lecturer_profile = _get_lecturer_by_username(add_lecturer_username) if add_lecturer_username else None  # Store the computed value.
    remove_lecturer_profile = _get_lecturer_by_username(remove_lecturer_username) if remove_lecturer_username else None  # Store the computed value.

    context = _admin_page_context(user, "Edit Enrollment")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "add_student_username": add_student_username,  # Set this mapping value.
            "remove_student_username": remove_student_username,  # Set this mapping value.
            "add_lecturer_username": add_lecturer_username,  # Set this mapping value.
            "remove_lecturer_username": remove_lecturer_username,  # Set this mapping value.
            "add_student_profile": add_student_profile,  # Set this mapping value.
            "remove_student_profile": remove_student_profile,  # Set this mapping value.
            "add_lecturer_profile": add_lecturer_profile,  # Set this mapping value.
            "remove_lecturer_profile": remove_lecturer_profile,  # Set this mapping value.
            "add_student_modules": _build_addable_modules_for_student(add_student_profile) if add_student_profile else [],  # Set this mapping value.
            "remove_student_modules": _build_removable_modules_for_student(remove_student_profile) if remove_student_profile else [],  # Set this mapping value.
            "add_lecturer_modules": _build_addable_modules_for_lecturer(add_lecturer_profile) if add_lecturer_profile else [],  # Set this mapping value.
            "remove_lecturer_modules": _build_removable_modules_for_lecturer(remove_lecturer_profile) if remove_lecturer_profile else [],  # Set this mapping value.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_edit_enrollment.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_create_global_announcement(request):  # Define admin_create_global_announcement.
    """Handle admin create global announcement."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title, content, errors = _validate_announcement_form(request)  # Unpack returned values.

        if not errors:  # Check the current condition.
            GlobalAnnouncement.objects.create(  # Create a database record.
                title=title,  # Store the computed value.
                content=content,  # Store the computed value.
                created_by=user,  # Store the computed value.
            )  # Close the current call.
            GlobalAnnouncement.trim_to_latest_three()  # Call the helper function.

            messages.success(request, "Global announcement created successfully.")  # Queue a success message.
            return redirect("accounts:admin_dashboard")  # Return the redirect response.

    context = _admin_page_context(user, "Create Global Announcement")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "errors": errors,  # Set errors.
            "initial": {  # Set initial.
                "title": request.POST.get("title", ""),  # Fetch a single record.
                "content": request.POST.get("content", ""),  # Fetch a single record.
            },  # Close the current mapping.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_global_announcement_form.html", context)  # Return the rendered template.


@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def admin_edit_global_announcement(request, announcement_id):  # Define admin_edit_global_announcement.
    """Handle admin edit global announcement."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    announcement = get_object_or_404(GlobalAnnouncement, pk=announcement_id)  # Store the computed value.
    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title, content, errors = _validate_announcement_form(request)  # Unpack returned values.

        if not errors:  # Check the current condition.
            announcement.title = title  # Store the computed value.
            announcement.content = content  # Store the computed value.
            announcement.save(update_fields=["title", "content", "updated_at"])  # Save model changes.

            messages.success(request, "Global announcement updated successfully.")  # Queue a success message.
            return redirect("accounts:admin_dashboard")  # Return the redirect response.

    context = _admin_page_context(user, "Edit Global Announcement")  # Build template context.
    context.update(  # Bulk update matching records.
        {  # Start the current mapping.
            "errors": errors,  # Set errors.
            "announcement": announcement,  # Set announcement.
            "initial": {  # Set initial.
                "title": request.POST.get("title", announcement.title) if request.method == "POST" else announcement.title,  # Fetch a single record.
                "content": request.POST.get("content", announcement.content) if request.method == "POST" else announcement.content,  # Fetch a single record.
            },  # Close the current mapping.
        }  # Close the current mapping.
    )  # Close the current call.
    return render(request, "accounts/admin_global_announcement_form.html", context)  # Return the rendered template.


@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def admin_delete_global_announcement(request, announcement_id):  # Define admin_delete_global_announcement.
    """Handle admin delete global announcement."""
    user: User = request.user  # Store the current user.
    _require_admin_user(user)  # Call the helper function.

    announcement = get_object_or_404(GlobalAnnouncement, pk=announcement_id)  # Store the computed value.
    announcement.delete()  # Delete the record.

    messages.success(request, "Global announcement deleted successfully.")  # Queue a success message.
    return redirect("accounts:admin_dashboard")  # Return the redirect response.

# ==========
# User Views
# ==========
@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def update_accessibility_preferences(request):  # Define update_accessibility_preferences.
    """Update accessibility preferences."""
    user = request.user  # Store the current user.

    colour_scheme = (request.POST.get("colour_scheme") or user.colour_scheme).strip()  # Fetch a single record.
    font_scheme = (request.POST.get("font_scheme") or user.font_scheme).strip()  # Fetch a single record.

    valid_colour_schemes = {choice[0] for choice in User.ColourScheme.choices}  # Store the computed value.
    valid_font_schemes = {choice[0] for choice in User.FontScheme.choices}  # Store the computed value.

    if colour_scheme not in valid_colour_schemes:  # Check the current condition.
        colour_scheme = User.ColourScheme.DEFAULT  # Store the computed value.

    if font_scheme not in valid_font_schemes:  # Check the current condition.
        font_scheme = User.FontScheme.DEFAULT  # Store the computed value.

    user.colour_scheme = colour_scheme  # Store the computed value.
    user.font_scheme = font_scheme  # Store the computed value.
    user.save(update_fields=["colour_scheme", "font_scheme"])  # Save model changes.

    next_url = request.POST.get("next") or reverse("accounts:dashboard")  # Fetch a single record.
    if not url_has_allowed_host_and_scheme(  # Check the current condition.
        next_url,  # Continue the current value.
        allowed_hosts={request.get_host()},  # Store the computed value.
        require_https=request.is_secure(),  # Store the computed value.
    ):  # Continue the current block.
        next_url = reverse("accounts:dashboard")  # Store the resolved URL.

    return redirect(next_url)  # Return the redirect response.

@login_required  # Require login.
def user_profile(request):  # Define user_profile.
    """Handle the user profile view."""
    user: User = request.user  # Store the current user.

    if user.is_admin():  # Check the current condition.
        return redirect("accounts:admin_dashboard")  # Return the redirect response.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "display_name": user.get_full_name() or user.username,  # Set display name.
        "profile_email": user.username,  # Set profile email.
    }  # Close the current mapping.

    if user.is_student():  # Check the current condition.
        student = get_object_or_404(  # Store the computed value.
            StudentProfile.objects.select_related("user"),  # Follow related objects.
            user=user,  # Store the current user.
        )  # Close the current call.

        current_offerings = _current_offering_queryset_for_student(student)  # Store the computed value.

        context.update(  # Bulk update matching records.
            {  # Start the current mapping.
                "profile_role": "student",  # Set profile role.
                "course": student.course or "N/A",  # Set course.
                "module_rows": _build_student_profile_modules(  # Set module rows.
                    current_offerings,  # Continue the current value.
                    student,  # Continue the current value.
                    request.get_full_path(),  # Call the helper function.
                ),  # Close the current call.
                "previous_year_groups": _build_previous_student_profile_year_groups(  # Set this mapping value.
                    student,  # Continue the current value.
                    request.get_full_path(),  # Call the helper function.
                ),  # Close the current call.
            }  # Close the current mapping.
        )  # Close the current call.

    elif user.is_lecturer():  # Check the alternate condition.
        lecturer = get_object_or_404(  # Store the computed value.
            LecturerProfile.objects.select_related("user"),  # Follow related objects.
            user=user,  # Store the current user.
        )  # Close the current call.

        current_offerings = _current_offering_queryset_for_lecturer(lecturer)  # Store the computed value.

        context.update(  # Bulk update matching records.
            {  # Start the current mapping.
                "profile_role": "lecturer",  # Set profile role.
                "module_rows": _build_lecturer_profile_modules(  # Set module rows.
                    current_offerings,  # Continue the current value.
                    lecturer,  # Continue the current value.
                    request.get_full_path(),  # Call the helper function.
                ),  # Close the current call.
                "previous_year_groups": _build_previous_lecturer_profile_year_groups(  # Set this mapping value.
                    lecturer,  # Continue the current value.
                    request.get_full_path(),  # Call the helper function.
                ),  # Close the current call.
            }  # Close the current mapping.
        )  # Close the current call.

    else:  # Handle the fallback case.
        raise Http404("Profile not found")  # Raise a not found error.

    return render(request, "accounts/profile.html", context)  # Return the rendered template.

@login_required  # Require login.
def open_notification(request, notification_id):  # Define open_notification.
    """Open a notification and redirect."""
    notification = get_object_or_404(  # Store the computed value.
        Notification,  # Continue the current value.
        pk=notification_id,  # Store the computed value.
        recipient=request.user,  # Store the computed value.
    )  # Close the current call.

    notification.mark_as_read()  # Call the helper function.

    target_url = notification.redirect_url or reverse("accounts:dashboard")  # Store the resolved URL.

    if not url_has_allowed_host_and_scheme(  # Check the current condition.
        target_url,  # Continue the current value.
        allowed_hosts={request.get_host()},  # Store the computed value.
        require_https=request.is_secure(),  # Store the computed value.
    ):  # Continue the current block.
        target_url = reverse("accounts:dashboard")  # Store the resolved URL.

    return redirect(target_url)  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def read_all_notifications(request):  # Define read_all_notifications.
    """Mark all notifications as read."""
    Notification.objects.filter(  # Filter queryset records.
        recipient=request.user,  # Store the computed value.
        is_read=False,  # Store the boolean state.
    ).update(  # Bulk update matching records.
        is_read=True,  # Store the boolean state.
        read_at=timezone.now(),  # Store the computed value.
    )  # Close the current call.

    next_url = request.POST.get("next") or reverse("accounts:dashboard")  # Fetch a single record.

    if not url_has_allowed_host_and_scheme(  # Check the current condition.
        next_url,  # Continue the current value.
        allowed_hosts={request.get_host()},  # Store the computed value.
        require_https=request.is_secure(),  # Store the computed value.
    ):  # Continue the current block.
        next_url = reverse("accounts:dashboard")  # Store the resolved URL.

    return redirect(next_url)  # Return the redirect response.

# =========================
# Portal and Offering Views
# =========================
@login_required  # Require login.
def portal(request):  # Define portal.
    """Handle the portal view."""
    user: User = request.user  # Store the current user.

    if user.is_admin():  # Check the current condition.
        return redirect("accounts:admin_dashboard")  # Return the redirect response.

    today = timezone.localdate()  # Store the computed value.

    try:  # Start guarded parsing.
        selected_year = int(request.GET.get("year", today.year))  # Fetch a single record.
        selected_month = int(request.GET.get("month", today.month))  # Fetch a single record.
        if selected_month < 1 or selected_month > 12:  # Check the current condition.
            raise ValueError  # Raise an application error.
    except (TypeError, ValueError):  # Handle the raised exception.
        selected_year = today.year  # Store the computed value.
        selected_month = today.month  # Store the computed value.

    office_tiles_primary, office_tile_more = _portal_office_tiles()  # Unpack returned values.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "office_tiles_primary": office_tiles_primary,  # Set this mapping value.
        "office_tile_more": office_tile_more,  # Set office tile more.
        "timetable_url": f"https://timetables.tudublin.ie/timetables?date={today.isoformat()}&view=week",  # Set timetable url.
    }  # Close the current mapping.

    context.update(  # Bulk update matching records.
        _build_portal_calendar_context(  # Open the current call.
            user=user,  # Store the current user.
            year=selected_year,  # Store the computed value.
            month=selected_month,  # Store the computed value.
            next_url=request.get_full_path(),  # Store the resolved URL.
        )  # Close the current call.
    )  # Close the current call.

    context.update(  # Bulk update matching records.
        _build_portal_week_context(  # Open the current call.
            user=user,  # Store the current user.
            today=today,  # Store the computed value.
            next_url=request.get_full_path(),  # Store the resolved URL.
        )  # Close the current call.
    )  # Close the current call.

    return render(request, "accounts/portal.html", context)  # Return the rendered template.

@login_required  # Require login.
def offering_detail(request, offering_id):  # Define offering_detail.
    """Handle the offering detail view."""
    user: User = request.user  # Store the current user.
    nav_items = _shared_nav_items()  # Build the list values.

    offering = _get_accessible_offering_for_user(user, offering_id)  # Store the computed value.
    module = offering.module  # Store the computed value.
    read_only = _is_read_only_offering(offering)  # Store the computed value.
    now = timezone.now()  # Store the computed value.
    module_announcements = _recent_offering_module_announcements(offering)  # Store the computed value.

    if user.is_student():  # Check the current condition.
        student = user.student_profile  # Store the computed value.

        assessment_items = _build_student_module_assessment_items(  # Build the list values.
            offering,  # Continue the current value.
            student,  # Continue the current value.
            now,  # Continue the current value.
            request.get_full_path(),  # Call the helper function.
        )  # Close the current call.

        weeks = (  # Store the computed value.
            offering.weeks  # Continue the current block.
            .filter(files__isnull=False)  # Filter queryset records.
            .prefetch_related("files__parsed_document")  # Prefetch related objects.
            .order_by("week_number")  # Order queryset results.
            .distinct()  # Remove duplicate rows.
        )  # Close the current call.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": nav_items,  # Set nav items.
            "offering": offering,  # Set offering.
            "module": module,  # Set module.
            "role": "student",  # Set role.
            "read_only": read_only,  # Set read only.
            "assessment_items": assessment_items,  # Set assessment items.
            "module_announcements": module_announcements,  # Set this mapping value.
            "weeks": weeks,  # Set weeks.
            "run_start": offering.academic_year.start_date,  # Set run start.
            "run_end": offering.academic_year.end_date,  # Set run end.
            "back_url": _safe_back_url(request, "accounts:dashboard"),  # Set back url.
        }  # Close the current mapping.

    elif user.is_lecturer():  # Check the alternate condition.
        assessment_items = _build_lecturer_module_assessment_items(  # Build the list values.
            offering,  # Continue the current value.
            request.get_full_path(),  # Call the helper function.
        )  # Close the current call.

        requested_week_number = request.GET.get("week")  # Fetch a single record.
        try:  # Start guarded parsing.
            requested_week_number = int(requested_week_number) if requested_week_number else None  # Store the computed value.
        except (TypeError, ValueError):  # Handle the raised exception.
            requested_week_number = None  # Store the computed value.

        all_weeks = list(  # Store the computed value.
            offering.weeks  # Continue the current block.
            .all()  # Return all records.
            .prefetch_related("files__parsed_document")  # Prefetch related objects.
            .order_by("week_number")  # Order queryset results.
        )  # Close the current call.

        weeks = []  # Store the computed value.
        for week in all_weeks:  # Iterate through the collection.
            has_description = bool((week.description or "").strip())  # Trim surrounding whitespace.
            has_files = bool(week.files.all())  # Return all records.
            if has_description or has_files:  # Check the current condition.
                weeks.append(week)  # Append to the list.

        if requested_week_number is not None:  # Check the current condition.
            requested_week = next(  # Store the computed value.
                (week for week in all_weeks if week.week_number == requested_week_number),  # Continue the current value.
                None,  # Continue the current value.
            )  # Close the current call.
            if requested_week and requested_week not in weeks:  # Check the current condition.
                weeks.append(requested_week)  # Append to the list.
                weeks.sort(key=lambda week: week.week_number)  # Call the helper function.

        student_enrolments = sorted(  # Store the computed value.
            offering.student_enrolments.select_related("student__user"),  # Follow related objects.
            key=lambda enrolment: (  # Store the computed value.
                (enrolment.student.user.get_full_name() or enrolment.student.user.username).lower(),  # Normalise text to lowercase.
                enrolment.student.user.username.lower(),  # Normalise text to lowercase.
            ),  # Close the current call.
        )  # Close the current call.

        enrolled_students = [  # Store the computed value.
            {  # Start the current mapping.
                "name": enrolment.student.user.get_full_name() or enrolment.student.user.username,  # Set name.
                "email": enrolment.student.user.username,  # Set email.
            }  # Close the current mapping.
            for enrolment in student_enrolments  # Iterate through the collection.
        ]  # Close the current list.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": nav_items,  # Set nav items.
            "offering": offering,  # Set offering.
            "module": module,  # Set module.
            "role": "lecturer",  # Set role.
            "read_only": read_only,  # Set read only.
            "assessment_items": assessment_items,  # Set assessment items.
            "module_announcements": module_announcements,  # Set this mapping value.
            "weeks": weeks,  # Set weeks.
            "enrolled_students": enrolled_students,  # Set enrolled students.
            "enrolled_student_count": len(enrolled_students),  # Set this mapping value.
            "run_start": offering.academic_year.start_date,  # Set run start.
            "run_end": offering.academic_year.end_date,  # Set run end.
            "back_url": _safe_back_url(request, "accounts:dashboard"),  # Set back url.
        }  # Close the current mapping.

    else:  # Handle the fallback case.
        return redirect("accounts:login")  # Return the redirect response.

    return render(request, "accounts/module_detail.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_create_module_announcement(request, offering_id):  # Define offering_create_module_announcement.
    """Handle offering create module announcement."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    module = offering.module  # Store the computed value.
    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title, content, errors = _validate_announcement_form(request)  # Unpack returned values.

        if not errors:  # Check the current condition.
            ModuleAnnouncement.objects.create(  # Create a database record.
                offering=offering,  # Store the computed value.
                title=title,  # Store the computed value.
                content=content,  # Store the computed value.
                created_by=user,  # Store the computed value.
            )  # Close the current call.
            ModuleAnnouncement.trim_to_latest_three_for_offering(offering)  # Call the helper function.

            messages.success(request, "Module announcement created successfully.")  # Queue a success message.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": module,  # Set module.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "title": request.POST.get("title", ""),  # Fetch a single record.
            "content": request.POST.get("content", ""),  # Fetch a single record.
        },  # Close the current mapping.
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/module_announcement_form.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_edit_module_announcement(request, offering_id, announcement_id):  # Define offering_edit_module_announcement.
    """Handle offering edit module announcement."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    module = offering.module  # Store the computed value.
    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, offering=offering)  # Store the computed value.

    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title, content, errors = _validate_announcement_form(request)  # Unpack returned values.

        if not errors:  # Check the current condition.
            announcement.title = title  # Store the computed value.
            announcement.content = content  # Store the computed value.
            announcement.save(update_fields=["title", "content", "updated_at"])  # Save model changes.

            messages.success(request, "Module announcement updated successfully.")  # Queue a success message.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": module,  # Set module.
        "announcement": announcement,  # Set announcement.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "title": request.POST.get("title", announcement.title) if request.method == "POST" else announcement.title,  # Fetch a single record.
            "content": request.POST.get("content", announcement.content) if request.method == "POST" else announcement.content,  # Fetch a single record.
        },  # Close the current mapping.
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/module_announcement_form.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_delete_module_announcement(request, offering_id, announcement_id):  # Define offering_delete_module_announcement.
    """Handle offering delete module announcement."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, offering=offering)  # Store the computed value.

    announcement.delete()  # Delete the record.
    messages.success(request, "Module announcement deleted successfully.")  # Queue a success message.
    return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

@login_required  # Require login.
def offering_upload_week_file(request, offering_id, week_number):  # Define offering_upload_week_file.
    """Handle offering upload week file."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    module = offering.module  # Store the computed value.

    week, _ = ModuleWeek.objects.get_or_create(  # Unpack returned values.
        offering=offering,  # Store the computed value.
        week_number=week_number,  # Store the computed value.
        defaults={"title": f"Week {week_number}"},  # Store the computed value.
    )  # Close the current call.

    if request.method == "POST":  # Check the current condition.
        was_visible = _week_is_viewable(week)  # Store the computed value.
        module_detail_url = reverse("accounts:offering_detail", args=[offering.id])  # Store the resolved URL.

        if "file" not in request.FILES:  # Check the current condition.
            messages.error(request, "Please choose a .docx or .pptx file to upload.")  # Queue an error message.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

        uploaded = request.FILES["file"]  # Store the computed value.

        try:  # Start guarded parsing.
            parsed_payload = parse_uploaded_office_file(uploaded)  # Store the computed value.
        except ValueError as exc:  # Handle the raised exception.
            _notify_lecturers_parser_failure(offering, uploaded.name, module_detail_url)  # Call the helper function.
            messages.error(request, str(exc))  # Queue an error message.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

        except Exception:  # Handle the raised exception.
            _notify_lecturers_parser_failure(offering, uploaded.name, module_detail_url)  # Call the helper function.
            messages.error(  # Queue an error message.
                request,  # Continue the current value.
                "The file could not be translated into accessible HTML. "  # Continue the current block.
                "Please upload a readable .docx or .pptx containing text, tables, and images.",  # Continue the current value.
            )  # Close the current call.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

        week_file = None  # Store the uploaded file.

        try:  # Start guarded parsing.
            with transaction.atomic():  # Open the resource safely.
                week_file = ModuleWeekFile.objects.create(  # Create a database record.
                    week=week,  # Store the computed value.
                    file=uploaded,  # Store the computed value.
                    original_name=uploaded.name,  # Store the computed value.
                    uploaded_by=user,  # Store the computed value.
                )  # Close the current call.

                _persist_parsed_document(  # Open the current call.
                    parsed_payload=parsed_payload,  # Store the computed value.
                    week_file=week_file,  # Store the uploaded file.
                )  # Close the current call.

        except Exception:  # Handle the raised exception.
            if week_file and week_file.file:  # Check the current condition.
                week_file.file.delete(save=False)  # Delete the record.

            _notify_lecturers_parser_failure(offering, uploaded.name, module_detail_url)  # Call the helper function.
            messages.error(  # Queue an error message.
                request,  # Continue the current value.
                "The file was not published because parsing/storage failed.",  # Continue the current value.
            )  # Close the current call.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

        _notify_lecturers_parser_success(offering, uploaded.name, module_detail_url)  # Call the helper function.

        if not was_visible:  # Check the current condition.
            _notify_students_if_week_now_viewable(week)  # Call the helper function.

        messages.success(request, "Weekly file uploaded and parsed successfully.")  # Queue a success message.

    return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_save_module_week(request, offering_id, week_number):  # Define offering_save_module_week.
    """Handle offering save module week."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    week, _ = ModuleWeek.objects.get_or_create(  # Unpack returned values.
        offering=offering,  # Store the computed value.
        week_number=week_number,  # Store the computed value.
        defaults={"title": f"Week {week_number}"},  # Store the computed value.
    )  # Close the current call.

    description = request.POST.get("description", "").strip()  # Fetch a single record.
    uploaded_files = request.FILES.getlist("files")  # Read repeated form values.
    module_detail_url = reverse("accounts:offering_detail", args=[offering.id])  # Store the resolved URL.
    was_visible = _week_is_viewable(week)  # Store the computed value.

    if not description:  # Check the current condition.
        messages.error(request, "A week description is required before saving.")  # Queue an error message.
        return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

    if not week.files.exists() and not uploaded_files:  # Check the current condition.
        messages.error(request, "Please add at least one .docx or .pptx file before saving this week.")  # Queue an error message.
        return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

    week.description = description  # Store the computed value.
    week.save(update_fields=["description"])  # Save model changes.

    for uploaded in uploaded_files:  # Iterate through the collection.
        try:  # Start guarded parsing.
            parsed_payload = parse_uploaded_office_file(uploaded)  # Store the computed value.
        except ValueError as exc:  # Handle the raised exception.
            messages.error(request, str(exc))  # Queue an error message.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.
        except Exception:  # Handle the raised exception.
            messages.error(  # Queue an error message.
                request,  # Continue the current value.
                "The file could not be translated into accessible HTML. "  # Continue the current block.
                "Please upload a readable .docx or .pptx containing text, tables, and images.",  # Continue the current value.
            )  # Close the current call.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

        week_file = None  # Store the uploaded file.
        try:  # Start guarded parsing.
            with transaction.atomic():  # Open the resource safely.
                week_file = ModuleWeekFile.objects.create(  # Create a database record.
                    week=week,  # Store the computed value.
                    file=uploaded,  # Store the computed value.
                    original_name=uploaded.name,  # Store the computed value.
                    uploaded_by=user,  # Store the computed value.
                )  # Close the current call.

                _persist_parsed_document(  # Open the current call.
                    parsed_payload=parsed_payload,  # Store the computed value.
                    week_file=week_file,  # Store the uploaded file.
                )  # Close the current call.
        except Exception:  # Handle the raised exception.
            if week_file and week_file.file:  # Check the current condition.
                week_file.file.delete(save=False)  # Delete the record.

            messages.error(  # Queue an error message.
                request,  # Continue the current value.
                "One of the uploaded files failed during parsing/storage, so the save was cancelled.",  # Continue the current value.
            )  # Close the current call.
            return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

        _notify_lecturers_parser_success(  # Open the current call.
            offering,  # Continue the current value.
            uploaded.name,  # Continue the current value.
            module_detail_url,  # Continue the current value.
        )  # Close the current call.

    if not was_visible:  # Check the current condition.
        _notify_students_if_week_now_viewable(week)  # Call the helper function.

    messages.success(request, f"Week {week.week_number} saved successfully.")  # Queue a success message.
    return redirect(f"{reverse('accounts:offering_detail', args=[offering.id])}?week={week.week_number}")  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_add_module_week(request, offering_id):  # Define offering_add_module_week.
    """Handle offering add module week."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    next_week_number = (  # Store the computed value.
        offering.weeks.aggregate(max_week=Max("week_number")).get("max_week") or 0  # Aggregate queryset values.
    ) + 1  # Continue the current block.

    week, created = ModuleWeek.objects.get_or_create(  # Unpack returned values.
        offering=offering,  # Store the computed value.
        week_number=next_week_number,  # Store the computed value.
        defaults={"title": f"Week {next_week_number}"},  # Store the computed value.
    )  # Close the current call.

    return redirect(f"{reverse('accounts:offering_detail', args=[offering.id])}?week={week.week_number}")  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_create_assignment(request, offering_id):  # Define offering_create_assignment.
    """Handle offering create assignment."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    module = offering.module  # Store the computed value.
    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title = request.POST.get("title", "").strip()  # Fetch a single record.
        description = request.POST.get("description", "").strip()  # Fetch a single record.
        due_date_str = request.POST.get("due_date", "").strip()  # Fetch a single record.
        due_time_str = request.POST.get("due_time", "").strip()  # Fetch a single record.
        max_mark_str = request.POST.get("max_mark", "").strip() or "100"  # Fetch a single record.

        if not title:  # Check the current condition.
            errors.append("Title is required.")  # Append to the list.
        if not due_date_str:  # Check the current condition.
            errors.append("Due date is required.")  # Append to the list.
        if not due_time_str:  # Check the current condition.
            errors.append("Due time is required.")  # Append to the list.

        due_dt = None  # Store the computed value.
        if due_date_str and due_time_str:  # Check the current condition.
            try:  # Start guarded parsing.
                due_dt = datetime.fromisoformat(f"{due_date_str} {due_time_str}")  # Store the computed value.
            except ValueError:  # Handle the raised exception.
                errors.append("Invalid due date/time format.")  # Append to the list.

        try:  # Start guarded parsing.
            max_mark_val = float(max_mark_str)  # Store the computed value.
        except ValueError:  # Handle the raised exception.
            errors.append("% of Module must be a number.")  # Append to the list.
            max_mark_val = 100.0  # Store the computed value.

        uploaded_files = request.FILES.getlist("files")  # Read repeated form values.
        parsed_file_payloads: list[tuple] = []  # Store the computed value.
        create_assignment_url = reverse("accounts:offering_create_assignment", args=[offering.id])  # Store the resolved URL.

        if not errors and uploaded_files:  # Check the current condition.
            for uploaded in uploaded_files:  # Iterate through the collection.
                try:  # Start guarded parsing.
                    parsed_payload = parse_uploaded_office_file(uploaded)  # Store the computed value.
                    parsed_file_payloads.append((uploaded, parsed_payload))  # Append to the list.
                except ValueError as exc:  # Handle the raised exception.
                    _notify_lecturers_parser_failure(offering, uploaded.name, create_assignment_url)  # Call the helper function.
                    errors.append(f"{uploaded.name}: {exc}")  # Append to the list.
                except Exception:  # Handle the raised exception.
                    _notify_lecturers_parser_failure(offering, uploaded.name, create_assignment_url)  # Call the helper function.
                    errors.append(  # Append to the list.
                        f"{uploaded.name}: The file could not be translated into accessible HTML."  # Continue the current block.
                    )  # Close the current call.

        if not errors and due_dt is not None:  # Check the current condition.
            assignment = None  # Store the computed value.
            created_assignment_files: list[AssignmentFile] = []  # Store the computed value.

            try:  # Start guarded parsing.
                with transaction.atomic():  # Open the resource safely.
                    assignment = Assignment.objects.create(  # Create a database record.
                        offering=offering,  # Store the computed value.
                        title=title,  # Store the computed value.
                        description=description,  # Store the computed value.
                        due_datetime=timezone.make_aware(due_dt)  # Store the computed value.
                        if timezone.is_naive(due_dt)  # Check the current condition.
                        else due_dt,  # Continue the current value.
                        max_mark=max_mark_val,  # Store the computed value.
                    )  # Close the current call.

                    for uploaded, parsed_payload in parsed_file_payloads:  # Iterate through the collection.
                        assignment_file = AssignmentFile.objects.create(  # Create a database record.
                            assignment=assignment,  # Store the computed value.
                            file=uploaded,  # Store the computed value.
                            original_name=uploaded.name,  # Store the computed value.
                            uploaded_by=user,  # Store the computed value.
                        )  # Close the current call.
                        created_assignment_files.append(assignment_file)  # Append to the list.

                        _persist_parsed_document(  # Open the current call.
                            parsed_payload=parsed_payload,  # Store the computed value.
                            assignment_file=assignment_file,  # Store the uploaded file.
                        )  # Close the current call.

            except Exception:  # Handle the raised exception.
                for assignment_file in created_assignment_files:  # Iterate through the collection.
                    if assignment_file.file:  # Check the current condition.
                        assignment_file.file.delete(save=False)  # Delete the record.

                _notify_lecturers_parser_failure(offering, "assignment materials", create_assignment_url)  # Call the helper function.
                errors.append(  # Append to the list.
                    "The assignment was not published because one or more uploaded files "  # Continue the current block.
                    "failed during parsing/storage."  # Continue the current block.
                )  # Close the current call.
            else:  # Handle the fallback case.
                assignment_detail_url = reverse(  # Store the resolved URL.
                    "accounts:offering_assignment_detail",  # Continue the current value.
                    args=[offering.id, assignment.id],  # Store the computed value.
                )  # Close the current call.

                for assignment_file in created_assignment_files:  # Iterate through the collection.
                    _notify_lecturers_parser_success(  # Open the current call.
                        offering,  # Continue the current value.
                        assignment_file.original_name or assignment_file.file.name,  # Continue the current value.
                        assignment_detail_url,  # Continue the current value.
                    )  # Close the current call.

                _notify_students_new_assignment(assignment)  # Call the helper function.

                messages.success(request, "Assignment created successfully.")  # Queue a success message.
                return redirect(  # Return the redirect response.
                    "accounts:offering_assignment_detail",  # Continue the current value.
                    offering_id=offering.id,  # Store the related id.
                    assignment_id=assignment.id,  # Store the related id.
                )  # Close the current call.

    else:  # Handle the fallback case.
        due_date_str = ""  # Store the computed value.
        due_time_str = ""  # Store the computed value.
        title = ""  # Store the computed value.
        description = ""  # Store the computed value.
        max_mark_str = "100"  # Store the computed value.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": module,  # Set module.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "title": title,  # Set title.
            "description": description,  # Set description.
            "due_date": due_date_str,  # Set due date.
            "due_time": due_time_str,  # Set due time.
            "max_mark": max_mark_str,  # Set max mark.
        },  # Close the current mapping.
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/create_assignment.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_create_quiz(request, offering_id):  # Define offering_create_quiz.
    """Handle offering create quiz."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.

    module = offering.module  # Store the computed value.
    errors = []  # Initialise error messages.
    initial_questions = []  # Store the computed value.

    if request.method == "POST":  # Check the current condition.
        title = request.POST.get("title", "").strip()  # Fetch a single record.
        description = request.POST.get("description", "").strip()  # Fetch a single record.
        open_date_str = request.POST.get("open_date", "").strip()  # Fetch a single record.
        open_time_str = request.POST.get("open_time", "").strip()  # Fetch a single record.
        close_date_str = request.POST.get("close_date", "").strip()  # Fetch a single record.
        close_time_str = request.POST.get("close_time", "").strip()  # Fetch a single record.
        time_limit_minutes = _parse_positive_int(  # Store the computed value.
            request.POST.get("time_limit_minutes", "20"),  # Fetch a single record.
            "Time limit",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=1,  # Store the computed value.
        )  # Close the current call.
        max_attempts = _parse_positive_int(  # Store the computed value.
            request.POST.get("max_attempts", "1"),  # Fetch a single record.
            "Attempt count",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=1,  # Store the computed value.
        )  # Close the current call.
        max_mark = _parse_decimal_value(  # Store the computed value.
            request.POST.get("max_mark", "100"),  # Fetch a single record.
            "% of Module",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=Decimal("1.00"),  # Store the computed value.
        )  # Close the current call.
        is_published = request.POST.get("is_published") == "on"  # Fetch a single record.

        if not title:  # Check the current condition.
            errors.append("Title is required.")  # Append to the list.

        open_dt = _parse_form_datetime(open_date_str, open_time_str, "Open", errors)  # Store the computed value.
        close_dt = _parse_form_datetime(close_date_str, close_time_str, "Close", errors)  # Store the computed value.

        if open_dt and close_dt and close_dt <= open_dt:  # Check the current condition.
            errors.append("Close date/time must be later than the open date/time.")  # Append to the list.

        raw_questions_payload = request.POST.get("questions_payload", "")  # Fetch a single record.
        try:  # Start guarded parsing.
            initial_questions = json.loads(raw_questions_payload or "[]")  # Store the computed value.
        except json.JSONDecodeError:  # Handle the raised exception.
            initial_questions = []  # Store the computed value.

        question_payloads = _parse_questions_payload(raw_questions_payload, errors)  # Store the computed value.

        if not errors:  # Check the current condition.
            with transaction.atomic():  # Open the resource safely.
                quiz = Quiz.objects.create(  # Create a database record.
                    offering=offering,  # Store the computed value.
                    title=title,  # Store the computed value.
                    description=description,  # Store the computed value.
                    open_datetime=open_dt,  # Store the computed value.
                    close_datetime=close_dt,  # Store the computed value.
                    time_limit_minutes=time_limit_minutes,  # Store the computed value.
                    max_attempts=max_attempts,  # Store the computed value.
                    max_mark=max_mark,  # Store the computed value.
                    is_published=is_published,  # Store the boolean state.
                )  # Close the current call.

                _create_quiz_questions(quiz, question_payloads)  # Call the helper function.

            _notify_students_new_quiz(quiz)  # Call the helper function.

            messages.success(request, "Quiz created successfully.")  # Queue a success message.
            return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    else:  # Handle the fallback case.
        initial_questions = []  # Store the computed value.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": module,  # Set module.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "title": request.POST.get("title", "") if request.method == "POST" else "",  # Fetch a single record.
            "description": request.POST.get("description", "") if request.method == "POST" else "",  # Fetch a single record.
            "open_date": request.POST.get("open_date", "") if request.method == "POST" else "",  # Fetch a single record.
            "open_time": request.POST.get("open_time", "") if request.method == "POST" else "",  # Fetch a single record.
            "close_date": request.POST.get("close_date", "") if request.method == "POST" else "",  # Fetch a single record.
            "close_time": request.POST.get("close_time", "") if request.method == "POST" else "",  # Fetch a single record.
            "time_limit_minutes": request.POST.get("time_limit_minutes", "20") if request.method == "POST" else "20",  # Fetch a single record.
            "max_attempts": request.POST.get("max_attempts", "1") if request.method == "POST" else "1",  # Fetch a single record.
            "max_mark": request.POST.get("max_mark", "100") if request.method == "POST" else "100",  # Fetch a single record.
            "is_published": (request.POST.get("is_published") == "on") if request.method == "POST" else True,  # Fetch a single record.
        },  # Close the current mapping.
        "initial_questions": initial_questions,  # Set initial questions.
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/create_quiz.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_edit_assignment(request, offering_id, assignment_id):  # Define offering_edit_assignment.
    """Handle offering edit assignment."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.
    assignment = get_object_or_404(  # Store the computed value.
        Assignment.objects.select_related("offering__module").prefetch_related("files__parsed_document__images"),  # Follow related objects.
        pk=assignment_id,  # Store the related id.
        offering=offering,  # Store the computed value.
    )  # Close the current call.

    if not _can_edit_assignment(assignment):  # Check the current condition.
        messages.error(request, "This assignment can no longer be edited because the due date has passed.")  # Queue an error message.
        return redirect("accounts:offering_assignment_detail", offering_id=offering.id, assignment_id=assignment.id)  # Return the redirect response.

    module = offering.module  # Store the computed value.
    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title = request.POST.get("title", "").strip()  # Fetch a single record.
        description = request.POST.get("description", "").strip()  # Fetch a single record.
        due_date_str = request.POST.get("due_date", "").strip()  # Fetch a single record.
        due_time_str = request.POST.get("due_time", "").strip()  # Fetch a single record.
        max_mark_str = request.POST.get("max_mark", "").strip() or "100"  # Fetch a single record.

        if not title:  # Check the current condition.
            errors.append("Title is required.")  # Append to the list.
        if not due_date_str:  # Check the current condition.
            errors.append("Due date is required.")  # Append to the list.
        if not due_time_str:  # Check the current condition.
            errors.append("Due time is required.")  # Append to the list.

        due_dt = None  # Store the computed value.
        if due_date_str and due_time_str:  # Check the current condition.
            try:  # Start guarded parsing.
                due_dt = datetime.fromisoformat(f"{due_date_str} {due_time_str}")  # Store the computed value.
            except ValueError:  # Handle the raised exception.
                errors.append("Invalid due date/time format.")  # Append to the list.

        try:  # Start guarded parsing.
            max_mark_val = float(max_mark_str)  # Store the computed value.
        except ValueError:  # Handle the raised exception.
            errors.append("% of Module must be a number.")  # Append to the list.
            max_mark_val = 100.0  # Store the computed value.

        uploaded_files = request.FILES.getlist("files")  # Read repeated form values.
        parsed_file_payloads: list[tuple] = []  # Store the computed value.
        edit_assignment_url = reverse("accounts:offering_edit_assignment", args=[offering.id, assignment.id])  # Store the resolved URL.

        if not errors and uploaded_files:  # Check the current condition.
            for uploaded in uploaded_files:  # Iterate through the collection.
                try:  # Start guarded parsing.
                    parsed_payload = parse_uploaded_office_file(uploaded)  # Store the computed value.
                    parsed_file_payloads.append((uploaded, parsed_payload))  # Append to the list.
                except ValueError as exc:  # Handle the raised exception.
                    _notify_lecturers_parser_failure(offering, uploaded.name, edit_assignment_url)  # Call the helper function.
                    errors.append(f"{uploaded.name}: {exc}")  # Append to the list.
                except Exception:  # Handle the raised exception.
                    _notify_lecturers_parser_failure(offering, uploaded.name, edit_assignment_url)  # Call the helper function.
                    errors.append(  # Append to the list.
                        f"{uploaded.name}: The file could not be translated into accessible HTML."  # Continue the current block.
                    )  # Close the current call.

        if not errors and due_dt is not None:  # Check the current condition.
            created_assignment_files: list[AssignmentFile] = []  # Store the computed value.

            try:  # Start guarded parsing.
                with transaction.atomic():  # Open the resource safely.
                    assignment.title = title  # Store the computed value.
                    assignment.description = description  # Store the computed value.
                    assignment.due_datetime = timezone.make_aware(due_dt) if timezone.is_naive(due_dt) else due_dt  # Store the computed value.
                    assignment.max_mark = max_mark_val  # Store the computed value.
                    assignment.save(update_fields=["title", "description", "due_datetime", "max_mark", "updated_at"])  # Save model changes.

                    for uploaded, parsed_payload in parsed_file_payloads:  # Iterate through the collection.
                        assignment_file = AssignmentFile.objects.create(  # Create a database record.
                            assignment=assignment,  # Store the computed value.
                            file=uploaded,  # Store the computed value.
                            original_name=uploaded.name,  # Store the computed value.
                            uploaded_by=user,  # Store the computed value.
                        )  # Close the current call.
                        created_assignment_files.append(assignment_file)  # Append to the list.

                        _persist_parsed_document(  # Open the current call.
                            parsed_payload=parsed_payload,  # Store the computed value.
                            assignment_file=assignment_file,  # Store the uploaded file.
                        )  # Close the current call.

            except Exception:  # Handle the raised exception.
                for assignment_file in created_assignment_files:  # Iterate through the collection.
                    if assignment_file.file:  # Check the current condition.
                        assignment_file.file.delete(save=False)  # Delete the record.

                _notify_lecturers_parser_failure(offering, "assignment materials", edit_assignment_url)  # Call the helper function.
                errors.append(  # Append to the list.
                    "The assignment was not updated because one or more uploaded files "  # Continue the current block.
                    "failed during parsing/storage."  # Continue the current block.
                )  # Close the current call.
            else:  # Handle the fallback case.
                assignment_detail_url = reverse(  # Store the resolved URL.
                    "accounts:offering_assignment_detail",  # Continue the current value.
                    args=[offering.id, assignment.id],  # Store the computed value.
                )  # Close the current call.

                for assignment_file in created_assignment_files:  # Iterate through the collection.
                    _notify_lecturers_parser_success(  # Open the current call.
                        offering,  # Continue the current value.
                        assignment_file.original_name or assignment_file.file.name,  # Continue the current value.
                        assignment_detail_url,  # Continue the current value.
                    )  # Close the current call.

                messages.success(request, "Assignment updated successfully.")  # Queue a success message.
                return redirect(  # Return the redirect response.
                    "accounts:offering_assignment_detail",  # Continue the current value.
                    offering_id=offering.id,  # Store the related id.
                    assignment_id=assignment.id,  # Store the related id.
                )  # Close the current call.

    else:  # Handle the fallback case.
        title = assignment.title  # Store the computed value.
        description = assignment.description  # Store the computed value.
        due_date_str = assignment.due_datetime.astimezone(timezone.get_current_timezone()).date().isoformat()  # Store the computed value.
        due_time_str = assignment.due_datetime.astimezone(timezone.get_current_timezone()).strftime("%H:%M")  # Store the computed value.
        max_mark_str = str(assignment.max_mark)  # Store the computed value.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": module,  # Set module.
        "assignment": assignment,  # Set assignment.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "title": title,  # Set title.
            "description": description,  # Set description.
            "due_date": due_date_str,  # Set due date.
            "due_time": due_time_str,  # Set due time.
            "max_mark": max_mark_str,  # Set max mark.
        },  # Close the current mapping.
        "back_url": _safe_back_url(request, "accounts:offering_assignment_detail", offering.id, assignment.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/edit_assignment.html", context)  # Return the rendered template.


@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_delete_assignment(request, offering_id, assignment_id):  # Define offering_delete_assignment.
    """Handle offering delete assignment."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.
    assignment = get_object_or_404(  # Store the computed value.
        Assignment.objects.select_related("offering__module").prefetch_related("files__parsed_document__images"),  # Follow related objects.
        pk=assignment_id,  # Store the related id.
        offering=offering,  # Store the computed value.
    )  # Close the current call.

    with transaction.atomic():  # Open the resource safely.
        _delete_assignment_with_assets(assignment)  # Call the helper function.

    messages.success(request, "Assignment deleted successfully.")  # Queue a success message.
    return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.


@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_edit_quiz(request, offering_id, quiz_id):  # Define offering_edit_quiz.
    """Handle offering edit quiz."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.
    quiz = get_object_or_404(  # Store the computed value.
        Quiz.objects.select_related("offering__module").prefetch_related("questions__options"),  # Follow related objects.
        pk=quiz_id,  # Store the related id.
        offering=offering,  # Store the computed value.
    )  # Close the current call.

    if not _can_edit_quiz(quiz):  # Check the current condition.
        messages.error(request, "This quiz can no longer be edited because it has already opened.")  # Queue an error message.
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    module = offering.module  # Store the computed value.
    errors = []  # Initialise error messages.

    if request.method == "POST":  # Check the current condition.
        title = request.POST.get("title", "").strip()  # Fetch a single record.
        description = request.POST.get("description", "").strip()  # Fetch a single record.
        open_date_str = request.POST.get("open_date", "").strip()  # Fetch a single record.
        open_time_str = request.POST.get("open_time", "").strip()  # Fetch a single record.
        close_date_str = request.POST.get("close_date", "").strip()  # Fetch a single record.
        close_time_str = request.POST.get("close_time", "").strip()  # Fetch a single record.
        time_limit_minutes = _parse_positive_int(  # Store the computed value.
            request.POST.get("time_limit_minutes", "20"),  # Fetch a single record.
            "Time limit",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=1,  # Store the computed value.
        )  # Close the current call.
        max_attempts = _parse_positive_int(  # Store the computed value.
            request.POST.get("max_attempts", "1"),  # Fetch a single record.
            "Attempt count",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=1,  # Store the computed value.
        )  # Close the current call.
        max_mark = _parse_decimal_value(  # Store the computed value.
            request.POST.get("max_mark", "100"),  # Fetch a single record.
            "% of Module",  # Continue the current value.
            errors,  # Continue the current value.
            minimum=Decimal("1.00"),  # Store the computed value.
        )  # Close the current call.
        is_published = request.POST.get("is_published") == "on"  # Fetch a single record.

        if not title:  # Check the current condition.
            errors.append("Title is required.")  # Append to the list.

        open_dt = _parse_form_datetime(open_date_str, open_time_str, "Open", errors)  # Store the computed value.
        close_dt = _parse_form_datetime(close_date_str, close_time_str, "Close", errors)  # Store the computed value.

        if open_dt and close_dt and close_dt <= open_dt:  # Check the current condition.
            errors.append("Close date/time must be later than the open date/time.")  # Append to the list.

        raw_questions_payload = request.POST.get("questions_payload", "")  # Fetch a single record.
        try:  # Start guarded parsing.
            initial_questions = json.loads(raw_questions_payload or "[]")  # Store the computed value.
        except json.JSONDecodeError:  # Handle the raised exception.
            initial_questions = []  # Store the computed value.

        question_payloads = _parse_questions_payload(raw_questions_payload, errors)  # Store the computed value.

        if not errors:  # Check the current condition.
            with transaction.atomic():  # Open the resource safely.
                quiz.title = title  # Store the computed value.
                quiz.description = description  # Store the computed value.
                quiz.open_datetime = open_dt  # Store the computed value.
                quiz.close_datetime = close_dt  # Store the computed value.
                quiz.time_limit_minutes = time_limit_minutes  # Store the computed value.
                quiz.max_attempts = max_attempts  # Store the computed value.
                quiz.max_mark = max_mark  # Store the computed value.
                quiz.is_published = is_published  # Store the boolean state.
                quiz.save(update_fields=[  # Save model changes.
                    "title",  # Continue the current value.
                    "description",  # Continue the current value.
                    "open_datetime",  # Continue the current value.
                    "close_datetime",  # Continue the current value.
                    "time_limit_minutes",  # Continue the current value.
                    "max_attempts",  # Continue the current value.
                    "max_mark",  # Continue the current value.
                    "is_published",  # Continue the current value.
                    "updated_at",  # Continue the current value.
                ])  # Close the current call.

                quiz.questions.all().delete()  # Delete the record.
                _create_quiz_questions(quiz, question_payloads)  # Call the helper function.

            messages.success(request, "Quiz updated successfully.")  # Queue a success message.
            return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    else:  # Handle the fallback case.
        initial_questions = _build_quiz_editor_initial_questions(quiz)  # Store the computed value.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": module,  # Set module.
        "quiz": quiz,  # Set quiz.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "title": request.POST.get("title", quiz.title) if request.method == "POST" else quiz.title,  # Fetch a single record.
            "description": request.POST.get("description", quiz.description) if request.method == "POST" else quiz.description,  # Fetch a single record.
            "open_date": request.POST.get("open_date", quiz.open_datetime.astimezone(timezone.get_current_timezone()).date().isoformat()) if request.method == "POST" else quiz.open_datetime.astimezone(timezone.get_current_timezone()).date().isoformat(),  # Fetch a single record.
            "open_time": request.POST.get("open_time", quiz.open_datetime.astimezone(timezone.get_current_timezone()).strftime("%H:%M")) if request.method == "POST" else quiz.open_datetime.astimezone(timezone.get_current_timezone()).strftime("%H:%M"),  # Fetch a single record.
            "close_date": request.POST.get("close_date", quiz.close_datetime.astimezone(timezone.get_current_timezone()).date().isoformat()) if request.method == "POST" else quiz.close_datetime.astimezone(timezone.get_current_timezone()).date().isoformat(),  # Fetch a single record.
            "close_time": request.POST.get("close_time", quiz.close_datetime.astimezone(timezone.get_current_timezone()).strftime("%H:%M")) if request.method == "POST" else quiz.close_datetime.astimezone(timezone.get_current_timezone()).strftime("%H:%M"),  # Fetch a single record.
            "time_limit_minutes": request.POST.get("time_limit_minutes", str(quiz.time_limit_minutes)) if request.method == "POST" else str(quiz.time_limit_minutes),  # Fetch a single record.
            "max_attempts": request.POST.get("max_attempts", str(quiz.max_attempts)) if request.method == "POST" else str(quiz.max_attempts),  # Fetch a single record.
            "max_mark": request.POST.get("max_mark", str(quiz.max_mark)) if request.method == "POST" else str(quiz.max_mark),  # Fetch a single record.
            "is_published": (request.POST.get("is_published") == "on") if request.method == "POST" else quiz.is_published,  # Fetch a single record.
        },  # Close the current mapping.
        "initial_questions": initial_questions,  # Set initial questions.
        "back_url": _safe_back_url(request, "accounts:offering_quiz_detail", offering.id, quiz.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/edit_quiz.html", context)  # Return the rendered template.


@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_delete_quiz(request, offering_id, quiz_id):  # Define offering_delete_quiz.
    """Handle offering delete quiz."""
    user: User = request.user  # Store the current user.
    offering = _get_writable_lecturer_offering_by_id(user, offering_id)  # Store the computed value.
    quiz = get_object_or_404(  # Store the computed value.
        Quiz.objects.select_related("offering__module"),  # Follow related objects.
        pk=quiz_id,  # Store the related id.
        offering=offering,  # Store the computed value.
    )  # Close the current call.

    if not _can_delete_quiz(quiz):  # Check the current condition.
        messages.error(request, "This quiz cannot be deleted while a student attempt is in progress.")  # Queue an error message.
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    quiz.delete()  # Delete the record.

    messages.success(request, "Quiz deleted successfully.")  # Queue a success message.
    return redirect("accounts:offering_detail", offering_id=offering.id)  # Return the redirect response.

@login_required  # Require login.
def offering_quiz_detail(request, offering_id, quiz_id):  # Define offering_quiz_detail.
    """Handle offering quiz detail."""
    user: User = request.user  # Store the current user.
    nav_items = _shared_nav_items()  # Build the list values.
    now = timezone.now()  # Store the computed value.

    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)  # Unpack returned values.
    module = offering.module  # Store the computed value.
    read_only = _is_read_only_offering(offering)  # Store the computed value.

    if user.is_lecturer():  # Check the current condition.
        question_rows = _build_question_rows(quiz)  # Build the list values.
        attempts = (  # Store the computed value.
            quiz.attempts  # Continue the current block.
            .select_related("student__user")  # Follow related objects.
            .order_by("-started_at")  # Order queryset results.
        )  # Close the current call.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": nav_items,  # Set nav items.
            "offering": offering,  # Set offering.
            "module": module,  # Set module.
            "quiz": quiz,  # Set quiz.
            "role": "lecturer",  # Set role.
            "read_only": read_only,  # Set read only.
            "question_rows": question_rows,  # Set question rows.
            "attempts": attempts,  # Set attempts.
            "can_edit_quiz": _can_edit_quiz(quiz, now=now),  # Set can edit quiz.
            "can_delete_quiz": _can_delete_quiz(quiz),  # Set can delete quiz.
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
        }  # Close the current mapping.
        return render(request, "accounts/quiz_detail.html", context)  # Return the rendered template.

    if user.is_student():  # Check the current condition.
        student = user.student_profile  # Store the computed value.

        if not quiz.is_published:  # Check the current condition.
            raise Http404("Quiz not found")  # Raise a not found error.

        if not read_only:  # Check the current condition.
            _auto_submit_expired_attempt_if_needed(quiz, student)  # Call the helper function.

        now = timezone.now()  # Store the computed value.
        state = _get_student_quiz_state(quiz, student, now=now)  # Store the computed value.
        active_attempt = state["active_attempt"] if not read_only else None  # Store the computed value.
        latest_submitted_attempt = state["latest_submitted_attempt"]  # Store the computed value.
        quiz_results_released = _quiz_results_released(quiz, now=now)  # Store the computed value.

        can_start_attempt = (  # Store the boolean state.
            not read_only  # Continue the current block.
            and quiz.is_published  # Continue the current block.
            and now >= quiz.open_datetime  # Continue the current block.
            and now <= quiz.close_datetime  # Continue the current block.
            and active_attempt is None  # Continue the current block.
            and state["attempts_used"] < quiz.max_attempts  # Continue the current block.
        )  # Close the current call.

        question_rows = []  # Build the list values.
        remaining_seconds = 0  # Store the computed value.

        if active_attempt:  # Check the current condition.
            question_rows = _build_question_rows(quiz, attempt=active_attempt)  # Build the list values.
            remaining_seconds = max(  # Store the computed value.
                0,  # Continue the current value.
                int((active_attempt.expires_at - now).total_seconds())  # Call the helper function.
            )  # Close the current call.
        elif latest_submitted_attempt and quiz_results_released:  # Check the alternate condition.
            question_rows = _build_question_rows(quiz, attempt=latest_submitted_attempt)  # Build the list values.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": nav_items,  # Set nav items.
            "offering": offering,  # Set offering.
            "module": module,  # Set module.
            "quiz": quiz,  # Set quiz.
            "role": "student",  # Set role.
            "read_only": read_only,  # Set read only.
            "state": state,  # Set state.
            "active_attempt": active_attempt,  # Set active attempt.
            "submitted_attempt": latest_submitted_attempt,  # Set submitted attempt.
            "quiz_results_released": quiz_results_released,  # Set quiz results released.
            "can_start_attempt": can_start_attempt,  # Set can start attempt.
            "question_rows": question_rows,  # Set question rows.
            "remaining_seconds": remaining_seconds,  # Set remaining seconds.
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
        }  # Close the current mapping.
        return render(request, "accounts/quiz_detail.html", context)  # Return the rendered template.

    return redirect("accounts:login")  # Return the redirect response.

@login_required  # Require login.
def offering_assignment_detail(request, offering_id, assignment_id):  # Define offering_assignment_detail.
    """Handle offering assignment detail."""
    user: User = request.user  # Store the current user.

    offering, assignment = _get_accessible_offering_assignment_for_user(user, offering_id, assignment_id)  # Unpack returned values.
    module = offering.module  # Store the computed value.
    read_only = _is_read_only_offering(offering)  # Store the computed value.
    now = timezone.now()  # Store the computed value.

    if user.is_student():  # Check the current condition.
        student = user.student_profile  # Store the computed value.

        submission = (  # Store the computed value.
            AssignmentSubmission.objects  # Continue the current block.
            .filter(assignment=assignment, student=student)  # Filter queryset records.
            .select_related("grade")  # Follow related objects.
            .prefetch_related("files")  # Prefetch related objects.
            .first()  # Return the first result.
        )  # Close the current call.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": _shared_nav_items(),  # Set nav items.
            "offering": offering,  # Set offering.
            "module": module,  # Set module.
            "assignment": assignment,  # Set assignment.
            "role": "student",  # Set role.
            "read_only": read_only,  # Set read only.
            "submission": submission,  # Set submission.
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
        }  # Close the current mapping.
        template = "accounts/assignment_detail.html"  # Store the computed value.

    elif user.is_lecturer():  # Check the alternate condition.
        submissions = (  # Store the computed value.
            AssignmentSubmission.objects  # Continue the current block.
            .filter(assignment=assignment)  # Filter queryset records.
            .select_related("student__user", "grade")  # Follow related objects.
            .prefetch_related("files")  # Prefetch related objects.
            .order_by("-submitted_at")  # Order queryset results.
        )  # Close the current call.

        context = {  # Build template context.
            "user": user,  # Set user.
            "nav_items": _shared_nav_items(),  # Set nav items.
            "offering": offering,  # Set offering.
            "module": module,  # Set module.
            "assignment": assignment,  # Set assignment.
            "role": "lecturer",  # Set role.
            "read_only": read_only,  # Set read only.
            "submissions": submissions,  # Set submissions.
            "can_edit_assignment": _can_edit_assignment(assignment, now=now),  # Set can edit assignment.
            "can_delete_assignment": True,  # Set can delete assignment.
            "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
        }  # Close the current mapping.
        template = "accounts/assignment_detail.html"  # Store the computed value.

    else:  # Handle the fallback case.
        return redirect("accounts:login")  # Return the redirect response.

    return render(request, template, context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_start_quiz_attempt(request, offering_id, quiz_id):  # Define offering_start_quiz_attempt.
    """Handle offering start quiz attempt."""
    user: User = request.user  # Store the current user.
    if not user.is_student():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    student = user.student_profile  # Store the computed value.
    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)  # Unpack returned values.

    if _is_read_only_offering(offering):  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    now = timezone.now()  # Store the computed value.
    if now < quiz.open_datetime or now > quiz.close_datetime:  # Check the current condition.
        messages.error(request, "This quiz is not currently open.")  # Queue an error message.
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    existing_active_attempt = (  # Store the computed value.
        quiz.attempts  # Continue the current block.
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)  # Filter queryset records.
        .order_by("-attempt_number")  # Order queryset results.
        .first()  # Return the first result.
    )  # Close the current call.
    if existing_active_attempt:  # Check the current condition.
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    attempts_used = quiz.attempts.filter(student=student).count()  # Filter queryset records.
    if attempts_used >= quiz.max_attempts:  # Check the current condition.
        messages.error(request, "You have used all available attempts for this quiz.")  # Queue an error message.
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    requested_expiry = now + timedelta(minutes=quiz.time_limit_minutes)  # Store the computed value.
    expires_at = min(requested_expiry, quiz.close_datetime)  # Store the computed value.

    QuizAttempt.objects.create(  # Create a database record.
        quiz=quiz,  # Store the computed value.
        student=student,  # Store the computed value.
        attempt_number=attempts_used + 1,  # Store the computed value.
        expires_at=expires_at,  # Store the computed value.
        status=QuizAttempt.Status.IN_PROGRESS,  # Store the computed value.
    )  # Close the current call.

    return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_save_quiz_progress(request, offering_id, quiz_id):  # Define offering_save_quiz_progress.
    """Handle offering save quiz progress."""
    user: User = request.user  # Store the current user.
    if not user.is_student():  # Check the current condition.
        return JsonResponse({"ok": False}, status=403)  # Return a JSON response.

    student = user.student_profile  # Store the computed value.
    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)  # Unpack returned values.

    if _is_read_only_offering(offering):  # Check the current condition.
        return JsonResponse({"ok": False}, status=404)  # Return a JSON response.

    attempt = (  # Store the computed value.
        quiz.attempts  # Continue the current block.
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)  # Filter queryset records.
        .order_by("-attempt_number")  # Order queryset results.
        .first()  # Return the first result.
    )  # Close the current call.
    if attempt is None:  # Check the current condition.
        return JsonResponse({"ok": False, "message": "No active attempt found."}, status=404)  # Return a JSON response.

    if attempt.is_expired():  # Check the current condition.
        _grade_attempt(attempt, auto_submitted=True)  # Call the helper function.
        return JsonResponse({"ok": False, "expired": True}, status=409)  # Return a JSON response.

    _upsert_attempt_answers(attempt, request.POST)  # Call the helper function.
    return JsonResponse({"ok": True})  # Return a JSON response.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_submit_quiz_attempt(request, offering_id, quiz_id):  # Define offering_submit_quiz_attempt.
    """Handle offering submit quiz attempt."""
    user: User = request.user  # Store the current user.
    if not user.is_student():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    student = user.student_profile  # Store the computed value.
    offering, quiz = _get_accessible_offering_quiz_for_user(user, offering_id, quiz_id)  # Unpack returned values.

    if _is_read_only_offering(offering):  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    attempt = (  # Store the computed value.
        quiz.attempts  # Continue the current block.
        .filter(student=student, status=QuizAttempt.Status.IN_PROGRESS)  # Filter queryset records.
        .order_by("-attempt_number")  # Order queryset results.
        .first()  # Return the first result.
    )  # Close the current call.
    if attempt is None:  # Check the current condition.
        messages.error(request, "No active quiz attempt was found.")  # Queue an error message.
        return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

    _upsert_attempt_answers(attempt, request.POST)  # Call the helper function.
    _grade_attempt(attempt, auto_submitted=attempt.is_expired())  # Call the helper function.

    messages.success(request, "Quiz submitted successfully.")  # Queue a success message.
    return redirect("accounts:offering_quiz_detail", offering_id=offering.id, quiz_id=quiz.id)  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["POST"])  # Restrict allowed HTTP methods.
def offering_submit_assignment(request, offering_id, assignment_id):  # Define offering_submit_assignment.
    """Handle offering submit assignment."""
    user: User = request.user  # Store the current user.
    if not user.is_student():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    student = user.student_profile  # Store the computed value.
    offering, assignment = _get_accessible_offering_assignment_for_user(user, offering_id, assignment_id)  # Unpack returned values.

    if _is_read_only_offering(offering):  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    uploaded_files = request.FILES.getlist("files")  # Read repeated form values.

    validation_errors = [  # Initialise error messages.
        error  # Continue the current block.
        for uploaded in uploaded_files  # Iterate through the collection.
        if (error := _validate_student_submission_upload(uploaded))  # Check the current condition.
    ]  # Close the current list.

    if validation_errors:  # Check the current condition.
        for error in validation_errors:  # Iterate through the collection.
            messages.error(request, error)  # Queue an error message.

        return redirect(  # Return the redirect response.
            "accounts:offering_assignment_detail",  # Continue the current value.
            offering_id=offering.id,  # Store the related id.
            assignment_id=assignment.id,  # Store the related id.
        )  # Close the current call.

    submission, created = AssignmentSubmission.objects.get_or_create(  # Unpack returned values.
        assignment=assignment,  # Store the computed value.
        student=student,  # Store the computed value.
        defaults={"status": AssignmentSubmission.Status.SUBMITTED},  # Store the computed value.
    )  # Close the current call.

    now = timezone.now()  # Store the computed value.
    if assignment.due_datetime and now > assignment.due_datetime:  # Check the current condition.
        submission.status = AssignmentSubmission.Status.LATE  # Store the computed value.
    else:  # Handle the fallback case.
        submission.status = AssignmentSubmission.Status.SUBMITTED  # Store the computed value.
    submission.submitted_at = now  # Store the computed value.
    submission.save()  # Save model changes.

    for uploaded in uploaded_files:  # Iterate through the collection.
        SubmissionFile.objects.create(  # Create a database record.
            submission=submission,  # Store the computed value.
            file=uploaded,  # Store the computed value.
            original_name=uploaded.name,  # Store the computed value.
            uploaded_by=user,  # Store the computed value.
        )  # Close the current call.

    _notify_student_assignment_submitted(submission)  # Call the helper function.

    return redirect("accounts:offering_assignment_detail", offering_id=offering.id, assignment_id=assignment.id)  # Return the redirect response.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def offering_grade_submission(request, offering_id, assignment_id, submission_id):  # Define offering_grade_submission.
    """Handle offering grade submission."""
    user: User = request.user  # Store the current user.
    if not user.is_lecturer():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    lecturer = user.lecturer_profile  # Store the computed value.
    offering, assignment = _get_accessible_offering_assignment_for_user(user, offering_id, assignment_id)  # Unpack returned values.

    if _is_read_only_offering(offering):  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    submission = get_object_or_404(  # Store the computed value.
        AssignmentSubmission.objects.select_related("student__user"),  # Follow related objects.
        pk=submission_id,  # Store the computed value.
        assignment=assignment,  # Store the computed value.
    )  # Close the current call.

    errors = []  # Initialise error messages.
    grade_obj = getattr(submission, "grade", None)  # Store the computed value.
    initial_value = ""  # Store the computed value.
    initial_feedback = ""  # Store the computed value.

    if grade_obj:  # Check the current condition.
        initial_value = grade_obj.value  # Store the computed value.
        initial_feedback = grade_obj.feedback_text or ""  # Store the computed value.

    if request.method == "POST":  # Check the current condition.
        value_str = request.POST.get("value", "").strip()  # Fetch a single record.
        feedback = request.POST.get("feedback", "").strip()  # Fetch a single record.

        if not value_str:  # Check the current condition.
            errors.append("A mark is required.")  # Append to the list.
        else:  # Handle the fallback case.
            try:  # Start guarded parsing.
                value_float = float(value_str)  # Store the computed value.
            except ValueError:  # Handle the raised exception.
                errors.append("Mark must be a number.")  # Append to the list.
                value_float = None  # Store the computed value.

        if not errors and value_float is not None:  # Check the current condition.
            if grade_obj is None:  # Check the current condition.
                grade_obj = AssignmentGrade.objects.create(  # Create a database record.
                    submission=submission,  # Store the computed value.
                    marker=lecturer,  # Store the computed value.
                    value=value_float,  # Store the computed value.
                    feedback_text=feedback,  # Store the computed value.
                )  # Close the current call.
            else:  # Handle the fallback case.
                grade_obj.value = value_float  # Store the computed value.
                grade_obj.feedback_text = feedback  # Store the computed value.
                grade_obj.marker = lecturer  # Store the computed value.
                grade_obj.save()  # Save model changes.

            _notify_student_assignment_graded(grade_obj)  # Call the helper function.

            return redirect(  # Return the redirect response.
                "accounts:offering_assignment_detail",  # Continue the current value.
                offering_id=offering.id,  # Store the related id.
                assignment_id=assignment.id,  # Store the related id.
            )  # Close the current call.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "offering": offering,  # Set offering.
        "module": offering.module,  # Set module.
        "assignment": assignment,  # Set assignment.
        "submission": submission,  # Set submission.
        "errors": errors,  # Set errors.
        "initial": {  # Set initial.
            "value": request.POST.get("value", initial_value) if request.method == "POST" else initial_value,  # Fetch a single record.
            "feedback": request.POST.get("feedback", initial_feedback) if request.method == "POST" else initial_feedback,  # Fetch a single record.
        },  # Close the current mapping.
        "back_url": _safe_back_url(request, "accounts:offering_assignment_detail", offering.id, assignment.id),  # Set back url.
    }  # Close the current mapping.

    return render(request, "accounts/grade_submission.html", context)  # Return the rendered template.

# ===========
# Modal Views
# ===========
@login_required  # Require login.
@require_http_methods(["GET"])  # Restrict allowed HTTP methods.
def parsed_document_modal(request, parsed_id):  # Define parsed_document_modal.
    """Render the parsed document modal."""
    user: User = request.user  # Store the current user.
    parsed_document, offering, module = _get_authorised_parsed_document(parsed_id, user)  # Unpack returned values.
    source_file = parsed_document.get_source_file()  # Store the uploaded file.

    context = {  # Build template context.
        "parsed_document": parsed_document,  # Set parsed document.
        "module": module,  # Set module.
        "source_file": source_file,  # Set source file.
        "document_title": parsed_document.get_source_name(),  # Set document title.
        "can_edit_images": user.is_lecturer() and not _is_read_only_offering(offering),  # Set can edit images.
    }  # Close the current mapping.
    return render(request, "accounts/partials/parsed_document_modal.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET"])  # Restrict allowed HTTP methods.
def global_announcement_modal(request, announcement_id):  # Define global_announcement_modal.
    """Render the global announcement modal."""
    announcement = get_object_or_404(GlobalAnnouncement, pk=announcement_id)  # Store the computed value.

    if request.user.is_admin():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    context = {  # Build template context.
        "announcement": announcement,  # Set announcement.
        "scope_label": "Global Announcement",  # Set scope label.
    }  # Close the current mapping.
    return render(request, "accounts/partials/announcement_modal.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET"])  # Restrict allowed HTTP methods.
def offering_module_announcement_modal(request, offering_id, announcement_id):  # Define offering_module_announcement_modal.
    """Render the module announcement modal."""
    offering = _get_accessible_offering_for_user(request.user, offering_id)  # Store the computed value.
    announcement = get_object_or_404(ModuleAnnouncement, pk=announcement_id, offering=offering)  # Store the computed value.

    context = {  # Build template context.
        "announcement": announcement,  # Set announcement.
        "scope_label": f"{offering.module.code} Announcement",  # Set scope label.
    }  # Close the current mapping.
    return render(request, "accounts/partials/announcement_modal.html", context)  # Return the rendered template.

@login_required  # Require login.
@require_http_methods(["GET", "POST"])  # Restrict allowed HTTP methods.
def edit_parsed_document_images(request, parsed_id):  # Define edit_parsed_document_images.
    """Handle parsed document image edits."""
    user: User = request.user  # Store the current user.
    if not user.is_lecturer():  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    parsed_document, offering, module = _get_authorised_parsed_document(parsed_id, user)  # Unpack returned values.

    if _is_read_only_offering(offering):  # Check the current condition.
        raise Http404("Not found")  # Raise a not found error.

    if request.method == "POST":  # Check the current condition.
        for image in parsed_document.images.all():  # Iterate through the collection.
            image.alt_text = request.POST.get(f"alt_{image.id}", "").strip()  # Fetch a single record.
            image.save(update_fields=["alt_text"])  # Save model changes.

        _rebuild_parsed_document_html(parsed_document, save=True)  # Call the helper function.
        messages.success(request, "Image descriptions updated successfully.")  # Queue a success message.

        return redirect("accounts:edit_parsed_document_images", parsed_id=parsed_document.id)  # Return the redirect response.

    context = {  # Build template context.
        "user": user,  # Set user.
        "nav_items": _shared_nav_items(),  # Set nav items.
        "module": module,  # Set module.
        "offering": offering,  # Set offering.
        "parsed_document": parsed_document,  # Set parsed document.
        "back_url": _safe_back_url(request, "accounts:offering_detail", offering.id),  # Set back url.
    }  # Close the current mapping.
    return render(request, "accounts/edit_parsed_document_images.html", context)  # Return the rendered template.

# ====================
# Registration Helpers
# ====================
def _validate_password_strength(password: str, user: User | None = None) -> list[str]:  # Define _validate_password_strength.
    """Validate password strength."""
    errors: list[str] = []  # Initialise error messages.

    if not re.search(r"[A-Z]", password):  # Check the current condition.
        errors.append("Password must contain at least one uppercase letter.")  # Append to the list.
    if not re.search(r"\d", password):  # Check the current condition.
        errors.append("Password must contain at least one number.")  # Append to the list.
    if not re.search(r"[^\w\s]", password):  # Check the current condition.
        errors.append("Password must contain at least one special character (e.g. !, @, #).")  # Append to the list.

    try:  # Start guarded parsing.
        validate_password(password, user=user)  # Call the helper function.
    except DjangoValidationError as exc:  # Handle the validation error.
        errors.extend(exc.messages)  # Extend the list.

    return errors  # Return the computed value.

def _get_all_valid_courses() -> list[str]:  # Define _get_all_valid_courses.
    """Return all valid courses."""
    return list(  # Return the computed value.
        Course.objects.filter(is_active=True)  # Filter queryset records.
        .order_by("code")  # Order queryset results.
        .values_list("code", flat=True)  # Select field values.
    )  # Close the current call.

COURSE_CODE_RE = re.compile(r"^[A-Z0-9]{3,10}$")  # Store the computed value.

def _normalize_course_code(raw: str) -> str:  # Define _normalize_course_code.
    """
    Normalize user-entered course code:
    - strip whitespace
    - remove internal spaces
    - uppercase
    """
    raw = (raw or "").strip().upper()  # Trim surrounding whitespace.
    raw = raw.replace(" ", "")  # Store the computed value.
    return raw  # Return the computed value.

def _build_registration_module_rows() -> list[dict]:  # Define _build_registration_module_rows.
    """Build registration module rows."""
    return _build_module_selector_rows()  # Return the computed value.
