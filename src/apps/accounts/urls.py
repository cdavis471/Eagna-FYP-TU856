# =======
# Imports
# =======
from django.urls import path  # Import URL path helper.
from django.contrib.auth.views import LogoutView  # Import the logout view.
from django.conf.urls.static import static  # Import static file helper.
from .views import RoleBasedLoginView, dashboard, admin_dashboard, admin_add_lecturer, admin_add_module, admin_edit_enrollment, admin_create_global_announcement, admin_edit_global_announcement, admin_delete_global_announcement, admin_add_course, admin_manage_student_account, admin_manage_lecturer_account, admin_manage_academic_year, admin_retire_module, user_profile, open_notification, portal, register_student, parsed_document_modal, edit_parsed_document_images, update_accessibility_preferences, global_announcement_modal, read_all_notifications, student_join_modules, offering_detail, offering_assignment_detail, offering_quiz_detail, offering_module_announcement_modal, offering_create_module_announcement, offering_edit_module_announcement, offering_delete_module_announcement, offering_add_module_week, offering_save_module_week, offering_upload_week_file, offering_create_assignment, offering_edit_assignment, offering_delete_assignment, offering_create_quiz, offering_edit_quiz, offering_delete_quiz, offering_start_quiz_attempt, offering_save_quiz_progress, offering_submit_quiz_attempt, offering_submit_assignment, offering_grade_submission  # Import referenced views.

# ============
# URL Patterns
# ============
app_name = "accounts"  # Set the application namespace.

urlpatterns = [  # Define application URL patterns.

    path("", dashboard, name="dashboard"),  # Map the dashboard route.

    path("login/", RoleBasedLoginView.as_view(), name="login"),  # Map the login route.
    path("logout/", LogoutView.as_view(next_page="accounts:login"), name="logout"),  # Map the logout route.
    path("register/", register_student, name="register"),  # Map the register route.

    path("admin-dashboard/", admin_dashboard, name="admin_dashboard"),  # Map the admin dashboard route.
    path("admin-dashboard/lecturers/new/", admin_add_lecturer, name="admin_add_lecturer"),  # Map the admin add lecturer route.
    path("admin-dashboard/modules/new/", admin_add_module, name="admin_add_module"),  # Map the admin add module route.
    path("admin-dashboard/enrollment/", admin_edit_enrollment, name="admin_edit_enrollment"),  # Map the admin edit enrollment route.
    path("admin-dashboard/students/manage/", admin_manage_student_account, name="admin_manage_student_account"),  # Map this application route.
    path("admin-dashboard/lecturers/manage/", admin_manage_lecturer_account, name="admin_manage_lecturer_account"),  # Map this application route.
    path("admin-dashboard/announcements/new/", admin_create_global_announcement, name="admin_create_global_announcement"),  # Map this application route.
    path("admin-dashboard/announcements/<int:announcement_id>/edit/", admin_edit_global_announcement, name="admin_edit_global_announcement"),  # Map this application route.
    path("admin-dashboard/announcements/<int:announcement_id>/delete/", admin_delete_global_announcement, name="admin_delete_global_announcement"),  # Map this application route.
    path("admin-dashboard/courses/new/", admin_add_course, name="admin_add_course"),  # Map the admin add course route.
    path("admin-dashboard/academic-year/", admin_manage_academic_year, name="admin_manage_academic_year"),  # Map this application route.
    path("admin-dashboard/modules/retire/", admin_retire_module, name="admin_retire_module"),  # Map the admin retire module route.

    path("student-dashboard/", dashboard, name="student_dashboard"),  # Map the student dashboard route.
    path("lecturer-dashboard/", dashboard, name="lecturer_dashboard"),  # Map the lecturer dashboard route.
    path("profile/", user_profile, name="profile"),  # Map the profile route.
    path("portal/", portal, name="portal"),  # Map the portal route.
    path("notifications/<int:notification_id>/open/", open_notification, name="open_notification"),  # Map the open notification route.
    path("my-modules/join/", student_join_modules, name="student_join_modules"),  # Map the student join modules route.

    path("offerings/<int:offering_id>/", offering_detail, name="offering_detail"),  # Map the offering detail route.
    path(  # Open a URL pattern.
        "parsed-documents/<int:parsed_id>/modal/",  # Set the route pattern.
        parsed_document_modal,  # Set the target view.
        name="parsed_document_modal",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "parsed-documents/<int:parsed_id>/images/",  # Set the route pattern.
        edit_parsed_document_images,  # Set the target view.
        name="edit_parsed_document_images",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "preferences/accessibility/",  # Set the route pattern.
        update_accessibility_preferences,  # Set the target view.
        name="update_accessibility_preferences",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "announcements/global/<int:announcement_id>/modal/",  # Set the route pattern.
        global_announcement_modal,  # Set the target view.
        name="global_announcement_modal",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "notifications/read-all/",  # Set the route pattern.
        read_all_notifications,  # Set the target view.
        name="read_all_notifications",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/",  # Set the route pattern.
        offering_assignment_detail,  # Set the target view.
        name="offering_assignment_detail",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/",  # Set the route pattern.
        offering_quiz_detail,  # Set the target view.
        name="offering_quiz_detail",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/announcements/<int:announcement_id>/modal/",  # Set the route pattern.
        offering_module_announcement_modal,  # Set the target view.
        name="offering_module_announcement_modal",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/announcements/new/",  # Set the route pattern.
        offering_create_module_announcement,  # Set the target view.
        name="offering_create_module_announcement",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/announcements/<int:announcement_id>/edit/",  # Set the route pattern.
        offering_edit_module_announcement,  # Set the target view.
        name="offering_edit_module_announcement",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/announcements/<int:announcement_id>/delete/",  # Set the route pattern.
        offering_delete_module_announcement,  # Set the target view.
        name="offering_delete_module_announcement",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/weeks/add/",  # Set the route pattern.
        offering_add_module_week,  # Set the target view.
        name="offering_add_module_week",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/weeks/<int:week_number>/save/",  # Set the route pattern.
        offering_save_module_week,  # Set the target view.
        name="offering_save_module_week",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/weeks/<int:week_number>/upload/",  # Set the route pattern.
        offering_upload_week_file,  # Set the target view.
        name="offering_upload_week_file",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/assignments/new/",  # Set the route pattern.
        offering_create_assignment,  # Set the target view.
        name="offering_create_assignment",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/new/",  # Set the route pattern.
        offering_create_quiz,  # Set the target view.
        name="offering_create_quiz",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/submit/",  # Set the route pattern.
        offering_submit_assignment,  # Set the target view.
        name="offering_submit_assignment",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/submissions/<int:submission_id>/grade/",  # Set the route pattern.
        offering_grade_submission,  # Set the target view.
        name="offering_grade_submission",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/start/",  # Set the route pattern.
        offering_start_quiz_attempt,  # Set the target view.
        name="offering_start_quiz_attempt",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/save-progress/",  # Set the route pattern.
        offering_save_quiz_progress,  # Set the target view.
        name="offering_save_quiz_progress",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/submit/",  # Set the route pattern.
        offering_submit_quiz_attempt,  # Set the target view.
        name="offering_submit_quiz_attempt",  # Set the route name.
    ),  # Close the current call.
        path(  # Open a URL pattern.
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/edit/",  # Set the route pattern.
        offering_edit_assignment,  # Set the target view.
        name="offering_edit_assignment",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/assignments/<int:assignment_id>/delete/",  # Set the route pattern.
        offering_delete_assignment,  # Set the target view.
        name="offering_delete_assignment",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/edit/",  # Set the route pattern.
        offering_edit_quiz,  # Set the target view.
        name="offering_edit_quiz",  # Set the route name.
    ),  # Close the current call.
    path(  # Open a URL pattern.
        "offerings/<int:offering_id>/quizzes/<int:quiz_id>/delete/",  # Set the route pattern.
        offering_delete_quiz,  # Set the target view.
        name="offering_delete_quiz",  # Set the route name.
    ),  # Close the current call.
]  # Close the current list.

