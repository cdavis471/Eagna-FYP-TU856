# =======
# Imports
# =======
from django.core.management.base import BaseCommand, CommandError  # Import Django command helpers.
from apps.accounts.models import User  # Import the custom user model.

# ==================
# Admin User Command
# ==================
class Command(BaseCommand):
    """Create or update an admin user."""

    help = "Create or update a custom Eagna admin user."  # Describe the command purpose.

    def add_arguments(self, parser):
        """Register command line arguments."""

        parser.add_argument("email")  # Require the admin email.
        parser.add_argument("password")  # Require the admin password.
        parser.add_argument("--first-name", default="Admin")  # Accept an optional first name.
        parser.add_argument("--last-name", default="User")  # Accept an optional last name.

    def handle(self, *args, **options):
        """Create or update the admin account."""

        email = (options["email"] or "").strip().lower()  # Normalise the supplied email.
        password = options["password"]  # Read the supplied password.
        first_name = (options["first_name"] or "").strip()  # Clean the first name.
        last_name = (options["last_name"] or "").strip()  # Clean the last name.

        if not email or "@" not in email:  # Reject invalid email values.
            raise CommandError("Please provide a valid email address.")  # Stop on invalid input.

        user = User.objects.filter(username__iexact=email).first()  # Find an existing matching user.
        created = user is None  # Track whether a new user is needed.

        if created:  # Build a new admin user.
            user = User(
                username=email,  # Set the username from email.
                email=email,  # Store the same email value.
                first_name=first_name,  # Set the first name.
                last_name=last_name,  # Set the last name.
                role=User.Role.ADMIN,  # Mark the user as admin.
                is_active=True,  # Ensure the account is active.
            )
        else:  # Update the existing user.
            user.username = email  # Keep username aligned to email.
            user.email = email  # Keep email stored consistently.
            user.first_name = first_name  # Refresh the first name.
            user.last_name = last_name  # Refresh the last name.
            user.role = User.Role.ADMIN  # Enforce the admin role.
            user.is_active = True  # Reactivate the user account.

        user.set_password(password)  # Hash and save the password.
        user.is_staff = False  # Keep staff access disabled.
        user.is_superuser = False  # Keep superuser access disabled.
        user.save()  # Persist the user changes.

        if created:  # Confirm a new user was created.
            self.stdout.write(self.style.SUCCESS(f"Created admin user: {email}"))  # Print the success message.
        else:  # Confirm an existing user was updated.
            self.stdout.write(self.style.SUCCESS(f"Updated existing user as admin: {email}"))  # Print the success message.
