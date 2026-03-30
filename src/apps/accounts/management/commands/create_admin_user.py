from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import User

class Command(BaseCommand):
    help = "Create or update a custom Eagna admin user."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("password")
        parser.add_argument("--first-name", default="Admin")
        parser.add_argument("--last-name", default="User")

    def handle(self, *args, **options):
        email = (options["email"] or "").strip().lower()
        password = options["password"]
        first_name = (options["first_name"] or "").strip()
        last_name = (options["last_name"] or "").strip()

        if not email or "@" not in email:
            raise CommandError("Please provide a valid email address.")

        user = User.objects.filter(username__iexact=email).first()
        created = user is None

        if created:
            user = User(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=User.Role.ADMIN,
                is_active=True,
            )
        else:
            user.username = email
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.role = User.Role.ADMIN
            user.is_active = True

        user.set_password(password)
        user.is_staff = False
        user.is_superuser = False
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Created admin user: {email}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Updated existing user as admin: {email}"))