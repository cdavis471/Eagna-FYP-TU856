from django.contrib.auth.models import AbstractUser  # Import Django's base user model that can be extended
from django.db import models  # Import Django's ORM model base classes and field types
from django.conf import settings  # Import project settings to reference AUTH_USER_MODEL, etc.

class User(AbstractUser):  # Custom user model extending Django's AbstractUser
    class Role(models.TextChoices):  # Inner class defining choices for the user's role
        STUDENT = "STUDENT", "Student"  # Database value and human-readable label for student role
        LECTURER = "LECTURER", "Lecturer"  # Database value and human-readable label for lecturer role

    role = models.CharField(  # Field storing whether this user is a student or lecturer
        max_length=20,  # Maximum length of the string stored for the role
        choices=Role.choices,  # Restricts allowed values to the Role enum choices
        default=Role.STUDENT,  # Default role if none is specified when creating a user
    )

    def is_student(self):  # Helper method to check if user is a student
        return self.role == self.Role.STUDENT  # Returns True if role field equals the STUDENT choice

    def is_lecturer(self):  # Helper method to check if user is a lecturer
        return self.role == self.Role.LECTURER  # Returns True if role field equals the LECTURER choice

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

class Module(models.Model):  # Represents a module/course unit students can be enrolled in
    code = models.CharField(max_length=32, unique=True)  # Unique code that identifies the module (e.g., TU856)
    title = models.CharField(max_length=255)  # Human-readable title/name of the module

    academic_year_start = models.PositiveIntegerField(default=2025)  # Starting year of academic cycle, e.g. 2025
    semester = models.PositiveSmallIntegerField(default=1) # Semester number (e.g. 1 or 2) for the module

    is_active = models.BooleanField(default=True)  # Flag to mark whether module is active/available

    students = models.ManyToManyField(  # Many-to-many relation to students enrolled in this module
        StudentProfile,  # Related model is StudentProfile
        through="ModuleEnrollmentStudent",  # Uses a custom through model storing extra enrolment data
        related_name="modules",  # Allows reverse lookup via student_profile.modules
        blank=True,  # Can be empty (no students enrolled yet)
    )
    lecturers = models.ManyToManyField(  # Many-to-many relation to lecturers teaching this module
        LecturerProfile,  # Related model is LecturerProfile
        through="ModuleEnrollmentLecturer",  # Uses a custom through model for lecturer enrolments
        related_name="modules",  # Allows reverse lookup via lecturer_profile.modules
        blank=True,  # Can be empty (no lecturers assigned yet)
    )

    allowed_courses = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="List of course codes (e.g. ['TU856', 'TU123']) that are allowed to enroll in this module. Leave empty for no restrictions."
    )

    def __str__(self):  # String representation for a module
        return f"{self.code} - {self.title}"  # Shows module code with its title

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

