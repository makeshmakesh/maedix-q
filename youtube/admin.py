from django.contrib import admin
from .models import YouTubeAccount


@admin.register(YouTubeAccount)
class YouTubeAccountAdmin(admin.ModelAdmin):
    pass
