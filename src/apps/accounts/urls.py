from django.urls import path  # Imports the path function for defining URL patterns in this app
from django.contrib.auth.views import LogoutView  # Imports Django's built-in view for handling user logout
from django.conf.urls.static import static  # Provides helper to serve static files in development (even if not used here directly)

from .views import RoleBasedLoginView, dashboard, admin_dashboard, admin_add_lecturer, admin_add_module, admin_edit_enrollment, admin_create_global_announcement, admin_edit_global_announcement, admin_delete_global_announcement, user_profile, open_notification, portal, module_detail, create_module_announcement, edit_module_announcement, delete_module_announcement, add_module_week, upload_week_file, create_assignment, assignment_detail, submit_assignment, grade_submission, register_student, parsed_document_modal, edit_parsed_document_images, create_quiz, quiz_detail, start_quiz_attempt, save_quiz_progress, submit_quiz_attempt, update_accessibility_preferences, global_announcement_modal, module_announcement_modal, save_module_week  # Imports all view functions/classes referenced in this URL config

app_name = "accounts"  # Namespaces these URLs under "accounts" so they can be reversed with the 'accounts:' prefix

urlpatterns = [  # List of URL patterns that map URLs to views for this app
    
    path("", dashboard, name="dashboard"),  # Root of the accounts app; sends user to the dashboard view

    path("login/", RoleBasedLoginView.as_view(), name="login"),  # URL for logging in; uses custom role-based login view
    path("logout/", LogoutView.as_view(next_page="accounts:login"), name="logout"),  # URL for logging out; redirects to login page afterwards
    path("register/", register_student, name="register"), # URL for student registration; uses a view that handles the registration form and logic

    path("admin-dashboard/", admin_dashboard, name="admin_dashboard"),
    path("admin-dashboard/lecturers/new/", admin_add_lecturer, name="admin_add_lecturer"),
    path("admin-dashboard/modules/new/", admin_add_module, name="admin_add_module"),
    path("admin-dashboard/enrollment/", admin_edit_enrollment, name="admin_edit_enrollment"),
    path("admin-dashboard/announcements/new/", admin_create_global_announcement, name="admin_create_global_announcement"),
    path("admin-dashboard/announcements/<int:announcement_id>/edit/", admin_edit_global_announcement, name="admin_edit_global_announcement"),
    path("admin-dashboard/announcements/<int:announcement_id>/delete/", admin_delete_global_announcement, name="admin_delete_global_announcement"),
    
    path("student-dashboard/", dashboard, name="student_dashboard"),  # URL alias for student dashboard; uses same dashboard view
    path("lecturer-dashboard/", dashboard, name="lecturer_dashboard"),  # URL alias for lecturer dashboard; also uses shared dashboard view
    path("profile/", user_profile, name="profile"),  # URL for viewing user profile; handled by user_profile view
    path("portal/", portal, name="portal"), # URL for the portal page; handled by the portal view
    path("notifications/<int:notification_id>/open/", open_notification, name="open_notification"),
    path("modules/<str:code>/", module_detail, name="module_detail"),  # URL for viewing a specific module; 'code' dynamic segment identifies module

    path(
        "modules/<str:code>/weeks/add/",
        add_module_week,
        name="add_module_week",
    ),
    path(  # URL pattern to upload a file for a specific week of a module
        "modules/<str:code>/weeks/<int:week_number>/upload/",  # Path with module code and week number as URL parameters
        upload_week_file,  # View handling the file upload logic for that week
        name="upload_week_file",  # Name used to reverse this route in templates and code
    ),
    path(  # URL pattern to edit description text for a specific week of a module
        "modules/<str:code>/weeks/<int:week_number>/description/",  # Path with module code and week number for description edits
        edit_week_description,  # View that processes updating the week description
        name="edit_week_description",  # Named route used for URL reversing in templates/forms
    ),

    path(  # URL pattern for creating a new assignment within a module
        "modules/<str:code>/assignments/new/",  # Module code in URL, with 'new' indicating assignment creation
        create_assignment,  # View that displays and processes the assignment creation form
        name="create_assignment",  # Named route for linking to the assignment creation page
    ),
    path(  # URL pattern for viewing details of a specific assignment
        "modules/<str:code>/assignments/<int:assignment_id>/",  # Includes module code and assignment ID as URL parameters
        assignment_detail,  # View that shows assignment info (different display for student/lecturer)
        name="assignment_detail",  # Name used for reversing this assignment detail URL
    ),
    path(  # URL pattern for a student to submit work for a specific assignment
        "modules/<str:code>/assignments/<int:assignment_id>/submit/",  # Path including module and assignment identifiers with 'submit' action
        submit_assignment,  # View that handles creating/updating an assignment submission
        name="submit_assignment",  # Named route to use in assignment submission forms
    ),
    path(  # URL pattern for a lecturer to grade a specific submission for an assignment
        "modules/<str:code>/assignments/<int:assignment_id>/submissions/<int:submission_id>/grade/",  # Includes module, assignment, and submission IDs
        grade_submission,  # View that displays and processes the grading form
        name="grade_submission",  # Named route for linking to or redirecting to the grading page
    ),
    path(
        "parsed-documents/<int:parsed_id>/modal/",
        parsed_document_modal,
        name="parsed_document_modal",
    ),
    path(
        "parsed-documents/<int:parsed_id>/images/",
        edit_parsed_document_images,
        name="edit_parsed_document_images",
    ),
        path(
        "modules/<str:code>/quizzes/new/",
        create_quiz,
        name="create_quiz",
    ),
    path(
        "modules/<str:code>/quizzes/<int:quiz_id>/",
        quiz_detail,
        name="quiz_detail",
    ),
    path(
        "modules/<str:code>/quizzes/<int:quiz_id>/start/",
        start_quiz_attempt,
        name="start_quiz_attempt",
    ),
    path(
        "modules/<str:code>/quizzes/<int:quiz_id>/save-progress/",
        save_quiz_progress,
        name="save_quiz_progress",
    ),
    path(
        "modules/<str:code>/quizzes/<int:quiz_id>/submit/",
        submit_quiz_attempt,
        name="submit_quiz_attempt",
    ),
    path(
        "modules/<str:code>/announcements/new/", 
        create_module_announcement, 
        name="create_module_announcement"
    ),
    path(
        "modules/<str:code>/announcements/<int:announcement_id>/edit/", 
        edit_module_announcement, 
        name="edit_module_announcement"
    ),
    path(
        "modules/<str:code>/announcements/<int:announcement_id>/delete/", 
        delete_module_announcement, 
        name="delete_module_announcement"
    ),
    path(
        "preferences/accessibility/",
        update_accessibility_preferences,
        name="update_accessibility_preferences",
    ),
    path(
        "announcements/global/<int:announcement_id>/modal/",
        global_announcement_modal,
        name="global_announcement_modal",
    ),
    path(
        "modules/<str:code>/announcements/<int:announcement_id>/modal/",
        module_announcement_modal,
        name="module_announcement_modal",
    ),
    path(
        "modules/<str:code>/weeks/<int:week_number>/save/",
        save_module_week,
        name="save_module_week",
    ),
]

