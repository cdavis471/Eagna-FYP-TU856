# =======
# Imports
# =======
from .models import Notification  # Import the notification model

# ====================
# Notification Context
# ====================
def notifications_context(request):
    """Build notification data for the header."""
    user = getattr(request, "user", None)  # Safely get the current user

    if not user or not user.is_authenticated:  # Return empty context for guests
        return {}

    notifications = list(  # Evaluate the notification queryset
        Notification.objects.filter(recipient=user)  # Filter notifications by recipient
        .select_related("offering__module")  # Join related offering and module
        .order_by("-created_at", "-id")  # Show newest notifications first
    )

    unread_count = sum(1 for item in notifications if not item.is_read)  # Count unread notifications

    return {
        "header_notifications_initial": notifications[:5],  # First five notifications
        "header_notifications_extra": notifications[5:],  # Remaining notifications
        "header_notification_unread_count": unread_count,  # Total unread count
        "header_notification_unread_display": "5+" if unread_count > 5 else str(unread_count),  # Cap the displayed count
        "header_notification_has_more": len(notifications) > 5,  # Flag extra notifications
    }
