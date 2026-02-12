from django.contrib import admin
from .models import (
    Category, Quiz, Question, Option, QuizAttempt, QuestionAnswer,
    VideoTemplate, Topic, TopicCard, TopicProgress, TopicCarouselExport
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
