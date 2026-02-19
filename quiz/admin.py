from django.contrib import admin
from .models import (
    Category, Quiz, Question, Option, QuizAttempt, QuestionAnswer,
    VideoTemplate, Topic, TopicCard, TopicProgress, TopicCarouselExport,
    GeneratedVideo, Leaderboard, BulkVideoJob, VideoJob,
)


@admin.register(VideoTemplate)
class VideoTemplateAdmin(admin.ModelAdmin):
    pass


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    pass


@admin.register(Quiz)
class QuizAdmin(admin.ModelAdmin):
    pass


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    pass


@admin.register(Option)
class OptionAdmin(admin.ModelAdmin):
    pass


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    pass


@admin.register(QuestionAnswer)
class QuestionAnswerAdmin(admin.ModelAdmin):
    pass


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    pass


@admin.register(TopicCard)
class TopicCardAdmin(admin.ModelAdmin):
    pass


@admin.register(TopicProgress)
class TopicProgressAdmin(admin.ModelAdmin):
    pass


@admin.register(TopicCarouselExport)
class TopicCarouselExportAdmin(admin.ModelAdmin):
    pass


@admin.register(GeneratedVideo)
class GeneratedVideoAdmin(admin.ModelAdmin):
    list_display = ['user', 'quiz', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__email', 'user__username']


@admin.register(Leaderboard)
class LeaderboardAdmin(admin.ModelAdmin):
    list_display = ['user', 'period', 'score', 'updated_at']
    list_filter = ['period']
    search_fields = ['user__email', 'user__username']


@admin.register(BulkVideoJob)
class BulkVideoJobAdmin(admin.ModelAdmin):
    list_display = ['user', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['user__email', 'user__username']


@admin.register(VideoJob)
class VideoJobAdmin(admin.ModelAdmin):
    list_display = ['user', 'job_type', 'status', 'created_at']
    list_filter = ['job_type', 'status', 'created_at']
    search_fields = ['user__email', 'user__username']
