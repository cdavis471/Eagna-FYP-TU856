from django.contrib.auth.models import AbstractUser  # Import Django's base user model that can be extended
from django.db import models  # Import Django's ORM model base classes and field types, and transaction management for atomic operations
from django.utils import timezone # Import timezone utilities to work with date and time fields in a timezone-aware manner
from django.conf import settings  # Import project settings to reference AUTH_USER_MODEL, etc.
from django.db.models import Sum, Q # Import aggregation function for summing marks, etc. and Q for complex queries
from django.core.exceptions import ValidationError  # Import exception for validating model data 
import os  # Import os module for file path operations

class User(AbstractUser):  # Custom user model extending Django's AbstractUser
    class Role(models.TextChoices):  # Inner class defining choices for the user's role
        STUDENT = "STUDENT", "Student"  # Database value and human-readable label for student role
        LECTURER = "LECTURER", "Lecturer"  # Database value and human-readable label for lecturer role
        ADMIN = "ADMIN", "Admin"  # Database value and human-readable label for admin role

    class ColourScheme(models.TextChoices):
        DEFAULT = "default", "Default"
        PROTANOPIA = "protanopia", "Protanopia"
        DEUTERANOPIA = "deuteranopia", "Deuteranopia"
        TRITANOPIA = "tritanopia", "Tritanopia"
        ACHROMATOPSIA = "achromatopsia", "Achromatopsia"
        HIGH_CONTRAST = "high-contrast", "High Contrast"

    class FontScheme(models.TextChoices):
        DEFAULT = "default", "Default"
        OPEN_DYSLEXIC = "open-dyslexic", "Open Dyslexic"
        ATKINSON_HYPERLEGIBLE = "atkinson-hyperlegible", "Atkinson Hyperlegible"

    role = models.CharField(  # Field storing whether this user is a student or lecturer
        max_length=20,  # Maximum length of the string stored for the role
        choices=Role.choices,  # Restricts allowed values to the Role enum choices
        default=Role.STUDENT,  # Default role if none is specified when creating a user
    )

    colour_scheme = models.CharField(
        max_length=24,
        choices=ColourScheme.choices,
        default=ColourScheme.DEFAULT,
    )

    font_scheme = models.CharField(
        max_length=32,
        choices=FontScheme.choices,
        default=FontScheme.DEFAULT,
    )

    def is_student(self):  # Helper method to check if user is a student
        return self.role == self.Role.STUDENT  # Returns True if role field equals the STUDENT choice

    def is_lecturer(self):  # Helper method to check if user is a lecturer
        return self.role == self.Role.LECTURER  # Returns True if role field equals the LECTURER choice
    
    def is_admin(self): # Helper method to check if user is an admin
        return self.role == self.Role.ADMIN # Returns True if role field equals the ADMIN choice

class StudentProfile(models.Model):  # Extra data model for users who are students

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        LOCKED = "LOCKED", "Locked"

    user = models.OneToOneField(  # One-to-one link between StudentProfile and User
        User,  # Related model is the custom User model
        on_delete=models.CASCADE,  # Delete student profile if the user is deleted
        related_name="student_profile",  # Allows reverse access via user.student_profile
    )
    student_number = models.CharField(max_length=32, unique=True)  # Unique identifier for a student (e.g. student ID)
    course = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Course Code(e.g. TU856 - No Name Included)"
    )

    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    def is_active_student(self):
        return self.status == self.Status.ACTIVE

    def is_completed_student(self):
        return self.status == self.Status.COMPLETED

    def is_locked_student(self):
        return self.status == self.Status.LOCKED

    def __str__(self):  # String representation used in admin and shell
        return f"{self.student_number} - {self.user.get_full_name() or self.user.username}"  # Shows ID plus student name or username

class LecturerProfile(models.Model):  # Extra data model for users who are lecturers
    user = models.OneToOneField(  # One-to-one link between LecturerProfile and User
        User,  # Related user model
        on_delete=models.CASCADE,  # Delete lecturer profile if the user is deleted
        related_name="lecturer_profile",  # Allows reverse access via user.lecturer_profile
    )
    staff_id = models.CharField(max_length=32, unique=True)  # Unique staff ID identifier for a lecturer

    def __str__(self):  # String representation for lecturer profile
        return f"{self.staff_id} - {self.user.get_full_name() or self.user.username}"  # Shows staff ID and lecturer name/username
    
# =========================
# Courses
# =========================

class Course(models.Model):
    code = models.CharField(max_length=16, unique=True)
    title = models.CharField(max_length=255)
    length_years = models.PositiveSmallIntegerField(default=4)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
    
    def includes_year(self, year_number):
        return 1 <= year_number <= self.length_years

    def __str__(self):
        return f"{self.code} - {self.title}"
    
# =========================
# Academic Year
# =========================

class AcademicYear(models.Model):
    label = models.CharField(max_length=16, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_current"],
                condition=Q(is_current=True),
                name="unique_current_academic_year",
            )
        ]

    def clean(self):
        if self.start_date >= self.end_date:
            raise ValidationError("Academic year end date must be after the start date.")

    def __str__(self):
        return self.label

# =========================
# Modules & Enrolment
# =========================

class Module(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.title}"


class ModulePlacement(models.Model):
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name="placements",
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name="module_placements",
    )
    year_number = models.PositiveSmallIntegerField()
    available_now = models.BooleanField(default=True)
    available_next_rollover = models.BooleanField(default=True)

    class Meta:
        ordering = ["course__code", "year_number", "module__code"]
        unique_together = ("module", "course", "year_number")

    def clean(self):
        if self.year_number < 1:
            raise ValidationError("Year number starts at 1.")

        if self.course_id and self.year_number > self.course.length_years:
            raise ValidationError(
                f"Year number cannot exceed the course length of ({self.course.length_years}) years."
            )

    def __str__(self):
        return f"{self.module.code} -> {self.course.code} Year {self.year_number}"


class ModuleOffering(models.Model):
    placement = models.ForeignKey(
        ModulePlacement,
        on_delete=models.CASCADE,
        related_name="offerings",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="module_offerings",
    )
    is_current = models.BooleanField(default=False)
    is_read_only = models.BooleanField(default=False)

    class Meta:
        ordering = [
            "placement__course__code",
            "placement__year_number",
            "placement__module__code",
        ]
        unique_together = ("placement", "academic_year")

    @property
    def module(self):
        return self.placement.module

    @property
    def course(self):
        return self.placement.course

    @property
    def year_number(self):
        return self.placement.year_number

    def clean(self):
        if self.is_current and self.is_read_only:
            raise ValidationError("A current module offering cannot also be read-only.")

    def __str__(self):
        return (
            f"{self.placement.module.code} - "
            f"{self.placement.course.code} Year {self.placement.year_number} "
            f"({self.academic_year.label})"
        )


class ModuleOfferingEnrollmentStudent(models.Model):
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.CASCADE,
        related_name="student_enrolments",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="offering_enrolments",
    )
    enrolled_on = models.DateField(auto_now_add=True)

    class Meta:
        unique_together = ("offering", "student")

    def __str__(self):
        return f"{self.student} -> {self.offering}"


class ModuleOfferingEnrollmentLecturer(models.Model):
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.CASCADE,
        related_name="lecturer_enrolments",
    )
    lecturer = models.ForeignKey(
        LecturerProfile,
        on_delete=models.CASCADE,
        related_name="offering_enrolments",
    )
    is_primary = models.BooleanField(default=False)

    class Meta:
        unique_together = ("offering", "lecturer")

    def __str__(self):
        return f"{self.lecturer} -> {self.offering}"

# =========================
# Assignments & Submissions
# =========================

class Assignment(models.Model):
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    due_datetime = models.DateTimeField()

    max_mark = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=100.00,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def module(self):
        return self.offering.module

    @property
    def course(self):
        return self.offering.course

    @property
    def academic_year(self):
        return self.offering.academic_year

    def __str__(self):
        return f"{self.module.code} - {self.title}"

class AssignmentSubmission(models.Model):  # Represents a student's submission for an assignment
    class Status(models.TextChoices):  # Inner choices class to represent submission status
        SUBMITTED = "SUBMITTED", "Submitted"  # Normal on-time submission
        LATE = "LATE", "Late"  # Submission made after the due date

    assignment = models.ForeignKey(  # Link to the assignment being submitted
        Assignment,  # Related assignment model
        on_delete=models.CASCADE,  # Delete submission if assignment is deleted
        related_name="submissions",  # Reverse access: assignment.submissions
    )
    student = models.ForeignKey(  # Link to the student who made this submission
        StudentProfile,  # Related student profile
        on_delete=models.CASCADE,  # Delete submission if student profile is deleted
        related_name="submissions",  # Reverse access: student_profile.submissions
    )
    status = models.CharField(  # Current status of the submission (e.g. submitted or late)
        max_length=16,  # Maximum length for the status string
        choices=Status.choices,  # Restrict to the Status enum choices
        default=Status.SUBMITTED,  # Default value is normal submitted (on time)
    )
    submitted_at = models.DateTimeField(auto_now_add=True)  # Timestamp when the submission was first created

    class Meta:  # Meta options for assignment submissions
        unique_together = ("assignment", "student")  # Each student can have at most one submission per assignment

    def __str__(self):  # String representation for a submission
        return f"{self.assignment} - {self.student}"  # Shows assignment and student together

def submission_file_upload_path(instance, filename):
    return (
        f"submission_files/{instance.submission.assignment.offering.id}/"
        f"{instance.submission.assignment.module.code}/"
        f"{instance.submission.assignment.id}/"
        f"{instance.submission.student.student_number or instance.submission.student.id}/"
        f"{filename}"
    )

class SubmissionFile(models.Model):  # Represents an individual file attached to a student's submission
    submission = models.ForeignKey(  # Link to the submission this file belongs to
        AssignmentSubmission,  # Related model is AssignmentSubmission
        on_delete=models.CASCADE,  # Delete file record if submission is deleted
        related_name="files",  # Reverse access: submission.files
    )
    file = models.FileField(upload_to=submission_file_upload_path)  # File itself, stored using provided upload path helper
    original_name = models.CharField(max_length=255, blank=True)  # Original file name as uploaded (optional, for display)
    uploaded_by = models.ForeignKey(  # Track which user uploaded this file
        settings.AUTH_USER_MODEL,  # Use the configured user model
        on_delete=models.SET_NULL,  # Keep file but set uploader to NULL if user is deleted
        null=True,  # Allow NULL if uploader is removed
        blank=True,  # Can be left blank when creating the record
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Timestamp when the file was uploaded

    def __str__(self):  # String representation of a submission file
        return self.original_name or self.file.name  # Prefer original name, fallback to stored file name

class AssignmentGrade(models.Model):  # Represents the grade/mark for a submission
    submission = models.OneToOneField(  # One-to-one relationship: each submission has at most one grade
        AssignmentSubmission,  # Related submission model
        on_delete=models.CASCADE,  # Delete grade if submission is deleted
        related_name="grade",  # Reverse access: submission.grade
    )
    marker = models.ForeignKey(  # Lecturer who graded this submission
        LecturerProfile,  # Related lecturer profile
        on_delete=models.SET_NULL,  # If marker is removed, keep grade but set marker to NULL
        null=True,  # Allow NULL if marker is deleted or unknown
        blank=True,  # Field can be left blank
        related_name="graded_submissions",  # Reverse access: lecturer_profile.graded_submissions
    )
    value = models.DecimalField(  # Numeric mark awarded to this submission
        max_digits=5,  # Total digits for mark (e.g. 100.00)
        decimal_places=2,  # Number of decimal places (two decimal precision)
        help_text="Mark awarded for this submission.",  # Helper text shown in forms/admin
    )
    feedback_text = models.TextField(blank=True)  # Optional textual feedback for the student
    graded_at = models.DateTimeField(auto_now_add=True)  # Timestamp when this grade was first created

    def __str__(self):  # String representation of grade
        return f"{self.submission} - {self.value}/{self.submission.assignment.max_mark}"  # Shows submission and mark over max

def assignment_file_upload_path(instance, filename):
    return (
        f"assignment_files/{instance.assignment.offering.id}/"
        f"{instance.assignment.module.code}/"
        f"{instance.assignment.id}/{filename}"
    )

class AssignmentFile(models.Model):  # Represents files attached by lecturers to an assignment
    assignment = models.ForeignKey(  # Link to the assignment this file belongs to
        Assignment,  # Related assignment model
        on_delete=models.CASCADE,  # Delete file record if assignment is deleted
        related_name="files",  # Reverse access: assignment.files
    )
    file = models.FileField(upload_to=assignment_file_upload_path)  # Uploaded file for assignment resources
    original_name = models.CharField(max_length=255, blank=True)  # Original file name, optional for nicer display
    uploaded_by = models.ForeignKey(  # User who uploaded this assignment file (likely a lecturer)
        settings.AUTH_USER_MODEL,  # Use the project’s configured user model
        on_delete=models.SET_NULL,  # Keep file record but clear uploader if user removed
        null=True,  # Allow NULL for uploader
        blank=True,  # Uploader does not have to be set
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Timestamp when this file was uploaded

    def __str__(self):  # String representation of assignment file
        return self.original_name or self.file.name  # Prefer original file name or fallback to stored name

class Quiz(models.Model):
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.CASCADE,
        related_name="quizzes",
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    open_datetime = models.DateTimeField()
    close_datetime = models.DateTimeField()

    time_limit_minutes = models.PositiveIntegerField(default=20)
    max_attempts = models.PositiveSmallIntegerField(default=1)

    max_mark = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=100.00,
        help_text="Weighted mark shown to students, similar to assignment max mark.",
    )

    is_published = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["close_datetime", "title"]

    @property
    def module(self):
        return self.offering.module

    @property
    def course(self):
        return self.offering.course

    @property
    def academic_year(self):
        return self.offering.academic_year

    def __str__(self):
        return f"{self.module.code} - Quiz - {self.title}"

    def has_started(self, now=None):
        now = now or timezone.now()
        return now >= self.open_datetime

    def has_closed(self, now=None):
        now = now or timezone.now()
        return now > self.close_datetime

    def is_open(self, now=None):
        now = now or timezone.now()
        return self.is_published and self.has_started(now=now) and not self.has_closed(now=now)

    def total_question_marks(self):
        return self.questions.aggregate(total=Sum("marks"))["total"] or 0


class QuizQuestion(models.Model):
    class Type(models.TextChoices):
        MULTIPLE_CHOICE = "MULTIPLE_CHOICE", "Multiple choice"
        MULTIPLE_SELECT = "MULTIPLE_SELECT", "Multiple select"
        TRUE_FALSE = "TRUE_FALSE", "True / False"
        FILL_BLANK = "FILL_BLANK", "Fill in the blank"

    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name="questions",
    )
    prompt = models.TextField()
    question_type = models.CharField(
        max_length=32,
        choices=Type.choices,
    )
    marks = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1.00,
    )
    display_order = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["display_order", "id"]

    def __str__(self):
        return f"{self.quiz.title} - Q{self.display_order}"


class QuizOption(models.Model):
    question = models.ForeignKey(
        QuizQuestion,
        on_delete=models.CASCADE,
        related_name="options",
    )
    text = models.CharField(max_length=255)
    display_order = models.PositiveIntegerField(default=1)
    is_correct = models.BooleanField(default=False)

    class Meta:
        ordering = ["display_order", "id"]

    def __str__(self):
        return self.text


class QuizAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        SUBMITTED = "SUBMITTED", "Submitted"
        AUTO_SUBMITTED = "AUTO_SUBMITTED", "Auto Submitted"

    quiz = models.ForeignKey(
        Quiz,
        on_delete=models.CASCADE,
        related_name="attempts",
    )
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="quiz_attempts",
    )
    attempt_number = models.PositiveSmallIntegerField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )

    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    submitted_at = models.DateTimeField(null=True, blank=True)

    raw_score = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.00,
    )
    weighted_score = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.00,
    )

    class Meta:
        ordering = ["-started_at"]
        unique_together = ("quiz", "student", "attempt_number")

    def __str__(self):
        return f"{self.quiz.title} - {self.student} - Attempt {self.attempt_number}"

    def is_active(self):
        return self.status == self.Status.IN_PROGRESS and self.submitted_at is None

    def is_expired(self, now=None):
        now = now or timezone.now()
        return now >= self.expires_at


class QuizAnswer(models.Model):
    attempt = models.ForeignKey(
        QuizAttempt,
        on_delete=models.CASCADE,
        related_name="answers",
    )
    question = models.ForeignKey(
        QuizQuestion,
        on_delete=models.CASCADE,
        related_name="answers",
    )

    selected_option = models.ForeignKey(
        QuizOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    selected_option_ids = models.JSONField(default=list, blank=True)

    is_correct = models.BooleanField(default=False)
    awarded_marks = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.00,
    )

    class Meta:
        unique_together = ("attempt", "question")

    def __str__(self):
        return f"{self.attempt} - {self.question}"

class ModuleWeek(models.Model):
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.CASCADE,
        related_name="weeks",
    )
    week_number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=255, blank=True, default="")
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ("offering", "week_number")
        ordering = ["week_number"]

    @property
    def module(self):
        return self.offering.module

    @property
    def course(self):
        return self.offering.course

    @property
    def academic_year(self):
        return self.offering.academic_year

    def __str__(self):
        return f"{self.module.code} - Week {self.week_number}"

def module_week_file_upload_path(instance, filename):
    return (
        f"module_files/{instance.week.offering.id}/"
        f"{instance.week.module.code}/"
        f"week-{instance.week.week_number}/{filename}"
    )

class ModuleWeekFile(models.Model):  # Represents a file resource attached to a specific teaching week
    week = models.ForeignKey(  # Link to the week this file belongs to
        ModuleWeek,  # Related ModuleWeek model
        on_delete=models.CASCADE,  # Delete file record if week is deleted
        related_name="files",  # Reverse access: week.files
    )
    file = models.FileField(upload_to=module_week_file_upload_path)  # Actual file stored for this week
    original_name = models.CharField(max_length=255, blank=True)  # Optional original filename for display
    uploaded_by = models.ForeignKey(  # User who uploaded this weekly file
        settings.AUTH_USER_MODEL,  # Use configured user model
        on_delete=models.SET_NULL,  # Keep file but clear uploader if user is removed
        null=True,  # Allow NULL uploader
        blank=True,  # Uploader not required
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Timestamp when this file was uploaded

    def __str__(self):  # String representation for a weekly module file
        return self.original_name or self.file.name  # Prefer original name, or fallback to stored filename

def parsed_document_image_upload_path(instance, filename):
    return f"parsed_documents/{instance.parsed_document_id}/{filename}"

class ParsedDocument(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "PROCESSING", "Processing"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"

    week_file = models.OneToOneField(
        "ModuleWeekFile",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="parsed_document",
    )
    assignment_file = models.OneToOneField(
        "AssignmentFile",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="parsed_document",
    )

    source_extension = models.CharField(max_length=10)
    parser_status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PROCESSING,
    )
    parsed_blocks = models.JSONField(default=list, blank=True)
    rendered_html = models.TextField(blank=True)
    parse_error = models.TextField(blank=True)
    page_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        has_week_file = bool(self.week_file_id)
        has_assignment_file = bool(self.assignment_file_id)
        if has_week_file == has_assignment_file:
            raise ValidationError(
                "ParsedDocument must be linked to exactly one source file: "
                "either week_file or assignment_file."
            )

    def get_source_module(self):
        if self.week_file_id:
            return self.week_file.week.offering.module
        if self.assignment_file_id:
            return self.assignment_file.assignment.offering.module
        return None

    def get_source_file(self):
        if self.week_file_id:
            return self.week_file
        if self.assignment_file_id:
            return self.assignment_file
        return None

    def get_source_name(self):
        source = self.get_source_file()
        if not source:
            return "Unknown file"
        return source.original_name or os.path.basename(source.file.name)

    def __str__(self):
        return f"Parsed: {self.get_source_name()}"

class ParsedDocumentImage(models.Model):
    parsed_document = models.ForeignKey(
        ParsedDocument,
        on_delete=models.CASCADE,
        related_name="images",
    )
    token = models.CharField(max_length=50)
    image = models.ImageField(upload_to=parsed_document_image_upload_path)
    display_order = models.PositiveIntegerField(default=0)
    page_number = models.PositiveIntegerField(null=True, blank=True)
    original_name = models.CharField(max_length=255, blank=True)
    alt_text = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "id"]
        unique_together = ("parsed_document", "token")

    def __str__(self):
        return self.original_name or self.token

class Notification(models.Model):
    class Type(models.TextChoices):
        GENERAL = "GENERAL", "General"

        ASSIGNMENT_NEW = "ASSIGNMENT_NEW", "New assignment"
        ASSIGNMENT_DUE_3D = "ASSIGNMENT_DUE_3D", "Assignment due in 3 days"
        ASSIGNMENT_DUE_24H = "ASSIGNMENT_DUE_24H", "Assignment due in 24 hours"
        ASSIGNMENT_SUBMITTED = "ASSIGNMENT_SUBMITTED", "Assignment submitted"
        ASSIGNMENT_GRADED = "ASSIGNMENT_GRADED", "Assignment graded"
        ASSIGNMENT_CLOSED_SUMMARY = "ASSIGNMENT_CLOSED_SUMMARY", "Assignment closed summary"
        ASSIGNMENT_GRADING_REMINDER = "ASSIGNMENT_GRADING_REMINDER", "Assignment grading reminder"

        QUIZ_NEW = "QUIZ_NEW", "New quiz"
        QUIZ_OPENED = "QUIZ_OPENED", "Quiz opened"
        QUIZ_CLOSED = "QUIZ_CLOSED", "Quiz closed"
        QUIZ_SUBMITTED = "QUIZ_SUBMITTED", "Quiz submitted"
        QUIZ_CLOSED_SUMMARY = "QUIZ_CLOSED_SUMMARY", "Quiz closed summary"

        WEEK_AVAILABLE = "WEEK_AVAILABLE", "New week available"

        PARSER_SUCCESS = "PARSER_SUCCESS", "Parser success"
        PARSER_FAILURE = "PARSER_FAILURE", "Parser failure"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notifications",
    )
    notification_type = models.CharField(
        max_length=40,
        choices=Type.choices,
        default=Type.GENERAL,
    )
    title = models.CharField(max_length=255)
    redirect_url = models.CharField(max_length=500, blank=True)
    event_key = models.CharField(max_length=255, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "event_key"],
                name="unique_notification_event_per_user",
            )
        ]

    @property
    def module(self):
        return self.offering.module if self.offering_id else None

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def __str__(self):
        return f"{self.recipient} - {self.title}"
    
class GlobalAnnouncement(models.Model):
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="global_announcements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title

    @classmethod
    def trim_to_latest_three(cls):
        stale_ids = list(
            cls.objects.order_by("-created_at", "-id")
            .values_list("id", flat=True)[3:]
        )
        if stale_ids:
            cls.objects.filter(id__in=stale_ids).delete()

class ModuleAnnouncement(models.Model):
    offering = models.ForeignKey(
        ModuleOffering,
        on_delete=models.CASCADE,
        related_name="module_announcements",
    )
    title = models.CharField(max_length=255)
    content = models.TextField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="module_announcements_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @property
    def module(self):
        return self.offering.module

    @property
    def course(self):
        return self.offering.course

    @property
    def academic_year(self):
        return self.offering.academic_year

    def __str__(self):
        return f"{self.module.code} - {self.title}"

    @classmethod
    def trim_to_latest_three_for_offering(cls, offering):
        stale_ids = list(
            cls.objects.filter(offering=offering)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)[3:]
        )
        if stale_ids:
            cls.objects.filter(id__in=stale_ids).delete()