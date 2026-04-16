# =======
# Imports
# =======
from django.contrib.auth import get_user_model  # Import user model getter
from .models import Notification  # Import notification model
User = get_user_model()  # Get the user model

# ====================
# Notification Creation
# ====================
def create_notification(  # Define function to create a single notification
    *,
    recipient,
    offering=None,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    """Create a single notification for a user."""
    defaults = {  # Set default values for notification
        "offering": offering,  # Offering associated with notification
        "title": title,  # Notification title
        "redirect_url": redirect_url,  # URL to redirect to
        "notification_type": notification_type,  # Type of notification
    }

    if event_key:  # If event key provided, get or create notification
        return Notification.objects.get_or_create(  # Get or create notification with event key
            recipient=recipient,  # Recipient of notification
            event_key=event_key,  # Unique event key
            defaults=defaults,  # Default values
        )

    return Notification.objects.create(  # Create new notification
        recipient=recipient,  # Recipient of notification
        event_key=None,  # No event key
        **defaults,  # Unpack defaults
    ), True  # Return created notification and True


def create_notifications_for_users(  # Define function to create notifications for multiple users
    recipients,
    *,
    offering=None,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    """Create notifications for multiple users."""
    if hasattr(recipients, "distinct"):  # Ensure distinct recipients if queryset
        recipients = recipients.distinct()  # Remove duplicates

    created_count = 0  # Initialize count of created notifications

    for recipient in recipients:  # Loop through each recipient
        _, created = create_notification(  # Create notification and check if created
            recipient=recipient,  # Current recipient
            offering=offering,  # Offering
            title=title,  # Title
            redirect_url=redirect_url,  # Redirect URL
            notification_type=notification_type,  # Notification type
            event_key=event_key,  # Event key
        )
        if created:  # If notification was created
            created_count += 1  # Increment count

    return created_count  # Return number of created notifications


def notify_offering_students(  # Define function to notify students in an offering
    offering,
    *,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    """Notify all students enrolled in an offering."""
    recipients = User.objects.filter(  # Get students enrolled in the offering
        student_profile__offering_enrolments__offering=offering  # Filter by offering
    ).distinct()  # Ensure distinct users

    return create_notifications_for_users(  # Create notifications for recipients
        recipients,  # List of recipients
        offering=offering,  # Offering
        title=title,  # Title
        redirect_url=redirect_url,  # Redirect URL
        notification_type=notification_type,  # Notification type
        event_key=event_key,  # Event key
    )


def notify_offering_lecturers(  # Define function to notify lecturers in an offering
    offering,
    *,
    title,
    redirect_url="",
    notification_type=Notification.Type.GENERAL,
    event_key=None,
):
    """Notify all lecturers enrolled in an offering."""
    recipients = User.objects.filter(  # Get lecturers enrolled in the offering
        lecturer_profile__offering_enrolments__offering=offering  # Filter by offering
    ).distinct()  # Ensure distinct users

    return create_notifications_for_users(  # Create notifications for recipients
        recipients,  # List of recipients
        offering=offering,  # Offering
        title=title,  # Title
        redirect_url=redirect_url,  # Redirect URL
        notification_type=notification_type,  # Notification type
        event_key=event_key,  # Event key
    )