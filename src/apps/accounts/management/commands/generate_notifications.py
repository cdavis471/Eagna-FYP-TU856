from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Assignment, Notification, Quiz
from apps.accounts.notifications import create_notifications_for_users

User = get_user_model()


class Command(BaseCommand):
    help = "Generate scheduled notifications for due dates, quiz open/close events, and grading reminders."

    def handle(self, *args, **options):
        now = timezone.now()
        window_start = now - timedelta(minutes=65)

        total_created = 0
        total_created += self._generate_assignment_due_notifications(now)
        total_created += self._generate_quiz_opened_notifications(window_start, now)
        total_created += self._generate_assignment_closed_notifications(window_start, now)
        total_created += self._generate_quiz_closed_notifications(window_start, now)
        total_created += self._generate_assignment_grading_reminders(window_start, now)

        self.stdout.write(self.style.SUCCESS(f"Generated {total_created} notifications."))

    def _student_users_for_offering(self, offering):
        return User.objects.filter(
            student_profile__offering_enrolments__offering=offering
        ).distinct()

    def _lecturer_users_for_offering(self, offering):
        return User.objects.filter(
            lecturer_profile__offering_enrolments__offering=offering
        ).distinct()

    def _students_without_submission(self, assignment):
        return (
            self._student_users_for_offering(assignment.offering)
            .exclude(student_profile__submissions__assignment=assignment)
            .distinct()
        )

    def _generate_assignment_due_notifications(self, now):
        created_count = 0

        three_day_lower = now + timedelta(hours=71)
        three_day_upper = now + timedelta(hours=72)

        one_day_lower = now + timedelta(hours=23)
        one_day_upper = now + timedelta(hours=24)

        assignments_three_days = (
            Assignment.objects.select_related("offering__module")
            .filter(due_datetime__gt=three_day_lower, due_datetime__lte=three_day_upper)
            .order_by("due_datetime")
        )

        for assignment in assignments_three_days:
            created_count += create_notifications_for_users(
                self._students_without_submission(assignment),
                offering=assignment.offering,
                title=f"Assignment due in 3 days: {assignment.title}",
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],
                ),
                notification_type=Notification.Type.ASSIGNMENT_DUE_3D,
                event_key=f"assignment-due-3d:{assignment.id}",
            )

        assignments_one_day = (
            Assignment.objects.select_related("offering__module")
            .filter(due_datetime__gt=one_day_lower, due_datetime__lte=one_day_upper)
            .order_by("due_datetime")
        )

        for assignment in assignments_one_day:
            created_count += create_notifications_for_users(
                self._students_without_submission(assignment),
                offering=assignment.offering,
                title=f"Assignment due in 24 hours: {assignment.title}",
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],
                ),
                notification_type=Notification.Type.ASSIGNMENT_DUE_24H,
                event_key=f"assignment-due-24h:{assignment.id}",
            )

        return created_count

    def _generate_quiz_opened_notifications(self, window_start, now):
        created_count = 0

        quizzes = (
            Quiz.objects.select_related("offering__module")
            .filter(
                is_published=True,
                open_datetime__gt=window_start,
                open_datetime__lte=now,
            )
            .order_by("open_datetime")
        )

        for quiz in quizzes:
            created_count += create_notifications_for_users(
                self._student_users_for_offering(quiz.offering),
                offering=quiz.offering,
                title=f"Quiz opened: {quiz.title}",
                redirect_url=reverse(
                    "accounts:offering_quiz_detail",
                    args=[quiz.offering.id, quiz.id],
                ),
                notification_type=Notification.Type.QUIZ_OPENED,
                event_key=f"quiz-opened:{quiz.id}",
            )

        return created_count

    def _generate_assignment_closed_notifications(self, window_start, now):
        created_count = 0

        assignments = (
            Assignment.objects.select_related("offering__module")
            .filter(
                due_datetime__gt=window_start,
                due_datetime__lte=now,
            )
            .order_by("due_datetime")
        )

        for assignment in assignments:
            submission_count = (
                assignment.submissions
                .values("student_id")
                .distinct()
                .count()
            )

            created_count += create_notifications_for_users(
                self._lecturer_users_for_offering(assignment.offering),
                offering=assignment.offering,
                title=f"Assignment closed: {assignment.title} ({submission_count} submissions)",
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],
                ),
                notification_type=Notification.Type.ASSIGNMENT_CLOSED_SUMMARY,
                event_key=f"assignment-closed-summary:{assignment.id}",
            )

        return created_count

    def _generate_quiz_closed_notifications(self, window_start, now):
        created_count = 0

        quizzes = (
            Quiz.objects.select_related("offering__module")
            .filter(
                is_published=True,
                close_datetime__gt=window_start,
                close_datetime__lte=now,
            )
            .order_by("close_datetime")
        )

        for quiz in quizzes:
            student_submission_count = (
                quiz.attempts
                .filter(submitted_at__isnull=False)
                .values("student_id")
                .distinct()
                .count()
            )

            created_count += create_notifications_for_users(
                self._student_users_for_offering(quiz.offering),
                offering=quiz.offering,
                title=f"Quiz closed: {quiz.title}",
                redirect_url=reverse(
                    "accounts:offering_quiz_detail",
                    args=[quiz.offering.id, quiz.id],
                ),
                notification_type=Notification.Type.QUIZ_CLOSED,
                event_key=f"quiz-closed:{quiz.id}",
            )

            created_count += create_notifications_for_users(
                self._lecturer_users_for_offering(quiz.offering),
                offering=quiz.offering,
                title=f"Quiz closed: {quiz.title} ({student_submission_count} submissions)",
                redirect_url=reverse(
                    "accounts:offering_quiz_detail",
                    args=[quiz.offering.id, quiz.id],
                ),
                notification_type=Notification.Type.QUIZ_CLOSED_SUMMARY,
                event_key=f"quiz-closed-summary:{quiz.id}",
            )

        return created_count

    def _generate_assignment_grading_reminders(self, window_start, now):
        created_count = 0
        weekly_seconds = 7 * 24 * 60 * 60

        assignments = (
            Assignment.objects.select_related("offering__module")
            .filter(due_datetime__lt=now - timedelta(days=7))
            .order_by("due_datetime")
        )

        for assignment in assignments:
            elapsed_now = max((now - assignment.due_datetime).total_seconds(), 0)
            elapsed_before = max((window_start - assignment.due_datetime).total_seconds(), 0)

            current_bucket = int(elapsed_now // weekly_seconds)
            previous_bucket = int(elapsed_before // weekly_seconds)

            if current_bucket < 1 or current_bucket == previous_bucket:
                continue

            pending_count = (
                assignment.submissions
                .filter(grade__isnull=True)
                .values("student_id")
                .distinct()
                .count()
            )

            if pending_count <= 0:
                continue

            created_count += create_notifications_for_users(
                self._lecturer_users_for_offering(assignment.offering),
                offering=assignment.offering,
                title=f"Grading reminder: {assignment.title} ({pending_count} students left to grade)",
                redirect_url=reverse(
                    "accounts:offering_assignment_detail",
                    args=[assignment.offering.id, assignment.id],
                ),
                notification_type=Notification.Type.ASSIGNMENT_GRADING_REMINDER,
                event_key=f"assignment-grading-reminder:{assignment.id}:week-{current_bucket}",
            )

        return created_count