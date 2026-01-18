import os
import json
import uuid
import time
import logging
import tempfile
import threading
from django.core.cache import cache
from django.utils.text import slugify
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.db.models import Count, Avg
from .models import (
    Category, Quiz, Question, Option, QuizAttempt, QuestionAnswer,
    GeneratedVideo, VideoTemplate,
    Topic, TopicCard, TopicProgress, TopicCarouselExport, VideoJob
)
from .forms import CategoryForm, QuizForm, QuestionForm, OptionFormSet, TopicForm, TopicCardForm, TopicCardFormSet, UserTopicForm
from core.models import Configuration
from core.subscription_utils import check_feature_access, use_feature, get_or_create_free_subscription, get_user_subscription
from . import lambda_service


class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to ensure user is staff"""

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class QuizHomeView(View):
    """Quiz home page - discover quizzes"""
    template_name = 'quiz/home.html'

    def get(self, request):
        featured_quizzes = Quiz.objects.filter(is_published=True, is_featured=True)[:6]
        categories = Category.objects.filter(is_active=True, parent__isnull=True)[:8]
        recent_quizzes = Quiz.objects.filter(is_published=True).order_by('-created_at')[:6]

        return render(request, self.template_name, {
            'featured_quizzes': featured_quizzes,
            'categories': categories,
            'recent_quizzes': recent_quizzes,
        })


class CategoriesView(View):
    """List all quiz categories"""
    template_name = 'quiz/categories.html'

    def get(self, request):
        categories = Category.objects.filter(is_active=True, parent__isnull=True)
        return render(request, self.template_name, {'categories': categories})


class CategoryDetailView(View):
    """View quizzes in a specific category"""
    template_name = 'quiz/category-detail.html'

    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug, is_active=True)
        quizzes = Quiz.objects.filter(category=category, is_published=True)

        # Filter by difficulty
        difficulty = request.GET.get('difficulty')
        if difficulty:
            quizzes = quizzes.filter(difficulty=difficulty)

        # Include subcategory quizzes
        subcategories = category.subcategories.filter(is_active=True)
        for subcat in subcategories:
            quizzes = quizzes | Quiz.objects.filter(category=subcat, is_published=True)

        return render(request, self.template_name, {
            'category': category,
            'quizzes': quizzes.distinct(),
            'subcategories': subcategories,
        })


class QuizDetailView(View):
    """Quiz detail page before starting"""
    template_name = 'quiz/quiz-detail.html'

    def get(self, request, slug):
        # Allow published quizzes OR creator's own drafts
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        user_attempts = []

        if request.user.is_authenticated:
            user_attempts = QuizAttempt.objects.filter(
                user=request.user,
                quiz=quiz,
                status='completed'
            ).order_by('-completed_at')[:5]

        return render(request, self.template_name, {
            'quiz': quiz,
            'user_attempts': user_attempts,
        })


class QuizStartView(LoginRequiredMixin, View):
    """Start a new quiz attempt"""

    def get(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug, is_published=True)

        # Check for existing in-progress attempt
        existing_attempt = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz,
            status='in_progress'
        ).first()

        if existing_attempt:
            return redirect('quiz_question', slug=slug, q_num=1)

        # Ensure user has a subscription (create free if needed)
        get_or_create_free_subscription(request.user)

        # Check subscription and usage for quiz_attempt feature
        can_access, message, subscription = check_feature_access(request.user, 'quiz_attempt')
        if not can_access:
            messages.warning(request, message)
            return redirect('subscription')

        # Use the feature (increment usage)
        use_feature(request.user, 'quiz_attempt')

        # Create new attempt
        QuizAttempt.objects.create(
            user=request.user,
            quiz=quiz,
            total_points=sum(q.points for q in quiz.questions.all())
        )

        return redirect('quiz_question', slug=slug, q_num=1)


class QuizQuestionView(LoginRequiredMixin, View):
    """Display and handle quiz question"""
    template_name = 'quiz/quiz-question.html'

    def get(self, request, slug, q_num):
        quiz = get_object_or_404(Quiz, slug=slug, is_published=True)

        # Check for in_progress attempt
        attempt = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz,
            status='in_progress'
        ).first()

        # If no in_progress attempt, check for completed and redirect to result
        if not attempt:
            completed_attempt = QuizAttempt.objects.filter(
                user=request.user,
                quiz=quiz,
                status='completed'
            ).order_by('-completed_at').first()

            if completed_attempt:
                messages.info(request, 'This quiz has already been completed.')
                return redirect('quiz_result', attempt_id=completed_attempt.id)
            else:
                # No attempt at all - redirect to start
                return redirect('quiz_start', slug=slug)

        questions = quiz.questions.all()
        if q_num < 1 or q_num > questions.count():
            return redirect('quiz_detail', slug=slug)

        question = questions[q_num - 1]

        # Check if already answered
        existing_answer = QuestionAnswer.objects.filter(
            attempt=attempt,
            question=question
        ).first()

        return render(request, self.template_name, {
            'quiz': quiz,
            'question': question,
            'q_num': q_num,
            'total_questions': questions.count(),
            'attempt': attempt,
            'existing_answer': existing_answer,
        })

    def post(self, request, slug, q_num):
        quiz = get_object_or_404(Quiz, slug=slug, is_published=True)

        # Check for in_progress attempt
        attempt = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz,
            status='in_progress'
        ).first()

        # If no in_progress attempt, redirect appropriately
        if not attempt:
            completed_attempt = QuizAttempt.objects.filter(
                user=request.user,
                quiz=quiz,
                status='completed'
            ).order_by('-completed_at').first()

            if completed_attempt:
                messages.info(request, 'This quiz has already been completed.')
                return redirect('quiz_result', attempt_id=completed_attempt.id)
            else:
                return redirect('quiz_start', slug=slug)

        questions = quiz.questions.all()
        question = questions[q_num - 1]

        # Get selected options
        selected_option_ids = request.POST.getlist('options')

        # Create or update answer
        answer, created = QuestionAnswer.objects.get_or_create(
            attempt=attempt,
            question=question
        )

        # Clear previous selections and set new ones
        answer.selected_options.clear()
        selected_options = Option.objects.filter(id__in=selected_option_ids)
        answer.selected_options.add(*selected_options)

        # Check if correct
        correct_options = question.options.filter(is_correct=True)
        if set(selected_options) == set(correct_options):
            answer.is_correct = True
            answer.points_earned = question.points
        else:
            answer.is_correct = False
            answer.points_earned = 0

        answer.save()

        # Go to next question or submit
        if q_num < questions.count():
            return redirect('quiz_question', slug=slug, q_num=q_num + 1)
        else:
            return redirect('quiz_submit', slug=slug)


class QuizSubmitView(LoginRequiredMixin, View):
    """Submit and complete the quiz"""

    def get(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug, is_published=True)

        # Check for in_progress attempt
        attempt = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz,
            status='in_progress'
        ).first()

        # If no in_progress attempt, redirect to result or start
        if not attempt:
            completed_attempt = QuizAttempt.objects.filter(
                user=request.user,
                quiz=quiz,
                status='completed'
            ).order_by('-completed_at').first()

            if completed_attempt:
                messages.info(request, 'This quiz has already been completed.')
                return redirect('quiz_result', attempt_id=completed_attempt.id)
            else:
                return redirect('quiz_start', slug=slug)

        # Calculate score
        total_score = sum(a.points_earned for a in attempt.answers.all())
        total_points = attempt.total_points or sum(q.points for q in quiz.questions.all())

        percentage = (total_score / total_points * 100) if total_points > 0 else 0
        passed = percentage >= quiz.pass_percentage

        # Update attempt
        attempt.score = total_score
        attempt.percentage = round(percentage, 1)
        attempt.passed = passed
        attempt.status = 'completed'
        attempt.completed_at = timezone.now()
        attempt.time_taken = int((attempt.completed_at - attempt.started_at).total_seconds())

        # Calculate XP (First pass only system)
        # Check if user has already passed this quiz before
        already_passed = QuizAttempt.objects.filter(
            user=request.user,
            quiz=quiz,
            passed=True,
            status='completed'
        ).exclude(id=attempt.id).exists()

        if passed and not already_passed:
            # First time passing - full XP
            attempt.xp_earned = quiz.xp_reward
        elif passed and already_passed:
            # Already passed before - no XP (practice mode)
            attempt.xp_earned = 0
        else:
            # Failed attempt - small encouragement XP (only if never passed)
            if not already_passed:
                attempt.xp_earned = int(quiz.xp_reward * 0.1)  # 10% XP for failed attempts
            else:
                attempt.xp_earned = 0

        attempt.save()

        # Update user stats
        self._update_user_stats(request.user, attempt)

        return redirect('quiz_result', attempt_id=attempt.id)

    def _update_user_stats(self, user, attempt):
        """Update user statistics after quiz completion"""
        from users.models import UserStats

        stats, _ = UserStats.objects.get_or_create(user=user)
        stats.total_quizzes_taken += 1
        if attempt.passed:
            stats.total_quizzes_passed += 1
        stats.total_questions_answered += attempt.answers.count()
        stats.total_correct_answers += attempt.answers.filter(is_correct=True).count()
        stats.xp_points += attempt.xp_earned

        # Update streak
        today = timezone.now().date()
        if stats.last_quiz_date:
            days_diff = (today - stats.last_quiz_date).days
            if days_diff == 1:
                stats.current_streak += 1
            elif days_diff > 1:
                stats.current_streak = 1
        else:
            stats.current_streak = 1

        if stats.current_streak > stats.longest_streak:
            stats.longest_streak = stats.current_streak

        stats.last_quiz_date = today
        stats.save()


class QuizResultView(LoginRequiredMixin, View):
    """Show quiz result"""
    template_name = 'quiz/quiz-result.html'

    def get(self, request, attempt_id):
        attempt = get_object_or_404(
            QuizAttempt,
            id=attempt_id,
            user=request.user,
            status='completed'
        )

        answers = attempt.answers.select_related('question').prefetch_related('selected_options')

        # Check if this was the first pass (for XP messaging)
        is_first_pass = not QuizAttempt.objects.filter(
            user=request.user,
            quiz=attempt.quiz,
            passed=True,
            status='completed'
        ).exclude(id=attempt.id).exists()

        return render(request, self.template_name, {
            'is_first_pass': is_first_pass,
            'attempt': attempt,
            'answers': answers,
        })


class QuizHistoryView(LoginRequiredMixin, View):
    """User's quiz history"""
    template_name = 'quiz/quiz-history.html'

    def get(self, request):
        attempts = QuizAttempt.objects.filter(
            user=request.user,
            status='completed'
        ).select_related('quiz', 'quiz__category')

        return render(request, self.template_name, {'attempts': attempts})


# =============================================================================
# Staff Admin Portal Views
# =============================================================================

class StaffDashboardView(StaffRequiredMixin, View):
    """Staff admin dashboard"""
    template_name = 'staff/dashboard.html'

    def get(self, request):
        stats = {
            'total_categories': Category.objects.count(),
            'total_quizzes': Quiz.objects.count(),
            'published_quizzes': Quiz.objects.filter(is_published=True).count(),
            'total_questions': Question.objects.count(),
            'total_attempts': QuizAttempt.objects.filter(status='completed').count(),
        }

        recent_quizzes = Quiz.objects.order_by('-created_at')[:5]
        recent_attempts = QuizAttempt.objects.filter(
            status='completed'
        ).select_related('user', 'quiz').order_by('-completed_at')[:10]

        return render(request, self.template_name, {
            'stats': stats,
            'recent_quizzes': recent_quizzes,
            'recent_attempts': recent_attempts,
        })


class StaffImageUploadView(StaffRequiredMixin, View):
    """AJAX endpoint for uploading images to S3"""

    def post(self, request):
        from core.s3_utils import upload_image_to_s3

        if 'image' not in request.FILES:
            return JsonResponse({'error': 'No image provided'}, status=400)

        uploaded_file = request.FILES['image']
        folder = request.POST.get('folder', 'topic-images')

        url, s3_key, error = upload_image_to_s3(uploaded_file, folder)

        if error:
            return JsonResponse({'error': error}, status=400)

        return JsonResponse({
            'success': True,
            'url': url,
            's3_key': s3_key
        })


# Category Management
class StaffCategoryListView(StaffRequiredMixin, View):
    """List all categories for staff"""
    template_name = 'staff/category-list.html'

    def get(self, request):
        categories = Category.objects.all().order_by('order', 'name')
        return render(request, self.template_name, {'categories': categories})


class StaffCategoryCreateView(StaffRequiredMixin, View):
    """Create a new category"""
    template_name = 'staff/category-form.html'

    def get(self, request):
        form = CategoryForm()
        return render(request, self.template_name, {'form': form, 'action': 'Create'})

    def post(self, request):
        form = CategoryForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category created successfully!')
            return redirect('staff_category_list')
        return render(request, self.template_name, {'form': form, 'action': 'Create'})


class StaffCategoryEditView(StaffRequiredMixin, View):
    """Edit an existing category"""
    template_name = 'staff/category-form.html'

    def get(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        form = CategoryForm(instance=category)
        return render(request, self.template_name, {
            'form': form,
            'category': category,
            'action': 'Edit'
        })

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        form = CategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Category updated successfully!')
            return redirect('staff_category_list')
        return render(request, self.template_name, {
            'form': form,
            'category': category,
            'action': 'Edit'
        })


class StaffCategoryDeleteView(StaffRequiredMixin, View):
    """Delete a category"""

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        category.delete()
        messages.success(request, 'Category deleted successfully!')
        return redirect('staff_category_list')


# Quiz Management
class StaffQuizListView(StaffRequiredMixin, View):
    """List all quizzes for staff"""
    template_name = 'staff/quiz-list.html'

    def get(self, request):
        quizzes = Quiz.objects.all().select_related('category', 'created_by').order_by('-created_at')
        return render(request, self.template_name, {'quizzes': quizzes})


class StaffQuizCreateView(StaffRequiredMixin, View):
    """Create a new quiz"""
    template_name = 'staff/quiz-form.html'

    def get(self, request):
        form = QuizForm()
        return render(request, self.template_name, {'form': form, 'action': 'Create'})

    def post(self, request):
        form = QuizForm(request.POST)
        if form.is_valid():
            quiz = form.save(commit=False)
            quiz.created_by = request.user
            quiz.save()
            messages.success(request, 'Quiz created successfully! Now add questions.')
            return redirect('staff_question_list', quiz_id=quiz.id)
        return render(request, self.template_name, {'form': form, 'action': 'Create'})


class StaffQuizEditView(StaffRequiredMixin, View):
    """Edit an existing quiz"""
    template_name = 'staff/quiz-form.html'

    def get(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk)
        form = QuizForm(instance=quiz)
        return render(request, self.template_name, {
            'form': form,
            'quiz': quiz,
            'action': 'Edit'
        })

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk)
        form = QuizForm(request.POST, instance=quiz)
        if form.is_valid():
            form.save()
            messages.success(request, 'Quiz updated successfully!')
            return redirect('staff_quiz_list')
        return render(request, self.template_name, {
            'form': form,
            'quiz': quiz,
            'action': 'Edit'
        })


class StaffQuizDeleteView(StaffRequiredMixin, View):
    """Delete a quiz"""

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk)
        quiz.delete()
        messages.success(request, 'Quiz deleted successfully!')
        return redirect('staff_quiz_list')


# Question Management
class StaffQuestionListView(StaffRequiredMixin, View):
    """List all questions for a quiz"""
    template_name = 'staff/question-list.html'

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        questions = quiz.questions.all().prefetch_related('options').order_by('order')
        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
        })


class StaffQuestionCreateView(StaffRequiredMixin, View):
    """Create a new question with options"""
    template_name = 'staff/question-form.html'

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        form = QuestionForm()
        option_formset = OptionFormSet()
        return render(request, self.template_name, {
            'quiz': quiz,
            'form': form,
            'option_formset': option_formset,
            'action': 'Create'
        })

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        form = QuestionForm(request.POST)
        option_formset = OptionFormSet(request.POST)

        if form.is_valid() and option_formset.is_valid():
            question = form.save(commit=False)
            question.quiz = quiz
            question.save()

            option_formset.instance = question
            option_formset.save()

            messages.success(request, 'Question created successfully!')
            return redirect('staff_question_list', quiz_id=quiz.id)

        return render(request, self.template_name, {
            'quiz': quiz,
            'form': form,
            'option_formset': option_formset,
            'action': 'Create'
        })


class StaffQuestionEditView(StaffRequiredMixin, View):
    """Edit an existing question with options"""
    template_name = 'staff/question-form.html'

    def get(self, request, quiz_id, pk):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        question = get_object_or_404(Question, pk=pk, quiz=quiz)
        form = QuestionForm(instance=question)
        option_formset = OptionFormSet(instance=question)
        return render(request, self.template_name, {
            'quiz': quiz,
            'question': question,
            'form': form,
            'option_formset': option_formset,
            'action': 'Edit'
        })

    def post(self, request, quiz_id, pk):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        question = get_object_or_404(Question, pk=pk, quiz=quiz)
        form = QuestionForm(request.POST, instance=question)
        option_formset = OptionFormSet(request.POST, instance=question)

        if form.is_valid() and option_formset.is_valid():
            form.save()
            option_formset.save()
            messages.success(request, 'Question updated successfully!')
            return redirect('staff_question_list', quiz_id=quiz.id)

        return render(request, self.template_name, {
            'quiz': quiz,
            'question': question,
            'form': form,
            'option_formset': option_formset,
            'action': 'Edit'
        })


class StaffQuestionDeleteView(StaffRequiredMixin, View):
    """Delete a question"""

    def post(self, request, quiz_id, pk):
        quiz = get_object_or_404(Quiz, pk=quiz_id)
        question = get_object_or_404(Question, pk=pk, quiz=quiz)
        question.delete()
        messages.success(request, 'Question deleted successfully!')
        return redirect('staff_question_list', quiz_id=quiz.id)


# =============================================================================
# Video Export Views
# =============================================================================

class QuizVideoExportView(LoginRequiredMixin, View):
    """Redirect to new video export flow"""

    def get(self, request, slug):
        # Redirect to new video export choice page
        return redirect('video_export_choice', slug=slug)

    def post(self, request, slug):
        # Redirect POST requests too
        return redirect('video_export_choice', slug=slug)


class VideoProgressView(LoginRequiredMixin, View):
    """Check video generation progress from DynamoDB"""

    def get(self, request, task_id):
        progress = lambda_service.get_job_status_for_view(task_id)
        return JsonResponse(progress)


class VideoDownloadView(LoginRequiredMixin, View):
    """Download completed video from S3"""

    def get(self, request, task_id):
        video_data = lambda_service.get_video_data_for_download(task_id)

        if not video_data:
            return JsonResponse({'error': 'Video not found or expired'}, status=404)

        s3_url = video_data.get('s3_url')
        if s3_url:
            return redirect(s3_url)

        return JsonResponse({'error': 'Video not ready'}, status=404)


class VideoUrlView(LoginRequiredMixin, View):
    """Get S3 URL for the video (used for Instagram posting)"""

    def get(self, request, task_id):
        video_data = lambda_service.get_video_data_for_download(task_id)

        if not video_data:
            return JsonResponse({'error': 'Video not found or expired'}, status=404)

        s3_url = video_data.get('s3_url')
        if not s3_url:
            return JsonResponse({'error': 'Video not ready'}, status=400)

        return JsonResponse({
            'success': True,
            'url': s3_url,
            'filename': video_data.get('filename', 'video.mp4')
        })


# =============================================================================
# Video Job Management Views (New unified video generation system)
# =============================================================================

class VideoExportChoiceView(LoginRequiredMixin, View):
    """
    Main video export page showing:
    - Choice between Single Video and Bulk Video
    - List of recent/pending video jobs
    - Block new generation if pending jobs exist
    """
    template_name = 'quiz/video-export-choice.html'

    def get(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        questions = quiz.questions.prefetch_related('options').order_by('order')
        if questions.count() < 1:
            messages.error(request, 'This quiz has no questions to export.')
            return redirect('quiz_detail', slug=slug)

        # Check subscription
        get_or_create_free_subscription(request.user)
        can_access, message, subscription = check_feature_access(request.user, 'video_gen')

        # Check for pending jobs (single or bulk)
        pending_jobs = VideoJob.objects.filter(
            user=request.user,
            quiz=quiz,
            status__in=['pending', 'processing']
        )
        has_pending_jobs = pending_jobs.exists()

        # Get recent jobs for this quiz
        recent_jobs = VideoJob.objects.filter(
            user=request.user,
            quiz=quiz
        ).order_by('-created_at')[:10]

        # Check if user can bulk generate
        can_bulk_generate = False
        if subscription and subscription.plan.has_feature('can_generate_and_post_multiple_auto'):
            can_bulk_generate = True
        elif request.user.is_staff:
            can_bulk_generate = True

        # Check platform connections
        instagram_connected = (
            hasattr(request.user, 'instagram_account') and
            request.user.instagram_account.is_connected
        )
        youtube_connected = (
            hasattr(request.user, 'youtube_account') and
            request.user.youtube_account.is_connected
        )

        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
            'can_generate': can_access,
            'subscription_message': message if not can_access else None,
            'subscription': subscription,
            'has_pending_jobs': has_pending_jobs,
            'pending_jobs': pending_jobs,
            'recent_jobs': recent_jobs,
            'can_bulk_generate': can_bulk_generate,
            'instagram_connected': instagram_connected,
            'youtube_connected': youtube_connected,
        })


class SingleVideoCreateView(LoginRequiredMixin, View):
    """
    Create a single video with up to 3 questions.
    User selects questions and configures social media posting.
    """
    template_name = 'quiz/single-video-create.html'

    def get(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        questions = quiz.questions.prefetch_related('options').order_by('order')
        if questions.count() < 1:
            messages.error(request, 'This quiz has no questions.')
            return redirect('video_export_choice', slug=slug)

        # Check subscription
        get_or_create_free_subscription(request.user)
        can_access, message, subscription = check_feature_access(request.user, 'video_gen')

        if not can_access:
            messages.warning(request, message)
            return redirect('subscription')

        # Check for pending jobs
        pending_jobs = VideoJob.objects.filter(
            user=request.user,
            quiz=quiz,
            status__in=['pending', 'processing']
        )
        if pending_jobs.exists():
            messages.warning(request, 'You have pending video jobs. Please wait for them to complete.')
            return redirect('video_export_choice', slug=slug)

        # Check features
        can_custom_handle = (
            (subscription and subscription.plan.has_feature('custom_handle_name_in_video_export'))
            or request.user.is_staff
        )
        can_custom_intro_outro = (
            (subscription and subscription.plan.has_feature('custom_intro_and_outro'))
            or request.user.is_staff
        )

        # Check platform connections
        instagram_connected = (
            hasattr(request.user, 'instagram_account') and
            request.user.instagram_account.is_connected
        )
        youtube_connected = (
            hasattr(request.user, 'youtube_account') and
            request.user.youtube_account.is_connected
        )

        # Get video templates
        templates = VideoTemplate.objects.filter(is_active=True).order_by('sort_order')
        has_premium_templates = (
            (subscription and subscription.plan.has_feature('premium_video_templates'))
            or request.user.is_staff
        )
        templates_data = []
        default_template_id = None
        for template in templates:
            can_use = not template.is_premium or has_premium_templates
            templates_data.append({
                'id': template.id,
                'name': template.name,
                'slug': template.slug,
                'description': template.description,
                'is_premium': template.is_premium,
                'is_default': template.is_default,
                'can_use': can_use,
            })
            if template.is_default:
                default_template_id = template.id

        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
            'can_custom_handle': can_custom_handle,
            'can_custom_intro_outro': can_custom_intro_outro,
            'instagram_connected': instagram_connected,
            'youtube_connected': youtube_connected,
            'templates': templates_data,
            'default_template_id': default_template_id,
        })

    def post(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        # Check subscription
        get_or_create_free_subscription(request.user)
        can_access, message, subscription = check_feature_access(request.user, 'video_gen')
        if not can_access:
            return JsonResponse({'error': message}, status=403)

        # Check for pending jobs
        pending_jobs = VideoJob.objects.filter(
            user=request.user,
            quiz=quiz,
            status__in=['pending', 'processing']
        )
        if pending_jobs.exists():
            return JsonResponse({'error': 'You have pending video jobs. Please wait.'}, status=400)

        # Get selected questions (1-3)
        selected_ids = request.POST.getlist('questions')
        if len(selected_ids) < 1 or len(selected_ids) > 3:
            return JsonResponse({'error': 'Please select 1 to 3 questions.'}, status=400)

        selected_questions = Question.objects.filter(
            id__in=selected_ids, quiz=quiz
        ).prefetch_related('options')

        if not selected_questions.exists():
            return JsonResponse({'error': 'Invalid question selection.'}, status=400)

        # Use the feature
        use_feature(request.user, 'video_gen')

        # Get configuration options
        show_answer = request.POST.get('show_answer') == 'on'

        # Handle name
        handle_name = "@maedix-q"
        can_custom_handle = (
            (subscription and subscription.plan.has_feature('custom_handle_name_in_video_export'))
            or request.user.is_staff
        )
        if can_custom_handle:
            custom_handle = request.POST.get('handle_name', '').strip()
            if custom_handle:
                if not custom_handle.startswith('@'):
                    custom_handle = '@' + custom_handle
                if len(custom_handle) <= 30 and ' ' not in custom_handle:
                    handle_name = custom_handle

        # Intro/outro settings
        can_custom_intro_outro = (
            (subscription and subscription.plan.has_feature('custom_intro_and_outro'))
            or request.user.is_staff
        )
        intro_text = None
        pre_outro_text = None
        quiz_heading = None
        if can_custom_intro_outro:
            intro_text = request.POST.get('intro_text', '').strip() or None
            pre_outro_text = request.POST.get('pre_outro_text', '').strip() or None
            quiz_heading_raw = request.POST.get('quiz_heading', '').strip()
            if quiz_heading_raw:
                quiz_heading = quiz_heading_raw[:40]

        # Audio settings
        audio_url = Configuration.get_value('video_background_music_url', '')
        audio_volume = float(Configuration.get_value('video_background_music_volume', '0.5'))
        intro_audio_url = Configuration.get_value('video_intro_music_url', '')
        intro_audio_volume = float(Configuration.get_value('video_intro_music_volume', '0.5'))
        answer_reveal_audio_url = Configuration.get_value('video_answer_reveal_music_url', '')
        answer_reveal_audio_volume = float(
            Configuration.get_value('video_answer_reveal_music_volume', '0.5')
        )

        # Get template
        template = None
        template_config = None
        template_id = request.POST.get('template_id')
        if template_id:
            try:
                template = VideoTemplate.objects.get(id=template_id, is_active=True)
                has_premium_templates = (
                    (subscription and subscription.plan.has_feature('premium_video_templates'))
                    or request.user.is_staff
                )
                if template.is_premium and not has_premium_templates:
                    template = VideoTemplate.objects.filter(is_default=True, is_active=True).first()
                if template:
                    template_config = template.config
            except VideoTemplate.DoesNotExist:
                template = VideoTemplate.objects.filter(is_default=True, is_active=True).first()
                if template:
                    template_config = template.config

        # Build question data
        question_data = []
        question_ids = []
        for q in selected_questions:
            question_ids.append(q.id)
            question_data.append({
                'text': q.text,
                'code_snippet': q.code_snippet or '',
                'code_language': q.code_language or 'python',
                'explanation': q.explanation or '',
                'options': [
                    {'text': opt.text, 'is_correct': opt.is_correct}
                    for opt in q.options.all()
                ]
            })

        # Social media posting
        post_to_instagram = request.POST.get('post_to_instagram') == 'on'
        post_to_youtube = request.POST.get('post_to_youtube') == 'on'
        instagram_caption = request.POST.get('instagram_caption', '').strip()
        youtube_title = request.POST.get('youtube_title', '').strip() or f"{quiz.title} - Quiz"
        youtube_description = request.POST.get('youtube_description', '').strip()
        youtube_tags = request.POST.get('youtube_tags', '').strip()

        # Build default caption if not provided
        if not instagram_caption:
            first_question = question_data[0]['text'] if question_data else ''
            instagram_caption = f"{quiz.title}\n\n{first_question[:100]}...\n\n#quiz #education #shorts"

        # Build Lambda config
        lambda_config = {
            'show_answer': show_answer,
            'handle_name': handle_name,
            'audio_url': audio_url,
            'audio_volume': audio_volume,
            'intro_text': intro_text,
            'intro_audio_url': intro_audio_url,
            'intro_audio_volume': intro_audio_volume,
            'pre_outro_text': pre_outro_text,
            'quiz_heading': quiz_heading,
            'template_config': template_config,
            'answer_reveal_audio_url': answer_reveal_audio_url,
            'answer_reveal_audio_volume': answer_reveal_audio_volume
        }

        # Social posting config
        social_posting = None
        if post_to_instagram or post_to_youtube:
            social_posting = {
                'post_to_instagram': post_to_instagram,
                'post_to_youtube': post_to_youtube,
                'caption': instagram_caption,
                'title': youtube_title,
                'description': youtube_description,
                'tags': youtube_tags,
            }

        try:
            # Invoke Lambda
            task_id = lambda_service.invoke_video_generation(
                user=request.user,
                quiz=quiz,
                questions=question_data,
                config=lambda_config,
                social_posting=social_posting
            )

            # Create VideoJob record
            video_job = VideoJob.objects.create(
                user=request.user,
                quiz=quiz,
                job_type='single',
                task_id=task_id,
                question_ids=question_ids,
                questions_data=question_data,
                status='pending',
                post_to_instagram=post_to_instagram,
                post_to_youtube=post_to_youtube,
                instagram_caption=instagram_caption,
                youtube_title=youtube_title,
                youtube_description=youtube_description,
                youtube_tags=youtube_tags,
                template=template,
                video_config=lambda_config
            )

            return JsonResponse({
                'success': True,
                'job_id': video_job.id,
                'task_id': task_id
            })

        except Exception as e:
            logging.error(f"Lambda video generation failed: {e}")
            return JsonResponse({
                'error': f'Video generation service unavailable: {str(e)}'
            }, status=503)


class BulkVideoCreateView(LoginRequiredMixin, View):
    """
    Create bulk videos - one job per question.
    Each selected question becomes a separate VideoJob.
    """
    template_name = 'quiz/bulk-video-create.html'

    def get(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        questions = quiz.questions.prefetch_related('options').order_by('order')
        if questions.count() < 1:
            messages.error(request, 'This quiz has no questions.')
            return redirect('video_export_choice', slug=slug)

        # Check subscription
        get_or_create_free_subscription(request.user)
        subscription = get_user_subscription(request.user)

        can_bulk = (
            (subscription and subscription.plan.has_feature('can_generate_and_post_multiple_auto'))
            or request.user.is_staff
        )
        if not can_bulk:
            messages.error(request, 'Bulk video generation requires a premium subscription.')
            return redirect('video_export_choice', slug=slug)

        # Check for pending jobs
        pending_jobs = VideoJob.objects.filter(
            user=request.user,
            quiz=quiz,
            status__in=['pending', 'processing']
        )
        if pending_jobs.exists():
            messages.warning(request, 'You have pending video jobs. Please wait for them to complete.')
            return redirect('video_export_choice', slug=slug)

        # Check platform connections
        instagram_connected = (
            hasattr(request.user, 'instagram_account') and
            request.user.instagram_account.is_connected
        )
        youtube_connected = (
            hasattr(request.user, 'youtube_account') and
            request.user.youtube_account.is_connected
        )

        # Get video templates
        templates = VideoTemplate.objects.filter(is_active=True).order_by('sort_order')
        has_premium_templates = (
            (subscription and subscription.plan.has_feature('premium_video_templates'))
            or request.user.is_staff
        )
        templates_data = []
        default_template_id = None
        for template in templates:
            can_use = not template.is_premium or has_premium_templates
            templates_data.append({
                'id': template.id,
                'name': template.name,
                'slug': template.slug,
                'description': template.description,
                'is_premium': template.is_premium,
                'is_default': template.is_default,
                'can_use': can_use,
            })
            if template.is_default:
                default_template_id = template.id

        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
            'instagram_connected': instagram_connected,
            'youtube_connected': youtube_connected,
            'templates': templates_data,
            'default_template_id': default_template_id,
        })

    def post(self, request, slug):
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        # Check subscription
        get_or_create_free_subscription(request.user)
        subscription = get_user_subscription(request.user)

        can_bulk = (
            (subscription and subscription.plan.has_feature('can_generate_and_post_multiple_auto'))
            or request.user.is_staff
        )
        if not can_bulk:
            return JsonResponse({'error': 'Feature not available'}, status=403)

        # Check for pending jobs
        pending_jobs = VideoJob.objects.filter(
            user=request.user,
            quiz=quiz,
            status__in=['pending', 'processing']
        )
        if pending_jobs.exists():
            return JsonResponse({'error': 'You have pending video jobs. Please wait.'}, status=400)

        # Get selected questions
        selected_ids = request.POST.getlist('questions')
        if not selected_ids:
            return JsonResponse({'error': 'No questions selected.'}, status=400)

        # Check credits
        num_questions = len(selected_ids)
        can_access, message, _ = check_feature_access(request.user, 'video_gen')
        if not can_access:
            return JsonResponse({'error': message}, status=403)

        if subscription:
            remaining = subscription.get_remaining('video_gen')
            if remaining is not None and remaining < num_questions:
                return JsonResponse({
                    'error': f'Not enough credits. You have {remaining} but need {num_questions}.'
                }, status=403)

        # Validate platform connections
        post_to_instagram = request.POST.get('post_to_instagram') == 'on'
        post_to_youtube = request.POST.get('post_to_youtube') == 'on'

        if post_to_instagram:
            if not hasattr(request.user, 'instagram_account') or not request.user.instagram_account.is_connected:
                return JsonResponse({'error': 'Instagram not connected'}, status=400)

        if post_to_youtube:
            if not hasattr(request.user, 'youtube_account') or not request.user.youtube_account.is_connected:
                return JsonResponse({'error': 'YouTube not connected'}, status=400)

        # Get template
        template = None
        template_config = None
        template_id = request.POST.get('template_id')
        if template_id:
            try:
                template = VideoTemplate.objects.get(id=template_id, is_active=True)
                has_premium_templates = (
                    (subscription and subscription.plan.has_feature('premium_video_templates'))
                    or request.user.is_staff
                )
                if template.is_premium and not has_premium_templates:
                    template = VideoTemplate.objects.filter(is_default=True, is_active=True).first()
                if template:
                    template_config = template.config
            except VideoTemplate.DoesNotExist:
                template = VideoTemplate.objects.filter(is_default=True, is_active=True).first()
                if template:
                    template_config = template.config

        # Audio settings
        audio_url = Configuration.get_value('video_background_music_url', '')
        audio_volume = float(Configuration.get_value('video_background_music_volume', '0.5'))
        intro_audio_url = Configuration.get_value('video_intro_music_url', '')
        intro_audio_volume = float(Configuration.get_value('video_intro_music_volume', '0.5'))
        answer_reveal_audio_url = Configuration.get_value('video_answer_reveal_music_url', '')
        answer_reveal_audio_volume = float(
            Configuration.get_value('video_answer_reveal_music_volume', '0.5')
        )

        # Generate bulk group ID
        bulk_group_id = uuid.uuid4()
        created_jobs = []

        for question_id in selected_ids:
            try:
                question = Question.objects.prefetch_related('options').get(
                    id=question_id, quiz=quiz
                )

                # Use feature credit
                use_feature(request.user, 'video_gen')

                # Build question data
                question_data = [{
                    'text': question.text,
                    'code_snippet': question.code_snippet or '',
                    'code_language': question.code_language or 'python',
                    'explanation': question.explanation or '',
                    'options': [
                        {'text': opt.text, 'is_correct': opt.is_correct}
                        for opt in question.options.all()
                    ]
                }]

                # Get per-question settings
                show_answer = request.POST.get(f'show_answer_{question_id}') == 'on'
                intro_text = request.POST.get(f'intro_text_{question_id}', '').strip()[:100] or None
                pre_outro_text = request.POST.get(f'outro_text_{question_id}', '').strip()[:100] or None
                quiz_heading = request.POST.get(f'quiz_heading_{question_id}', '').strip()[:40] or None

                # Build caption
                instagram_caption = request.POST.get(f'caption_{question_id}', '').strip()
                if not instagram_caption:
                    instagram_caption = f"{quiz.title}\n\n{question.text[:100]}...\n\n#quiz #education #shorts"

                youtube_title = request.POST.get(f'yt_title_{question_id}', '').strip()
                if not youtube_title:
                    youtube_title = f"{quiz.title} - Q{question.order + 1}"

                youtube_description = request.POST.get(f'yt_desc_{question_id}', '').strip()
                youtube_tags = request.POST.get(f'yt_tags_{question_id}', '').strip()

                # Build Lambda config
                lambda_config = {
                    'show_answer': show_answer,
                    'handle_name': '@maedix-q',
                    'audio_url': audio_url,
                    'audio_volume': audio_volume,
                    'intro_text': intro_text,
                    'intro_audio_url': intro_audio_url,
                    'intro_audio_volume': intro_audio_volume,
                    'pre_outro_text': pre_outro_text,
                    'quiz_heading': quiz_heading,
                    'template_config': template_config,
                    'answer_reveal_audio_url': answer_reveal_audio_url,
                    'answer_reveal_audio_volume': answer_reveal_audio_volume
                }

                # Social posting config
                social_posting = None
                if post_to_instagram or post_to_youtube:
                    social_posting = {
                        'post_to_instagram': post_to_instagram,
                        'post_to_youtube': post_to_youtube,
                        'caption': instagram_caption,
                        'title': youtube_title,
                        'description': youtube_description,
                        'tags': youtube_tags,
                    }

                # Invoke Lambda
                task_id = lambda_service.invoke_video_generation(
                    user=request.user,
                    quiz=quiz,
                    questions=question_data,
                    config=lambda_config,
                    social_posting=social_posting
                )

                # Create VideoJob record
                video_job = VideoJob.objects.create(
                    user=request.user,
                    quiz=quiz,
                    job_type='bulk_item',
                    bulk_group_id=bulk_group_id,
                    task_id=task_id,
                    question_ids=[question.id],
                    questions_data=question_data,
                    status='pending',
                    post_to_instagram=post_to_instagram,
                    post_to_youtube=post_to_youtube,
                    instagram_caption=instagram_caption,
                    youtube_title=youtube_title,
                    youtube_description=youtube_description,
                    youtube_tags=youtube_tags,
                    template=template,
                    video_config=lambda_config
                )
                created_jobs.append(video_job.id)

            except Question.DoesNotExist:
                continue
            except Exception as e:
                logging.error(f"Failed to create job for question {question_id}: {e}")
                continue

        if not created_jobs:
            return JsonResponse({'error': 'Failed to create any jobs.'}, status=500)

        return JsonResponse({
            'success': True,
            'bulk_group_id': str(bulk_group_id),
            'job_ids': created_jobs,
            'total_jobs': len(created_jobs)
        })


class VideoJobListView(LoginRequiredMixin, View):
    """List all video jobs for the current user"""
    template_name = 'quiz/video-job-list.html'

    def get(self, request):
        jobs = VideoJob.objects.filter(user=request.user).order_by('-created_at')

        # Filter by status if provided
        status_filter = request.GET.get('status')
        if status_filter:
            jobs = jobs.filter(status=status_filter)

        # Filter by quiz if provided
        quiz_slug = request.GET.get('quiz')
        if quiz_slug:
            jobs = jobs.filter(quiz__slug=quiz_slug)

        return render(request, self.template_name, {
            'jobs': jobs[:50],  # Limit to 50 most recent
            'status_filter': status_filter,
            'quiz_slug': quiz_slug,
        })


class VideoJobDetailView(LoginRequiredMixin, View):
    """Detailed view of a single video job"""
    template_name = 'quiz/video-job-detail.html'

    def get(self, request, job_id):
        job = get_object_or_404(VideoJob, id=job_id, user=request.user)

        # Get related bulk jobs if this is part of a bulk group
        related_jobs = []
        if job.bulk_group_id:
            related_jobs = VideoJob.objects.filter(
                bulk_group_id=job.bulk_group_id
            ).exclude(id=job.id).order_by('created_at')

        # Sync status from DynamoDB if job is still pending/processing
        if job.status in ['pending', 'processing']:
            job_status = lambda_service.get_job_status(job.task_id)
            if job_status:
                job.sync_from_dynamodb(job_status)

        # Check social media connections
        instagram_connected = hasattr(request.user, 'instagram_account') and request.user.instagram_account.is_connected
        youtube_connected = hasattr(request.user, 'youtube_account') and request.user.youtube_account.is_connected

        return render(request, self.template_name, {
            'job': job,
            'related_jobs': related_jobs,
            'instagram_connected': instagram_connected,
            'youtube_connected': youtube_connected,
        })


class VideoJobStatusAPIView(LoginRequiredMixin, View):
    """API endpoint to get video job status (for polling)"""

    def get(self, request, job_id):
        try:
            job = VideoJob.objects.get(id=job_id, user=request.user)
        except VideoJob.DoesNotExist:
            return JsonResponse({'error': 'Job not found'}, status=404)

        # Get status from DynamoDB
        job_status = lambda_service.get_job_status(job.task_id)

        if job_status:
            # Update local record
            job.sync_from_dynamodb(job_status)

        return JsonResponse({
            'id': job.id,
            'task_id': job.task_id,
            'status': job.status,
            'progress_percent': job.progress_percent,
            'progress_message': job.progress_message,
            's3_url': job.s3_url,
            'instagram_posted': job.instagram_posted,
            'youtube_posted': job.youtube_posted,
            'instagram_error': job.instagram_error,
            'youtube_error': job.youtube_error,
            'error_message': job.error_message,
        })


class BulkGroupStatusAPIView(LoginRequiredMixin, View):
    """API endpoint to get status of all jobs in a bulk group"""

    def get(self, request, bulk_group_id):
        jobs = VideoJob.objects.filter(
            user=request.user,
            bulk_group_id=bulk_group_id
        ).order_by('created_at')

        if not jobs.exists():
            return JsonResponse({'error': 'Bulk group not found'}, status=404)

        # Sync all pending/processing jobs from DynamoDB
        jobs_data = []
        for job in jobs:
            if job.status in ['pending', 'processing']:
                job_status = lambda_service.get_job_status(job.task_id)
                if job_status:
                    job.sync_from_dynamodb(job_status)

            jobs_data.append({
                'id': job.id,
                'task_id': job.task_id,
                'question_ids': job.question_ids,
                'status': job.status,
                'progress_percent': job.progress_percent,
                'progress_message': job.progress_message,
                's3_url': job.s3_url,
                'instagram_posted': job.instagram_posted,
                'youtube_posted': job.youtube_posted,
                'error_message': job.error_message,
            })

        # Calculate overall progress
        total = len(jobs_data)
        completed = sum(1 for j in jobs_data if j['status'] == 'completed')
        failed = sum(1 for j in jobs_data if j['status'] == 'failed')
        processing = sum(1 for j in jobs_data if j['status'] in ['pending', 'processing'])

        overall_status = 'processing'
        if completed == total:
            overall_status = 'completed'
        elif failed == total:
            overall_status = 'failed'
        elif completed + failed == total and failed > 0:
            overall_status = 'partially_completed'

        return JsonResponse({
            'bulk_group_id': str(bulk_group_id),
            'total': total,
            'completed': completed,
            'failed': failed,
            'processing': processing,
            'overall_status': overall_status,
            'jobs': jobs_data,
        })


# =============================================================================
# User Quiz Management Views (Create, Edit, Submit for Approval)
# =============================================================================

class UserQuizListView(LoginRequiredMixin, View):
    """List user's own quizzes"""
    template_name = 'quiz/user/my-quizzes.html'

    def get(self, request):
        quizzes = Quiz.objects.filter(created_by=request.user).order_by('-created_at')
        return render(request, self.template_name, {
            'quizzes': quizzes,
        })


class UserQuizCreateView(LoginRequiredMixin, View):
    """Create a new quiz"""
    template_name = 'quiz/user/quiz-form.html'

    def get(self, request):
        # Ensure user has a subscription
        get_or_create_free_subscription(request.user)

        # Check if user can create more quizzes
        can_access, message, _ = check_feature_access(request.user, 'quiz_create')
        if not can_access:
            messages.warning(request, message)
            return redirect('subscription')

        form = QuizForm()
        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'categories': categories,
            'is_edit': False,
        })

    def post(self, request):
        # Ensure user has a subscription
        get_or_create_free_subscription(request.user)

        # Check if user can create more quizzes
        can_access, message, _ = check_feature_access(request.user, 'quiz_create')
        if not can_access:
            messages.warning(request, message)
            return redirect('subscription')

        form = QuizForm(request.POST)
        if form.is_valid():
            # Use the feature (increment usage)
            use_feature(request.user, 'quiz_create')

            quiz = form.save(commit=False)
            quiz.created_by = request.user
            quiz.status = 'draft'
            quiz.is_published = False
            quiz.save()
            messages.success(request, 'Quiz created! Now add some questions.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'categories': categories,
            'is_edit': False,
        })


class UserQuizEditView(LoginRequiredMixin, View):
    """Edit user's quiz (only if not approved)"""
    template_name = 'quiz/user/quiz-form.html'

    def get(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, created_by=request.user)

        if not quiz.can_be_edited:
            messages.error(request, 'Approved quizzes cannot be edited.')
            return redirect('user_quiz_list')

        form = QuizForm(instance=quiz)
        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'quiz': quiz,
            'categories': categories,
            'is_edit': True,
        })

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, created_by=request.user)

        if not quiz.can_be_edited:
            messages.error(request, 'Approved quizzes cannot be edited.')
            return redirect('user_quiz_list')

        form = QuizForm(request.POST, instance=quiz)
        if form.is_valid():
            # Reset to draft if it was rejected
            if quiz.status == 'rejected':
                quiz.status = 'draft'
                quiz.rejection_reason = ''
            form.save()
            messages.success(request, 'Quiz updated successfully!')
            return redirect('user_quiz_list')

        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'quiz': quiz,
            'categories': categories,
            'is_edit': True,
        })


class UserQuizDeleteView(LoginRequiredMixin, View):
    """Delete user's quiz (only if not approved)"""

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, created_by=request.user)

        if not quiz.can_be_deleted:
            messages.error(request, 'Approved quizzes cannot be deleted.')
            return redirect('user_quiz_list')

        quiz.delete()
        messages.success(request, 'Quiz deleted successfully!')
        return redirect('user_quiz_list')


class UserQuizQuestionsView(LoginRequiredMixin, View):
    """Manage questions for user's quiz"""
    template_name = 'quiz/user/quiz-questions.html'

    def get(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, created_by=request.user)
        questions = quiz.questions.prefetch_related('options').order_by('order')
        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
        })


class UserQuestionCreateView(LoginRequiredMixin, View):
    """Add question to user's quiz"""
    template_name = 'quiz/user/question-form.html'

    def get(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)

        if not quiz.can_be_edited:
            messages.error(request, 'Cannot add questions to approved quizzes.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        form = QuestionForm()
        formset = OptionFormSet()
        return render(request, self.template_name, {
            'quiz': quiz,
            'form': form,
            'formset': formset,
            'is_edit': False,
        })

    def post(self, request, quiz_id):
        quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)

        if not quiz.can_be_edited:
            messages.error(request, 'Cannot add questions to approved quizzes.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        form = QuestionForm(request.POST)
        formset = OptionFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            question = form.save(commit=False)
            question.quiz = quiz
            question.order = quiz.questions.count() + 1
            question.save()

            # Set the question instance and save only non-empty options
            formset.instance = question
            for option_form in formset:
                if option_form.cleaned_data and option_form.cleaned_data.get('text', '').strip():
                    option = option_form.save(commit=False)
                    option.question = question
                    option.save()

            messages.success(request, 'Question added successfully!')
            return redirect('user_quiz_questions', pk=quiz.pk)

        return render(request, self.template_name, {
            'quiz': quiz,
            'form': form,
            'formset': formset,
            'is_edit': False,
        })


class UserQuestionEditView(LoginRequiredMixin, View):
    """Edit question in user's quiz"""
    template_name = 'quiz/user/question-form.html'

    def get(self, request, quiz_id, pk):
        quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)
        question = get_object_or_404(Question, pk=pk, quiz=quiz)

        if not quiz.can_be_edited:
            messages.error(request, 'Cannot edit questions in approved quizzes.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        form = QuestionForm(instance=question)
        formset = OptionFormSet(instance=question)
        return render(request, self.template_name, {
            'quiz': quiz,
            'question': question,
            'form': form,
            'formset': formset,
            'is_edit': True,
        })

    def post(self, request, quiz_id, pk):
        quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)
        question = get_object_or_404(Question, pk=pk, quiz=quiz)

        if not quiz.can_be_edited:
            messages.error(request, 'Cannot edit questions in approved quizzes.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        form = QuestionForm(request.POST, instance=question)
        formset = OptionFormSet(request.POST, instance=question)

        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Question updated successfully!')
            return redirect('user_quiz_questions', pk=quiz.pk)

        return render(request, self.template_name, {
            'quiz': quiz,
            'question': question,
            'form': form,
            'formset': formset,
            'is_edit': True,
        })


class UserQuestionDeleteView(LoginRequiredMixin, View):
    """Delete question from user's quiz"""

    def post(self, request, quiz_id, pk):
        quiz = get_object_or_404(Quiz, pk=quiz_id, created_by=request.user)
        question = get_object_or_404(Question, pk=pk, quiz=quiz)

        if not quiz.can_be_edited:
            messages.error(request, 'Cannot delete questions from approved quizzes.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        question.delete()
        messages.success(request, 'Question deleted successfully!')
        return redirect('user_quiz_questions', pk=quiz.pk)


class UserQuizSubmitApprovalView(LoginRequiredMixin, View):
    """Submit quiz for admin approval"""

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, created_by=request.user)

        # Check if quiz has at least 1 question
        if quiz.questions.count() < 1:
            messages.error(request, 'Quiz must have at least 1 question before submitting for approval.')
            return redirect('user_quiz_questions', pk=quiz.pk)

        # Check all questions have at least 2 options with 1 correct
        for question in quiz.questions.all():
            options = question.options.all()
            if options.count() < 2:
                messages.error(request, f'Question "{question.text[:50]}..." must have at least 2 options.')
                return redirect('user_quiz_questions', pk=quiz.pk)
            if not options.filter(is_correct=True).exists():
                messages.error(request, f'Question "{question.text[:50]}..." must have at least 1 correct answer.')
                return redirect('user_quiz_questions', pk=quiz.pk)

        quiz.status = 'pending'
        quiz.save()
        messages.success(request, 'Quiz submitted for approval! You will be notified once reviewed.')
        return redirect('user_quiz_list')


# =============================================================================
# User Topic Management Views
# =============================================================================

class UserTopicListView(LoginRequiredMixin, View):
    """List user's own topics"""
    template_name = 'quiz/user/my-topics.html'

    def get(self, request):
        topics = Topic.objects.filter(created_by=request.user).order_by('-created_at')
        return render(request, self.template_name, {
            'topics': topics,
        })


class UserTopicCreateView(LoginRequiredMixin, View):
    """Create a new topic"""
    template_name = 'quiz/user/topic-form.html'

    def get(self, request):
        # Ensure user has a subscription
        get_or_create_free_subscription(request.user)

        # Check if user can create more topics
        can_access, message, _ = check_feature_access(request.user, 'topic_create')
        if not can_access:
            messages.warning(request, message)
            return redirect('subscription')

        form = UserTopicForm()
        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'categories': categories,
            'is_edit': False,
        })

    def post(self, request):
        # Ensure user has a subscription
        get_or_create_free_subscription(request.user)

        # Check if user can create more topics
        can_access, message, _ = check_feature_access(request.user, 'topic_create')
        if not can_access:
            messages.warning(request, message)
            return redirect('subscription')

        form = UserTopicForm(request.POST)
        if form.is_valid():
            # Use the feature (increment usage)
            use_feature(request.user, 'topic_create')

            topic = form.save(commit=False)
            topic.created_by = request.user
            topic.status = 'draft'
            topic.save()
            messages.success(request, 'Topic created! Now add some cards.')
            return redirect('user_topic_cards', pk=topic.pk)

        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'categories': categories,
            'is_edit': False,
        })


class UserTopicEditView(LoginRequiredMixin, View):
    """Edit user's topic (only if not approved)"""
    template_name = 'quiz/user/topic-form.html'

    def get(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, created_by=request.user)

        if not topic.can_be_edited:
            messages.error(request, 'Approved topics cannot be edited.')
            return redirect('user_topic_list')

        form = UserTopicForm(instance=topic)
        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'topic': topic,
            'categories': categories,
            'is_edit': True,
        })

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, created_by=request.user)

        if not topic.can_be_edited:
            messages.error(request, 'Approved topics cannot be edited.')
            return redirect('user_topic_list')

        form = UserTopicForm(request.POST, instance=topic)
        if form.is_valid():
            # Reset to draft if it was rejected
            if topic.status == 'rejected':
                topic.status = 'draft'
                topic.rejection_reason = ''
            form.save()
            messages.success(request, 'Topic updated successfully!')
            return redirect('user_topic_list')

        categories = Category.objects.filter(is_active=True)
        return render(request, self.template_name, {
            'form': form,
            'topic': topic,
            'categories': categories,
            'is_edit': True,
        })


class UserTopicDeleteView(LoginRequiredMixin, View):
    """Delete user's topic (only if not approved)"""

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, created_by=request.user)

        if not topic.can_be_deleted:
            messages.error(request, 'Approved topics cannot be deleted.')
            return redirect('user_topic_list')

        topic.delete()
        messages.success(request, 'Topic deleted successfully!')
        return redirect('user_topic_list')


class UserTopicCardsView(LoginRequiredMixin, View):
    """Manage cards for user's topic"""
    template_name = 'quiz/user/topic-cards.html'

    def get(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, created_by=request.user)
        cards = topic.cards.all().order_by('order')
        return render(request, self.template_name, {
            'topic': topic,
            'cards': cards,
        })


class UserCardCreateView(LoginRequiredMixin, View):
    """Add card to user's topic"""
    template_name = 'quiz/user/card-form.html'

    def get(self, request, topic_id):
        topic = get_object_or_404(Topic, pk=topic_id, created_by=request.user)

        if not topic.can_be_edited:
            messages.error(request, 'Cannot add cards to approved topics.')
            return redirect('user_topic_cards', pk=topic.pk)

        form = TopicCardForm()
        # Set default order to next available
        next_order = topic.cards.count()
        form.initial['order'] = next_order
        return render(request, self.template_name, {
            'topic': topic,
            'form': form,
            'is_edit': False,
        })

    def post(self, request, topic_id):
        topic = get_object_or_404(Topic, pk=topic_id, created_by=request.user)

        if not topic.can_be_edited:
            messages.error(request, 'Cannot add cards to approved topics.')
            return redirect('user_topic_cards', pk=topic.pk)

        form = TopicCardForm(request.POST)
        if form.is_valid():
            card = form.save(commit=False)
            card.topic = topic
            card.save()
            messages.success(request, 'Card added successfully!')
            return redirect('user_topic_cards', pk=topic.pk)

        return render(request, self.template_name, {
            'topic': topic,
            'form': form,
            'is_edit': False,
        })


class UserCardEditView(LoginRequiredMixin, View):
    """Edit card in user's topic"""
    template_name = 'quiz/user/card-form.html'

    def get(self, request, topic_id, pk):
        topic = get_object_or_404(Topic, pk=topic_id, created_by=request.user)
        card = get_object_or_404(TopicCard, pk=pk, topic=topic)

        if not topic.can_be_edited:
            messages.error(request, 'Cannot edit cards in approved topics.')
            return redirect('user_topic_cards', pk=topic.pk)

        form = TopicCardForm(instance=card)
        return render(request, self.template_name, {
            'topic': topic,
            'card': card,
            'form': form,
            'is_edit': True,
        })

    def post(self, request, topic_id, pk):
        topic = get_object_or_404(Topic, pk=topic_id, created_by=request.user)
        card = get_object_or_404(TopicCard, pk=pk, topic=topic)

        if not topic.can_be_edited:
            messages.error(request, 'Cannot edit cards in approved topics.')
            return redirect('user_topic_cards', pk=topic.pk)

        form = TopicCardForm(request.POST, instance=card)
        if form.is_valid():
            form.save()
            messages.success(request, 'Card updated successfully!')
            return redirect('user_topic_cards', pk=topic.pk)

        return render(request, self.template_name, {
            'topic': topic,
            'card': card,
            'form': form,
            'is_edit': True,
        })


class UserCardDeleteView(LoginRequiredMixin, View):
    """Delete card from user's topic"""

    def post(self, request, topic_id, pk):
        topic = get_object_or_404(Topic, pk=topic_id, created_by=request.user)
        card = get_object_or_404(TopicCard, pk=pk, topic=topic)

        if not topic.can_be_edited:
            messages.error(request, 'Cannot delete cards from approved topics.')
            return redirect('user_topic_cards', pk=topic.pk)

        card.delete()
        messages.success(request, 'Card deleted successfully!')
        return redirect('user_topic_cards', pk=topic.pk)


class UserTopicSubmitApprovalView(LoginRequiredMixin, View):
    """Submit topic for admin approval"""

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, created_by=request.user)

        # Check if topic has at least 1 card
        if topic.cards.count() < 1:
            messages.error(request, 'Topic must have at least 1 card before submitting for approval.')
            return redirect('user_topic_cards', pk=topic.pk)

        # Check all cards have content
        for card in topic.cards.all():
            if not card.content.strip():
                messages.error(request, f'Card "{card.title or "Untitled"}" must have content.')
                return redirect('user_topic_cards', pk=topic.pk)

        topic.status = 'pending'
        topic.save()
        messages.success(request, 'Topic submitted for approval! You will be notified once reviewed.')
        return redirect('user_topic_list')


# =============================================================================
# Admin Approval Views
# =============================================================================

class StaffPendingApprovalsView(StaffRequiredMixin, View):
    """List quizzes and topics pending approval"""
    template_name = 'staff/pending-approvals.html'

    def get(self, request):
        pending_quizzes = Quiz.objects.filter(status='pending').select_related('created_by', 'category').order_by('created_at')
        pending_topics = Topic.objects.filter(status='pending').select_related('created_by', 'category').order_by('created_at')
        return render(request, self.template_name, {
            'pending_quizzes': pending_quizzes,
            'pending_topics': pending_topics,
        })


class StaffQuizPreviewView(StaffRequiredMixin, View):
    """Preview quiz before approval"""
    template_name = 'staff/quiz-preview.html'

    def get(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk)
        questions = quiz.questions.prefetch_related('options').order_by('order')
        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
        })


class StaffApproveQuizView(StaffRequiredMixin, View):
    """Approve a quiz"""

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, status='pending')
        quiz.status = 'approved'
        quiz.is_published = True
        quiz.approved_by = request.user
        quiz.approved_at = timezone.now()
        quiz.save()
        messages.success(request, f'Quiz "{quiz.title}" has been approved and published!')
        return redirect('staff_pending_approvals')


class StaffRejectQuizView(StaffRequiredMixin, View):
    """Reject a quiz"""

    def post(self, request, pk):
        quiz = get_object_or_404(Quiz, pk=pk, status='pending')
        reason = request.POST.get('reason', '')
        quiz.status = 'rejected'
        quiz.rejection_reason = reason
        quiz.save()
        messages.success(request, f'Quiz "{quiz.title}" has been rejected.')
        return redirect('staff_pending_approvals')


class StaffTopicPreviewView(StaffRequiredMixin, View):
    """Preview topic before approval"""
    template_name = 'staff/topic-preview.html'

    def get(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk)
        cards = topic.cards.all().order_by('order')
        return render(request, self.template_name, {
            'topic': topic,
            'cards': cards,
        })


class StaffApproveTopicView(StaffRequiredMixin, View):
    """Approve a topic"""

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, status='pending')
        topic.status = 'approved'
        topic.approved_by = request.user
        topic.approved_at = timezone.now()
        topic.save()
        messages.success(request, f'Topic "{topic.title}" has been approved!')
        return redirect('staff_pending_approvals')


class StaffRejectTopicView(StaffRequiredMixin, View):
    """Reject a topic"""

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk, status='pending')
        reason = request.POST.get('reason', '')
        topic.status = 'rejected'
        topic.rejection_reason = reason
        topic.save()
        messages.success(request, f'Topic "{topic.title}" has been rejected.')
        return redirect('staff_pending_approvals')


class StaffQuizImportView(StaffRequiredMixin, View):
    """Import quiz from JSON - for automation"""
    template_name = 'staff/quiz-import.html'

    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by('name')
        sample_json = '''{
  "title": "Sample Quiz Title",
  "description": "Quiz description here",
  "difficulty": "beginner",
  "time_limit": 600,
  "pass_percentage": 70,
  "xp_reward": 10,
  "is_published": true,
  "is_featured": false,
  "questions": [
    {
      "text": "What is the output of print(2 + 2)?",
      "question_type": "single",
      "code_snippet": "print(2 + 2)",
      "code_language": "python",
      "explanation": "2 + 2 equals 4",
      "points": 1,
      "options": [
        {"text": "2", "is_correct": false},
        {"text": "4", "is_correct": true},
        {"text": "22", "is_correct": false},
        {"text": "Error", "is_correct": false}
      ]
    }
  ]
}'''
        return render(request, self.template_name, {
            'categories': categories,
            'sample_json': sample_json,
        })

    def post(self, request):
        categories = Category.objects.filter(is_active=True).order_by('name')
        category_id = request.POST.get('category')
        json_data = request.POST.get('json_data', '').strip()

        errors = []

        # Validate category
        try:
            category = Category.objects.get(pk=category_id, is_active=True)
        except Category.DoesNotExist:
            errors.append('Please select a valid category.')

        # Parse JSON
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            errors.append(f'Invalid JSON format: {str(e)}')
            return render(request, self.template_name, {
                'categories': categories,
                'errors': errors,
                'json_data': json_data,
                'selected_category': category_id,
            })

        # Validate required fields
        if not data.get('title'):
            errors.append('Quiz title is required.')
        if not data.get('questions') or len(data.get('questions', [])) < 1:
            errors.append('At least one question is required.')

        # Check for duplicate slug
        title = data.get('title', '')
        slug = slugify(title)
        if Quiz.objects.filter(slug=slug).exists():
            # Make slug unique
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        if errors:
            return render(request, self.template_name, {
                'categories': categories,
                'errors': errors,
                'json_data': json_data,
                'selected_category': category_id,
            })

        try:
            # Create Quiz
            quiz = Quiz.objects.create(
                title=data.get('title'),
                slug=slug,
                description=data.get('description', ''),
                category=category,
                difficulty=data.get('difficulty', 'beginner'),
                time_limit=data.get('time_limit', 600),
                pass_percentage=data.get('pass_percentage', 70),
                xp_reward=data.get('xp_reward', 10),
                is_published=data.get('is_published', False),
                is_featured=data.get('is_featured', False),
                status='approved' if data.get('is_published', False) else 'draft',
                approved_by=request.user if data.get('is_published', False) else None,
                approved_at=timezone.now() if data.get('is_published', False) else None,
                created_by=request.user,
            )

            # Create Questions and Options
            questions_created = 0
            for q_order, q_data in enumerate(data.get('questions', []), start=1):
                if not q_data.get('text'):
                    continue

                question = Question.objects.create(
                    quiz=quiz,
                    text=q_data.get('text'),
                    question_type=q_data.get('question_type', 'single'),
                    code_snippet=q_data.get('code_snippet', ''),
                    code_language=q_data.get('code_language', 'python'),
                    explanation=q_data.get('explanation', ''),
                    order=q_order,
                    points=q_data.get('points', 1),
                )

                # Create Options
                for o_order, o_data in enumerate(q_data.get('options', []), start=1):
                    if not o_data.get('text'):
                        continue

                    Option.objects.create(
                        question=question,
                        text=o_data.get('text'),
                        is_correct=o_data.get('is_correct', False),
                        order=o_order,
                    )

                questions_created += 1

            messages.success(
                request,
                f'Quiz "{quiz.title}" created successfully with {questions_created} questions!'
            )
            return redirect('staff_question_list', quiz_id=quiz.id)

        except Exception as e:
            errors.append(f'Error creating quiz: {str(e)}')
            return render(request, self.template_name, {
                'categories': categories,
                'errors': errors,
                'json_data': json_data,
                'selected_category': category_id,
            })


# =============================================================================
# Bulk Video Export Views
# =============================================================================

def _post_to_instagram_sync(user, video_url, quiz_title, question_text):
    """Synchronously post video to Instagram"""
    import requests

    ig_account = user.instagram_account
    access_token = ig_account.access_token
    ig_user_id = ig_account.instagram_user_id

    caption = f"{quiz_title}\n\n{question_text[:100]}...\n\n#quiz #education #maedixq #shorts"

    # Step 1: Create media container for Reel
    container_response = requests.post(
        f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "access_token": access_token,
        },
        timeout=30,
    )
    container_data = container_response.json()

    if "id" not in container_data:
        raise Exception(container_data.get("error", {}).get("message", "Failed to create media"))

    container_id = container_data["id"]

    # Step 2: Wait for video processing to complete
    for _ in range(30):
        status_response = requests.get(
            f"https://graph.instagram.com/v21.0/{container_id}",
            params={"fields": "status_code", "access_token": access_token},
            timeout=10,
        )
        status_code = status_response.json().get("status_code")
        if status_code == "FINISHED":
            break
        elif status_code == "ERROR":
            raise Exception("Video processing failed")
        time.sleep(10)
    else:
        raise Exception("Video processing timeout")

    # Step 3: Publish
    publish_response = requests.post(
        f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
        data={"creation_id": container_id, "access_token": access_token},
        timeout=60,
    )
    if "id" not in publish_response.json():
        raise Exception(publish_response.json().get("error", {}).get("message", "Failed to publish"))


def _post_to_youtube_sync(user, video_url, quiz_title, question_text):
    """Synchronously post video to YouTube"""
    import requests
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from youtube.views import get_valid_credentials

    youtube_account = user.youtube_account
    credentials = get_valid_credentials(youtube_account)
    youtube = build('youtube', 'v3', credentials=credentials)

    # Download video to temp file
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_file:
        response = requests.get(video_url, stream=True)
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=8192):
            tmp_file.write(chunk)
        tmp_path = tmp_file.name

    try:
        body = {
            'snippet': {
                'title': f"{quiz_title} - Quiz"[:100],
                'description': f"{question_text[:200]}...\n\n#Shorts #quiz #education",
                'tags': ['quiz', 'education', 'shorts'],
                'categoryId': '27',  # Education
            },
            'status': {
                'privacyStatus': 'public',
                'selfDeclaredMadeForKids': False,
            },
        }

        media = MediaFileUpload(tmp_path, mimetype='video/mp4', resumable=True)
        insert_request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)

        response = None
        while response is None:
            _, response = insert_request.next_chunk()
    finally:
        os.unlink(tmp_path)


class BulkVideoExportView(LoginRequiredMixin, View):
    """Redirect to new bulk video flow"""

    def get(self, request, slug):
        return redirect('bulk_video_create', slug=slug)

    def post(self, request, slug):
        return redirect('bulk_video_create', slug=slug)


# =============================================================================
# TOPIC MANAGEMENT - Staff Views
# =============================================================================

class StaffTopicListView(StaffRequiredMixin, View):
    """List all topics for staff"""
    template_name = 'staff/topic-list.html'

    def get(self, request):
        topics = Topic.objects.all().select_related('category', 'created_by').order_by('-created_at')
        return render(request, self.template_name, {'topics': topics})


class StaffTopicImportView(StaffRequiredMixin, View):
    """Import topic from JSON - for bulk creation"""
    template_name = 'staff/topic-import.html'

    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by('name')
        sample_json = '''{
  "title": "Python Variables",
  "description": "Learn about variables in Python",
  "status": "published",
  "is_featured": false,
  "estimated_time": 3,
  "cards": [
    {
      "title": "What are Variables?",
      "content": "Variables are containers for storing data values. In Python, you don't need to declare the type of a variable - it's determined automatically when you assign a value.",
      "card_type": "text"
    },
    {
      "title": "Creating Variables",
      "content": "To create a variable, simply assign a value using the equals sign. Python will automatically determine the data type based on the value you assign.",
      "card_type": "text_code",
      "code_snippet": "name = \\"John\\"\\nage = 25\\nheight = 5.9\\nis_student = True",
      "code_language": "python"
    },
    {
      "title": "Variable Naming Rules",
      "content": "Variable names must start with a letter or underscore. They can contain letters, numbers, and underscores. Python is case-sensitive, so 'name' and 'Name' are different variables.",
      "card_type": "text"
    }
  ]
}'''
        return render(request, self.template_name, {
            'categories': categories,
            'sample_json': sample_json,
        })

    def post(self, request):
        categories = Category.objects.filter(is_active=True).order_by('name')
        category_id = request.POST.get('category')
        json_data = request.POST.get('json_data', '').strip()

        errors = []

        # Validate category
        category = None
        try:
            category = Category.objects.get(pk=category_id, is_active=True)
        except Category.DoesNotExist:
            errors.append('Please select a valid category.')

        # Parse JSON
        try:
            data = json.loads(json_data)
        except json.JSONDecodeError as e:
            errors.append(f'Invalid JSON format: {str(e)}')
            return render(request, self.template_name, {
                'categories': categories,
                'errors': errors,
                'json_data': json_data,
                'selected_category': category_id,
            })

        # Validate required fields
        if not data.get('title'):
            errors.append('Topic title is required.')
        if not data.get('cards') or len(data.get('cards', [])) < 1:
            errors.append('At least one card is required.')

        # Check for duplicate slug
        title = data.get('title', '')
        slug = slugify(title)
        if Topic.objects.filter(slug=slug).exists():
            # Make slug unique
            slug = f"{slug}-{uuid.uuid4().hex[:6]}"

        if errors:
            return render(request, self.template_name, {
                'categories': categories,
                'errors': errors,
                'json_data': json_data,
                'selected_category': category_id,
            })

        try:
            # Create Topic
            topic = Topic.objects.create(
                title=data.get('title'),
                slug=slug,
                description=data.get('description', ''),
                category=category,
                status=data.get('status', 'draft'),
                is_featured=data.get('is_featured', False),
                estimated_time=data.get('estimated_time', 2),
                thumbnail_url=data.get('thumbnail_url', ''),
                created_by=request.user,
            )

            # Create Cards
            cards_created = 0
            for c_order, c_data in enumerate(data.get('cards', [])):
                if not c_data.get('content'):
                    continue

                TopicCard.objects.create(
                    topic=topic,
                    title=c_data.get('title', ''),
                    content=c_data.get('content'),
                    card_type=c_data.get('card_type', 'text'),
                    code_snippet=c_data.get('code_snippet', ''),
                    code_language=c_data.get('code_language', 'python'),
                    image_url=c_data.get('image_url', ''),
                    image_caption=c_data.get('image_caption', ''),
                    order=c_order,
                )
                cards_created += 1

            messages.success(
                request,
                f'Topic "{topic.title}" created successfully with {cards_created} cards!'
            )
            return redirect('staff_topic_cards', topic_id=topic.id)

        except Exception as e:
            errors.append(f'Error creating topic: {str(e)}')
            return render(request, self.template_name, {
                'categories': categories,
                'errors': errors,
                'json_data': json_data,
                'selected_category': category_id,
            })


class StaffTopicCreateView(StaffRequiredMixin, View):
    """Create a new topic"""
    template_name = 'staff/topic-form.html'

    def get(self, request):
        form = TopicForm()
        return render(request, self.template_name, {'form': form, 'action': 'Create'})

    def post(self, request):
        form = TopicForm(request.POST)
        if form.is_valid():
            topic = form.save(commit=False)
            topic.created_by = request.user
            topic.save()
            messages.success(request, 'Topic created successfully! Now add cards.')
            return redirect('staff_topic_cards', topic_id=topic.id)
        return render(request, self.template_name, {'form': form, 'action': 'Create'})


class StaffTopicEditView(StaffRequiredMixin, View):
    """Edit an existing topic"""
    template_name = 'staff/topic-form.html'

    def get(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk)
        form = TopicForm(instance=topic)
        return render(request, self.template_name, {
            'form': form,
            'topic': topic,
            'action': 'Edit'
        })

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk)
        form = TopicForm(request.POST, instance=topic)
        if form.is_valid():
            form.save()
            messages.success(request, 'Topic updated successfully!')
            return redirect('staff_topic_list')
        return render(request, self.template_name, {
            'form': form,
            'topic': topic,
            'action': 'Edit'
        })


class StaffTopicDeleteView(StaffRequiredMixin, View):
    """Delete a topic"""

    def post(self, request, pk):
        topic = get_object_or_404(Topic, pk=pk)
        topic.delete()
        messages.success(request, 'Topic deleted successfully!')
        return redirect('staff_topic_list')


class StaffTopicCardsView(StaffRequiredMixin, View):
    """List and manage cards for a topic"""
    template_name = 'staff/topic-cards.html'

    def get(self, request, topic_id):
        topic = get_object_or_404(Topic, pk=topic_id)
        cards = topic.cards.all().order_by('order')
        return render(request, self.template_name, {
            'topic': topic,
            'cards': cards,
        })


class StaffCardCreateView(StaffRequiredMixin, View):
    """Create a new card for a topic"""
    template_name = 'staff/card-form.html'

    def get(self, request, topic_id):
        topic = get_object_or_404(Topic, pk=topic_id)
        form = TopicCardForm()
        # Set default order to next available
        next_order = topic.cards.count()
        form.initial['order'] = next_order
        return render(request, self.template_name, {
            'topic': topic,
            'form': form,
            'action': 'Create'
        })

    def post(self, request, topic_id):
        topic = get_object_or_404(Topic, pk=topic_id)
        form = TopicCardForm(request.POST)
        if form.is_valid():
            card = form.save(commit=False)
            card.topic = topic
            card.save()
            messages.success(request, 'Card created successfully!')
            return redirect('staff_topic_cards', topic_id=topic.id)
        return render(request, self.template_name, {
            'topic': topic,
            'form': form,
            'action': 'Create'
        })


class StaffCardEditView(StaffRequiredMixin, View):
    """Edit an existing card"""
    template_name = 'staff/card-form.html'

    def get(self, request, topic_id, pk):
        topic = get_object_or_404(Topic, pk=topic_id)
        card = get_object_or_404(TopicCard, pk=pk, topic=topic)
        form = TopicCardForm(instance=card)
        return render(request, self.template_name, {
            'topic': topic,
            'card': card,
            'form': form,
            'action': 'Edit'
        })

    def post(self, request, topic_id, pk):
        topic = get_object_or_404(Topic, pk=topic_id)
        card = get_object_or_404(TopicCard, pk=pk, topic=topic)
        form = TopicCardForm(request.POST, instance=card)
        if form.is_valid():
            form.save()
            messages.success(request, 'Card updated successfully!')
            return redirect('staff_topic_cards', topic_id=topic.id)
        return render(request, self.template_name, {
            'topic': topic,
            'card': card,
            'form': form,
            'action': 'Edit'
        })


class StaffCardDeleteView(StaffRequiredMixin, View):
    """Delete a card"""

    def post(self, request, topic_id, pk):
        topic = get_object_or_404(Topic, pk=topic_id)
        card = get_object_or_404(TopicCard, pk=pk, topic=topic)
        card.delete()
        messages.success(request, 'Card deleted successfully!')
        return redirect('staff_topic_cards', topic_id=topic.id)


# =============================================================================
# TOPIC - Public Views
# =============================================================================

class TopicsHomeView(View):
    """Topics home page - discover learning topics"""
    template_name = 'quiz/topics/home.html'

    def get(self, request):
        featured_topics = Topic.objects.filter(status='published', is_featured=True)[:6]
        categories = Category.objects.filter(is_active=True, parent__isnull=True)[:8]
        recent_topics = Topic.objects.filter(status='published').order_by('-created_at')[:6]

        # Get user's in-progress topics
        in_progress_topics = []
        if request.user.is_authenticated:
            in_progress_progress = TopicProgress.objects.filter(
                user=request.user,
                is_completed=False
            ).select_related('topic')[:3]
            in_progress_topics = [p.topic for p in in_progress_progress]

        return render(request, self.template_name, {
            'featured_topics': featured_topics,
            'categories': categories,
            'recent_topics': recent_topics,
            'in_progress_topics': in_progress_topics,
        })


class TopicCategoryView(View):
    """View topics in a specific category"""
    template_name = 'quiz/topics/category.html'

    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug, is_active=True)
        topics = Topic.objects.filter(category=category, status='published')

        # Include subcategory topics
        subcategories = category.subcategories.filter(is_active=True)
        for subcat in subcategories:
            topics = topics | Topic.objects.filter(category=subcat, status='published')

        return render(request, self.template_name, {
            'category': category,
            'topics': topics.distinct().order_by('order', 'title'),
            'subcategories': subcategories,
        })


class TopicDetailView(View):
    """Topic detail page before starting"""
    template_name = 'quiz/topics/detail.html'

    def get(self, request, slug):
        topic = get_object_or_404(Topic, slug=slug, status='published')
        cards = topic.cards.all().order_by('order')

        user_progress = None
        if request.user.is_authenticated:
            user_progress = TopicProgress.objects.filter(
                user=request.user,
                topic=topic
            ).first()

        return render(request, self.template_name, {
            'topic': topic,
            'cards': cards,
            'user_progress': user_progress,
        })


class TopicCardView(LoginRequiredMixin, View):
    """View/swipe through topic cards"""
    template_name = 'quiz/topics/card.html'

    def get(self, request, slug, card_num):
        topic = get_object_or_404(Topic, slug=slug, status='published')
        cards = list(topic.cards.all().order_by('order'))

        if not cards:
            messages.error(request, 'This topic has no cards yet.')
            return redirect('topic_detail', slug=slug)

        # Validate card_num (1-indexed for URL)
        card_index = card_num - 1
        if card_index < 0 or card_index >= len(cards):
            return redirect('topic_card', slug=slug, card_num=1)

        card = cards[card_index]

        # Get or create progress (only on first card view, check subscription)
        progress, created = TopicProgress.objects.get_or_create(
            user=request.user,
            topic=topic,
            defaults={'current_card_index': card_index}
        )

        # Check subscription for new topics
        if created:
            get_or_create_free_subscription(request.user)
            can_access, message, subscription = check_feature_access(request.user, 'topics_view')
            if not can_access:
                progress.delete()
                messages.warning(request, message)
                return redirect('subscription')
            use_feature(request.user, 'topics_view')

        # Update progress
        if card_index > progress.current_card_index:
            progress.current_card_index = card_index
            progress.save()

        return render(request, self.template_name, {
            'topic': topic,
            'card': card,
            'card_num': card_num,
            'total_cards': len(cards),
            'progress': progress,
            'prev_card': card_num - 1 if card_num > 1 else None,
            'next_card': card_num + 1 if card_num < len(cards) else None,
        })


class TopicCompleteView(LoginRequiredMixin, View):
    """Mark topic as completed"""
    template_name = 'quiz/topics/complete.html'

    def get(self, request, slug):
        topic = get_object_or_404(Topic, slug=slug, status='published')

        progress = get_object_or_404(TopicProgress, user=request.user, topic=topic)

        # Mark as completed if not already
        if not progress.is_completed:
            progress.is_completed = True
            progress.completed_at = timezone.now()
            progress.save()

        # Get similar topics from same category (excluding current)
        similar_topics = Topic.objects.filter(
            category=topic.category,
            status='published'
        ).exclude(id=topic.id).order_by('?')[:3]

        # If not enough from same category, fill with featured topics
        if similar_topics.count() < 3:
            additional_count = 3 - similar_topics.count()
            additional_topics = Topic.objects.filter(
                status='published',
                is_featured=True
            ).exclude(
                id=topic.id
            ).exclude(
                id__in=similar_topics.values_list('id', flat=True)
            ).order_by('?')[:additional_count]
            similar_topics = list(similar_topics) + list(additional_topics)

        return render(request, self.template_name, {
            'topic': topic,
            'progress': progress,
            'similar_topics': similar_topics,
        })


class TopicMiniQuizView(LoginRequiredMixin, View):
    """Start mini-quiz for a topic"""

    def get(self, request, slug):
        topic = get_object_or_404(Topic, slug=slug, status='published')

        if not topic.mini_quiz:
            messages.info(request, 'This topic does not have a mini-quiz.')
            return redirect('topic_complete', slug=slug)

        # Redirect to quiz start
        return redirect('quiz_start', slug=topic.mini_quiz.slug)


class TopicProgressView(LoginRequiredMixin, View):
    """User's topic learning history"""
    template_name = 'quiz/topics/my-progress.html'

    def get(self, request):
        progress_list = TopicProgress.objects.filter(
            user=request.user
        ).select_related('topic', 'topic__category').order_by('-updated_at')

        completed = progress_list.filter(is_completed=True)
        in_progress = progress_list.filter(is_completed=False)

        return render(request, self.template_name, {
            'completed': completed,
            'in_progress': in_progress,
        })


# =============================================================================
# Topic Instagram Carousel Export Views
# =============================================================================

class TopicExportView(LoginRequiredMixin, View):
    """Export topic cards as Instagram carousel images"""
    template_name = 'quiz/topics/export.html'

    def get(self, request, slug):
        # Allow export for: published topics OR user's own approved/draft topics
        topic = get_object_or_404(Topic, slug=slug)

        # Check access: must be published OR owned by user with approved/draft status
        if topic.status != 'published':
            if topic.created_by != request.user:
                messages.error(request, 'You can only export your own topics or published topics.')
                return redirect('topics_home')
            if topic.status not in ['draft', 'approved', 'pending']:
                messages.error(request, 'This topic cannot be exported.')
                return redirect('user_topic_list')

        cards = topic.cards.order_by('order')

        if cards.count() < 1:
            messages.error(request, 'This topic has no cards to export.')
            return redirect('topic_detail', slug=slug)

        # Check Instagram connection
        instagram_connected = False
        if hasattr(request.user, 'instagram_account'):
            instagram_connected = request.user.instagram_account.is_connected

        # Get subscription for feature checks
        subscription = get_user_subscription(request.user)

        # Check if user has custom handle name feature
        can_custom_handle = False
        if subscription and subscription.plan.has_feature('custom_handle_name_in_video_export'):
            can_custom_handle = True
        elif request.user.is_staff:
            can_custom_handle = True

        # Check premium templates access
        has_premium_templates = (
            (subscription and subscription.plan.has_feature('premium_video_templates'))
            or request.user.is_staff
        )

        # Get video templates for styling
        templates = VideoTemplate.objects.filter(is_active=True).order_by('sort_order')
        templates_data = []
        for t in templates:
            templates_data.append({
                'id': t.id,
                'name': t.name,
                'is_premium': t.is_premium,
                'can_use': not t.is_premium or has_premium_templates,
                'preview_url': t.preview_url if hasattr(t, 'preview_url') else None,
            })

        # Get recent exports for this topic
        recent_exports = TopicCarouselExport.objects.filter(
            user=request.user,
            topic=topic
        ).order_by('-created_at')[:5]

        return render(request, self.template_name, {
            'topic': topic,
            'cards': cards,
            'instagram_connected': instagram_connected,
            'templates': templates,
            'templates_data': templates_data,
            'recent_exports': recent_exports,
            'can_custom_handle': can_custom_handle,
            'has_premium_templates': has_premium_templates,
        })

    def post(self, request, slug):
        """Start carousel image generation"""
        topic = get_object_or_404(Topic, slug=slug)

        # Check access: must be published OR owned by user
        if topic.status != 'published':
            if topic.created_by != request.user:
                return JsonResponse({'error': 'You can only export your own topics.'}, status=403)
            if topic.status not in ['draft', 'approved', 'pending']:
                return JsonResponse({'error': 'This topic cannot be exported.'}, status=403)

        cards = topic.cards.order_by('order')

        if cards.count() < 1:
            return JsonResponse({'error': 'No cards to export.'}, status=400)

        # Check subscription for carousel export
        get_or_create_free_subscription(request.user)
        subscription = get_user_subscription(request.user)
        can_access, message, _ = check_feature_access(request.user, 'carousel_export')
        if not can_access:
            return JsonResponse({'error': message}, status=403)

        # Use the feature (increment usage)
        use_feature(request.user, 'carousel_export')

        # Check custom handle feature
        can_custom_handle = False
        if subscription and subscription.plan.has_feature('custom_handle_name_in_video_export'):
            can_custom_handle = True
        elif request.user.is_staff:
            can_custom_handle = True

        # Check premium templates access
        has_premium_templates = (
            (subscription and subscription.plan.has_feature('premium_video_templates'))
            or request.user.is_staff
        )

        # Get template
        template_id = request.POST.get('template_id')
        template = None
        if template_id:
            template = VideoTemplate.objects.filter(id=template_id, is_active=True).first()
            # Check if user has access to premium template
            if template and template.is_premium and not has_premium_templates:
                return JsonResponse({
                    'error': 'Premium templates require a Pro or Creator subscription.'
                }, status=403)

        # Get handle name (only if user has the feature)
        handle_name = request.POST.get('handle_name', '@maedix-q').strip()
        if not handle_name.startswith('@'):
            handle_name = '@' + handle_name
        # Reset to default if user doesn't have custom handle feature
        if not can_custom_handle and handle_name != '@maedix-q':
            handle_name = '@maedix-q'

        # Generate unique task ID
        task_id = str(uuid.uuid4())

        # Store initial progress
        cache.set(f'carousel_progress_{task_id}', {
            'percent': 0,
            'message': 'Starting image generation...',
            'status': 'processing'
        }, timeout=600)

        # Start background generation
        thread = threading.Thread(
            target=self._generate_carousel_images,
            args=(task_id, topic.id, template.id if template else None,
                  handle_name, request.user.id)
        )
        thread.start()

        return JsonResponse({
            'task_id': task_id,
            'message': 'Carousel generation started'
        })

    def _generate_carousel_images(self, task_id, topic_id, template_id, handle_name, user_id):
        """Background task to generate carousel images"""
        from io import BytesIO
        from .topic_image_generator import TopicCardImageGenerator
        from core.s3_utils import upload_to_s3

        try:
            topic = Topic.objects.get(id=topic_id)
            cards = list(topic.cards.order_by('order'))

            # Load template config
            template_config = None
            if template_id:
                template = VideoTemplate.objects.filter(id=template_id).first()
                if template and template.config:
                    template_config = template.config

            # Update progress
            cache.set(f'carousel_progress_{task_id}', {
                'percent': 10,
                'message': 'Initializing image generator...',
                'status': 'processing'
            }, timeout=600)

            # Initialize generator
            generator = TopicCardImageGenerator(
                handle_name=handle_name,
                template_config=template_config
            )

            # Generate images
            cache.set(f'carousel_progress_{task_id}', {
                'percent': 20,
                'message': 'Generating carousel images...',
                'status': 'processing'
            }, timeout=600)

            images = generator.generate_carousel_images(topic, cards)

            # Upload images to S3
            cache.set(f'carousel_progress_{task_id}', {
                'percent': 60,
                'message': 'Uploading images to S3...',
                'status': 'processing'
            }, timeout=600)

            uploaded_images = []
            for i, pil_image in enumerate(images):
                # Convert PIL Image to bytes
                img_buffer = BytesIO()
                pil_image.save(img_buffer, format='PNG', quality=95)
                img_bytes = img_buffer.getvalue()

                s3_key = f"topic-carousels/{topic.slug}/{task_id}/card_{i+1}.png"
                s3_url, _, error = upload_to_s3(
                    img_bytes,
                    s3_key,
                    content_type='image/png'
                )
                if error:
                    raise Exception(f"Failed to upload image {i+1}: {error}")

                uploaded_images.append({
                    's3_url': s3_url,
                    's3_key': s3_key
                })

                # Update progress
                progress_pct = 60 + int((i + 1) / len(images) * 30)
                cache.set(f'carousel_progress_{task_id}', {
                    'percent': progress_pct,
                    'message': f'Uploaded image {i+1} of {len(images)}...',
                    'status': 'processing'
                }, timeout=600)

            # Save export record
            export = TopicCarouselExport.objects.create(
                user_id=user_id,
                topic=topic,
                images=uploaded_images,
                cards_count=len(cards)
            )

            # Store completed result
            cache.set(f'carousel_progress_{task_id}', {
                'percent': 100,
                'message': 'Carousel images ready!',
                'status': 'completed',
                'export_id': export.id,
                'images': uploaded_images
            }, timeout=1800)

        except Exception as e:
            logging.error(f"Carousel generation error: {e}")
            cache.set(f'carousel_progress_{task_id}', {
                'percent': 0,
                'message': f'Error: {str(e)}',
                'status': 'error'
            }, timeout=600)


class TopicExportProgressView(LoginRequiredMixin, View):
    """Check progress of carousel image generation"""

    def get(self, request, task_id):
        progress = cache.get(f'carousel_progress_{task_id}')
        if not progress:
            return JsonResponse({
                'percent': 0,
                'message': 'Task not found or expired.',
                'status': 'error'
            })
        return JsonResponse(progress)


class TopicPostInstagramView(LoginRequiredMixin, View):
    """Post topic carousel to Instagram"""
    template_name = 'quiz/topics/post-instagram.html'

    def get(self, request, slug):
        topic = get_object_or_404(Topic, slug=slug, status='published')
        export_id = request.GET.get('export_id')

        if not export_id:
            messages.error(request, 'No export selected.')
            return redirect('topic_export', slug=slug)

        export = get_object_or_404(
            TopicCarouselExport,
            id=export_id,
            user=request.user,
            topic=topic
        )

        # Check Instagram connection
        if not hasattr(request.user, 'instagram_account'):
            messages.error(request, 'Please connect your Instagram account first.')
            return redirect('instagram_connect')

        if not request.user.instagram_account.is_connected:
            messages.error(request, 'Your Instagram token has expired. Please reconnect.')
            return redirect('instagram_connect')

        return render(request, self.template_name, {
            'topic': topic,
            'export': export,
            'instagram_username': request.user.instagram_account.username,
        })

    def post(self, request, slug):
        """Post carousel to Instagram"""
        import requests as http_requests

        topic = get_object_or_404(Topic, slug=slug, status='published')
        export_id = request.POST.get('export_id')
        caption = request.POST.get('caption', '')

        export = get_object_or_404(
            TopicCarouselExport,
            id=export_id,
            user=request.user,
            topic=topic
        )

        # Check Instagram connection
        if not hasattr(request.user, 'instagram_account'):
            return JsonResponse({'error': 'Instagram not connected.'}, status=400)

        ig_account = request.user.instagram_account
        if not ig_account.is_connected:
            return JsonResponse({'error': 'Instagram token expired.'}, status=400)

        access_token = ig_account.access_token
        ig_user_id = ig_account.instagram_user_id

        try:
            # Step 1: Create individual image containers
            children_ids = []
            for img_data in export.images:
                container_response = http_requests.post(
                    f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                    data={
                        "image_url": img_data['s3_url'],
                        "is_carousel_item": "true",
                        "access_token": access_token,
                    },
                    timeout=30,
                )
                container_data = container_response.json()

                if "id" not in container_data:
                    error_msg = container_data.get("error", {}).get(
                        "message", "Failed to create image container"
                    )
                    return JsonResponse({'error': f'Instagram error: {error_msg}'}, status=400)

                children_ids.append(container_data["id"])

            # Step 2: Create carousel container
            carousel_response = http_requests.post(
                f"https://graph.instagram.com/v21.0/{ig_user_id}/media",
                data={
                    "media_type": "CAROUSEL",
                    "children": ",".join(children_ids),
                    "caption": caption,
                    "access_token": access_token,
                },
                timeout=30,
            )
            carousel_data = carousel_response.json()

            if "id" not in carousel_data:
                error_msg = carousel_data.get("error", {}).get(
                    "message", "Failed to create carousel"
                )
                return JsonResponse({'error': f'Instagram error: {error_msg}'}, status=400)

            carousel_id = carousel_data["id"]

            # Step 3: Wait for processing
            for _ in range(30):
                status_response = http_requests.get(
                    f"https://graph.instagram.com/v21.0/{carousel_id}",
                    params={
                        "fields": "status_code,status",
                        "access_token": access_token,
                    },
                    timeout=10,
                )
                status_data = status_response.json()
                status_code = status_data.get("status_code")

                if status_code == "FINISHED":
                    break
                elif status_code == "ERROR":
                    return JsonResponse({
                        'error': f'Processing failed: {status_data.get("status", "Unknown error")}'
                    }, status=400)
                else:
                    time.sleep(5)
            else:
                return JsonResponse({'error': 'Processing timeout.'}, status=400)

            # Step 4: Publish carousel
            publish_response = http_requests.post(
                f"https://graph.instagram.com/v21.0/{ig_user_id}/media_publish",
                data={
                    "creation_id": carousel_id,
                    "access_token": access_token,
                },
                timeout=60,
            )
            publish_data = publish_response.json()

            if "id" not in publish_data:
                error_msg = publish_data.get("error", {}).get(
                    "message", "Failed to publish"
                )
                return JsonResponse({'error': f'Instagram error: {error_msg}'}, status=400)

            return JsonResponse({
                'success': True,
                'message': 'Carousel posted to Instagram successfully!'
            })

        except http_requests.RequestException as e:
            return JsonResponse({'error': f'Network error: {str(e)}'}, status=500)
        except Exception as e:
            return JsonResponse({'error': f'Error: {str(e)}'}, status=500)
