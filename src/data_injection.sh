#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Auto Activate Venv (supports /srv/eagna/src and /srv/eagna)
if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "../venv/bin/activate" ]; then
  source ../venv/bin/activate
fi

python manage.py migrate
echo "Seeding Demo Dataset (1 student, 8 lecturers, 8 modules)..."

python manage.py shell << 'PY'
from apps.accounts.models import (
    User,
    StudentProfile,
    LecturerProfile,
    Module,
    ModuleEnrollmentStudent,
    ModuleEnrollmentLecturer,
)

# -----------------------------
# CONFIG (edit these)
# -----------------------------

COURSE_CODE = "TU856"  # 3–10 chars, letters/numbers only (matches your registration validation)

# Student (you)
STUDENT_EMAIL = "C20441826@mytudublin.ie"
STUDENT_FIRST_NAME = "Conor"
STUDENT_LAST_NAME = "Davis"
STUDENT_NUMBER = "C20441826"
STUDENT_PASSWORD = "DevPass123!"  # new password rules

# Lecturer password (shared for demo)
LECTURER_PASSWORD = "DevPass123!"

LECTURER_NAMES = [
    ("Aoife", "Murphy"),
    ("Eoin", "Rogers"),
    ("Niamh", "Kelly"),
    ("Cian", "Byrne"),
    ("Saoirse", "Walsh"),
    ("Eoin", "Ryan"),
    ("Ciara", "Dunne"),
    ("Darragh", "Fitzgerald"),
]

# 8 module definitions: (code, title)
MODULE_DEFS = [
    ("CMPU4032", "Enterprise Application Development"),
    ("CMPU4003", "Advanced Databases"),
    ("CMPU4008", "Advanced Security II"),
    ("CMPU4028", "Forensics"),
    ("CMPU4043", "Rich Web Application Technology"),
    ("CMPU4007", "Advanced Security I"),
    ("CMPU4051", "Systems Software"),
    ("CMPU4091", "Visualizing Data"),
]

# If your Module has start_date/end_date fields (after your rollover changes),
# these default dates will be used. End date may be in next year (Sep→May).
DEFAULT_START_DATE = date(2025, 9, 1)
DEFAULT_END_DATE   = date(2026, 5, 31)

# -----------------------------
# Helpers
# -----------------------------

def has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
        return True
    except FieldDoesNotExist:
        return False

def allowed_courses_value_for_model(course_code: str):
    """
    allowed_courses is intended to be a JSON list in your design.
    If it is a JSONField, store [course_code].
    If it’s still a CharField (older), store the raw string as a fallback.
    """
    f = Module._meta.get_field("allowed_courses")
    internal = f.get_internal_type()
    if internal == "JSONField":
        return [course_code]
    return course_code

@transaction.atomic
def main():
    # Safety: refuse to seed if non-empty (prevents UNIQUE constraint spam)
    if User.objects.exists() or Module.objects.exists():
        raise SystemExit(
            "ERROR: Users or Modules already exist. Clear the database (or run flush) before seeding."
        )

    print("Creating Student User and Profile...")
    student_user = User.objects.create_user(
        username=STUDENT_EMAIL,
        email=STUDENT_EMAIL,
        password=STUDENT_PASSWORD,
        first_name=STUDENT_FIRST_NAME,
        last_name=STUDENT_LAST_NAME,
        role=User.Role.STUDENT,
    )

    student_profile = StudentProfile.objects.create(
        user=student_user,
        student_number=STUDENT_NUMBER,
        course=COURSE_CODE,
    )

    print(f"  -> Student: {student_user.first_name} / Student Number: {STUDENT_NUMBER} / Course: {COURSE_CODE}")

    print("Creating Modules and Lecturer Users...")

    for idx, (mod_code, mod_title) in enumerate(MODULE_DEFS, start=1):
        # Lecturer account + profile
        first_name, last_name = LECTURER_NAMES[idx - 1]
        lect_email = f"{first_name.lower()}.{last_name.lower()}@tudublin.ie"

        lect_user = User.objects.create_user(
            username=lect_email,          # your system uses username as login identifier
            email=lect_email,
            password=LECTURER_PASSWORD,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.LECTURER,
        )
        lect_profile = LecturerProfile.objects.create(
            user=lect_user,
            staff_id=f"L{idx:04d}",
        )

        # Module fields (adaptive: works before/after your rollover schema change)
        module_kwargs = {
            "code": mod_code,
            "title": mod_title,
            "is_active": True,
            "allowed_courses": allowed_courses_value_for_model(COURSE_CODE),
        }

        # Older schema fields
        if has_field(Module, "academic_year_start"):
            module_kwargs["academic_year_start"] = 2025
        if has_field(Module, "semester"):
            module_kwargs["semester"] = 1  # not used if you remove it later

        # New rollover schema fields (if present)
        if has_field(Module, "start_date"):
            module_kwargs["start_date"] = DEFAULT_START_DATE
        if has_field(Module, "end_date"):
            module_kwargs["end_date"] = DEFAULT_END_DATE
        if has_field(Module, "last_rollover_year"):
            module_kwargs["last_rollover_year"] = 0

        module = Module.objects.create(**module_kwargs)

        # Link lecturer to module (keep lecturer permanently)
        ModuleEnrollmentLecturer.objects.create(
            module=module,
            lecturer=lect_profile,
            is_primary=True,
        )

        # Enrol student in module
        ModuleEnrollmentStudent.objects.create(
            module=module,
            student=student_profile,
        )

        print(f"  -> {module.code}: Lecturer: {lect_user.username} | Module: {mod_title}")

    print("\nCompleted! Demo dataset created with 1 student and 8 lecturers / modules.")
    print("Student Login:")
    print(f"  Username: {STUDENT_EMAIL}")
    print(f"  Password: {STUDENT_PASSWORD}")
    print("\nLecturer Logins:")
    print(f"  Password: {LECTURER_PASSWORD}")
    for idx, (mod_code, mod_title) in enumerate(MODULE_DEFS, start=1):
        fn, ln = LECTURER_NAMES[idx - 1]
        print(f"  {fn.lower()}.{ln.lower()}@tudublin.ie teaches {mod_code} - {mod_title}")

main()
PY

echo "Seed complete."