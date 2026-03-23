from django.contrib.auth.models import AbstractUser  # Import Django's base user model that can be extended
from django.db import models, transaction  # Import Django's ORM model base classes and field types, and transaction management for atomic operations
from django.utils import timezone # Import timezone utilities to work with date and time fields in a timezone-aware manner
from django.conf import settings  # Import project settings to reference AUTH_USER_MODEL, etc.
from datetime import date # Import date class for handling module cycle dates
from django.db.models import Sum # Import aggregation function for summing marks, etc.
from django.core.exceptions import ValidationError  # Import exception for validating model data 
import os  # Import os module for file path operations

class User(AbstractUser):  # Custom user model extending Django's AbstractUser
    class Role(models.TextChoices):  # Inner class defining choices for the user's role
        STUDENT = "STUDENT", "Student"  # Database value and human-readable label for student role
        LECTURER = "LECTURER", "Lecturer"  # Database value and human-readable label for lecturer role
        ADMIN = "ADMIN", "Admin"  # Database value and human-readable label for admin role

    role = models.CharField(  # Field storing whether this user is a student or lecturer
        max_length=20,  # Maximum length of the string stored for the role
        choices=Role.choices,  # Restricts allowed values to the Role enum choices
        default=Role.STUDENT,  # Default role if none is specified when creating a user
    )

    def is_student(self):  # Helper method to check if user is a student
        return self.role == self.Role.STUDENT  # Returns True if role field equals the STUDENT choice

    def is_lecturer(self):  # Helper method to check if user is a lecturer
        return self.role == self.Role.LECTURER  # Returns True if role field equals the LECTURER choice
    
    def is_admin(self): # Helper method to check if user is an admin
        return self.role == self.Role.ADMIN # Returns True if role field equals the ADMIN choice

class StudentProfile(models.Model):  # Extra data model for users who are students
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
# Modules & Enrolment
# =========================

class Module(models.Model):
    code = models.CharField(max_length=32, unique=True)
    title = models.CharField(max_length=255)

    start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Module start date (month/day used for annual rollover).",
    )
    end_date = models.DateField(
        null=True,
        blank=True,
        help_text="Module end date (month/day used; can be before start for Sep→May style modules).",
    )

    last_rollover_year = models.PositiveIntegerField(
        default=0,
        help_text="The start-year of the most recent rollover cycle (e.g. 2025).",
    )

    is_active = models.BooleanField(default=True)

    students = models.ManyToManyField(
        StudentProfile,
        through="ModuleEnrollmentStudent",
        related_name="modules",
        blank=True,
    )
    lecturers = models.ManyToManyField(
        LecturerProfile,
        through="ModuleEnrollmentLecturer",
        related_name="modules",
        blank=True,
    )

    allowed_courses = models.JSONField(
        default=list,
        blank=True,
        help_text="List of course codes allowed to enroll (e.g. ['TU856','DT228']). Empty = no restriction.",
    )

    def __str__(self):
        return f"{self.code} - {self.title}"

    def _start_md(self):
        return (self.start_date.month, self.start_date.day) if self.start_date else None

    def _end_md(self):
        return (self.end_date.month, self.end_date.day) if self.end_date else None

    def current_cycle_window(self):
        """
        Returns (run_start, run_end) for the current cycle, based on last_rollover_year.
        Handles cross-year modules like Sep→May.
        """
        if not self.start_date or not self.end_date:
            return (None, None)

        start_md = self._start_md()
        end_md = self._end_md()
        if not start_md or not end_md:
            return (None, None)

        start_year = self.last_rollover_year or self.start_date.year

        run_start = date(start_year, start_md[0], start_md[1])

        ends_next_year = (end_md[0], end_md[1]) < (start_md[0], start_md[1])
        end_year = start_year + 1 if ends_next_year else start_year
        run_end = date(end_year, end_md[0], end_md[1])

        return (run_start, run_end)

    def needs_rollover(self, today=None):
        """
        True if we've passed the module's start month/day in the current calendar year,
        and we haven't rolled over for this year yet.
        """
        if not self.start_date:
            return False

        today = today or timezone.localdate()
        start_md = self._start_md()
        if not start_md:
            return False

        start_this_year = date(today.year, start_md[0], start_md[1])
        return today >= start_this_year and self.last_rollover_year < today.year

    @transaction.atomic
    def rollover(self, today=None):
        """
        Wipes module content for a new iteration:
        - Deletes assignments + submissions + grades + all related files
        - Deletes weeks + week files
        - Removes student enrolments
        - Keeps lecturer enrolments
        """
        today = today or timezone.localdate()
        if not self.needs_rollover(today=today):
            return False

        for wf in ModuleWeekFile.objects.filter(week__module=self):
            if wf.file:
                wf.file.delete(save=False)
        ModuleWeekFile.objects.filter(week__module=self).delete()
        ModuleWeek.objects.filter(module=self).delete()

        for sf in SubmissionFile.objects.filter(submission__assignment__module=self):
            if sf.file:
                sf.file.delete(save=False)
        SubmissionFile.objects.filter(submission__assignment__module=self).delete()

        for af in AssignmentFile.objects.filter(assignment__module=self):
            if af.file:
                af.file.delete(save=False)
        AssignmentFile.objects.filter(assignment__module=self).delete()

        Assignment.objects.filter(module=self).delete()

        Quiz.objects.filter(module=self).delete()

        ModuleEnrollmentStudent.objects.filter(module=self).delete()

        self.last_rollover_year = today.year
        self.save(update_fields=["last_rollover_year"])

        return True

class ModuleEnrollmentStudent(models.Model):  # Through model representing a student's enrolment in a module
    module = models.ForeignKey(  # Link to the module that the student is enrolled in
        Module,  # Related module model
        on_delete=models.CASCADE,  # Delete enrolment if module is deleted
        related_name="student_enrolments",  # Reverse access: module.student_enrolments
    )
    student = models.ForeignKey(  # Link to the student that is enrolled
        StudentProfile,  # Related student profile
        on_delete=models.CASCADE,  # Delete enrolment if student profile is deleted
        related_name="module_enrolments",  # Reverse access: student_profile.module_enrolments
    )
    enrolled_on = models.DateField(auto_now_add=True)  # Date when the student was enrolled, set automatically on creation

    class Meta:  # Meta options for the student enrolment model
        unique_together = ("module", "student")  # Ensure each student can only be enrolled once per module

    def __str__(self):  # String representation of student enrolment
        return f"{self.student} -> {self.module}"  # Shows which student is enrolled in which module

class ModuleEnrollmentLecturer(models.Model):  # Through model representing a lecturer assigned to a module
    module = models.ForeignKey(  # Link to the module being taught
        Module,  # Related module model
        on_delete=models.CASCADE,  # Delete record if module is deleted
        related_name="lecturer_enrolments",  # Reverse access: module.lektor_enrolments
    )
    lecturer = models.ForeignKey(  # Link to the lecturer teaching the module
        LecturerProfile,  # Related lecturer profile
        on_delete=models.CASCADE,  # Delete record if lecturer profile is deleted
        related_name="module_enrolments",  # Reverse access: lecturer_profile.module_enrolments
    )
    is_primary = models.BooleanField(default=False)  # Flag to indicate if this lecturer is the primary/lead for this module

    class Meta:  # Meta configuration for lecturer enrolment
        unique_together = ("module", "lecturer")  # A lecturer should only appear once per module

    def __str__(self):  # String representation of lecturer enrolment
        return f"{self.lecturer} -> {self.module}"  # Shows which lecturer is linked to which module

# =========================
# Assignments & Submissions
# =========================

class Assignment(models.Model):  # Represents an assignment belonging to a module
    module = models.ForeignKey(  # Link to the module this assignment is for
        Module,  # Related module model
        on_delete=models.CASCADE,  # Delete assignments if the module is deleted
        related_name="assignments",  # Reverse access: module.assignments
    )
    title = models.CharField(max_length=255)  # Title of the assignment shown to students/lecturers
    description = models.TextField(blank=True)  # Detailed description or instructions for the assignment
    due_datetime = models.DateTimeField()  # Date and time when the assignment is due

    max_mark = models.DecimalField(  # Maximum mark that can be awarded for this assignment
        max_digits=5,  # Total number of digits allowed in the stored number
        decimal_places=2,  # Number of decimal places (e.g. 100.00)
        default=100.00,  # Default maximum mark is 100.00
    )

    created_at = models.DateTimeField(auto_now_add=True)  # Timestamp when the assignment was created
    updated_at = models.DateTimeField(auto_now=True)  # Timestamp automatically updated whenever the assignment is saved

    def __str__(self):  # String representation of an assignment
        return f"{self.module.code} - {self.title}"  # Shows module code followed by assignment title

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

def submission_file_upload_path(instance, filename):  # Helper function to compute upload path for submission files
    return (  # Return a dynamic path that organizes files by module, assignment, and student
        f"submission_files/{instance.submission.assignment.module.code}/"  # Folder by module code
        f"{instance.submission.assignment.id}/"  # Nested folder by assignment ID
        f"{instance.submission.student.student_number or instance.submission.student.id}/"  # Folder by student number or ID
        f"{filename}"  # Final part is the original filename
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

def assignment_file_upload_path(instance, filename):  # Helper function for assignment file storage path
    return (  # Return path that organizes files by module and assignment
        f"assignment_files/{instance.assignment.module.code}/"  # Folder by module code
        f"{instance.assignment.id}/{filename}"  # Nested folder by assignment ID and filename
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
    module = models.ForeignKey(
        Module,
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

class ModuleWeek(models.Model):  # Represents a single teaching week within a module
    module = models.ForeignKey(  # Link to the module this week belongs to
        Module,  # Related module model
        on_delete=models.CASCADE,  # Delete week if module is deleted
        related_name="weeks",  # Reverse access: module.weeks
    )
    week_number = models.PositiveSmallIntegerField()  # Numeric week indicator (e.g. 1–30)
    title = models.CharField(max_length=255, blank=True, default="")  # Optional human-readable title for the week
    description = models.TextField(blank=True)  # Optional text description or summary of the week’s content

    class Meta:  # Meta configuration for ModuleWeek
        unique_together = ("module", "week_number")  # Prevent duplicate week numbers for the same module
        ordering = ["week_number"]  # Default ordering of weeks is ascending by week_number

    def __str__(self):  # String representation of a module week
        return f"{self.module.code} - Week {self.week_number}"  # Shows module code plus week number

def module_week_file_upload_path(instance, filename):  # Helper to determine upload path for weekly module files
    return (  # Build a structured path for module week files
        f"module_files/{instance.week.module.code}/"  # Folder by module code
        f"week-{instance.week.week_number}/{filename}"  # Nested folder by week number and filename
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
            return self.week_file.week.module
        if self.assignment_file_id:
            return self.assignment_file.assignment.module
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
    module = models.ForeignKey(
        Module,
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
    module = models.ForeignKey(
        Module,
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

    def __str__(self):
        return f"{self.module.code} - {self.title}"

    @classmethod
    def trim_to_latest_three_for_module(cls, module):
        stale_ids = list(
            cls.objects.filter(module=module)
            .order_by("-created_at", "-id")
            .values_list("id", flat=True)[3:]
        )
        if stale_ids:
            cls.objects.filter(id__in=stale_ids).delete()