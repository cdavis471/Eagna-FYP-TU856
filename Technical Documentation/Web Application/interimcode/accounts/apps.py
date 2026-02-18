from django.apps import AppConfig  # Imports Django's base application configuration class, used to configure this app


class AccountsConfig(AppConfig):  # Defines the configuration class for the 'accounts' application, subclassing AppConfig
    default_auto_field = 'django.db.models.BigAutoField'  # Sets the default primary key field type for models in this app to BigAutoField
    name = 'accounts'  # Declares the full Python path of this application; used by Django to register and reference the app
