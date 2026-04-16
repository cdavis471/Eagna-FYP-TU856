# =======
# Imports
# =======
from datetime import timedelta  # Import time offset helpers.
from django.contrib.auth import get_user_model  # Import the active user model.
from django.core.management.base import BaseCommand  # Import the base command class.
from django.urls import reverse  # Import URL reversing helpers.
from django.utils import timezone  # Import timezone-aware helpers.
from apps.accounts.models import Assignment, Notification, Quiz  # Import notification source models.
from apps.accounts.notifications import create_notifications_for_users  # Import notification creation helper.

# ==========
# User Model
# ==========
User = get_user_model()  # Resolve the configured user model.

# ===============================
# Notification Generation Command
# ===============================
class Command(BaseCommand):
    """Generate scheduled assignment and quiz notifications."""

    help = "Generate scheduled notifications for due dates, quiz open/close events, and grading reminders."  # Describe the command purpose.

    def handle(self, *args, **options):
        """Run all scheduled notification generators."""

        now = timezone.now()  # Capture the current time.
        window_start = now - timedelta(minutes=65)  # Create the recent event window.

        total_created = 0  # Track all created notifications.
        total_created += self._generate_assignment_due_notifications(now)  # Add due date reminders.
        total_created += self._generate_quiz_opened_notifications(window_start, now)  # Add quiz opening notices.
        total_created += self._generate_assignment_closed_notifications(window_start, now)  # Add assignment closure summaries.
        total_created += self._generate_quiz_closed_notifications(window_start, now)  # Add quiz closure summaries.
        total_created += self._generate_assignment_grading_reminders(window_start, now)  # Add grading reminders.

        self.stdout.write(self.style.SUCCESS(f"Generated {total_created} notifications."))  # Print the final total.

    # =======================
    # Recipient Query Helpers
    # =======================
    def _student_users_for_offering(self, offering):
        """Return enrolled students for an offering."""

        return User.objects.filter(  # Query students linked to the offering.
            student_profile__offering_enrolments__offering=offering  # Match the target offering.
        ).distinct()  # Remove duplicate user rows.

    def _lecturer_users_for_offering(self, offering):
        """Return lecturers assigned to an offering."""

        return User.objects.filter(  # Query lecturers linked to the offering.
            lecturer_profile__offering_enrolments__offering=offering  # Match the target offering.
        ).distinct()  # Remove duplicate user rows.

    def _students_without_submission(self, assignment):
        """Return students missing an assignment submission."""

        return (  # Build the missing-submission student queryset.
            self._student_users_for_offering(assignment.offering)  # Start with enrolled students.
            .exclude(student_profile__submissions__assignment=assignment)  # Exclude submitted students.
            .distinct()  # Remove duplicate user rows.
        )

    # ============================
    # Assignment Due Notifications
    # ============================
    def _generate_assignment_due_notifications(self, now):
        """Create three-day and one-day assignment reminders."""

        created_count = 0  # Track created notifications.

        three_day_lower = now + timedelta(hours=71)  # Start the three-day window.
        three_day_upper = now + timedelta(hours=72)  # End the three-day window.

        one_day_lower = now + timedelta(hours=23)  # Start the one-day window.
        one_day_upper = now + timedelta(hours=24)  # End the one-day window.

        assignments_three_days = (  # Fetch assignments due in three days.
            Assignment.objects.select_related("offering__module")
            .filter(due_datetime__gt=three_day_lower, due_datetime__lte=three_day_upper)
            .order_by("due_datetime")
        )

        for assignment in assignments_three_days:  # Notify students about three-day deadlines.
            created_count += create_notifications_for_users(
                self._students_without_submission(assignment),  # Target students without submissions.
                offering=assignment.offering,  # Link the relevant offering.
                title=f"Assignment due in 3 days: {assignment.title}",  # Build the notification title.
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],  # Link to the assignment detail page.
                ),
                notification_type=Notification.Type.ASSIGNMENT_DUE_3D,  # Mark the notification type.
                event_key=f"assignment-due-3d:{assignment.id}",  # Prevent duplicate notifications.
            )

        assignments_one_day = (  # Fetch assignments due in one day.
            Assignment.objects.select_related("offering__module")
            .filter(due_datetime__gt=one_day_lower, due_datetime__lte=one_day_upper)
            .order_by("due_datetime")
        )

        for assignment in assignments_one_day:  # Notify students about one-day deadlines.
            created_count += create_notifications_for_users(
                self._students_without_submission(assignment),  # Target students without submissions.
                offering=assignment.offering,  # Link the relevant offering.
                title=f"Assignment due in 24 hours: {assignment.title}",  # Build the notification title.
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],  # Link to the assignment detail page.
                ),
                notification_type=Notification.Type.ASSIGNMENT_DUE_24H,  # Mark the notification type.
                event_key=f"assignment-due-24h:{assignment.id}",  # Prevent duplicate notifications.
            )

        return created_count  # Return the created total.

    # ==========================
    # Quiz Opening Notifications
    # ==========================
    def _generate_quiz_opened_notifications(self, window_start, now):
        """Create notifications for newly opened quizzes."""

        created_count = 0  # Track created notifications.

        quizzes = (  # Fetch quizzes opened within the window.
            Quiz.objects.select_related("offering__module")
            .filter(
                is_published=True,  # Only include published quizzes.
                open_datetime__gt=window_start,  # Keep recent openings only.
                open_datetime__lte=now,  # Exclude future openings.
            )
            .order_by("open_datetime")
        )

        for quiz in quizzes:  # Notify students about opened quizzes.
            created_count += create_notifications_for_users(
                self._student_users_for_offering(quiz.offering),  # Target enrolled students.
                offering=quiz.offering,  # Link the relevant offering.
                title=f"Quiz opened: {quiz.title}",  # Build the notification title.
                redirect_url=reverse(
                    "accounts:offering_quiz_detail",
                    args=[quiz.offering.id, quiz.id],  # Link to the quiz detail page.
                ),
                notification_type=Notification.Type.QUIZ_OPENED,  # Mark the notification type.
                event_key=f"quiz-opened:{quiz.id}",  # Prevent duplicate notifications.
            )

        return created_count  # Return the created total.

    # ================================
    # Assignment Closure Notifications
    # ================================
    def _generate_assignment_closed_notifications(self, window_start, now):
        """Create lecturer summaries for closed assignments."""

        created_count = 0  # Track created notifications.

        assignments = (  # Fetch assignments closed within the window.
            Assignment.objects.select_related("offering__module")
            .filter(
                due_datetime__gt=window_start,  # Keep recent closures only.
                due_datetime__lte=now,  # Exclude future closures.
            )
            .order_by("due_datetime")
        )

        for assignment in assignments:  # Notify lecturers about closed assignments.
            submission_count = (  # Count distinct student submissions.
                assignment.submissions
                .values("student_id")
                .distinct()
                .count()
            )

            created_count += create_notifications_for_users(
                self._lecturer_users_for_offering(assignment.offering),  # Target offering lecturers.
                offering=assignment.offering,  # Link the relevant offering.
                title=f"Assignment closed: {assignment.title} ({submission_count} submissions)",  # Build the summary title.
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],  # Link to the assignment detail page.
                ),
                notification_type=Notification.Type.ASSIGNMENT_CLOSED_SUMMARY,  # Mark the notification type.
                event_key=f"assignment-closed-summary:{assignment.id}",  # Prevent duplicate notifications.
            )

        return created_count  # Return the created total.

    # ==========================
    # Quiz Closure Notifications
    # ==========================
    def _generate_quiz_closed_notifications(self, window_start, now):
        """Create quiz closure notifications and summaries."""

        created_count = 0  # Track created notifications.

        quizzes = (  # Fetch quizzes closed within the window.
            Quiz.objects.select_related("offering__module")
            .filter(
                is_published=True,  # Only include published quizzes.
                close_datetime__gt=window_start,  # Keep recent closures only.
                close_datetime__lte=now,  # Exclude future closures.
            )
            .order_by("close_datetime")
        )

        for quiz in quizzes:  # Notify students and lecturers about closure.
            student_submission_count = (  # Count submitted quiz attempts.
                quiz.attempts
                .filter(submitted_at__isnull=False)
                .values("student_id")
                .distinct()
                .count()
            )

            created_count += create_notifications_for_users(
                self._student_users_for_offering(quiz.offering),  # Target enrolled students.
                offering=quiz.offering,  # Link the relevant offering.
                title=f"Quiz closed: {quiz.title}",  # Build the student title.
                redirect_url=reverse(
                    "accounts:offering_quiz_detail",
                    args=[quiz.offering.id, quiz.id],  # Link to the quiz detail page.
                ),
                notification_type=Notification.Type.QUIZ_CLOSED,  # Mark the notification type.
                event_key=f"quiz-closed:{quiz.id}",  # Prevent duplicate notifications.
            )

            created_count += create_notifications_for_users(
                self._lecturer_users_for_offering(quiz.offering),  # Target offering lecturers.
                offering=quiz.offering,  # Link the relevant offering.
                title=f"Quiz closed: {quiz.title} ({student_submission_count} submissions)",  # Build the lecturer title.
                redirect_url=reverse(
                    "accounts:offering_quiz_detail",
                    args=[quiz.offering.id, quiz.id],  # Link to the quiz detail page.
                ),
                notification_type=Notification.Type.QUIZ_CLOSED_SUMMARY,  # Mark the notification type.
                event_key=f"quiz-closed-summary:{quiz.id}",  # Prevent duplicate notifications.
            )

        return created_count  # Return the created total.

    # ============================
    # Assignment Grading Reminders
    # ============================
    def _generate_assignment_grading_reminders(self, window_start, now):
        """Create weekly reminders for ungraded assignments."""

        created_count = 0  # Track created notifications.
        weekly_seconds = 7 * 24 * 60 * 60  # Define one week in seconds.

        assignments = (  # Fetch assignments overdue by one week.
            Assignment.objects.select_related("offering__module")
            .filter(due_datetime__lt=now - timedelta(days=7))
            .order_by("due_datetime")
        )

        for assignment in assignments:  # Evaluate reminder timing for each assignment.
            elapsed_now = max((now - assignment.due_datetime).total_seconds(), 0)  # Measure elapsed seconds now.
            elapsed_before = max((window_start - assignment.due_datetime).total_seconds(), 0)  # Measure elapsed seconds earlier.

            current_bucket = int(elapsed_now // weekly_seconds)  # Calculate the current week bucket.
            previous_bucket = int(elapsed_before // weekly_seconds)  # Calculate the previous week bucket.

            if current_bucket < 1 or current_bucket == previous_bucket:  # Skip unchanged weekly buckets.
                continue

            pending_count = (  # Count distinct ungraded submissions.
                assignment.submissions
                .filter(grade__isnull=True)
                .values("student_id")
                .distinct()
                .count()
            )

            if pending_count <= 0:  # Skip fully graded assignments.
                continue

            created_count += create_notifications_for_users(
                self._lecturer_users_for_offering(assignment.offering),  # Target offering lecturers.
                offering=assignment.offering,  # Link the relevant offering.
                title=f"Grading reminder: {assignment.title} ({pending_count} students left to grade)",  # Build the reminder title.
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],  # Link to the assignment detail page.
                ),
                notification_type=Notification.Type.ASSIGNMENT_GRADING_REMINDER,  # Mark the notification type.
                event_key=f"assignment-grading-reminder:{assignment.id}:week-{current_bucket}",  # Prevent duplicate weekly reminders.
            )

        return created_count  # Return the created total.
