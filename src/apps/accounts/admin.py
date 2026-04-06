from django.contrib import admin

from .models import AcademicYear, Course, LecturerProfile, Module, ModuleOffering, ModuleOfferingEnrollmentLecturer, ModuleOfferingEnrollmentStudent, ModulePlacement, StudentProfile,User

admin.site.register(User)
admin.site.register(StudentProfile)
admin.site.register(LecturerProfile)
admin.site.register(Course)
admin.site.register(AcademicYear)
admin.site.register(Module)
admin.site.register(ModulePlacement)
admin.site.register(ModuleOffering)
admin.site.register(ModuleOfferingEnrollmentStudent)
admin.site.register(ModuleOfferingEnrollmentLecturer)