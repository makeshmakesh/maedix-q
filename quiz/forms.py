from django import forms
from .models import Category, Quiz, Question, Option, Topic, TopicCard


class CategoryForm(forms.ModelForm):
    """Form for creating/editing quiz categories"""

    class Meta:
        model = Category
        fields = ['name', 'description', 'icon', 'color', 'parent', 'order', 'is_active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'icon': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., code, cpu, database'}),
            'color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.NumberInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['parent'].queryset = Category.objects.filter(parent__isnull=True)
        self.fields['parent'].required = False
        self.fields['description'].required = False


class QuizForm(forms.ModelForm):
    """Form for creating/editing quizzes"""

    class Meta:
        model = Quiz
        fields = [
            'title', 'description', 'category', 'difficulty',
            'time_limit', 'pass_percentage', 'xp_reward',
            'is_published', 'is_featured'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            'time_limit': forms.NumberInput(attrs={'class': 'form-control', 'min': 60, 'step': 60}),
            'pass_percentage': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'xp_reward': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'is_published': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(is_active=True)


class QuestionForm(forms.ModelForm):
    """Form for creating/editing questions"""

    class Meta:
        model = Question
        fields = ['text', 'question_type', 'code_snippet', 'explanation', 'order', 'points']
        widgets = {
            'text': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'question_type': forms.Select(attrs={'class': 'form-select'}),
            'code_snippet': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Optional code snippet'}),
            'explanation': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Explanation shown after answering'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'points': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code_snippet'].required = False
        self.fields['explanation'].required = False


class OptionForm(forms.ModelForm):
    """Form for creating/editing answer options"""

    class Meta:
        model = Option
        fields = ['text', 'is_correct', 'order']
        widgets = {
            'text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Option text...'}),
            'is_correct': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make text not required at form level - we'll validate in the view
        self.fields['text'].required = False


class BaseOptionFormSet(forms.BaseInlineFormSet):
    """Custom formset that allows empty options and validates minimum"""

    def clean(self):
        super().clean()
        # Count non-empty, non-deleted forms
        filled_forms = 0
        has_correct = False

        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                text = form.cleaned_data.get('text', '').strip()
                if text:
                    filled_forms += 1
                    if form.cleaned_data.get('is_correct', False):
                        has_correct = True

        if filled_forms < 2:
            raise forms.ValidationError('Please provide at least 2 options.')

        if not has_correct:
            raise forms.ValidationError('At least one option must be marked as correct.')


# Formset for managing multiple options
OptionFormSet = forms.inlineformset_factory(
    Question,
    Option,
    form=OptionForm,
    formset=BaseOptionFormSet,
    extra=4,
    min_num=0,
    validate_min=False,
    can_delete=True
)


class TopicForm(forms.ModelForm):
    """Form for creating/editing topics"""

    class Meta:
        model = Topic
        fields = [
            'title', 'description', 'category', 'thumbnail_url',
            'linked_quiz', 'mini_quiz', 'status', 'order',
            'is_featured', 'estimated_time'
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'maxlength': 500,
                'placeholder': 'Brief description of the topic (max 500 characters)'
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'thumbnail_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'S3 URL for thumbnail image'
            }),
            'linked_quiz': forms.Select(attrs={'class': 'form-select'}),
            'mini_quiz': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'estimated_time': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 30,
                'placeholder': 'Minutes'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(is_active=True)
        self.fields['linked_quiz'].queryset = Quiz.objects.filter(
            is_published=True, is_mini_quiz=False
        )
        self.fields['mini_quiz'].queryset = Quiz.objects.filter(is_mini_quiz=True)
        self.fields['linked_quiz'].required = False
        self.fields['mini_quiz'].required = False
        self.fields['thumbnail_url'].required = False
        self.fields['description'].required = False


class UserTopicForm(forms.ModelForm):
    """Simplified form for users to create/edit topics"""

    class Meta:
        model = Topic
        fields = ['title', 'description', 'category', 'thumbnail_url', 'estimated_time']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Understanding Python Decorators'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'maxlength': 500,
                'placeholder': 'Brief description of what this topic covers...'
            }),
            'category': forms.Select(attrs={'class': 'form-select'}),
            'thumbnail_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com/image.jpg'
            }),
            'estimated_time': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 30,
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].queryset = Category.objects.filter(is_active=True)
        self.fields['thumbnail_url'].required = False
        self.fields['description'].required = False
        self.fields['estimated_time'].initial = 2


class TopicCardForm(forms.ModelForm):
    """Form for creating/editing topic cards"""

    class Meta:
        model = TopicCard
        fields = [
            'card_type', 'title', 'content', 'code_snippet',
            'code_language', 'image_url', 'image_caption', 'order'
        ]
        widgets = {
            'card_type': forms.Select(attrs={'class': 'form-select'}),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Optional card title'
            }),
            'content': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'maxlength': 600,
                'placeholder': 'Main content (~100 words recommended)'
            }),
            'code_snippet': forms.Textarea(attrs={
                'class': 'form-control font-monospace',
                'rows': 6,
                'placeholder': 'Code snippet (for Text + Code cards)'
            }),
            'code_language': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., python, javascript, go'
            }),
            'image_url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'S3 URL for image (for Text + Image cards)'
            }),
            'image_caption': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Image caption'
            }),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].required = False
        self.fields['code_snippet'].required = False
        self.fields['code_language'].required = False
        self.fields['image_url'].required = False
        self.fields['image_caption'].required = False

    def clean_content(self):
        content = self.cleaned_data.get('content', '')
        word_count = len(content.split())
        if word_count > 150:
            raise forms.ValidationError(
                f'Content is {word_count} words. Please keep it under 150 words for best readability.'
            )
        return content

    def clean(self):
        cleaned_data = super().clean()
        card_type = cleaned_data.get('card_type')
        code_snippet = cleaned_data.get('code_snippet')
        image_url = cleaned_data.get('image_url')

        if card_type == 'text_code' and not code_snippet:
            self.add_error('code_snippet', 'Code snippet is required for Text + Code cards.')

        if card_type == 'text_image' and not image_url:
            self.add_error('image_url', 'Image URL is required for Text + Image cards.')

        return cleaned_data


class BaseTopicCardFormSet(forms.BaseInlineFormSet):
    """Custom formset for topic cards"""

    def clean(self):
        super().clean()
        filled_forms = 0

        for form in self.forms:
            if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                content = form.cleaned_data.get('content', '').strip()
                if content:
                    filled_forms += 1

        if filled_forms < 1:
            raise forms.ValidationError('Please provide at least 1 card.')


# Formset for managing multiple topic cards
TopicCardFormSet = forms.inlineformset_factory(
    Topic,
    TopicCard,
    form=TopicCardForm,
    formset=BaseTopicCardFormSet,
    extra=3,
    min_num=0,
    validate_min=False,
    can_delete=True
)
