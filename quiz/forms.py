from django import forms
from .models import Category, Quiz, Question, Option


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
