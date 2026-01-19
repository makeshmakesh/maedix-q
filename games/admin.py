from django.contrib import admin
from .models import Category, WordBank, GameSession, PlayerStats, Leaderboard


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'icon', 'word_count', 'is_active', 'order']
    list_filter = ['is_active']
    list_editable = ['is_active', 'order']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['order', 'name']

    def word_count(self, obj):
        return obj.words.filter(is_active=True).count()
    word_count.short_description = 'Active Words'


@admin.register(WordBank)
class WordBankAdmin(admin.ModelAdmin):
    list_display = ['word', 'category', 'difficulty', 'hint', 'is_active', 'times_played', 'times_solved', 'solve_rate']
    list_filter = ['category', 'difficulty', 'is_active']
    search_fields = ['word', 'hint']
    list_editable = ['is_active', 'difficulty']
    ordering = ['word']
    autocomplete_fields = ['category']

    fieldsets = (
        (None, {
            'fields': ('word', 'category', 'difficulty')
        }),
        ('Details', {
            'fields': ('hint', 'is_active')
        }),
        ('Statistics', {
            'fields': ('times_played', 'times_solved'),
            'classes': ('collapse',)
        }),
    )


@admin.register(GameSession)
class GameSessionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'word', 'category', 'attempts_used', 'is_won', 'is_completed', 'xp_earned', 'started_at']
    list_filter = ['is_won', 'is_completed', 'category', 'started_at']
    search_fields = ['user__email', 'word__word']
    readonly_fields = ['guesses', 'id']
    date_hierarchy = 'started_at'


@admin.register(PlayerStats)
class PlayerStatsAdmin(admin.ModelAdmin):
    list_display = ['user', 'total_games', 'total_wins', 'win_rate', 'total_xp', 'current_streak', 'longest_streak']
    search_fields = ['user__email']
    readonly_fields = ['guess_distribution', 'category_stats']


@admin.register(Leaderboard)
class LeaderboardAdmin(admin.ModelAdmin):
    list_display = ['rank', 'user', 'category', 'period', 'games_won', 'games_played', 'total_xp', 'win_rate']
    list_filter = ['category', 'period']
    search_fields = ['user__email']
    ordering = ['category', 'period', 'rank']
