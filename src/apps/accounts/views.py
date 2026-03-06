from django.contrib.auth.decorators import login_required  # Imports decorator to ensure some views are only accessible to authenticated users
from django.contrib.auth.views import LoginView  # Imports Django’s built-in class-based login view for handling authentication
from django.shortcuts import redirect, render, get_object_or_404  # Common shortcuts for redirects, rendering templates, and fetching objects or returning 404
from django.urls import reverse  # Used to dynamically resolve URL patterns by their name
from django.utils import timezone  # Provides timezone-aware datetime utilities compatible with Django settings
from django.http import Http404  # Exception used to immediately return a 404 Not Found response
from django.db.models import Count, Q  # ORM helpers: Count for aggregation and Q for complex query filters
from django.views.decorators.http import require_http_methods  # Decorator to restrict allowed HTTP methods per view
from datetime import datetime  # Standard library datetime class used for parsing date and time input
from django.contrib import messages  # Django's messaging framework for passing one-time messages to templates
from django.core.files.base import ContentFile  # Utility for creating file objects from raw content, used in file handling
from django.db import transaction  # Provides atomic transaction management for database operations, ensuring data integrity
from .document_parsing import build_rendered_html_from_blocks, parse_uploaded_office_file
from .models import User, Module, Assignment, AssignmentSubmission, AssignmentGrade, AssignmentFile, SubmissionFile, ModuleWeek, ModuleWeekFile, ParsedDocument, ParsedDocumentImage  # Imports all custom models referenced by these views
import re  # Regular expressions module, used for validating input

# Shared Navigation Menu Items (used in multiple views for consistent header/footer links)
def _shared_nav_items():
    return [
        {"label": "Dashboard", "url": reverse("accounts:dashboard")},
        {"label": "Inbox", "url": "https://outlook.office.com/mail/"},
        {"label": "Website", "url": "https://www.tudublin.ie/"},
    ]

# Parsed Document Handling
# Rebuild the rendered HTML for a parsed document based on its blocks and associated images, and optionally save the updated document. 
# This is used after parsing a new document or when updating an existing one to ensure the rendered HTML reflects the current parsed content and images.
def _rebuild_parsed_document_html(parsed_document: ParsedDocument, save: bool = True) -> str:
    image_lookup = {
        image.token: {
            "src": image.image.url,
            "alt_text": image.alt_text or "",
        }
        for image in parsed_document.images.all()
    }

    parsed_document.rendered_html = build_rendered_html_from_blocks(
        parsed_document.parsed_blocks or [],
        image_lookup=image_lookup,
    )

    if save:
        parsed_document.save(update_fields=["rendered_html", "updated_at"])

    return parsed_document.rendered_html

# Persistent Parsed Document Creation with Error Handling
# This function takes the raw parsed payload from the document parsing process, creates a ParsedDocument record, saves associated images, and builds the rendered HTML. 
# If any step fails, it ensures that all created records and files are cleaned up to maintain data integrity.
def _persist_parsed_document(
    *,
    parsed_payload: dict,
    week_file: ModuleWeekFile | None = None,
    assignment_file: AssignmentFile | None = None,
) -> ParsedDocument:
    parsed_document = ParsedDocument.objects.create(
        week_file=week_file,
        assignment_file=assignment_file,
        source_extension=parsed_payload["extension"],
        parser_status=ParsedDocument.Status.PROCESSING,
        parsed_blocks=parsed_payload["blocks"],
        page_count=parsed_payload["page_count"],
    )

    created_images: list[ParsedDocumentImage] = []

    try:
        for image_data in parsed_payload.get("images", []):
            image_obj = ParsedDocumentImage(
                parsed_document=parsed_document,
                token=image_data["token"],
                display_order=image_data.get("display_order") or 0,
                page_number=image_data.get("page_number"),
                original_name=image_data.get("filename", ""),
                alt_text=image_data.get("alt_text", ""),
            )
            image_obj.image.save(
                image_data["filename"],
                ContentFile(image_data["content"]),
                save=True,
            )
            created_images.append(image_obj)

        _rebuild_parsed_document_html(parsed_document, save=False)

        parsed_document.parser_status = ParsedDocument.Status.READY
        parsed_document.parse_error = ""
        parsed_document.save(update_fields=["rendered_html", "parser_status", "parse_error", "updated_at"])

        return parsed_document

    except Exception:
        for image in created_images:
            if image.image:
                image.image.delete(save=False)

        ParsedDocumentImage.objects.filter(parsed_document=parsed_document).delete()
        parsed_document.delete()
        raise

# Authorization Check for Parsed Document Access
# This function retrieves a ParsedDocument by its ID and checks if the given user has permission to access it based on their role and module associations. 
# It returns the parsed document and its source module if authorized, or raises a 404 error if the document doesn't exist or the user isn't authorized to view it.
def _get_authorised_parsed_document(parsed_id: int, user: User) -> tuple[ParsedDocument, Module]:
    parsed_document = get_object_or_404(
        ParsedDocument.objects.select_related(
            "week_file__week__module",
            "assignment_file__assignment__module",
        ).prefetch_related("images"),
        pk=parsed_id,
    )

    module = parsed_document.get_source_module()
    if module is None:
        raise Http404("Parsed document not found")

    if user.is_student():
        if not user.student_profile.modules.filter(pk=module.pk).exists():
            raise Http404("Parsed document not found")
    elif user.is_lecturer():
        if not user.lecturer_profile.modules.filter(pk=module.pk).exists():
            raise Http404("Parsed document not found")
    else:
        raise Http404("Parsed document not found")

    return parsed_document, module

# Rollover Maintenance
def _rollover_modules_if_due():
    today = timezone.localdate()
    qs = Module.objects.filter(is_active=True).exclude(start_date__isnull=True)
    for m in qs:
        if m.needs_rollover(today=today):
            m.rollover(today=today)

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
    # If someone is already logged in, don't let them register again
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        email = (request.POST.get("email") or "").strip().lower()
        password1 = request.POST.get("password1") or ""
        password2 = request.POST.get("password2") or ""
        course_raw = request.POST.get("course") or ""
        course = _normalize_course_code(course_raw)
        module_ids = request.POST.getlist("module_ids")  # multiple values

        errors: dict[str, list[str]] = {}

        # Presence Checks
        if not first_name:
            errors.setdefault("first_name", []).append("First name is required.")
        if not last_name:
            errors.setdefault("last_name", []).append("Surname is required.")
        if not email:
            errors.setdefault("email", []).append("Student email is required.")
        if not password1 or not password2:
            errors.setdefault("password", []).append("Both password fields are required.")
        if not course:
            errors.setdefault("course", []).append("Course code is required.")
        elif not COURSE_CODE_RE.match(course):
            errors.setdefault("course", []).append(
                "Course code must be 3–10 characters and contain only letters / numbers."
            )
        if not module_ids:
            errors.setdefault("modules", []).append("Please select at least one module.")

        # Email Rules
        if email and not email.endswith("@mytudublin.ie"):
            errors.setdefault("email", []).append(
                "Student email must end with @mytudublin.ie."
            )

        if email and User.objects.filter(username=email).exists():
            errors.setdefault("email", []).append(
                "An account already exists for this email address."
            )

        # Password Rules
        if password1 and password2 and password1 != password2:
            errors.setdefault("password", []).append("Passwords do not match.")

        pw_errors = _validate_password_strength(password1)
        if pw_errors:
            errors.setdefault("password", []).extend(pw_errors)

        # Course validity: must be one of the codes from allowed_courses
        valid_courses = _get_all_valid_courses()
        if course and course not in valid_courses:
            errors.setdefault("course", []).append(
                "Selected course is not recognised for any module."
            )

        # Modules must exist and allow this course
        selected_modules = []
        if module_ids:
            selected_modules = list(
                Module.objects.filter(pk__in=module_ids, is_active=True).filter(
                    Q(allowed_courses=[]) | Q(allowed_courses__contains=[course])
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
            return render(request, "accounts/registration.html", context)

        # Create User + StudentProfile
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
            "Registration Successful. You can now log in with your student email and password!",
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
    return render(request, "accounts/registration.html", context)


@login_required  # Ensures only authenticated users can view the dashboard
def dashboard(request):  # Main dashboard view for both students and lecturers
    _rollover_modules_if_due() # Check For Rollover
    user: User = request.user  # Retrieve the currently logged-in user from the request

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
            "nav_items": _shared_nav_items(),  # Provide navigation items for the header and footer
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
            "nav_items": _shared_nav_items(),  # Navigation links shown in the template
            "modules": modules_qs,  # List of modules taught by the lecturer
            "ungraded_submissions": ungraded_submissions_qs,  # List of submissions needing grading
        }

    else:  # If user has neither recognized role, treat as invalid for this dashboard
        return redirect("accounts:login")  # Redirect non-student/non-lecturer users back to the login page

    return render(request, template, context)  # Render the appropriate dashboard template with the assembled context


@login_required  # Only authenticated users can view module details
def module_detail(request, code):  # View that shows detailed information for a specific module by its code

    user: User = request.user  # Get the currently authenticated user from the request

    # Try to fetch the module by code
    try:
        module = (  # Attempt to fetch the module instance matching the provided code
            Module.objects
            .prefetch_related("assignments")  # Prefetch related assignments to reduce later queries
            .get(code=code)  # Filter the Module table by the given module code
        )
    except Module.DoesNotExist:  # If the module code is invalid or not found
        raise Http404("Module not found")  # Immediately return a 404 response indicating missing module
    
    run_start, run_end = module.current_cycle_window()  # Get the current run's start and end dates for display in the template

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
            .prefetch_related("files__parsed_document")
            .order_by("week_number")  # Order weeks chronologically by week number
            .distinct()  # Remove duplicate rows caused by joins on files
        )

        context = {  # Context for the student module detail template
            "user": user,  # Current user object for per-user presentation
            "nav_items": _shared_nav_items(),  # Shared navigation links
            "module": module,  # The module being viewed
            "role": role,  # Role string so template can branch on permissions
            "assignments": assignments,  # List of assignments in this module
            "weeks": weeks,  # Only weeks that have attached learning files
            "run_start": run_start, # Pass the module's run_start date for display in the template
            "run_end": run_end, # Pass the module's run_end date for display in the template
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
            .prefetch_related("files__parsed_document")
            .order_by("week_number")  # Sort by week number to show a chronological view
        )

        context = {  # Context for the lecturer module detail template
            "user": user,  # Current user object
            "nav_items": _shared_nav_items(),  # Common navigation bar items
            "module": module,  # The module being examined
            "role": role,  # Lecturer role for template branching
            "assignments": assignments,  # Assignments along with submission counts
            "weeks": weeks,  # All weeks for this module, even without content
            "run_start": run_start, # Pass the module's run_start date for display in the template
            "run_end": run_end, # Pass the module's run_end date for display in the template
        }

    else:  # If user is neither student nor lecturer
        return redirect("accounts:login")  # Redirect back to login as a fallback

    return render(request, "accounts/module_detail.html", context)  # Render module detail template with the prepared context


@login_required  # Restrict file uploads to authenticated users
def upload_week_file(request, code, week_number):  # View for lecturers to upload a file to a specific module week

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

    if request.method == "POST":
        if "file" not in request.FILES:
            messages.error(request, "Please choose a .docx or .pptx file to upload.")
            return redirect("accounts:module_detail", code=module.code)

        uploaded = request.FILES["file"]

        try:
            parsed_payload = parse_uploaded_office_file(uploaded)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("accounts:module_detail", code=module.code)
        except Exception:
            messages.error(
                request,
                "The file could not be translated into accessible HTML. "
                "Please upload a readable .docx or .pptx containing text, tables, and images.",
            )
            return redirect("accounts:module_detail", code=module.code)

        week_file = None

        try:
            with transaction.atomic():
                week_file = ModuleWeekFile.objects.create(
                    week=week,
                    file=uploaded,
                    original_name=uploaded.name,
                    uploaded_by=user,
                )

                _persist_parsed_document(
                    parsed_payload=parsed_payload,
                    week_file=week_file,
                )

        except Exception:
            if week_file and week_file.file:
                week_file.file.delete(save=False)

            messages.error(
                request,
                "The file was not published because parsing/storage failed.",
            )
            return redirect("accounts:module_detail", code=module.code)

        messages.success(request, "Weekly file uploaded and parsed successfully.")

    return redirect("accounts:module_detail", code=module.code)  # After processing, redirect back to the module detail page


@login_required  # Only authenticated users can access week description editing
def edit_week_description(request, code, week_number):  # View allowing lecturers to edit text description for a week

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


@login_required
@require_http_methods(["GET", "POST"])
def create_assignment(request, code):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    lecturer = user.lecturer_profile
    module = get_object_or_404(Module, code=code, lecturers=lecturer)

    errors = []

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        description = request.POST.get("description", "").strip()
        due_date_str = request.POST.get("due_date", "").strip()
        due_time_str = request.POST.get("due_time", "").strip()
        max_mark_str = request.POST.get("max_mark", "").strip() or "100"

        if not title:
            errors.append("Title is required.")
        if not due_date_str:
            errors.append("Due date is required.")
        if not due_time_str:
            errors.append("Due time is required.")

        due_dt = None
        if due_date_str and due_time_str:
            try:
                due_dt = datetime.fromisoformat(f"{due_date_str} {due_time_str}")
            except ValueError:
                errors.append("Invalid due date/time format.")

        try:
            max_mark_val = float(max_mark_str)
        except ValueError:
            errors.append("Max mark must be a number.")
            max_mark_val = 100.0

        uploaded_files = request.FILES.getlist("files")
        parsed_file_payloads: list[tuple] = []

        if not errors and uploaded_files:
            for uploaded in uploaded_files:
                try:
                    parsed_payload = parse_uploaded_office_file(uploaded)
                    parsed_file_payloads.append((uploaded, parsed_payload))
                except ValueError as exc:
                    errors.append(f"{uploaded.name}: {exc}")
                except Exception:
                    errors.append(
                        f"{uploaded.name}: The file could not be translated into accessible HTML."
                    )

        if not errors and due_dt is not None:
            assignment = None
            created_assignment_files: list[AssignmentFile] = []

            try:
                with transaction.atomic():
                    assignment = Assignment.objects.create(
                        module=module,
                        title=title,
                        description=description,
                        due_datetime=timezone.make_aware(due_dt)
                        if timezone.is_naive(due_dt)
                        else due_dt,
                        max_mark=max_mark_val,
                    )

                    for uploaded, parsed_payload in parsed_file_payloads:
                        assignment_file = AssignmentFile.objects.create(
                            assignment=assignment,
                            file=uploaded,
                            original_name=uploaded.name,
                            uploaded_by=user,
                        )
                        created_assignment_files.append(assignment_file)

                        _persist_parsed_document(
                            parsed_payload=parsed_payload,
                            assignment_file=assignment_file,
                        )

            except Exception:
                for assignment_file in created_assignment_files:
                    if assignment_file.file:
                        assignment_file.file.delete(save=False)

                errors.append(
                    "The assignment was not published because one or more uploaded files "
                    "failed during parsing/storage."
                )
            else:
                messages.success(request, "Assignment created successfully.")
                return redirect(
                    "accounts:assignment_detail",
                    code=module.code,
                    assignment_id=assignment.id,
                )

    else:
        due_date_str = ""
        due_time_str = ""
        title = ""
        description = ""
        max_mark_str = "100"

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "errors": errors,
        "initial": {
            "title": title,
            "description": description,
            "due_date": due_date_str,
            "due_time": due_time_str,
            "max_mark": max_mark_str,
        },
    }
    return render(request, "accounts/create_assignment.html", context)

@login_required  # Ensure only authenticated users can view assignment details
def assignment_detail(request, code, assignment_id):  # View that displays details for a particular assignment within a module

    user: User = request.user  # Get the current authenticated user

    module = get_object_or_404(Module, code=code)  # Fetch module by code, or return 404 if not found

    # Fetch assignment from this module
    assignment = get_object_or_404(  # Fetch assignment ensuring that it belongs to the specified module
        Assignment.objects.select_related("module").prefetch_related("files__parsed_document"),
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
            "nav_items": _shared_nav_items(),  # Shared navigation links
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
            "nav_items": _shared_nav_items(),  # Navigation items
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
        "nav_items": _shared_nav_items(),
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

@login_required
@require_http_methods(["GET"])
def parsed_document_modal(request, parsed_id):
    user: User = request.user
    parsed_document, module = _get_authorised_parsed_document(parsed_id, user)
    source_file = parsed_document.get_source_file()

    context = {
        "parsed_document": parsed_document,
        "module": module,
        "source_file": source_file,
        "document_title": parsed_document.get_source_name(),
        "can_edit_images": user.is_lecturer(),
    }
    return render(request, "accounts/partials/parsed_document_modal.html", context)

@login_required
@require_http_methods(["GET", "POST"])
def edit_parsed_document_images(request, parsed_id):
    user: User = request.user
    if not user.is_lecturer():
        raise Http404("Not found")

    parsed_document, module = _get_authorised_parsed_document(parsed_id, user)

    if request.method == "POST":
        for image in parsed_document.images.all():
            image.alt_text = request.POST.get(f"alt_{image.id}", "").strip()
            image.save(update_fields=["alt_text"])

        _rebuild_parsed_document_html(parsed_document, save=True)
        messages.success(request, "Image descriptions updated successfully.")

        return redirect("accounts:edit_parsed_document_images", parsed_id=parsed_document.id)

    context = {
        "user": user,
        "nav_items": _shared_nav_items(),
        "module": module,
        "parsed_document": parsed_document,
    }
    return render(request, "accounts/edit_parsed_document_images.html", context)

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
    Returns a sorted unique list of normalized codes (3–10 chars, A–Z/0–9).
    """
    courses_set = set()
    for allowed in Module.objects.values_list("allowed_courses", flat=True):
        if isinstance(allowed, list):
            for c in allowed:
                code = _normalize_course_code(str(c))
                if COURSE_CODE_RE.match(code):
                    courses_set.add(code)
    return sorted(courses_set)

COURSE_CODE_RE = re.compile(r"^[A-Z0-9]{3,10}$")

def _normalize_course_code(raw: str) -> str:
    """
    Normalize user-entered course code:
    - strip whitespace
    - remove internal spaces
    - uppercase
    """
    raw = (raw or "").strip().upper()
    raw = raw.replace(" ", "")
    return raw
