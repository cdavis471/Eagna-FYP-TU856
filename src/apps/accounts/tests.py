# =======
# Imports
# =======
from datetime import date  # Import date class

from django.contrib.auth import get_user_model  # Import user model getter
from django.test import TestCase, override_settings  # Import test case and settings override
from django.urls import reverse  # Import URL reverse function

from apps.accounts.models import (  # Import models from accounts app
    AcademicYear,  # Academic year model
    Assignment,  # Assignment model
    AssignmentSubmission,  # Assignment submission model
    Course,  # Course model
    LecturerProfile,  # Lecturer profile model
    Module,  # Module model
    ModuleOffering,  # Module offering model
    ModuleOfferingEnrollmentLecturer,  # Lecturer enrollment model
    ModuleOfferingEnrollmentStudent,  # Student enrollment model
    ModulePlacement,  # Module placement model
    StudentProfile,  # Student profile model
)

User = get_user_model()  # Get the user model

# ==============
# Base Test Case
# ==============
@override_settings(SECURE_SSL_REDIRECT=False)  # Override SSL redirect setting
class EagnaBaseTestCase(TestCase):  # Define base test case class
    def create_academic_year(  # Define method to create academic year
        self,
        *,
        label: str,
        start_date: date,
        end_date: date,
        is_current: bool,
    ) -> AcademicYear:
        return AcademicYear.objects.create(  # Create and return academic year
            label=label,  # Label for the year
            start_date=start_date,  # Start date
            end_date=end_date,  # End date
            is_current=is_current,  # Whether it's current
        )

    def create_course(self, code: str = "TU856", title: str = "Computing") -> Course:  # Define method to create course
        return Course.objects.create(  # Create and return course
            code=code,  # Course code
            title=title,  # Course title
            length_years=4,  # Length in years
            is_active=True,  # Active status
        )

    def create_module(self, code: str, title: str) -> Module:  # Define method to create module
        return Module.objects.create(  # Create and return module
            code=code,  # Module code
            title=title,  # Module title
            is_active=True,  # Active status
        )

    def place_module_on_course(self, module: Module, course: Course) -> ModulePlacement:  # Define method to place module on course
        return ModulePlacement.objects.create(  # Create and return module placement
            module=module,  # Module to place
            course=course,  # Course to place on
            available_now=True,  # Available now
            available_next_rollover=True,  # Available next rollover
        )

    def create_student(self, *, email: str, course_code: str = "TU856") -> User:  # Define method to create student
        user = User.objects.create_user(  # Create user
            username=email,  # Username
            email=email,  # Email
            password="StrongPass!23",  # Password
            first_name="Conor",  # First name
            last_name="Student",  # Last name
            role=User.Role.STUDENT,  # Role
        )
        StudentProfile.objects.create(  # Create student profile
            user=user,  # Associated user
            student_number=email.split("@")[0],  # Student number
            course=course_code,  # Course code
            status=StudentProfile.Status.ACTIVE,  # Status
        )
        return user  # Return created user

    def create_lecturer(self, *, email: str = "lecturer@tudublin.ie") -> User:  # Define method to create lecturer
        user = User.objects.create_user(  # Create user
            username=email,  # Username
            email=email,  # Email
            password="StrongPass!23",  # Password
            first_name="Aoife",  # First name
            last_name="Lecturer",  # Last name
            role=User.Role.LECTURER,  # Role
        )
        LecturerProfile.objects.create(  # Create lecturer profile
            user=user,  # Associated user
            staff_id="L001",  # Staff ID
        )
        return user  # Return created user

    def create_offering(  # Define method to create offering
        self,
        *,
        module: Module,
        academic_year: AcademicYear,
        is_current: bool,
        is_read_only: bool = False,
    ) -> ModuleOffering:
        return ModuleOffering.objects.create(  # Create and return offering
            module=module,  # Module
            academic_year=academic_year,  # Academic year
            is_current=is_current,  # Current status
            is_read_only=is_read_only,  # Read-only status
        )

# ================================================
# Unit Test I - Confirm Valid Student Registration
# ================================================
class RegistrationTests(EagnaBaseTestCase):  # Define registration tests class
    def test_registration_creates_student_profile_and_current_enrolments(self):  # Define test method
        current_year = self.create_academic_year(  # Create current academic year
            label="2025/26",  # Label
            start_date=date(2025, 9, 1),  # Start date
            end_date=date(2026, 8, 31),  # End date
            is_current=True,  # Current
        )
        course = self.create_course(code="TU856")  # Create course

        module_one = self.create_module(code="CMPU1010", title="Web Development")  # Create first module
        module_two = self.create_module(code="CMPU1020", title="Databases")  # Create second module
        self.place_module_on_course(module_one, course)  # Place first module on course
        self.place_module_on_course(module_two, course)  # Place second module on course

        response = self.client.post(  # Post to registration URL
            reverse("accounts:register"),  # Reverse URL
            {
                "first_name": "Conor",  # First name
                "last_name": "Davis",  # Last name
                "email": "c20441826@mytudublin.ie",  # Email
                "password1": "StrongPass!23",  # Password 1
                "password2": "StrongPass!23",  # Password 2
                "course": "tu856",  # Course
                "module_ids": [str(module_one.id), str(module_two.id)],  # Module IDs
            },
        )

        self.assertRedirects(response, reverse("accounts:login"))  # Assert redirect to login

        user = User.objects.get(username="c20441826@mytudublin.ie")  # Get created user
        self.assertEqual(user.role, User.Role.STUDENT)  # Assert role is student
        self.assertEqual(user.student_profile.student_number, "c20441826")  # Assert student number
        self.assertEqual(user.student_profile.course, "TU856")  # Assert course

        enrolments = ModuleOfferingEnrollmentStudent.objects.filter(  # Filter enrolments
            student=user.student_profile,  # For the student
            offering__academic_year=current_year,  # In current year
            offering__is_current=True,  # Current offerings
        )
        self.assertEqual(enrolments.count(), 2)  # Assert 2 enrolments
        self.assertSetEqual(  # Assert set of module codes
            set(enrolments.values_list("offering__module__code", flat=True)),  # Module codes
            {"CMPU1010", "CMPU1020"},  # Expected codes
        )

# ================================================================
# Unit Test II - Access Control Testing - Grading View Permissions
# ================================================================
class AccessControlTests(EagnaBaseTestCase):  # Define access control tests class
    def setUp(self):  # Define setUp method
        self.current_year = self.create_academic_year(  # Create current year
            label="2025/26",  # Label
            start_date=date(2025, 9, 1),  # Start date
            end_date=date(2026, 8, 31),  # End date
            is_current=True,  # Current
        )
        self.course = self.create_course(code="TU856")  # Create course
        self.module = self.create_module(code="CMPU2010", title="Software Engineering")  # Create module
        self.place_module_on_course(self.module, self.course)  # Place module on course

        self.offering = self.create_offering(  # Create offering
            module=self.module,  # Module
            academic_year=self.current_year,  # Academic year
            is_current=True,  # Current
        )

        self.student_user = self.create_student(email="c11111111@mytudublin.ie")  # Create student
        self.lecturer_user = self.create_lecturer()  # Create lecturer

        ModuleOfferingEnrollmentStudent.objects.create(  # Create student enrollment
            offering=self.offering,  # Offering
            student=self.student_user.student_profile,  # Student
        )
        ModuleOfferingEnrollmentLecturer.objects.create(  # Create lecturer enrollment
            offering=self.offering,  # Offering
            lecturer=self.lecturer_user.lecturer_profile,  # Lecturer
            is_primary=True,  # Primary
        )

        self.assignment = Assignment.objects.create(  # Create assignment
            offering=self.offering,  # Offering
            title="CA 1",  # Title
            description="Upload one file",  # Description
            due_datetime="2026-01-15T12:00:00Z",  # Due date
            max_mark=100,  # Max mark
        )
        self.submission = AssignmentSubmission.objects.create(  # Create submission
            assignment=self.assignment,  # Assignment
            student=self.student_user.student_profile,  # Student
        )

    def test_student_cannot_access_lecturer_grading_view(self):  # Define test method
        self.client.force_login(self.student_user)  # Login as student

        response = self.client.get(  # Get grading view
            reverse(  # Reverse URL
                "accounts:offering_grade_submission",  # View name
                args=[self.offering.id, self.assignment.id, self.submission.id],  # Args
            )
        )

        self.assertEqual(response.status_code, 404)  # Assert 404 status

    def test_lecturer_can_access_grading_view_for_their_own_offering(self):  # Define test method
        self.client.force_login(self.lecturer_user)  # Login as lecturer

        response = self.client.get(  # Get grading view
            reverse(  # Reverse URL
                "accounts:offering_grade_submission",  # View name
                args=[self.offering.id, self.assignment.id, self.submission.id],  # Args
            )
        )

        self.assertEqual(response.status_code, 200)  # Assert 200 status
        self.assertEqual(response.context["submission"].id, self.submission.id)  # Assert submission ID
        self.assertEqual(response.context["assignment"].id, self.assignment.id)  # Assert assignment ID

# ============================================================================================
# Unit Test III - Academic Year Visibility - Check Separation of Current Year / Previous Years
# ============================================================================================
class AcademicYearVisibilityTests(EagnaBaseTestCase):  # Define academic year visibility tests class
    def test_student_dashboard_separates_current_and_previous_year_modules(self):  # Define test method
        current_year = self.create_academic_year(  # Create current year
            label="2025/26",  # Label
            start_date=date(2025, 9, 1),  # Start date
            end_date=date(2026, 8, 31),  # End date
            is_current=True,  # Current
        )
        previous_year = self.create_academic_year(  # Create previous year
            label="2024/25",  # Label
            start_date=date(2024, 9, 1),  # Start date
            end_date=date(2025, 8, 31),  # End date
            is_current=False,  # Not current
        )
        course = self.create_course(code="TU856")  # Create course

        current_module = self.create_module(code="CMPU3010", title="Current Module")  # Create current module
        previous_module = self.create_module(code="CMPU3020", title="Previous Module")  # Create previous module
        self.place_module_on_course(current_module, course)  # Place current module
        self.place_module_on_course(previous_module, course)  # Place previous module

        current_offering = self.create_offering(  # Create current offering
            module=current_module,  # Module
            academic_year=current_year,  # Year
            is_current=True,  # Current
        )
        previous_offering = self.create_offering(  # Create previous offering
            module=previous_module,  # Module
            academic_year=previous_year,  # Year
            is_current=False,  # Not current
            is_read_only=True,  # Read-only
        )

        student_user = self.create_student(email="c22222222@mytudublin.ie")  # Create student

        ModuleOfferingEnrollmentStudent.objects.create(  # Enroll in current
            offering=current_offering,  # Offering
            student=student_user.student_profile,  # Student
        )
        ModuleOfferingEnrollmentStudent.objects.create(  # Enroll in previous
            offering=previous_offering,  # Offering
            student=student_user.student_profile,  # Student
        )

        self.client.force_login(student_user)  # Login as student
        response = self.client.get(reverse("accounts:dashboard"))  # Get dashboard

        self.assertEqual(response.status_code, 200)  # Assert 200 status

        current_rows = response.context["current_module_rows"]  # Get current rows
        previous_year_groups = response.context["previous_year_groups"]  # Get previous groups

        self.assertEqual(len(current_rows), 1)  # Assert 1 current row
        self.assertEqual(current_rows[0]["code"], "CMPU3010")  # Assert code

        self.assertEqual(len(previous_year_groups), 1)  # Assert 1 previous group
        self.assertEqual(previous_year_groups[0]["academic_year_label"], "2024/25")  # Assert label
        previous_codes = {  # Get previous codes
            row["code"]  # Code
            for row in previous_year_groups[0]["rows"]  # Rows
        }
        self.assertSetEqual(previous_codes, {"CMPU3020"})  # Assert codes

# =====================================================================
# Unit Test IV - Confirm Accessibility Value & Unsafe Redirect Handling
# =====================================================================
class AccessibilityPreferenceTests(EagnaBaseTestCase):  # Define accessibility preference tests class
    def test_invalid_accessibility_values_fall_back_to_defaults_and_ignore_unsafe_redirect(self):  # Define test method
        student_user = self.create_student(email="c33333333@mytudublin.ie")  # Create student
        self.client.force_login(student_user)  # Login as student

        response = self.client.post(  # Post to update preferences
            reverse("accounts:update_accessibility_preferences"),  # Reverse URL
            {
                "colour_scheme": "totally-invalid",  # Invalid colour scheme
                "font_scheme": "also-invalid",  # Invalid font scheme
                "next": "https://evil.example.com/phish",  # Unsafe redirect
            },
        )

        self.assertRedirects(response, reverse("accounts:dashboard"))  # Assert redirect to dashboard

        student_user.refresh_from_db()  # Refresh user from DB
        self.assertEqual(student_user.colour_scheme, User.ColourScheme.DEFAULT)  # Assert default colour
        self.assertEqual(student_user.font_scheme, User.FontScheme.DEFAULT)  # Assert default font
