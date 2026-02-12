from django.contrib import admin
from .models import Category, WordBank, GameSession, PlayerStats


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    pass


@admin.register(WordBank)
class WordBankAdmin(admin.ModelAdmin):
    pass


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    pass


@admin.register(PlayerStats)
class PlayerStatsAdmin(admin.ModelAdmin):
    pass
