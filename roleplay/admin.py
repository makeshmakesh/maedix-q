from django.contrib import admin
from .models import RolePlayBot, RoleplaySession, CreditTransaction


@admin.register(RolePlayBot)
class RolePlayBotAdmin(admin.ModelAdmin):
    pass


@admin.register(RoleplaySession)
class RoleplaySessionAdmin(admin.ModelAdmin):
    pass


@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    pass
