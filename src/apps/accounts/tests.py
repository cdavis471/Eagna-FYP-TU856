from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import (
    AcademicYear,
    Assignment,
    AssignmentSubmission,
    Course,
    LecturerProfile,
    Module,
    ModuleOffering,
    ModuleOfferingEnrollmentLecturer,
    ModuleOfferingEnrollmentStudent,
    ModulePlacement,
    StudentProfile,
)

User = get_user_model()

@override_settings(SECURE_SSL_REDIRECT=False)
class EagnaBaseTestCase(TestCase):
    def create_academic_year(
        self,
        *,
        label: str,
        start_date: date,
        end_date: date,
        is_current: bool,
    ) -> AcademicYear:
        return AcademicYear.objects.create(
            label=label,
            start_date=start_date,
            end_date=end_date,
            is_current=is_current,
        )

    def create_course(self, code: str = "TU856", title: str = "Computing") -> Course:
        return Course.objects.create(code=code, title=title, length_years=4, is_active=True)

    def create_module(self, code: str, title: str) -> Module:
        return Module.objects.create(code=code, title=title, is_active=True)

    def place_module_on_course(self, module: Module, course: Course) -> ModulePlacement:
        return ModulePlacement.objects.create(
            module=module,
            course=course,
            available_now=True,
            available_next_rollover=True,
        )

    def create_student(self, *, email: str, course_code: str = "TU856") -> User:
        user = User.objects.create_user(
            username=email,
            email=email,
            password="StrongPass!23",
            first_name="Conor",
            last_name="Student",
            role=User.Role.STUDENT,
        )
        StudentProfile.objects.create(
            user=user,
            student_number=email.split("@")[0],
            course=course_code,
            status=StudentProfile.Status.ACTIVE,
        )
        return user

    def create_lecturer(self, *, email: str = "lecturer@tudublin.ie") -> User:
        user = User.objects.create_user(
            username=email,
            email=email,
            password="StrongPass!23",
            first_name="Aoife",
            last_name="Lecturer",
            role=User.Role.LECTURER,
        )
        LecturerProfile.objects.create(
            user=user,
            staff_id="L001",
        )
        return user

    def create_offering(
        self,
        *,
        module: Module,
        academic_year: AcademicYear,
        is_current: bool,
        is_read_only: bool = False,
    ) -> ModuleOffering:
        return ModuleOffering.objects.create(
            module=module,
            academic_year=academic_year,
            is_current=is_current,
            is_read_only=is_read_only,
        )

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Unit Test I - Confirm Valid Student Registration
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class RegistrationTests(EagnaBaseTestCase):
    def test_registration_creates_student_profile_and_current_enrolments(self):
        current_year = self.create_academic_year(
            label="2025/26",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        course = self.create_course(code="TU856")

        module_one = self.create_module(code="CMPU1010", title="Web Development")
        module_two = self.create_module(code="CMPU1020", title="Databases")
        self.place_module_on_course(module_one, course)
        self.place_module_on_course(module_two, course)

        response = self.client.post(
            reverse("accounts:register"),
            {
                "first_name": "Conor",
                "last_name": "Davis",
                "email": "c20441826@mytudublin.ie",
                "password1": "StrongPass!23",
                "password2": "StrongPass!23",
                "course": "tu856",
                "module_ids": [str(module_one.id), str(module_two.id)],
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))

        user = User.objects.get(username="c20441826@mytudublin.ie")
        self.assertEqual(user.role, User.Role.STUDENT)
        self.assertEqual(user.student_profile.student_number, "c20441826")
        self.assertEqual(user.student_profile.course, "TU856")

        enrolments = ModuleOfferingEnrollmentStudent.objects.filter(
            student=user.student_profile,
            offering__academic_year=current_year,
            offering__is_current=True,
        )
        self.assertEqual(enrolments.count(), 2)
        self.assertSetEqual(
            set(enrolments.values_list("offering__module__code", flat=True)),
            {"CMPU1010", "CMPU1020"},
        )

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Unit Test II - Access Control Testing - Grading View Permissions
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AccessControlTests(EagnaBaseTestCase):
    def setUp(self):
        self.current_year = self.create_academic_year(
            label="2025/26",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        self.course = self.create_course(code="TU856")
        self.module = self.create_module(code="CMPU2010", title="Software Engineering")
        self.place_module_on_course(self.module, self.course)

        self.offering = self.create_offering(
            module=self.module,
            academic_year=self.current_year,
            is_current=True,
        )

        self.student_user = self.create_student(email="c11111111@mytudublin.ie")
        self.lecturer_user = self.create_lecturer()

        ModuleOfferingEnrollmentStudent.objects.create(
            offering=self.offering,
            student=self.student_user.student_profile,
        )
        ModuleOfferingEnrollmentLecturer.objects.create(
            offering=self.offering,
            lecturer=self.lecturer_user.lecturer_profile,
            is_primary=True,
        )

        self.assignment = Assignment.objects.create(
            offering=self.offering,
            title="CA 1",
            description="Upload one file",
            due_datetime="2026-01-15T12:00:00Z",
            max_mark=100,
        )
        self.submission = AssignmentSubmission.objects.create(
            assignment=self.assignment,
            student=self.student_user.student_profile,
        )

    def test_student_cannot_access_lecturer_grading_view(self):
        self.client.force_login(self.student_user)

        response = self.client.get(
            reverse(
                "accounts:offering_grade_submission",
                args=[self.offering.id, self.assignment.id, self.submission.id],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_lecturer_can_access_grading_view_for_their_own_offering(self):
        self.client.force_login(self.lecturer_user)

        response = self.client.get(
            reverse(
                "accounts:offering_grade_submission",
                args=[self.offering.id, self.assignment.id, self.submission.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["submission"].id, self.submission.id)
        self.assertEqual(response.context["assignment"].id, self.assignment.id)

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Unit Test III - Academic Year Visibility - Check Separation of Current Year / Previous Years
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AcademicYearVisibilityTests(EagnaBaseTestCase):
    def test_student_dashboard_separates_current_and_previous_year_modules(self):
        current_year = self.create_academic_year(
            label="2025/26",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 8, 31),
            is_current=True,
        )
        previous_year = self.create_academic_year(
            label="2024/25",
            start_date=date(2024, 9, 1),
            end_date=date(2025, 8, 31),
            is_current=False,
        )
        course = self.create_course(code="TU856")

        current_module = self.create_module(code="CMPU3010", title="Current Module")
        previous_module = self.create_module(code="CMPU3020", title="Previous Module")
        self.place_module_on_course(current_module, course)
        self.place_module_on_course(previous_module, course)

        current_offering = self.create_offering(
            module=current_module,
            academic_year=current_year,
            is_current=True,
        )
        previous_offering = self.create_offering(
            module=previous_module,
            academic_year=previous_year,
            is_current=False,
            is_read_only=True,
        )

        student_user = self.create_student(email="c22222222@mytudublin.ie")

        ModuleOfferingEnrollmentStudent.objects.create(
            offering=current_offering,
            student=student_user.student_profile,
        )
        ModuleOfferingEnrollmentStudent.objects.create(
            offering=previous_offering,
            student=student_user.student_profile,
        )

        self.client.force_login(student_user)
        response = self.client.get(reverse("accounts:dashboard"))

        self.assertEqual(response.status_code, 200)

        current_rows = response.context["current_module_rows"]
        previous_year_groups = response.context["previous_year_groups"]

        self.assertEqual(len(current_rows), 1)
        self.assertEqual(current_rows[0]["module_code"], "CMPU3010")

        self.assertEqual(len(previous_year_groups), 1)
        self.assertEqual(previous_year_groups[0]["academic_year_label"], "2024/25")
        previous_codes = {
            row["module_code"]
            for row in previous_year_groups[0]["module_rows"]
        }
        self.assertSetEqual(previous_codes, {"CMPU3020"})

# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# Unit Test IV - Confirm Accessibility Value & Unsafe Redirect Handling
# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
class AccessibilityPreferenceTests(EagnaBaseTestCase):
    def test_invalid_accessibility_values_fall_back_to_defaults_and_ignore_unsafe_redirect(self):
        student_user = self.create_student(email="c33333333@mytudublin.ie")
        self.client.force_login(student_user)

        response = self.client.post(
            reverse("accounts:update_accessibility_preferences"),
            {
                "colour_scheme": "totally-invalid",
                "font_scheme": "also-invalid",
                "next": "https://evil.example.com/phish",
            },
        )

        self.assertRedirects(response, reverse("accounts:dashboard"))

        student_user.refresh_from_db()
        self.assertEqual(student_user.colour_scheme, User.ColourScheme.DEFAULT)
        self.assertEqual(student_user.font_scheme, User.FontScheme.DEFAULT)
