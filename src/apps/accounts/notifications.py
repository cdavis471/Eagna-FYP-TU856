from django.contrib.auth import get_user_model

from .models import Notification

User = get_user_model()

def create_notification(
    *,
    recipient,
    module=None,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    defaults = {
        "module": module,
        "title": title,
        "redirect_url": redirect_url,
        "notification_type": notification_type,
    }

    if event_key:
        return Notification.objects.get_or_create(
            recipient=recipient,
            event_key=event_key,
            defaults=defaults,
        )

    return Notification.objects.create(
        recipient=recipient,
        event_key=None,
        **defaults,
    ), True


def create_notifications_for_users(
    recipients,
    *,
    module=None,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    if hasattr(recipients, "distinct"):
        recipients = recipients.distinct()

    created_count = 0

    for recipient in recipients:
        _, created = create_notification(
            recipient=recipient,
            module=module,
            title=title,
            redirect_url=redirect_url,
            notification_type=notification_type,
            event_key=event_key,
        )
        if created:
            created_count += 1

    return created_count


def notify_module_students(
    module,
    *,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    recipients = User.objects.filter(
        student_profile__modules=module
    ).distinct()

    return create_notifications_for_users(
        recipients,
        module=module,
        title=title,
        redirect_url=redirect_url,
        notification_type=notification_type,
        event_key=event_key,
    )


def notify_module_lecturers(
    module,
    *,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    recipients = User.objects.filter(
        lecturer_profile__modules=module
    ).distinct()

    return create_notifications_for_users(
        recipients,
        module=module,
        title=title,
        redirect_url=redirect_url,
        notification_type=notification_type,
        event_key=event_key,
    )