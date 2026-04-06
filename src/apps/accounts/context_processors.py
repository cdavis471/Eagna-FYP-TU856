from .models import Notification

def notifications_context(request):
    user = getattr(request, "user", None)

    if not user or not user.is_authenticated:
        return {}

    notifications = list(
        Notification.objects.filter(recipient=user)
        .select_related("offering__placement__module")
        .order_by("-created_at", "-id")
    )

    unread_count = sum(1 for item in notifications if not item.is_read)

    return {
        "header_notifications_initial": notifications[:5],
        "header_notifications_extra": notifications[5:],
        "header_notification_unread_count": unread_count,
        "header_notification_unread_display": "5+" if unread_count > 5 else str(unread_count),
        "header_notification_has_more": len(notifications) > 5,
    }