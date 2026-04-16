# =======
# Imports
# =======
from django.contrib import admin  # Import Django admin utilities
from .models import AcademicYear, Course, LecturerProfile, Module, ModuleOffering, ModuleOfferingEnrollmentLecturer, ModuleOfferingEnrollmentStudent, ModulePlacement, StudentProfile,User  # Import account-related models

# ==================
# Model Registration
# ==================
admin.site.register(User)  # Register the custom user model
admin.site.register(StudentProfile)  # Register the student profile model
admin.site.register(LecturerProfile)  # Register the lecturer profile model
admin.site.register(Course)  # Register the course model
admin.site.register(AcademicYear)  # Register the academic year model
admin.site.register(Module)  # Register the module model
admin.site.register(ModulePlacement)  # Register the module placement model
admin.site.register(ModuleOffering)  # Register the module offering model
admin.site.register(ModuleOfferingEnrollmentStudent)  # Register student offering enrolments
admin.site.register(ModuleOfferingEnrollmentLecturer)  # Register lecturer offering enrolments