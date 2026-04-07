#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f "venv/bin/activate" ]; then
  source venv/bin/activate
elif [ -f "../venv/bin/activate" ]; then
  source ../venv/bin/activate
fi

python manage.py migrate
echo "Seeding Demo Dataset (1 student, 8 lecturers, 8 modules, offerings)..."

python manage.py shell << 'PY'
from datetime import date
from django.db import transaction

from apps.accounts.models import (
    User,
    StudentProfile,
    LecturerProfile,
    Course,
    AcademicYear,
    Module,
    ModulePlacement,
    ModuleOffering,
    ModuleOfferingEnrollmentStudent,
    ModuleOfferingEnrollmentLecturer,
)

COURSE_CODE = "TU856"
COURSE_TITLE = "BSc in Computer Science"
COURSE_LENGTH = 4

ACADEMIC_YEAR_START = date(2025, 9, 1)
ACADEMIC_YEAR_END = date(2026, 5, 31)

STUDENT_EMAIL = "c20441826@mytudublin.ie"
STUDENT_FIRST_NAME = "Conor"
STUDENT_LAST_NAME = "Davis"
STUDENT_NUMBER = "C20441826"
STUDENT_PASSWORD = "DevPass123!"

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

@transaction.atomic
def main():
    if User.objects.exists() or Module.objects.exists() or Course.objects.exists():
        raise SystemExit(
            "ERROR: Users, Modules, or Courses already exist. Clear the database before seeding."
        )

    course = Course.objects.create(
        code=COURSE_CODE,
        title=COURSE_TITLE,
        length_years=COURSE_LENGTH,
        is_active=True,
    )

    academic_year = AcademicYear.objects.create(
        label=f"{ACADEMIC_YEAR_START.year}/{str(ACADEMIC_YEAR_END.year)[-2:]}",
        start_date=ACADEMIC_YEAR_START,
        end_date=ACADEMIC_YEAR_END,
        is_current=True,
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
        status=StudentProfile.Status.ACTIVE,
    )

    print(f"  -> Student: {student_user.first_name} / Student Number: {STUDENT_NUMBER} / Course: {COURSE_CODE}")

    print("Creating Modules, Placements, Offerings, and Lecturer Users...")

    for idx, (mod_code, mod_title) in enumerate(MODULE_DEFS, start=1):
        first_name, last_name = LECTURER_NAMES[idx - 1]
        lect_email = f"{first_name.lower()}.{last_name.lower()}@tudublin.ie"

        lect_user = User.objects.create_user(
            username=lect_email,
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

        module = Module.objects.create(
            code=mod_code,
            title=mod_title,
            is_active=True,
        )

        placement = ModulePlacement.objects.create(
            module=module,
            course=course,
            year_number=1,
            available_now=True,
            available_next_rollover=True,
        )

        offering = ModuleOffering.objects.create(
            placement=placement,
            academic_year=academic_year,
            is_current=True,
            is_read_only=False,
        )

        ModuleOfferingEnrollmentLecturer.objects.create(
            offering=offering,
            lecturer=lect_profile,
            is_primary=True,
        )

        ModuleOfferingEnrollmentStudent.objects.create(
            offering=offering,
            student=student_profile,
        )

        print(f"  -> {module.code}: Lecturer: {lect_user.username} | Module: {mod_title}")

    print("\nCompleted! Demo dataset created with 1 student and 8 lecturers / modules / offerings.")
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