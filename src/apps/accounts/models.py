# =======
# Imports
# =======
from django.contrib.auth.models import AbstractUser  # Extend Django's base user model.
from django.db import models  # Use Django model fields.
from django.utils import timezone  # Work with timezone-aware datetimes.
from django.conf import settings  # Reference project settings.
from django.db.models import Sum, Q  # Use aggregate and query helpers.
from django.core.exceptions import ValidationError  # Raise model validation errors.
import os  # Handle path utilities.

# ==================
# Users and Profiles
# ==================
class User(AbstractUser):  # Define the User model.
    """Represent an application user."""
    class Role(models.TextChoices):  # Define the Role choices.
        """Define role choices."""
        STUDENT = "STUDENT", "Student"  # Define the student option.
        LECTURER = "LECTURER", "Lecturer"  # Define the lecturer option.
        ADMIN = "ADMIN", "Admin"  # Define the admin option.

    class ColourScheme(models.TextChoices):  # Define colour scheme choices.
        """Define colour scheme choices."""
        DEFAULT = "default", "Default"  # Define the default option.
        PROTANOPIA = "protanopia", "Protanopia"  # Define the protanopia option.
        DEUTERANOPIA = "deuteranopia", "Deuteranopia"  # Define the deuteranopia option.
        TRITANOPIA = "tritanopia", "Tritanopia"  # Define the tritanopia option.
        ACHROMATOPSIA = "achromatopsia", "Achromatopsia"  # Define the achromatopsia option.
        HIGH_CONTRAST = "high-contrast", "High Contrast"  # Define the high contrast option.

    class FontScheme(models.TextChoices):  # Define font scheme choices.
        """Define font scheme choices."""
        DEFAULT = "default", "Default"  # Define the default option.
        OPEN_DYSLEXIC = "open-dyslexic", "Open Dyslexic"  # Define the open dyslexic option.
        ATKINSON_HYPERLEGIBLE = "atkinson-hyperlegible", "Atkinson Hyperlegible"  # Define the atkinson hyperlegible option.

    role = models.CharField(  # Store role.
        max_length=20,  # Limit stored text length.
        choices=Role.choices,  # Restrict allowed values.
        default=Role.STUDENT,  # Set the default value.
    )

    colour_scheme = models.CharField(  # Store colour scheme.
        max_length=24,  # Limit stored text length.
        choices=ColourScheme.choices,  # Restrict allowed values.
        default=ColourScheme.DEFAULT,  # Set the default value.
    )

    font_scheme = models.CharField(  # Store font scheme.
        max_length=32,  # Limit stored text length.
        choices=FontScheme.choices,  # Restrict allowed values.
        default=FontScheme.DEFAULT,  # Set the default value.
    )

    def is_student(self):  # Define is_student.
        """Return whether the user is a student."""
        return self.role == self.Role.STUDENT  # Return the computed value.

    def is_lecturer(self):  # Define is_lecturer.
        """Return whether the user is a lecturer."""
        return self.role == self.Role.LECTURER  # Return the computed value.

    def is_admin(self):  # Define is_admin.
        """Return whether the user is an admin."""
        return self.role == self.Role.ADMIN  # Return the computed value.

class StudentProfile(models.Model):  # Define the StudentProfile model.
    """Represent a student profile."""
    class Status(models.TextChoices):  # Define status choices.
        """Define status choices."""
        ACTIVE = "ACTIVE", "Active"  # Define the active option.
        COMPLETED = "COMPLETED", "Completed"  # Define the completed option.
        LOCKED = "LOCKED", "Locked"  # Define the locked option.

    user = models.OneToOneField(  # Link to the related user.
        User,  # Reference the related user model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="student_profile",  # Define reverse relation access.
    )
    student_number = models.CharField(max_length=32, unique=True)  # Store student number.
    course = models.CharField(  # Store course.
        max_length=10,  # Limit stored text length.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
        help_text="Course Code(e.g. TU856 - No Name Included)"  # Show form help text.
    )

    status = models.CharField(  # Store status.
        max_length=16,  # Limit stored text length.
        choices=Status.choices,  # Restrict allowed values.
        default=Status.ACTIVE,  # Set the default value.
    )

    def is_active_student(self):  # Define is_active_student.
        """Return whether the student is active."""
        return self.status == self.Status.ACTIVE  # Return the computed value.

    def is_completed_student(self):  # Define is_completed_student.
        """Return whether the student is completed."""
        return self.status == self.Status.COMPLETED  # Return the computed value.

    def is_locked_student(self):  # Define is_locked_student.
        """Return whether the student is locked."""
        return self.status == self.Status.LOCKED  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.student_number} - {self.user.get_full_name() or self.user.username}"  # Return the display string.

class LecturerProfile(models.Model):  # Define the LecturerProfile model.
    """Represent a lecturer profile."""
    user = models.OneToOneField(  # Link to the related user.
        User,  # Reference the related user model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="lecturer_profile",  # Define reverse relation access.
    )
    staff_id = models.CharField(max_length=32, unique=True)  # Store staff id.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.staff_id} - {self.user.get_full_name() or self.user.username}"  # Return the display string.


# =======
# Courses
# =======
class Course(models.Model):  # Define the Course model.
    """Represent a course."""
    code = models.CharField(max_length=16, unique=True)  # Store code.
    title = models.CharField(max_length=255)  # Store title.
    length_years = models.PositiveSmallIntegerField(default=4)  # Store length years.
    is_active = models.BooleanField(default=True)  # Store is active.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["code"]  # Define default ordering.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.code} - {self.title}"  # Return the display string.


# ==============
# Academic Years
# ==============
class AcademicYear(models.Model):  # Define the AcademicYear model.
    """Represent an academic year."""
    label = models.CharField(max_length=16, unique=True)  # Store the academic year label.
    start_date = models.DateField()  # Store start date.
    end_date = models.DateField()  # Store end date.
    is_current = models.BooleanField(default=False)  # Store is current.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["-start_date"]  # Define default ordering.
        constraints = [  # Define model constraints.
            models.UniqueConstraint(  # Define a unique constraint.
                fields=["is_current"],  # Target these constraint fields.
                condition=Q(is_current=True),  # Apply the constraint condition.
                name="unique_current_academic_year",  # Name the database constraint.
            )
        ]

    def clean(self):  # Define clean.
        """Validate the model state."""
        if self.start_date >= self.end_date:  # Check the current condition.
            raise ValidationError("Academic year end date must be after the start date.")  # Raise a validation error.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.label  # Return the computed value.

# =====================
# Modules and Enrolment
# =====================
class Module(models.Model):  # Define the Module model.
    """Represent a module."""
    code = models.CharField(max_length=32, unique=True)  # Store code.
    title = models.CharField(max_length=255)  # Store title.
    is_active = models.BooleanField(default=True)  # Store is active.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.code} - {self.title}"  # Return the display string.

class ModulePlacement(models.Model):  # Define the ModulePlacement model.
    """Represent a module placement."""
    module = models.ForeignKey(  # Link to the related module.
        Module,  # Reference the related module model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="placements",  # Define reverse relation access.
    )
    course = models.ForeignKey(  # Link to the related course.
        Course,  # Reference the related course model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="module_placements",  # Define reverse relation access.
    )
    available_now = models.BooleanField(default=True)  # Store available now.
    available_next_rollover = models.BooleanField(default=True)  # Store available next rollover.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["course__code", "module__code"]  # Define default ordering.
        unique_together = ("module", "course")  # Enforce unique combinations.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.module.code} -> {self.course.code}"  # Return the display string.

class ModuleOffering(models.Model):  # Define the ModuleOffering model.
    """Represent a module offering."""
    module = models.ForeignKey(  # Link to the related module.
        Module,  # Reference the related module model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="offerings",  # Define reverse relation access.
    )
    academic_year = models.ForeignKey(  # Link to the related academic year.
        AcademicYear,  # Reference the related academic year model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="module_offerings",  # Define reverse relation access.
    )
    is_current = models.BooleanField(default=False)  # Store is current.
    is_read_only = models.BooleanField(default=False)  # Store is read only.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["module__code", "academic_year__start_date"]  # Define default ordering.
        unique_together = ("module", "academic_year")  # Enforce unique combinations.

    @property  # Expose a computed property.
    def course_codes(self):  # Define course_codes.
        """Return related course codes."""
        return list(  # Return the computed value.
            self.module.placements  # Start from related placements.
            .select_related("course")  # Join related course rows.
            .filter(course__is_active=True)  # Keep active courses only.
            .order_by("course__code")  # Order by course code.
            .values_list("course__code", flat=True)  # Read course codes only.
            .distinct()  # Remove duplicate codes.
        )

    @property  # Expose a computed property.
    def course_codes_display(self):  # Define course_codes_display.
        """Return joined course codes."""
        return ", ".join(self.course_codes)  # Return the computed value.

    def clean(self):  # Define clean.
        """Validate the model state."""
        if self.is_current and self.is_read_only:  # Check the current condition.
            raise ValidationError("A current module offering cannot also be read-only.")  # Raise a validation error.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.module.code} ({self.academic_year.label})"  # Return the display string.

class ModuleOfferingEnrollmentStudent(models.Model):  # Define the student enrolment model.
    """Represent a student enrolment."""
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="student_enrolments",  # Define reverse relation access.
    )
    student = models.ForeignKey(  # Link to the related student.
        StudentProfile,  # Reference the related student profile model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="offering_enrolments",  # Define reverse relation access.
    )
    enrolled_on = models.DateField(auto_now_add=True)  # Store enrolled on.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        unique_together = ("offering", "student")  # Enforce unique combinations.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.student} -> {self.offering}"  # Return the display string.

class ModuleOfferingEnrollmentLecturer(models.Model):  # Define the lecturer enrolment model.
    """Represent a lecturer enrolment."""
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="lecturer_enrolments",  # Define reverse relation access.
    )
    lecturer = models.ForeignKey(  # Link to the related lecturer.
        LecturerProfile,  # Reference the related lecturer profile model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="offering_enrolments",  # Define reverse relation access.
    )
    is_primary = models.BooleanField(default=False)  # Store is primary.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        unique_together = ("offering", "lecturer")  # Enforce unique combinations.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.lecturer} -> {self.offering}"  # Return the display string.

# =====================
# Assignments and Files
# =====================
class Assignment(models.Model):  # Define the Assignment model.
    """Represent an assignment."""
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="assignments",  # Define reverse relation access.
    )
    title = models.CharField(max_length=255)  # Store title.
    description = models.TextField(blank=True)  # Store description.
    due_datetime = models.DateTimeField()  # Store due datetime.

    max_mark = models.DecimalField(  # Store max mark.
        max_digits=5,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        default=100.00,  # Set the default value.
    )

    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.
    updated_at = models.DateTimeField(auto_now=True)  # Store updated at.

    @property  # Expose a computed property.
    def module(self):  # Define module.
        """Return the related module."""
        return self.offering.module  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes(self):  # Define course_codes.
        """Return related course codes."""
        return self.offering.course_codes  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes_display(self):  # Define course_codes_display.
        """Return joined course codes."""
        return self.offering.course_codes_display  # Return the computed value.

    @property  # Expose a computed property.
    def academic_year(self):  # Define academic_year.
        """Return the related academic year."""
        return self.offering.academic_year  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.module.code} - {self.title}"  # Return the display string.

class AssignmentSubmission(models.Model):  # Define the AssignmentSubmission model.
    """Represent an assignment submission."""
    class Status(models.TextChoices):  # Define status choices.
        """Define status choices."""
        SUBMITTED = "SUBMITTED", "Submitted"  # Define the submitted option.
        LATE = "LATE", "Late"  # Define the late option.

    assignment = models.ForeignKey(  # Link to the related assignment.
        Assignment,  # Reference the related assignment model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="submissions",  # Define reverse relation access.
    )
    student = models.ForeignKey(  # Link to the related student.
        StudentProfile,  # Reference the related student profile model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="submissions",  # Define reverse relation access.
    )
    status = models.CharField(  # Store status.
        max_length=16,  # Limit stored text length.
        choices=Status.choices,  # Restrict allowed values.
        default=Status.SUBMITTED,  # Set the default value.
    )
    submitted_at = models.DateTimeField(auto_now_add=True)  # Store submitted at.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        unique_together = ("assignment", "student")  # Enforce unique combinations.

    @property  # Expose a computed property.
    def grade_safe(self):  # Define grade safe.
        """Return the grade when present."""
        try:  # Start guarded parsing.
            return self.grade  # Return the computed value.
        except AssignmentGrade.DoesNotExist:  # Handle parsing failures.
            return None  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.assignment} - {self.student}"  # Return the display string.

def submission_file_upload_path(instance, filename):  # Define submission file upload path.
    """Build the submission upload path."""
    return (  # Return the computed value.
        f"submission_files/{instance.submission.assignment.offering.id}/"  # Start the submission path.
        f"{instance.submission.assignment.module.code}/"  # Add the module code.
        f"{instance.submission.assignment.id}/"  # Add the assignment id.
        f"{instance.submission.student.student_number or instance.submission.student.id}/"  # Add the student folder.
        f"{filename}"  # Add the original filename.
    )

class SubmissionFile(models.Model):  # Define the SubmissionFile model.
    """Represent a submission file."""
    submission = models.ForeignKey(  # Link to the related submission.
        AssignmentSubmission,  # Reference the related submission model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="files",  # Define reverse relation access.
    )
    file = models.FileField(upload_to=submission_file_upload_path)  # Store the uploaded file.
    original_name = models.CharField(max_length=255, blank=True)  # Store original name.
    uploaded_by = models.ForeignKey(  # Link to the related uploaded by.
        settings.AUTH_USER_MODEL,  # Reference the configured user model.
        on_delete=models.SET_NULL,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Store uploaded at.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.original_name or self.file.name  # Return the computed value.

class AssignmentGrade(models.Model):  # Define the AssignmentGrade model.
    """Represent an assignment grade."""
    submission = models.OneToOneField(  # Link to the related submission.
        AssignmentSubmission,  # Reference the related submission model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="grade",  # Define reverse relation access.
    )
    marker = models.ForeignKey(  # Link to the related marker.
        LecturerProfile,  # Reference the related lecturer profile model.
        on_delete=models.SET_NULL,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
        related_name="graded_submissions",  # Define reverse relation access.
    )
    value = models.DecimalField(  # Store value.
        max_digits=5,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        help_text="Mark awarded for this submission.",  # Show form help text.
    )
    feedback_text = models.TextField(blank=True)  # Store feedback text.
    graded_at = models.DateTimeField(auto_now_add=True)  # Store graded at.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.submission} - {self.value}/{self.submission.assignment.max_mark}"  # Return the display string.

def assignment_file_upload_path(instance, filename):  # Define assignment file upload path.
    """Build the assignment upload path."""
    return (  # Return the computed value.
        f"assignment_files/{instance.assignment.offering.id}/"  # Start the assignment path.
        f"{instance.assignment.module.code}/"  # Add the module code.
        f"{instance.assignment.id}/{filename}"  # Add the assignment file name.
    )

class AssignmentFile(models.Model):  # Define the AssignmentFile model.
    """Represent an assignment file."""
    assignment = models.ForeignKey(  # Link to the related assignment.
        Assignment,  # Reference the related assignment model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="files",  # Define reverse relation access.
    )
    file = models.FileField(upload_to=assignment_file_upload_path)  # Store the uploaded file.
    original_name = models.CharField(max_length=255, blank=True)  # Store original name.
    uploaded_by = models.ForeignKey(  # Link to the related uploaded by.
        settings.AUTH_USER_MODEL,  # Reference the configured user model.
        on_delete=models.SET_NULL,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Store uploaded at.

    @property  # Expose a computed property.
    def parsed_document_safe(self):  # Define parsed document safe.
        """Return the parsed document when present."""
        try:  # Start guarded parsing.
            return self.parsed_document  # Return the computed value.
        except ParsedDocument.DoesNotExist:  # Handle parsing failures.
            return None  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.original_name or self.file.name  # Return the computed value.

# =======
# Quizzes
# =======
class Quiz(models.Model):  # Define the Quiz model.
    """Represent a quiz."""
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="quizzes",  # Define reverse relation access.
    )
    title = models.CharField(max_length=255)  # Store title.
    description = models.TextField(blank=True)  # Store description.

    open_datetime = models.DateTimeField()  # Store open datetime.
    close_datetime = models.DateTimeField()  # Store close datetime.

    time_limit_minutes = models.PositiveIntegerField(default=20)  # Store time limit minutes.
    max_attempts = models.PositiveSmallIntegerField(default=1)  # Store max attempts.

    max_mark = models.DecimalField(  # Store max mark.
        max_digits=6,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        default=100.00,  # Set the default value.
        help_text="Weighted mark shown to students, similar to assignment max mark.",  # Show form help text.
    )

    is_published = models.BooleanField(default=True)  # Store is published.

    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.
    updated_at = models.DateTimeField(auto_now=True)  # Store updated at.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["close_datetime", "title"]  # Define default ordering.

    @property  # Expose a computed property.
    def module(self):  # Define module.
        """Return the related module."""
        return self.offering.module  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes(self):  # Define course_codes.
        """Return related course codes."""
        return self.offering.course_codes  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes_display(self):  # Define course_codes_display.
        """Return joined course codes."""
        return self.offering.course_codes_display  # Return the computed value.

    @property  # Expose a computed property.
    def academic_year(self):  # Define academic_year.
        """Return the related academic year."""
        return self.offering.academic_year  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.module.code} - Quiz - {self.title}"  # Return the display string.

    def has_started(self, now=None):  # Define has_started.
        """Return whether the quiz has started."""
        now = now or timezone.now()  # Set now.
        return now >= self.open_datetime  # Return the computed value.

    def has_closed(self, now=None):  # Define has_closed.
        """Return whether the quiz has closed."""
        now = now or timezone.now()  # Set now.
        return now > self.close_datetime  # Return the computed value.

    def is_open(self, now=None):  # Define is_open.
        """Return whether the quiz is open."""
        now = now or timezone.now()  # Set now.
        return self.is_published and self.has_started(now=now) and not self.has_closed(now=now)  # Return the computed value.

    def total_question_marks(self):  # Define total_question_marks.
        """Return total question marks."""
        return self.questions.aggregate(total=Sum("marks"))["total"] or 0  # Return the computed value.

class QuizQuestion(models.Model):  # Define the QuizQuestion model.
    """Represent a quiz question."""
    class Type(models.TextChoices):  # Define type choices.
        """Define type choices."""
        MULTIPLE_CHOICE = "MULTIPLE_CHOICE", "Multiple choice"  # Define the multiple choice option.
        MULTIPLE_SELECT = "MULTIPLE_SELECT", "Multiple select"  # Define the multiple select option.
        TRUE_FALSE = "TRUE_FALSE", "True / False"  # Define the true / false option.
        FILL_BLANK = "FILL_BLANK", "Fill in the blank"  # Define the fill in the blank option.

    quiz = models.ForeignKey(  # Link to the related quiz.
        Quiz,  # Reference the related quiz model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="questions",  # Define reverse relation access.
    )
    prompt = models.TextField()  # Store prompt.
    question_type = models.CharField(  # Store question type.
        max_length=32,  # Limit stored text length.
        choices=Type.choices,  # Restrict allowed values.
    )
    marks = models.DecimalField(  # Store marks.
        max_digits=5,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        default=1.00,  # Set the default value.
    )
    display_order = models.PositiveIntegerField(default=1)  # Store display order.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["display_order", "id"]  # Define default ordering.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.quiz.title} - Q{self.display_order}"  # Return the display string.

class QuizOption(models.Model):  # Define the QuizOption model.
    """Represent a quiz option."""
    question = models.ForeignKey(  # Link to the related question.
        QuizQuestion,  # Reference the related quiz question model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="options",  # Define reverse relation access.
    )
    text = models.CharField(max_length=255)  # Escape the run text.
    display_order = models.PositiveIntegerField(default=1)  # Store display order.
    is_correct = models.BooleanField(default=False)  # Store is correct.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["display_order", "id"]  # Define default ordering.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.text  # Return the computed value.

class QuizAttempt(models.Model):  # Define the QuizAttempt model.
    """Represent a quiz attempt."""
    class Status(models.TextChoices):  # Define status choices.
        """Define status choices."""
        IN_PROGRESS = "IN_PROGRESS", "In Progress"  # Define the in progress option.
        SUBMITTED = "SUBMITTED", "Submitted"  # Define the submitted option.
        AUTO_SUBMITTED = "AUTO_SUBMITTED", "Auto Submitted"  # Define the auto submitted option.

    quiz = models.ForeignKey(  # Link to the related quiz.
        Quiz,  # Reference the related quiz model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="attempts",  # Define reverse relation access.
    )
    student = models.ForeignKey(  # Link to the related student.
        StudentProfile,  # Reference the related student profile model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="quiz_attempts",  # Define reverse relation access.
    )
    attempt_number = models.PositiveSmallIntegerField()  # Store attempt number.

    status = models.CharField(  # Store status.
        max_length=20,  # Limit stored text length.
        choices=Status.choices,  # Restrict allowed values.
        default=Status.IN_PROGRESS,  # Set the default value.
    )

    started_at = models.DateTimeField(auto_now_add=True)  # Store started at.
    expires_at = models.DateTimeField()  # Store expires at.
    submitted_at = models.DateTimeField(null=True, blank=True)  # Store submitted at.

    raw_score = models.DecimalField(  # Store raw score.
        max_digits=7,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        default=0.00,  # Set the default value.
    )
    weighted_score = models.DecimalField(  # Store weighted score.
        max_digits=7,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        default=0.00,  # Set the default value.
    )

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["-started_at"]  # Define default ordering.
        unique_together = ("quiz", "student", "attempt_number")  # Enforce unique combinations.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.quiz.title} - {self.student} - Attempt {self.attempt_number}"  # Return the display string.

    def is_active(self):  # Define is_active.
        """Return whether the attempt is active."""
        return self.status == self.Status.IN_PROGRESS and self.submitted_at is None  # Return the computed value.

    def is_expired(self, now=None):  # Define is_expired.
        """Return whether the attempt expired."""
        now = now or timezone.now()  # Set now.
        return now >= self.expires_at  # Return the computed value.

class QuizAnswer(models.Model):  # Define the QuizAnswer model.
    """Represent a quiz answer."""
    attempt = models.ForeignKey(  # Link to the related attempt.
        QuizAttempt,  # Reference the related quiz attempt model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="answers",  # Define reverse relation access.
    )
    question = models.ForeignKey(  # Link to the related question.
        QuizQuestion,  # Reference the related quiz question model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="answers",  # Define reverse relation access.
    )

    selected_option = models.ForeignKey(  # Link to the related selected option.
        QuizOption,  # Reference the related quiz option model.
        on_delete=models.SET_NULL,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
        related_name="+",  # Define reverse relation access.
    )
    selected_option_ids = models.JSONField(default=list, blank=True)  # Store selected option ids.

    is_correct = models.BooleanField(default=False)  # Store is correct.
    awarded_marks = models.DecimalField(  # Store awarded marks.
        max_digits=7,  # Limit total decimal digits.
        decimal_places=2,  # Set decimal precision.
        default=0.00,  # Set the default value.
    )

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        unique_together = ("attempt", "question")  # Enforce unique combinations.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.attempt} - {self.question}"  # Return the display string.

# ==========================
# Weeks and Parsed Documents
# ==========================
class ModuleWeek(models.Model):  # Define the ModuleWeek model.
    """Represent a module week."""
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="weeks",  # Define reverse relation access.
    )
    week_number = models.PositiveSmallIntegerField()  # Store week number.
    title = models.CharField(max_length=255, blank=True, default="")  # Store title.
    description = models.TextField(blank=True)  # Store description.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        unique_together = ("offering", "week_number")  # Enforce unique combinations.
        ordering = ["week_number"]  # Define default ordering.

    @property  # Expose a computed property.
    def module(self):  # Define module.
        """Return the related module."""
        return self.offering.module  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes(self):  # Define course_codes.
        """Return related course codes."""
        return self.offering.course_codes  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes_display(self):  # Define course_codes_display.
        """Return joined course codes."""
        return self.offering.course_codes_display  # Return the computed value.

    @property  # Expose a computed property.
    def academic_year(self):  # Define academic_year.
        """Return the related academic year."""
        return self.offering.academic_year  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.module.code} - Week {self.week_number}"  # Return the display string.

def module_week_file_upload_path(instance, filename):  # Define module week file upload path.
    """Build the week file upload path."""
    return (  # Return the computed value.
        f"module_files/{instance.week.offering.id}/"  # Start the week file path.
        f"{instance.week.module.code}/"  # Build this path segment.
        f"week-{instance.week.week_number}/{filename}"  # Add the week folder.
    )

class ModuleWeekFile(models.Model):  # Define the ModuleWeekFile model.
    """Represent a weekly module file."""
    week = models.ForeignKey(  # Link to the related week.
        ModuleWeek,  # Reference the related module week model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="files",  # Define reverse relation access.
    )
    file = models.FileField(upload_to=module_week_file_upload_path)  # Store the uploaded file.
    original_name = models.CharField(max_length=255, blank=True)  # Store original name.
    uploaded_by = models.ForeignKey(  # Link to the related uploaded by.
        settings.AUTH_USER_MODEL,  # Reference the configured user model.
        on_delete=models.SET_NULL,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)  # Store uploaded at.

    @property  # Expose a computed property.
    def parsed_document_safe(self):  # Define parsed document safe.
        """Return the parsed document when present."""
        try:  # Start guarded parsing.
            return self.parsed_document  # Return the computed value.
        except ParsedDocument.DoesNotExist:  # Handle parsing failures.
            return None  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.original_name or self.file.name  # Return the computed value.

def parsed_document_image_upload_path(instance, filename):  # Define parsed document image upload path.
    """Build the parsed image upload path."""
    return f"parsed_documents/{instance.parsed_document_id}/{filename}"  # Return the display string.

class ParsedDocument(models.Model):  # Define the ParsedDocument model.
    """Represent a parsed document."""
    class Status(models.TextChoices):  # Define status choices.
        """Define status choices."""
        PROCESSING = "PROCESSING", "Processing"  # Define the processing option.
        READY = "READY", "Ready"  # Define the ready option.
        FAILED = "FAILED", "Failed"  # Define the failed option.

    week_file = models.OneToOneField(  # Link to the related week file.
        "ModuleWeekFile",  # Allow the ModuleWeekFile entry.
        on_delete=models.CASCADE,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
        related_name="parsed_document",  # Define reverse relation access.
    )
    assignment_file = models.OneToOneField(  # Link to the related assignment file.
        "AssignmentFile",  # Allow the AssignmentFile entry.
        on_delete=models.CASCADE,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
        related_name="parsed_document",  # Define reverse relation access.
    )

    source_extension = models.CharField(max_length=10)  # Store source extension.
    parser_status = models.CharField(  # Store parser status.
        max_length=20,  # Limit stored text length.
        choices=Status.choices,  # Restrict allowed values.
        default=Status.PROCESSING,  # Set the default value.
    )
    parsed_blocks = models.JSONField(default=list, blank=True)  # Store parsed blocks.
    rendered_html = models.TextField(blank=True)  # Store rendered html.
    parse_error = models.TextField(blank=True)  # Store parse error.
    page_count = models.PositiveIntegerField(default=0)  # Store page count.

    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.
    updated_at = models.DateTimeField(auto_now=True)  # Store updated at.

    def clean(self):  # Define clean.
        """Validate the model state."""
        has_week_file = bool(self.week_file_id)  # Set has week file.
        has_assignment_file = bool(self.assignment_file_id)  # Set has assignment file.
        if has_week_file == has_assignment_file:  # Check the current condition.
            raise ValidationError(  # Raise a validation error.
                "ParsedDocument must be linked to exactly one source file: "  # Explain the validation rule.
                "either week_file or assignment_file."  # Complete the validation message.
            )

    def get_source_module(self):  # Define get_source_module.
        """Return the source module."""
        if self.week_file_id:  # Check the current condition.
            return self.week_file.week.offering.module  # Return the computed value.
        if self.assignment_file_id:  # Check the current condition.
            return self.assignment_file.assignment.offering.module  # Return the computed value.
        return None  # Return the computed value.

    def get_source_file(self):  # Define get_source_file.
        """Return the source file."""
        if self.week_file_id:  # Check the current condition.
            return self.week_file  # Return the computed value.
        if self.assignment_file_id:  # Check the current condition.
            return self.assignment_file  # Return the computed value.
        return None  # Return the computed value.

    def get_source_name(self):  # Define get_source_name.
        """Return the source file name."""
        source = self.get_source_file()  # Set source.
        if not source:  # Check the current condition.
            return "Unknown file"  # Return the computed value.
        return source.original_name or os.path.basename(source.file.name)  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"Parsed: {self.get_source_name()}"  # Return the display string.

class ParsedDocumentImage(models.Model):  # Define the ParsedDocumentImage model.
    """Represent a parsed document image."""
    parsed_document = models.ForeignKey(  # Link to the related parsed document.
        ParsedDocument,  # Reference the parsed document model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="images",  # Define reverse relation access.
    )
    token = models.CharField(max_length=50)  # Build a stable image token.
    image = models.ImageField(upload_to=parsed_document_image_upload_path)  # Store the uploaded image.
    display_order = models.PositiveIntegerField(default=0)  # Store display order.
    page_number = models.PositiveIntegerField(null=True, blank=True)  # Store page number.
    original_name = models.CharField(max_length=255, blank=True)  # Store original name.
    alt_text = models.TextField(blank=True)  # Build the image alt text.

    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["display_order", "id"]  # Define default ordering.
        unique_together = ("parsed_document", "token")  # Enforce unique combinations.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.original_name or self.token  # Return the computed value.

# ===============================
# Notifications and Announcements
# ===============================
class Notification(models.Model):  # Define the Notification model.
    """Represent a notification."""
    class Type(models.TextChoices):  # Define type choices.
        """Define type choices."""
        GENERAL = "GENERAL", "General"  # Define the general option.

        ASSIGNMENT_NEW = "ASSIGNMENT_NEW", "New assignment"  # Define the new assignment option.
        ASSIGNMENT_DUE_3D = "ASSIGNMENT_DUE_3D", "Assignment due in 3 days"  # Define the three-day reminder.
        ASSIGNMENT_DUE_24H = "ASSIGNMENT_DUE_24H", "Assignment due in 24 hours"  # Define the one-day reminder.
        ASSIGNMENT_SUBMITTED = "ASSIGNMENT_SUBMITTED", "Assignment submitted"  # Define the assignment submitted option.
        ASSIGNMENT_GRADED = "ASSIGNMENT_GRADED", "Assignment graded"  # Define the assignment graded option.
        ASSIGNMENT_CLOSED_SUMMARY = "ASSIGNMENT_CLOSED_SUMMARY", "Assignment closed summary"  # Define the assignment closed summary option.
        ASSIGNMENT_GRADING_REMINDER = "ASSIGNMENT_GRADING_REMINDER", "Assignment grading reminder"  # Define the assignment grading reminder option.

        QUIZ_NEW = "QUIZ_NEW", "New quiz"  # Define the new quiz option.
        QUIZ_OPENED = "QUIZ_OPENED", "Quiz opened"  # Define the quiz opened option.
        QUIZ_CLOSED = "QUIZ_CLOSED", "Quiz closed"  # Define the quiz closed option.
        QUIZ_SUBMITTED = "QUIZ_SUBMITTED", "Quiz submitted"  # Define the quiz submitted option.
        QUIZ_CLOSED_SUMMARY = "QUIZ_CLOSED_SUMMARY", "Quiz closed summary"  # Define the quiz closed summary option.

        WEEK_AVAILABLE = "WEEK_AVAILABLE", "New week available"  # Define the new week available option.

        PARSER_SUCCESS = "PARSER_SUCCESS", "Parser success"  # Define the parser success option.
        PARSER_FAILURE = "PARSER_FAILURE", "Parser failure"  # Define the parser failure option.

    recipient = models.ForeignKey(  # Link to the related recipient.
        settings.AUTH_USER_MODEL,  # Reference the configured user model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="notifications",  # Define reverse relation access.
    )
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.SET_NULL,  # Define delete behaviour.
        null=True,  # Allow null database values.
        blank=True,  # Allow blank form values.
        related_name="notifications",  # Define reverse relation access.
    )
    notification_type = models.CharField(  # Store notification type.
        max_length=40,  # Limit stored text length.
        choices=Type.choices,  # Restrict allowed values.
        default=Type.GENERAL,  # Set the default value.
    )
    title = models.CharField(max_length=255)  # Store title.
    redirect_url = models.CharField(max_length=500, blank=True)  # Store redirect url.
    event_key = models.CharField(max_length=255, null=True, blank=True)  # Store event key.
    is_read = models.BooleanField(default=False)  # Store is read.
    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.
    read_at = models.DateTimeField(null=True, blank=True)  # Store read at.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["-created_at", "-id"]  # Define default ordering.
        constraints = [  # Define model constraints.
            models.UniqueConstraint(  # Define a unique constraint.
                fields=["recipient", "event_key"],  # Target these constraint fields.
                name="unique_notification_event_per_user",  # Read the uploaded filename.
            )
        ]

    @property  # Expose a computed property.
    def module(self):  # Define module.
        """Return the related module."""
        return self.offering.module if self.offering_id else None  # Return the computed value.

    def mark_as_read(self):  # Define mark_as_read.
        """Mark the notification as read."""
        if not self.is_read:  # Check the current condition.
            self.is_read = True  # Update the model field.
            self.read_at = timezone.now()  # Update the model field.
            self.save(update_fields=["is_read", "read_at"])  # Update the model field.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.recipient} - {self.title}"  # Return the display string.

class GlobalAnnouncement(models.Model):  # Define the GlobalAnnouncement model.
    """Represent a global announcement."""
    title = models.CharField(max_length=255)  # Store title.
    content = models.TextField()  # Store content.
    created_by = models.ForeignKey(  # Link to the related created by.
        settings.AUTH_USER_MODEL,  # Reference the configured user model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="global_announcements_created",  # Define reverse relation access.
    )
    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.
    updated_at = models.DateTimeField(auto_now=True)  # Store updated at.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["-created_at", "-id"]  # Define default ordering.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return self.title  # Return the computed value.

    @classmethod  # Define a class-level helper.
    def trim_to_latest_three(cls):  # Define trim_to_latest_three.
        """Trim to the latest three announcements."""
        stale_ids = list(  # Set stale ids.
            cls.objects.order_by("-created_at", "-id")  # Order newest announcements first.
            .values_list("id", flat=True)[3:]  # Keep ids beyond the latest three.
        )
        if stale_ids:  # Check the current condition.
            cls.objects.filter(id__in=stale_ids).delete()  # Delete older announcements.

class ModuleAnnouncement(models.Model):  # Define the ModuleAnnouncement model.
    """Represent a module announcement."""
    offering = models.ForeignKey(  # Link to the related offering.
        ModuleOffering,  # Reference the related module offering model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="module_announcements",  # Define reverse relation access.
    )
    title = models.CharField(max_length=255)  # Store title.
    content = models.TextField()  # Store content.
    created_by = models.ForeignKey(  # Link to the related created by.
        settings.AUTH_USER_MODEL,  # Reference the configured user model.
        on_delete=models.CASCADE,  # Define delete behaviour.
        related_name="module_announcements_created",  # Define reverse relation access.
    )
    created_at = models.DateTimeField(auto_now_add=True)  # Store created at.
    updated_at = models.DateTimeField(auto_now=True)  # Store updated at.

    class Meta:  # Define the Meta class.
        """Configure model metadata."""
        ordering = ["-created_at", "-id"]  # Define default ordering.

    @property  # Expose a computed property.
    def module(self):  # Define module.
        """Return the related module."""
        return self.offering.module  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes(self):  # Define course_codes.
        """Return related course codes."""
        return self.offering.course_codes  # Return the computed value.

    @property  # Expose a computed property.
    def course_codes_display(self):  # Define course_codes_display.
        """Return joined course codes."""
        return self.offering.course_codes_display  # Return the computed value.

    @property  # Expose a computed property.
    def academic_year(self):  # Define academic_year.
        """Return the related academic year."""
        return self.offering.academic_year  # Return the computed value.

    def __str__(self):  # Define __str__.
        """Return the string representation."""
        return f"{self.module.code} - {self.title}"  # Return the display string.

    @classmethod  # Define a class-level helper.
    def trim_to_latest_three_for_offering(cls, offering):  # Define trim_to_latest_three_for_offering.
        """Trim to the latest three module announcements."""
        stale_ids = list(  # Set stale ids.
            cls.objects.filter(offering=offering)  # Limit results to this offering.
            .order_by("-created_at", "-id")  # Order newest announcements first.
            .values_list("id", flat=True)[3:]  # Keep ids beyond the latest three.
        )
        if stale_ids:  # Check the current condition.
            cls.objects.filter(id__in=stale_ids).delete()  # Delete older announcements.