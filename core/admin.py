from django import forms
from django.contrib import admin, messages

from .models import Configuration, Plan, Subscription, Transaction, ContactMessage, Banner, LinkRedirectEvent


@admin.register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
    pass


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    pass


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    pass


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    pass


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    pass


class BannerAdminForm(forms.ModelForm):
    image = forms.ImageField(required=False, help_text="Upload an image (JPEG, PNG, GIF, WebP). Uploaded to S3.")

    class Meta:
        model = Banner
        fields = '__all__'


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    form = BannerAdminForm
    list_display = ('title', 'banner_type', 'display_mode', 'requires_auth', 'is_active', 'order', 'updated_at')
    list_filter = ('banner_type', 'display_mode', 'requires_auth', 'is_active')
    list_editable = ('is_active', 'order')

    def save_model(self, request, obj, form, change):
        image = form.cleaned_data.get('image')
        if image:
            from .s3_utils import upload_image_to_s3
            url, s3_key, error = upload_image_to_s3(image, folder='banners')
            if error:
                messages.error(request, f"Image upload failed: {error}")
            else:
                obj.image_url = url
                obj.image_s3_key = s3_key
        super().save_model(request, obj, form, change)


@admin.register(LinkRedirectEvent)
class LinkRedirectEventAdmin(admin.ModelAdmin):
    list_display = ['target_domain', 'clicked', 'duration_display', 'ip_hash_short', 'created_at']
    list_filter = ['clicked', 'target_domain', 'created_at']
    search_fields = ['target_url', 'target_domain']
    readonly_fields = ['target_url', 'target_domain', 'ip_hash', 'referrer', 'user_agent', 'duration_ms', 'clicked', 'created_at']
    date_hierarchy = 'created_at'

    @admin.display(description='Duration')
    def duration_display(self, obj):
        if obj.duration_ms is None:
            return '—'
        seconds = obj.duration_ms / 1000
        return f'{seconds:.1f}s'

    @admin.display(description='IP')
    def ip_hash_short(self, obj):
        return obj.ip_hash[:12] + '...'
