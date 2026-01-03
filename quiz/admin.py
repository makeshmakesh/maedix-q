from django.contrib import admin
from .models import Category, Quiz, Question, Option, QuizAttempt, QuestionAnswer, Leaderboard


class OptionInline(admin.TabularInline):
    model = Option
    extra = 4


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 1
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'parent', 'quiz_count', 'order', 'is_active']
    list_filter = ['is_active', 'parent']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['order', 'name']


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'difficulty', 'question_count', 'time_limit', 'is_published', 'is_featured']
    list_filter = ['category', 'difficulty', 'is_published', 'is_featured']
    search_fields = ['title', 'description']
    prepopulated_fields = {'slug': ('title',)}
    inlines = [QuestionInline]
    raw_id_fields = ['created_by']


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ['quiz', 'text_preview', 'question_type', 'order', 'points']
    list_filter = ['quiz', 'question_type']
    search_fields = ['text', 'quiz__title']
    inlines = [OptionInline]
    ordering = ['quiz', 'order']

    def text_preview(self, obj):
        return obj.text[:50] + '...' if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Question'


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
    list_display = ['question', 'text_preview', 'is_correct', 'order']
    list_filter = ['is_correct', 'question__quiz']
    search_fields = ['text', 'question__text']

    def text_preview(self, obj):
        return obj.text[:50] + '...' if len(obj.text) > 50 else obj.text
    text_preview.short_description = 'Option'


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ['user', 'quiz', 'status', 'score', 'percentage', 'passed', 'xp_earned', 'started_at']
    list_filter = ['status', 'passed', 'quiz']
    search_fields = ['user__email', 'quiz__title']
    readonly_fields = ['started_at', 'completed_at']


@admin.register(QuestionAnswer)
class QuestionAnswerAdmin(admin.ModelAdmin):
    list_display = ['attempt', 'question', 'is_correct', 'points_earned', 'answered_at']
    list_filter = ['is_correct', 'attempt__quiz']
    search_fields = ['attempt__user__email']


@admin.register(Leaderboard)
class LeaderboardAdmin(admin.ModelAdmin):
    list_display = ['user', 'category', 'period', 'score', 'quizzes_completed', 'rank']
    list_filter = ['period', 'category']
    search_fields = ['user__email']
    ordering = ['period', 'rank']
