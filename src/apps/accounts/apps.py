# =======
# Imports
# =======
from django.apps import AppConfig  # Import the Django app config base

# ==========
# App Config
# ==========
class AccountsConfig(AppConfig):  # Define the accounts app configuration
    """Configure the accounts application."""
    default_auto_field = 'django.db.models.BigAutoField'  # Use BigAutoField for primary keys
    name = 'apps.accounts'  # Register the app module path
