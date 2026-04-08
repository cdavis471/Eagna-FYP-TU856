from django.urls import path  # Imports the path function for defining URL patterns in this app
from django.contrib.auth.views import LogoutView  # Imports Django's built-in view for handling user logout
from django.conf.urls.static import static  # Provides helper to serve static files in development (even if not used here directly)

from .views import RoleBasedLoginView, dashboard, admin_dashboard, admin_add_lecturer, admin_add_module, admin_edit_enrollment, admin_create_global_announcement, admin_edit_global_announcement, admin_delete_global_announcement, admin_add_course, admin_manage_student_account, admin_manage_lecturer_account, admin_manage_academic_year, admin_retire_module, user_profile, open_notification, portal, register_student, parsed_document_modal, edit_parsed_document_images, update_accessibility_preferences, global_announcement_modal, read_all_notifications, student_join_modules, offering_detail, offering_assignment_detail, offering_quiz_detail, offering_module_announcement_modal, offering_create_module_announcement, offering_edit_module_announcement, offering_delete_module_announcement, offering_add_module_week, offering_save_module_week, offering_upload_week_file, offering_create_assignment, offering_create_quiz, offering_start_quiz_attempt, offering_save_quiz_progress, offering_submit_quiz_attempt, offering_submit_assignment, offering_grade_submission  # Imports all view functions/classes referenced in this URL config

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
    path("admin-dashboard/students/manage/", admin_manage_student_account, name="admin_manage_student_account"),
    path("admin-dashboard/lecturers/manage/", admin_manage_lecturer_account, name="admin_manage_lecturer_account"),
    path("admin-dashboard/announcements/new/", admin_create_global_announcement, name="admin_create_global_announcement"),
    path("admin-dashboard/announcements/<int:announcement_id>/edit/", admin_edit_global_announcement, name="admin_edit_global_announcement"),
    path("admin-dashboard/announcements/<int:announcement_id>/delete/", admin_delete_global_announcement, name="admin_delete_global_announcement"),
    path("admin-dashboard/courses/new/", admin_add_course, name="admin_add_course"),
    path("admin-dashboard/academic-year/", admin_manage_academic_year, name="admin_manage_academic_year"),
    path("admin-dashboard/modules/retire/", admin_retire_module, name="admin_retire_module"),

    path("student-dashboard/", dashboard, name="student_dashboard"),  # URL alias for student dashboard; uses same dashboard view
    path("lecturer-dashboard/", dashboard, name="lecturer_dashboard"),  # URL alias for lecturer dashboard; also uses shared dashboard view
    path("profile/", user_profile, name="profile"),  # URL for viewing user profile; handled by user_profile view
    path("portal/", portal, name="portal"), # URL for the portal page; handled by the portal view
    path("notifications/<int:notification_id>/open/", open_notification, name="open_notification"),
    path("my-modules/join/", student_join_modules, name="student_join_modules"),

    path("offerings/<int:offering_id>/", offering_detail, name="offering_detail"),
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
        "notifications/read-all/",
        read_all_notifications,
        name="read_all_notifications",
    ),
    path(
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/",
        offering_assignment_detail,
        name="offering_assignment_detail",
    ),
    path(
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/",
        offering_quiz_detail,
        name="offering_quiz_detail",
    ),
    path(
        "offerings/<int:offering_id>/announcements/<int:announcement_id>/modal/",
        offering_module_announcement_modal,
        name="offering_module_announcement_modal",
    ),
    path(
        "offerings/<int:offering_id>/announcements/new/",
        offering_create_module_announcement,
        name="offering_create_module_announcement",
    ),
    path(
        "offerings/<int:offering_id>/announcements/<int:announcement_id>/edit/",
        offering_edit_module_announcement,
        name="offering_edit_module_announcement",
    ),
    path(
        "offerings/<int:offering_id>/announcements/<int:announcement_id>/delete/",
        offering_delete_module_announcement,
        name="offering_delete_module_announcement",
    ),
    path(
        "offerings/<int:offering_id>/weeks/add/",
        offering_add_module_week,
        name="offering_add_module_week",
    ),
    path(
        "offerings/<int:offering_id>/weeks/<int:week_number>/save/",
        offering_save_module_week,
        name="offering_save_module_week",
    ),
    path(
        "offerings/<int:offering_id>/weeks/<int:week_number>/upload/",
        offering_upload_week_file,
        name="offering_upload_week_file",
    ),
    path(
        "offerings/<int:offering_id>/assignments/new/",
        offering_create_assignment,
        name="offering_create_assignment",
    ),
    path(
        "offerings/<int:offering_id>/quizzes/new/",
        offering_create_quiz,
        name="offering_create_quiz",
    ),
    path(
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/submit/",
        offering_submit_assignment,
        name="offering_submit_assignment",
    ),
    path(
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/submissions/<int:submission_id>/grade/",
        offering_grade_submission,
        name="offering_grade_submission",
    ),
    path(
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/start/",
        offering_start_quiz_attempt,
        name="offering_start_quiz_attempt",
    ),
    path(
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/save-progress/",
        offering_save_quiz_progress,
        name="offering_save_quiz_progress",
    ),
    path(
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/submit/",
        offering_submit_quiz_attempt,
        name="offering_submit_quiz_attempt",
    ),
]

