from django import forms
from django.contrib import admin
from django.utils.html import format_html
from django_ckeditor_5.widgets import CKEditor5Widget
from .models import Category, BlogPost


class BlogPostAdminForm(forms.ModelForm):
    """Custom form to use CKEditor for content field"""
    content = forms.CharField(widget=CKEditor5Widget(config_name='default'))

    class Meta:
        model = BlogPost
        fields = '__all__'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug', 'post_count', 'order']
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ['name']
    ordering = ['order', 'name']

    def post_count(self, obj):
        return obj.posts.filter(is_published=True).count()
    post_count.short_description = 'Published Posts'


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    form = BlogPostAdminForm
    list_display = ['title', 'category', 'is_published', 'published_at', 'preview_link']
    list_filter = ['is_published', 'category', 'created_at']
    search_fields = ['title', 'content', 'excerpt']
    prepopulated_fields = {'slug': ('title',)}
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    fieldsets = (
        (None, {
            'fields': ('title', 'slug', 'category')
        }),
        ('Content', {
            'fields': ('excerpt', 'content'),
            'description': 'Use the visual editor to write your post. Tables, images, code blocks all supported.'
        }),
        ('Featured Image', {
            'fields': ('featured_image', 'featured_image_alt'),
            'classes': ('collapse',)
        }),
        ('SEO', {
            'fields': ('meta_description', 'meta_keywords'),
            'classes': ('collapse',)
        }),
        ('Publishing', {
            'fields': ('is_published', 'published_at')
        }),
    )

    def preview_link(self, obj):
        if obj.slug:
            return format_html(
                '<a href="{}" target="_blank">Preview</a>',
                obj.get_absolute_url()
            )
        return '-'
    preview_link.short_description = 'Preview'
