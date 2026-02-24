from django.contrib.auth.decorators import login_required  # Imports decorator to ensure some views are only accessible to authenticated users
from django.contrib.auth.views import LoginView  # Imports Django’s built-in class-based login view for handling authentication
from django.shortcuts import redirect, render, get_object_or_404  # Common shortcuts for redirects, rendering templates, and fetching objects or returning 404
from django.urls import reverse  # Used to dynamically resolve URL patterns by their name
from django.utils import timezone  # Provides timezone-aware datetime utilities compatible with Django settings
from django.http import Http404  # Exception used to immediately return a 404 Not Found response
from django.db.models import Count, Q  # ORM helpers: Count for aggregation and Q for complex query filters
from django.views.decorators.http import require_http_methods  # Decorator to restrict allowed HTTP methods per view
from datetime import datetime  # Standard library datetime class used for parsing date and time input
from .models import User, Module, Assignment, AssignmentSubmission, AssignmentGrade, AssignmentFile, SubmissionFile, ModuleWeek, ModuleWeekFile  # Imports all custom models referenced by these views
import re  # Regular expressions module, used for validating input
from django.contrib import messages  # Django's messaging framework for passing one-time messages to templates

class RoleBasedLoginView(LoginView):  # Custom login view that extends Django’s built-in LoginView to add role-based redirects
    template_name = "accounts/login.html"  # Specifies the template to use when displaying the login form

    def get_success_url(self):  # Overrides method to control where a user is redirected after successful login
        # Redirect based on role
        user: User = self.request.user  # Grabs the authenticated user object from the current request
        if user.is_student():  # If the user has the student role, send them to the student dashboard
            return "/student-dashboard/"
        if user.is_lecturer():  # If the user has the lecturer role, send them to the lecturer dashboard
            return "/lecturer-dashboard/"
        return "/"  # fallback  # If neither role matches, fall back to redirecting to the site root
    
def register_student(request):
    """
    Public student registration.

    Fields:
      - first_name, last_name
      - email (used as username, must end with @mytudublin.ie)
      - password1, password2 (strength-checked)
      - course (string; must be one of the course codes derived from Module.allowed_courses)
      - modules (multi-select; each chosen module must allow that course)
    """
    # If someone is already logged in, don't let them register again
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""
        course = (request.POST.get("course") or "").strip()
        module_ids = request.POST.getlist("module_ids")  # multiple values

        errors: dict[str, list[str]] = {}

        # ---- Presence checks ----
        if not first_name:
            errors.setdefault("first_name", []).append("First name is required.")
        if not last_name:
            errors.setdefault("last_name", []).append("Surname is required.")
        if not email:
            errors.setdefault("email", []).append("Student email is required.")
        if not password1 or not password2:
            errors.setdefault("password", []).append("Both password fields are required.")
        if not course:
            errors.setdefault("course", []).append("Please choose a course.")
        if not module_ids:
            errors.setdefault("modules", []).append("Please select at least one module.")

        # ---- Email rules ----
        if email and not email.endswith("@mytudublin.ie"):
            errors.setdefault("email", []).append(
                "Student email must end with @mytudublin.ie."
            )

        if email and User.objects.filter(username=email).exists():
            errors.setdefault("email", []).append(
                "An account already exists for this email address."
            )

        # ---- Password rules ----
        if password1 and password2 and password1 != password2:
            errors.setdefault("password", []).append("Passwords do not match.")

        pw_errors = _validate_password_strength(password1)
        if pw_errors:
            errors.setdefault("password", []).extend(pw_errors)

        # ---- Course validity: must be one of the codes from allowed_courses ----
        valid_courses = _get_all_valid_courses()
        if course and course not in valid_courses:
            errors.setdefault("course", []).append(
                "Selected course is not recognised for any module."
            )

        # ---- Modules must exist and allow this course ----
        selected_modules = []
        if module_ids:
            selected_modules = list(
                Module.objects.filter(
                    pk__in=module_ids,
                    is_active=True,
                    allowed_courses__contains=[course],  # JSONField containment; requires PostgreSQL
                )
            )
            if len(selected_modules) != len(module_ids):
                errors.setdefault("modules", []).append(
                    "One or more selected modules are invalid for the chosen course."
                )

        if errors:
            # Re-render form with errors + previous data
            all_modules = Module.objects.filter(is_active=True).order_by("code")
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
                "modules": all_modules,
            }
            return render(request, "accounts/register_student.html", context)

        # ---- Create User + StudentProfile ----
        user = User.objects.create_user(
            username=email,         # login identifier
            email=email,            # store real email as well
            password=password1,
            first_name=first_name,
            last_name=last_name,
            role=User.Role.STUDENT,
        )

        # Use the part before '@' as student_number (e.g. 'C20441826')
        student_number = email.split("@")[0]

        from .models import StudentProfile  # local import to avoid circulars

        student_profile = StudentProfile.objects.create(
            user=user,
            student_number=student_number,
            course=course,  # store course code here
        )

        # Link modules (through ModuleEnrollmentStudent via the M2M)
        student_profile.modules.set(selected_modules)

        messages.success(
            request,
            "Registration successful. You can now log in with your student email and password.",
        )
        return redirect("accounts:login")

    # ---- GET: show empty form ----
    valid_courses = _get_all_valid_courses()
    all_modules = Module.objects.filter(is_active=True).order_by("code")

    context = {
        "errors": {},
        "form_data": {},
        "valid_courses": valid_courses,
        "modules": all_modules,
    }
    return render(request, "accounts/register_student.html", context)


@login_required  # Ensures only authenticated users can view the dashboard
def dashboard(request):  # Main dashboard view for both students and lecturers
    user: User = request.user  # Retrieve the currently logged-in user from the request

    # Shared nav items for header + footer
    nav_items = [  # Defines navigation links shared across dashboard templates
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},  # Link back to the dashboard using URL reversing
        # {"label": "Tools", "url": "#"},   # Placeholder for potential future navigation item
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},   # External link to email inbox (Outlook)
        {"label": "Website", "url": "https://www.tudublin.ie/"},  # External link to institution’s main website
    ]

    now = timezone.now()  # Capture the current timezone-aware datetime for use in date comparisons

    if user.is_student():  # Branch logic if the logged-in user is a student
        template = "accounts/student_dashboard.html"  # Use the student-specific dashboard template

        student = user.student_profile  # Get the related Student profile associated with this User

        # All active modules this student is enrolled in
        modules_qs = student.modules.filter(is_active=True).select_related()  # Query active modules related to the student, using select_related for efficiency

        # Upcoming assignments (due in the future) for those modules
        upcoming_assignments_qs = (  # Build queryset of upcoming assignments relevant to this student
            Assignment.objects.filter(
                module__in=modules_qs,  # Only include assignments from the modules the student is enrolled in
                due_datetime__gte=now,  # Restrict to assignments whose due date/time has not yet passed
            )
            .exclude(submissions__student=student)  # Exclude assignments that the student has already submitted
            .distinct()  # Ensure no duplicate assignments in case of multiple module relationships
            .select_related("module")  # Optimize queries by joining module table in the same database hit
            .order_by("due_datetime")[:6]  # Sort soonest first and limit the number of upcoming assignments shown
        )

        context = {  # Context passed into the student dashboard template
            "user": user,  # Provide the current user object so the template can show user-related information
            "nav_items": nav_items,  # Provide navigation items for the header and footer
            "modules": modules_qs,  # Provide the queryset of modules that the student is taking
            "upcoming_assignments": upcoming_assignments_qs,  # Provide the list of upcoming assignments for display
        }

    elif user.is_lecturer():  # Branch logic when the logged-in user is a lecturer
        template = "accounts/lecturer_dashboard.html"  # Use the lecturer-specific dashboard template

        lecturer = user.lecturer_profile  # Get the related Lecturer profile associated with this User

        # All active modules this lecturer teaches
        modules_qs = lecturer.modules.filter(is_active=True).select_related()  # Query all active modules connected to this lecturer

        # Ungraded submissions for those modules (no AssignmentGrade attached)
        ungraded_submissions_qs = (  # Prepare a queryset of assignment submissions that still need grading
            AssignmentSubmission.objects.filter(
                assignment__module__in=modules_qs,  # Only submissions for assignments within the lecturer’s modules
                grade__isnull=True,  # Filter to only submissions where no grade object is linked yet
            )
            .select_related(
                "assignment",  # Include referenced assignment in the same query for efficiency
                "assignment__module",  # Also prefetch the module related to the assignment
                "student",  # Include the student profile object on the submission
                "student__user",  # Include the underlying User object connected to the student profile
            )
            .order_by("-submitted_at")[:10]  # Show the most recently submitted ungraded submissions first, limited to 10
        )

        context = {  # Context passed into the lecturer dashboard template
            "user": user,  # Current logged-in user
            "nav_items": nav_items,  # Navigation links shown in the template
            "modules": modules_qs,  # List of modules taught by the lecturer
            "ungraded_submissions": ungraded_submissions_qs,  # List of submissions needing grading
        }

    else:  # If user has neither recognized role, treat as invalid for this dashboard
        return redirect("accounts:login")  # Redirect non-student/non-lecturer users back to the login page

    return render(request, template, context)  # Render the appropriate dashboard template with the assembled context


@login_required  # Only authenticated users can view module details
def module_detail(request, code):  # View that shows detailed information for a specific module by its code
    """
    Show details for a single module:
    - For students: module info + assignments + weeks that have files
    - For lecturers: module info + assignments + all weeks (1–15) with upload & edit
    """
    user: User = request.user  # Get the currently authenticated user from the request

    # Shared nav items for header + footer
    nav_items = [  # Reuse the navigation structure for module detail pages
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},  # Link back to the dashboard
        # {"label": "Tools", "url": "#"},   # Placeholder for potential future navigation item
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},   # Link to external email inbox
        {"label": "Website", "url": "https://www.tudublin.ie/"},  # Link to main institutional website
    ]
    # Try to fetch the module by code
    try:
        module = (  # Attempt to fetch the module instance matching the provided code
            Module.objects
            .prefetch_related("assignments")  # Prefetch related assignments to reduce later queries
            .get(code=code)  # Filter the Module table by the given module code
        )
    except Module.DoesNotExist:  # If the module code is invalid or not found
        raise Http404("Module not found")  # Immediately return a 404 response indicating missing module

    if user.is_student():  # Branch for student view of module details
        student = user.student_profile  # Retrieve Student profile linked to current user
        if not student.modules.filter(pk=module.pk).exists():  # Ensure the student is actually enrolled in this module
            raise Http404("Module not found")  # If not enrolled, treat as nonexistent to the student

        role = "student"  # Track current role for template logic

        assignments = module.assignments.order_by("due_datetime")  # Get module’s assignments ordered by due date

        # Only weeks that actually have files (so students only see populated weeks)
        weeks = (  # Build queryset of weeks visible to students
            module.weeks
            .filter(files__isnull=False)  # Only include weeks that have at least one attached file
            .prefetch_related("files")  # Prefetch the related files for efficiency
            .order_by("week_number")  # Order weeks chronologically by week number
            .distinct()  # Remove duplicate rows caused by joins on files
        )

        context = {  # Context for the student module detail template
            "user": user,  # Current user object for per-user presentation
            "nav_items": nav_items,  # Shared navigation links
            "module": module,  # The module being viewed
            "role": role,  # Role string so template can branch on permissions
            "assignments": assignments,  # List of assignments in this module
            "weeks": weeks,  # Only weeks that have attached learning files
        }

    elif user.is_lecturer():  # Branch for lecturer view of module details
        lecturer = user.lecturer_profile  # Retrieve Lecturer profile for this user
        if not lecturer.modules.filter(pk=module.pk).exists():  # Ensure this lecturer actually teaches the module
            raise Http404("Module not found")  # If not, return a 404 to avoid leaking module existence

        role = "lecturer"  # Track role for use in the template logic

        # Assignments + submissions summary
        assignments = (  # Generate a queryset of assignments with summary fields
            module.assignments
            .all()  # Start from all assignments linked to this module
            .annotate(
                total_submissions=Count("submissions", distinct=True),  # Count how many submissions each assignment has
                ungraded_submissions=Count(
                    "submissions",
                    filter=Q(submissions__grade__isnull=True),  # Count only submissions that have no grade yet
                    distinct=True,
                ),
            )
            .order_by("due_datetime")  # Sort assignments by due date for logical display
        )

        # Ensure weeks 1–30 exist for this module
        for wn in range(1, 31):  # Loop through week numbers 1 to 30 inclusive
            ModuleWeek.objects.get_or_create(
                module=module,  # Attach the week to the current module
                week_number=wn,  # Set the numeric week identifier
                defaults={"title": f"Week {wn}"},  # If created, give the week a default title based on its number
            )

        # Lecturers see all weeks 1–30 (even if empty)
        weeks = (  # Queryset of all weeks for this module
            module.weeks
            .all()  # Include every week row regardless of whether it has files
            .prefetch_related("files")  # Prefetch related files to minimize database queries
            .order_by("week_number")  # Sort by week number to show a chronological view
        )

        context = {  # Context for the lecturer module detail template
            "user": user,  # Current user object
            "nav_items": nav_items,  # Common navigation bar items
            "module": module,  # The module being examined
            "role": role,  # Lecturer role for template branching
            "assignments": assignments,  # Assignments along with submission counts
            "weeks": weeks,  # All weeks for this module, even without content
        }

    else:  # If user is neither student nor lecturer
        return redirect("accounts:login")  # Redirect back to login as a fallback

    return render(request, "accounts/module_detail.html", context)  # Render module detail template with the prepared context


@login_required  # Restrict file uploads to authenticated users
def upload_week_file(request, code, week_number):  # View for lecturers to upload a file to a specific module week
    """Lecturer-only upload of a file for a given week."""
    user: User = request.user  # Get the logged-in user
    if not user.is_lecturer():  # Check that the user is a lecturer before proceeding
        raise Http404("Not found")  # Return 404 to hide this functionality from non-lecturers

    lecturer = user.lecturer_profile  # Retrieve Lecturer profile tied to this user
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Fetch module by code that is taught by this lecturer or 404

    week, _ = ModuleWeek.objects.get_or_create(  # Fetch the ModuleWeek instance for this module and week number, creating if missing
        module=module,  # Attach the week to the fetched module
        week_number=week_number,  # Use supplied week number from the URL
        defaults={"title": f"Week {week_number}"},  # If a new week is created, assign a default title with week number
    )

    if request.method == "POST" and "file" in request.FILES:  # Only handle file uploads when request is POST and a file is provided
        uploaded = request.FILES["file"]  # Retrieve the uploaded file object from form data
        ModuleWeekFile.objects.create(  # Create a new ModuleWeekFile record representing the uploaded file
            week=week,  # Associate the file with the relevant module week
            file=uploaded,  # Store the uploaded file in the configured storage
            original_name=uploaded.name,  # Preserve original filename for display
            uploaded_by=user,  # Track which user uploaded the file
        )

    return redirect("accounts:module_detail", code=module.code)  # After processing, redirect back to the module detail page


@login_required  # Only authenticated users can access week description editing
def edit_week_description(request, code, week_number):  # View allowing lecturers to edit text description for a week
    """Lecturer-only: update the description text for a given week."""
    user: User = request.user  # Retrieve the current user
    if not user.is_lecturer():  # Confirm the user has lecturer role
        raise Http404("Not found")  # Return 404 to disallow non-lecturer access

    lecturer = user.lecturer_profile  # Get Lecturer profile for authorization
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Ensure module exists and is taught by this lecturer

    week, _ = ModuleWeek.objects.get_or_create(  # Get or create corresponding ModuleWeek for the provided week number
        module=module,  # Tie the week to the selected module
        week_number=week_number,  # Identify which week is being edited
        defaults={"title": f"Week {week_number}"},  # Assign default title if the week is newly created
    )

    if request.method == "POST":  # Only update when submitted via POST
        description = request.POST.get("description", "").strip()  # Extract and clean the new description text from the form
        week.description = description  # Assign the description to the week object
        week.save()  # Persist the changes to the database

    return redirect("accounts:module_detail", code=module.code)  # Redirect back to the module detail page afterward


@login_required  # Require authentication for creating assignments
@require_http_methods(["GET", "POST"])  # Limit this view to only handle GET and POST methods
def create_assignment(request, code):  # View that lets a lecturer create a new assignment for a given module
    """
    Lecturer-only view: create an assignment for a specific module,
    with optional attached files.
    """
    user: User = request.user  # Get the current user from request
    if not user.is_lecturer():  # Verify the user has lecturer privileges
        raise Http404("Not found")  # Deny access to non-lecturers with a 404

    lecturer = user.lecturer_profile  # Retrieve Lecturer profile from user
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Fetch the module that belongs to this lecturer or raise 404

    errors = []  # Initialize a list to accumulate validation error messages
    if request.method == "POST":  # Handle form submission logic
        title = request.POST.get("title", "").strip()  # Extract the assignment title from form POST data
        description = request.POST.get("description", "").strip()  # Extract the assignment description text
        due_date_str = request.POST.get("due_date", "").strip()  # Extract string representing the due date
        due_time_str = request.POST.get("due_time", "").strip()  # Extract string representing the due time
        max_mark_str = request.POST.get("max_mark", "").strip() or "100"  # Extract maximum mark, defaulting to "100" if missing

        if not title:  # Check that a title was provided
            errors.append("Title is required.")  # Add readable error message to the list
        if not due_date_str:  # Ensure due date string is not empty
            errors.append("Due date is required.")  # Add error if missing
        if not due_time_str:  # Ensure due time string is not empty
            errors.append("Due time is required.")  # Add error if missing

        due_dt = None  # Initialize due datetime variable to None before parsing
        if due_date_str and due_time_str:  # Only attempt to parse when both date and time strings are present
            try:
                # Expecting HTML date + time-local format: YYYY-MM-DD and HH:MM
                due_dt = datetime.fromisoformat(f"{due_date_str} {due_time_str}")  # Combine date and time strings into a single datetime object
            except ValueError:  # Catch parsing issues if the input format is invalid
                errors.append("Invalid due date/time format.")  # Record a validation error

        try:
            max_mark_val = float(max_mark_str)  # Attempt to convert the maximum mark string into a floating-point number
        except ValueError:  # Handle invalid numeric input for max mark
            errors.append("Max mark must be a number.")  # Add an error message describing the issue
            max_mark_val = 100.0  # Fallback default value if parsing fails

        if not errors and due_dt is not None:  # Proceed only if there are no validation errors and due date/time is valid
            assignment = Assignment.objects.create(  # Create a new Assignment record in the database
                module=module,  # Attach the new assignment to the selected module
                title=title,  # Store the assignment title
                description=description,  # Store the assignment description
                due_datetime=timezone.make_aware(due_dt)  # Convert naive datetime to timezone-aware if needed
                if timezone.is_naive(due_dt)
                else due_dt,  # Otherwise, use as-is if already timezone-aware
                max_mark=max_mark_val,  # Set the maximum mark that can be awarded
            )

            # Handle file uploads (multiple allowed)
            for uploaded in request.FILES.getlist("files"):  # Iterate over all uploaded files from the file input named "files"
                AssignmentFile.objects.create(  # Create an AssignmentFile entry for each uploaded file
                    assignment=assignment,  # Link file to the newly created assignment
                    file=uploaded,  # Save the file content to storage
                    original_name=uploaded.name,  # Store original filename for reference
                    uploaded_by=user,  # Indicate which lecturer uploaded the file
                )

            return redirect("accounts:module_detail", code=module.code)  # Redirect to the module detail page after successful creation

    else:
        # Defaults for GET
        assignment = None  # Placeholder variable for template compatibility (no assignment yet on GET)
        due_date_str = ""  # Empty default due date string for a blank form
        due_time_str = ""  # Empty default due time string
        max_mark_str = "100"  # Default maximum mark shown as 100
        description = ""  # Default description field content
        title = ""  # Default title field content

    # Render the form with any errors
    context = {  # Context dictionary for the assignment creation template
        "user": user,  # Current user for template use
	# Shared nav items for header + footer
        "nav_items": [  # Provide navigation links
            {"label": "Dashboard", "url": reverse("accounts:dashboard")},  # Dashboard link
            # {"label": "Tools", "url": "#"},   # Placeholder for extra nav item
            {"label": "Inbox", "url": "https://outlook.office.com/mail/"},   # Link to external Outlook inbox
            {"label": "Website", "url": "https://www.tudublin.ie/"},  # Instituitional website link
        ],
        "module": module,  # Module context for which assignment is being created
        "errors": errors,  # Any validation errors to be displayed in the template
        "initial": {  # Values used to refill the form fields in case of errors
            "title": request.POST.get("title", "") if request.method == "POST" else "",  # Preserve or default the title field
            "description": request.POST.get("description", "") if request.method == "POST" else "",  # Preserve or default description
            "due_date": request.POST.get("due_date", "") if request.method == "POST" else "",  # Preserve or default due date
            "due_time": request.POST.get("due_time", "") if request.method == "POST" else "",  # Preserve or default due time
            "max_mark": request.POST.get("max_mark", "") if request.method == "POST" else "100",  # Preserve or default maximum mark
        },
    }

    return render(request, "accounts/create_assignment.html", context)  # Render the assignment creation form template with this context


@login_required  # Ensure only authenticated users can view assignment details
def assignment_detail(request, code, assignment_id):  # View that displays details for a particular assignment within a module
    """
    Show details for a single assignment.
    - Student: sees description, lecturer files, their own submission (+ grade if any), upload form.
    - Lecturer: sees description, files, and all submissions for that assignment.
    """
    user: User = request.user  # Get the current authenticated user

    # Shared nav items for header + footer
    nav_items = [  # Navigation links used on assignment detail pages
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},  # Link to dashboard
        # {"label": "Tools", "url": "#"},   # Placeholder for future nav elements
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},   # Direct link to Outlook inbox
        {"label": "Website", "url": "https://www.tudublin.ie/"},  # Direct link to website homepage
    ]

    module = get_object_or_404(Module, code=code)  # Fetch module by code, or return 404 if not found

    # Fetch assignment from this module
    assignment = get_object_or_404(  # Fetch assignment ensuring that it belongs to the specified module
        Assignment.objects.select_related("module"),  # Optimize query by selecting related module
        pk=assignment_id,  # Filter by primary key of the assignment
        module=module,  # Ensure the assignment is tied to the current module
    )

    if user.is_student():  # If the user is a student, show student-specific assignment view
        student = user.student_profile  # Retrieve the Student profile associated with the user
        # must be enrolled in this module
        if not student.modules.filter(pk=module.pk).exists():  # Ensure student is actually enrolled in this module
            raise Http404("Assignment not found")  # Hide existence of assignment if not enrolled

        # student's own submission (if any)
        submission = (  # Query for a single AssignmentSubmission object for this student and assignment
            AssignmentSubmission.objects
            .filter(assignment=assignment, student=student)  # Filter by current assignment and student
            .select_related("grade")  # Include related grade if it exists
            .prefetch_related("files")  # Prefetch any attached submission files
            .first()  # Return first result or None if there is no submission yet
        )

        context = {  # Context for rendering the student assignment detail template
            "user": user,  # Current user object
            "nav_items": nav_items,  # Shared navigation links
            "module": module,  # Module that the assignment belongs to
            "assignment": assignment,  # The assignment being viewed
            "role": "student",  # Role string used by template to branch behavior
            "submission": submission,  # Student’s existing submission, if present
        }
        template = "accounts/assignment_detail.html"  # Template used for both student and lecturer assignment detail views

    elif user.is_lecturer():  # If the user is a lecturer, show lecturer-specific assignment view
        lecturer = user.lecturer_profile  # Retrieve Lecturer profile for the user
        # must teach this module
        if not lecturer.modules.filter(pk=module.pk).exists():  # Ensure this lecturer teaches the module
            raise Http404("Assignment not found")  # Hide assignment if lecturer has no relation to the module

        # all submissions for this assignment
        submissions = (  # Build queryset of all submissions for this assignment
            AssignmentSubmission.objects
            .filter(assignment=assignment)  # Filter submissions by current assignment
            .select_related("student__user", "grade")  # Prefetch student’s user object and attached grade
            .prefetch_related("files")  # Prefetch any files uploaded with each submission
            .order_by("-submitted_at")  # Sort submissions with the most recent at the top
        )

        context = {  # Context for lecturer assignment detail template
            "user": user,  # Current user
            "nav_items": nav_items,  # Navigation items
            "module": module,  # Module object
            "assignment": assignment,  # Assignment object
            "role": "lecturer",  # Role string used for template branching
            "submissions": submissions,  # All submissions for this assignment
        }
        template = "accounts/assignment_detail.html"  # Use the assignment detail template for lecturer view as well

    else:  # If user is not recognized as student or lecturer
        return redirect("accounts:login")  # Send them back to the login page

    return render(request, template, context)  # Render the chosen template with the computed context


@login_required  # Require authentication to submit assignments
@require_http_methods(["POST"])  # This view only accepts POST requests (submissions)
def submit_assignment(request, code, assignment_id):  # View that handles submission of assignment files by a student
    """
    Student-only: submit files for an assignment.
    Creates or updates a single AssignmentSubmission per student+assignment.
    """
    user: User = request.user  # Get the authenticated user
    if not user.is_student():  # Ensure that only students can submit assignments
        raise Http404("Not found")  # Return 404 if a non-student tries this endpoint

    student = user.student_profile  # Retrieve Student profile linked to this user
    module = get_object_or_404(Module, code=code)  # Fetch the module by its code or raise 404 if missing

    # must be enrolled
    if not student.modules.filter(pk=module.pk).exists():  # Confirm that the student is enrolled in this module
        raise Http404("Not found")  # If not enrolled, hide the endpoint with a 404

    assignment = get_object_or_404(  # Fetch assignment linked to module and given ID or 404 if not found
        Assignment,
        pk=assignment_id,  # Primary key of the assignment
        module=module,  # Enforce that the assignment belongs to this module
    )

    # create or get submission
    submission, created = AssignmentSubmission.objects.get_or_create(  # Retrieve existing submission or create a new one for student+assignment
        assignment=assignment,  # Link submission to the chosen assignment
        student=student,  # Link submission to the current student
        defaults={"status": AssignmentSubmission.Status.SUBMITTED},  # Initial default status if a new submission is created
    )

    # update status (handle late)
    now = timezone.now()  # Capture the current time for comparison with due datetime
    if assignment.due_datetime and now > assignment.due_datetime:  # Check if the current time is later than assignment due time
        submission.status = AssignmentSubmission.Status.LATE  # Mark submission as late if submitted after due date
    else:
        submission.status = AssignmentSubmission.Status.SUBMITTED  # Otherwise mark as a normal submitted status
    submission.submitted_at = now  # Record the timestamp at which the submission was made or updated
    submission.save()  # Persist submission changes to the database

    # attach uploaded files
    for uploaded in request.FILES.getlist("files"):  # Iterate over each uploaded file from the submission form
        SubmissionFile.objects.create(  # Create a new SubmissionFile record for each uploaded file
            submission=submission,  # Attach the file to the existing submission object
            file=uploaded,  # Save file binary data through Django’s file storage
            original_name=uploaded.name,  # Keep original filename for display to user
            uploaded_by=user,  # Track which user uploaded the file (the student)
        )

    return redirect("accounts:assignment_detail", code=module.code, assignment_id=assignment.id)  # Redirect back to the assignment detail page after submission


@login_required  # Ensure user is logged in to grade submissions
@require_http_methods(["GET", "POST"])  # Allow both GET (display form) and POST (submit form) on this view
def grade_submission(request, code, assignment_id, submission_id):  # View for lecturers to create or update a grade for a submission
    """
    Lecturer-only: create or update a grade for a specific submission.
    """
    user: User = request.user  # Get the current authenticated user
    if not user.is_lecturer():  # Make sure only lecturers can access grading functionality
        raise Http404("Not found")  # Return 404 for unauthorized roles to conceal endpoint

    lecturer = user.lecturer_profile  # Retrieve Lecturer profile instance
    module = get_object_or_404(Module, code=code, lecturers=lecturer)  # Confirm module exists and is taught by this lecturer
    assignment = get_object_or_404(Assignment, pk=assignment_id, module=module)  # Fetch assignment belonging to this module or 404
    submission = get_object_or_404(  # Fetch the specific submission to be graded
        AssignmentSubmission.objects.select_related("student__user"),  # Prefetch related student and user for display
        pk=submission_id,  # Primary key of submission
        assignment=assignment,  # Ensure submission belongs to this assignment
    )

    errors = []  # Initialize list to hold validation error messages
    grade_obj = getattr(submission, "grade", None)  # Retrieve the associated grade object if it exists, else None
    initial_value = ""  # Default initial value for mark input
    initial_feedback = ""  # Default initial feedback text

    if grade_obj:  # If a grade already exists
        initial_value = grade_obj.value  # Use existing grade value as initial form value
        initial_feedback = grade_obj.feedback_text or ""  # Use existing feedback text or empty string if None

    if request.method == "POST":  # When form is submitted to create or update a grade
        value_str = request.POST.get("value", "").strip()  # Extract mark (as string) from POST data
        feedback = request.POST.get("feedback", "").strip()  # Extract feedback text from POST data

        if not value_str:  # Ensure that a mark value has been provided
            errors.append("A mark is required.")  # Add validation error for missing mark
        else:
            try:
                value_float = float(value_str)  # Attempt to convert mark to float
            except ValueError:  # If conversion fails, mark input is invalid
                errors.append("Mark must be a number.")  # Notify user of invalid mark
                value_float = None  # Reset parsed value

        if not errors and value_float is not None:  # Only proceed when there are no validation errors and mark is numeric
            if grade_obj is None:  # If no grade record exists yet, create a new one
                grade_obj = AssignmentGrade.objects.create(
                    submission=submission,  # Link grade to this submission
                    marker=lecturer,  # Set the marker as the current lecturer
                    value=value_float,  # Store the numeric grade value
                    feedback_text=feedback,  # Store textual feedback
                )
            else:  # If a grade already exists, update it in place
                grade_obj.value = value_float  # Update the numeric grade
                grade_obj.feedback_text = feedback  # Update the feedback text
                grade_obj.marker = lecturer  # Update marker to reflect who last updated the grade
                grade_obj.save()  # Save updated grade information to the database

            return redirect("accounts:assignment_detail", code=module.code, assignment_id=assignment.id)  # After saving, redirect back to the assignment detail page

    context = {  # Build context for the grade submission template
        "user": user,  # Current user
        # Shared nav items for header + footer
        "nav_items": [  # Reusable navigation menu
            {"label": "Dashboard", "url": reverse("accounts:dashboard")},  # Link to dashboard
            # {"label": "Tools", "url": "#"},   # Placeholder route not yet active
            {"label": "Inbox", "url": "https://outlook.office.com/mail/"},   # Link to Outlook inbox
            {"label": "Website", "url": "https://www.tudublin.ie/"},  # Institutional website link
        ],
        "module": module,  # Current module context
        "assignment": assignment,  # Current assignment context
        "submission": submission,  # Submission being graded
        "errors": errors,  # List of any validation error messages
        "initial": {  # Initial values to pre-populate the grading form
            "value": request.POST.get("value", initial_value) if request.method == "POST" else initial_value,  # Mark value
            "feedback": request.POST.get("feedback", initial_feedback) if request.method == "POST" else initial_feedback,  # Feedback text
        },
    }

    return render(request, "accounts/grade_submission.html", context)  # Render the grade submission template with provided context

def _validate_password_strength(password: str) -> list[str]:
    errors: list[str] = []
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter.")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one number.")
    if not re.search(r"[^\w\s]", password):
        errors.append("Password must contain at least one special character (e.g. !, @, #).")
    return errors

def _get_all_valid_courses() -> list[str]:
    """
    Aggregate all allowed course codes from Module.allowed_courses.
    Returns a sorted unique list, e.g. ["TU856", "TU123"].
    """
    courses_set = set()
    # allowed_courses is a JSONField storing a list of course codes per module
    for allowed in Module.objects.values_list("allowed_courses", flat=True):
        if isinstance(allowed, list):
            for c in allowed:
                if c:
                    courses_set.add(str(c))
    return sorted(courses_set)
