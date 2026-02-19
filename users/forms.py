import re
from django import forms
from django.contrib.auth import get_user_model
from .models import UserProfile, ProfileLink, generate_unique_username

User = get_user_model()

RESERVED_USERNAMES = {
    'admin', 'administrator', 'users', 'user', 'instagram', 'blog', 'static',
    'media', 'api', 'settings', 'login', 'signup', 'logout', 'profile',
    'dashboard', 'help', 'support', 'about', 'contact', 'terms', 'privacy',
    'pricing', 'home', 'root', 'www', 'mail', 'ftp', 'ssh', 'test',
    'maedix', 'system', 'moderator', 'mod', 'staff', 'null', 'undefined',
    'quiz', 'youtube', 'roleplay', 'games', 'core', 'sitemap', 'robots',
}


class SignupForm(forms.ModelForm):
    """User registration form"""
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm Password'
        })
    )

    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name']
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email Address'
            }),
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First Name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last Name'
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError('Passwords do not match')

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        user.username = generate_unique_username(user.email)
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    """User login form"""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email Address'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )


class UserForm(forms.ModelForm):
    """Form for editing user basic info"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'pattern': '[a-zA-Z0-9_]+',
            }),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip().lower()
        if len(username) < 3:
            raise forms.ValidationError('Username must be at least 3 characters.')
        if len(username) > 30:
            raise forms.ValidationError('Username must be 30 characters or fewer.')
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            raise forms.ValidationError('Username may only contain letters, numbers, and underscores.')
        if username in RESERVED_USERNAMES:
            raise forms.ValidationError('This username is reserved. Please choose another.')
        # Case-insensitive uniqueness check (exclude current user)
        if User.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('This username is already taken.')
        return username


class ProfileForm(forms.ModelForm):
    """Form for editing user profile"""
    class Meta:
        model = UserProfile
        fields = ['bio', 'location', 'website', 'github_username', 'linkedin_url', 'twitter_handle']
        widgets = {
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'github_username': forms.TextInput(attrs={'class': 'form-control'}),
            'linkedin_url': forms.URLInput(attrs={'class': 'form-control'}),
            'twitter_handle': forms.TextInput(attrs={'class': 'form-control'}),
        }


class OTPVerificationForm(forms.Form):
    """Form for OTP verification during signup"""
    otp = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg text-center',
            'placeholder': 'Enter 6-digit OTP',
            'maxlength': '6',
            'pattern': '[0-9]{6}',
            'inputmode': 'numeric',
            'autocomplete': 'one-time-code',
        })
    )

    def clean_otp(self):
        otp = self.cleaned_data.get('otp')
        if not otp.isdigit():
            raise forms.ValidationError('OTP must contain only digits')
        return otp


class ProfileLinkForm(forms.ModelForm):
    """Form for adding/editing a profile link."""
    class Meta:
        model = ProfileLink
        fields = ['title', 'url', 'icon']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. My Website',
            }),
            'url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com',
            }),
            'icon': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g. bi-globe (optional)',
            }),
        }
        help_texts = {
            'icon': 'Bootstrap icon class. Examples: bi-globe, bi-github, bi-youtube, bi-instagram, bi-linkedin, bi-twitter-x',
        }
