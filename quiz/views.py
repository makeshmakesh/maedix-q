import os
import json
import tempfile
import uuid
import threading
from threading import Semaphore
from django.utils.text import slugify
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.utils import timezone
from django.http import JsonResponse, FileResponse, HttpResponse, Http404
from django.db.models import Count, Avg
from django.core.cache import cache
from .models import Category, Quiz, Question, Option, QuizAttempt, QuestionAnswer, Leaderboard
from .forms import CategoryForm, QuizForm, QuestionForm, OptionFormSet
from core.models import Configuration
from core.subscription_utils import check_feature_access, use_feature, get_or_create_free_subscription

# Limit concurrent video generations (adjust based on server capacity)
VIDEO_GENERATION_SEMAPHORE = Semaphore(1)  # Max 2 concurrent video generations


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
        quiz = get_object_or_404(Quiz, slug=slug, is_published=True)
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


class LeaderboardView(View):
    """Overall leaderboard"""
    template_name = 'quiz/leaderboard.html'

    def get(self, request):
        from users.models import UserStats

        sort_by = request.GET.get('sort', 'xp')

        # Get top users by XP or quizzes passed
        if sort_by == 'quizzes':
            leaderboard = UserStats.objects.select_related('user').order_by(
                '-total_quizzes_passed', '-xp_points'
            )[:100]
        elif sort_by == 'streak':
            leaderboard = UserStats.objects.select_related('user').order_by(
                '-longest_streak', '-xp_points'
            )[:100]
        else:  # default: xp
            leaderboard = UserStats.objects.select_related('user').order_by(
                '-xp_points', '-total_quizzes_passed'
            )[:100]

        # Get current user's rank if authenticated
        user_rank = None
        user_stats = None
        if request.user.is_authenticated:
            user_stats = UserStats.objects.filter(user=request.user).first()
            if user_stats:
                if sort_by == 'quizzes':
                    user_rank = UserStats.objects.filter(
                        total_quizzes_passed__gt=user_stats.total_quizzes_passed
                    ).count() + 1
                elif sort_by == 'streak':
                    user_rank = UserStats.objects.filter(
                        longest_streak__gt=user_stats.longest_streak
                    ).count() + 1
                else:
                    user_rank = UserStats.objects.filter(
                        xp_points__gt=user_stats.xp_points
                    ).count() + 1

        return render(request, self.template_name, {
            'leaderboard': leaderboard,
            'sort_by': sort_by,
            'user_rank': user_rank,
            'user_stats': user_stats,
        })


class CategoryLeaderboardView(View):
    """Category-specific leaderboard"""
    template_name = 'quiz/category-leaderboard.html'

    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug, is_active=True)
        period = request.GET.get('period', 'all_time')

        leaderboard = Leaderboard.objects.filter(
            category=category,
            period=period
        ).select_related('user')[:100]

        return render(request, self.template_name, {
            'category': category,
            'leaderboard': leaderboard,
            'period': period,
        })


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

def _generate_video_task(task_id, question_data, output_path, quiz_slug, show_answer=True,
                         handle_name="@maedix-q", audio_url=None, audio_volume=0.3):
    """Background task to generate video with progress updates"""
    import shutil
    from .video_generator import generate_quiz_video

    def progress_callback(percent, message):
        cache.set(f'video_progress_{task_id}', {
            'percent': percent,
            'message': message,
            'status': 'processing'
        }, timeout=600)

    # Acquire semaphore to limit concurrent generations
    acquired = VIDEO_GENERATION_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        # Wait in queue
        progress_callback(0, "Waiting in queue...")
        VIDEO_GENERATION_SEMAPHORE.acquire(blocking=True)

    try:
        progress_callback(5, "Starting video generation...")
        generate_quiz_video(
            question_data, output_path, progress_callback,
            show_answer=show_answer, handle_name=handle_name,
            audio_url=audio_url, audio_volume=audio_volume
        )

        # Read video into memory and store in cache
        with open(output_path, 'rb') as f:
            video_content = f.read()

        # Clean up temp file
        temp_dir = os.path.dirname(output_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

        # Store completed video in cache (5 minute expiry)
        cache.set(f'video_file_{task_id}', {
            'content': video_content,
            'filename': f'{quiz_slug}_reel.mp4'
        }, timeout=300)

        cache.set(f'video_progress_{task_id}', {
            'percent': 100,
            'message': 'Video ready for download!',
            'status': 'completed'
        }, timeout=600)

    except Exception as e:
        # Clean up on error
        try:
            temp_dir = os.path.dirname(output_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

        cache.set(f'video_progress_{task_id}', {
            'percent': 0,
            'message': f'Error: {str(e)}',
            'status': 'error'
        }, timeout=600)

    finally:
        # Always release the semaphore
        VIDEO_GENERATION_SEMAPHORE.release()


class QuizVideoExportView(LoginRequiredMixin, View):
    """Export quiz as video for Instagram Reels"""
    template_name = 'quiz/video-export.html'

    def get(self, request, slug):
        # Allow published quizzes OR creator's own drafts
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")
        questions = quiz.questions.prefetch_related('options').order_by('order')

        if questions.count() < 1:
            messages.error(request, 'This quiz has no questions to export.')
            if quiz.created_by == request.user and not quiz.is_published:
                return redirect('user_quiz_questions', pk=quiz.pk)
            return redirect('quiz_detail', slug=slug)

        # Check subscription for video generation
        get_or_create_free_subscription(request.user)
        can_access, message, subscription = check_feature_access(request.user, 'video_gen')

        # Check if user has custom handle name feature
        can_custom_handle = False
        if subscription and subscription.plan.has_feature('custom_handle_name_in_video_export'):
            can_custom_handle = True
        elif request.user.is_staff:
            can_custom_handle = True

        return render(request, self.template_name, {
            'quiz': quiz,
            'questions': questions,
            'can_generate': can_access,
            'subscription_message': message if not can_access else None,
            'subscription': subscription,
            'can_custom_handle': can_custom_handle,
        })

    def post(self, request, slug):
        # Allow published quizzes OR creator's own drafts
        quiz = get_object_or_404(Quiz, slug=slug)
        if not quiz.is_published and quiz.created_by != request.user:
            raise Http404("Quiz not found")

        # Check subscription for video generation
        get_or_create_free_subscription(request.user)
        can_access, message, subscription = check_feature_access(request.user, 'video_gen')
        if not can_access:
            return JsonResponse({'error': message}, status=403)

        # Use the feature (increment usage)
        use_feature(request.user, 'video_gen')

        # Get selected question IDs (1-3 questions required)
        selected_ids = request.POST.getlist('questions')
        if len(selected_ids) < 1 or len(selected_ids) > 3:
            return JsonResponse({'error': 'Please select 1 to 3 questions.'}, status=400)

        selected_questions = Question.objects.filter(
            id__in=selected_ids,
            quiz=quiz
        ).prefetch_related('options')

        if not selected_questions.exists():
            return JsonResponse({'error': 'Invalid question selection.'}, status=400)

        # Get show_answer option (checkbox sends value only when checked)
        show_answer = request.POST.get('show_answer') == 'on'

        # Get handle name (only if user has the feature)
        handle_name = "@maedix-q"  # Default
        can_custom_handle = False
        if subscription and subscription.plan.has_feature('custom_handle_name_in_video_export'):
            can_custom_handle = True
        elif request.user.is_staff:
            can_custom_handle = True

        if can_custom_handle:
            custom_handle = request.POST.get('handle_name', '').strip()
            if custom_handle:
                # Ensure it starts with @
                if not custom_handle.startswith('@'):
                    custom_handle = '@' + custom_handle
                # Basic validation: max 30 chars, no spaces
                if len(custom_handle) <= 30 and ' ' not in custom_handle:
                    handle_name = custom_handle

        # Convert questions to dict format for background thread
        question_data = []
        for q in selected_questions:
            question_data.append({
                'text': q.text,
                'options': [
                    {'text': opt.text, 'is_correct': opt.is_correct}
                    for opt in q.options.all()
                ]
            })

        # Generate unique task ID
        task_id = str(uuid.uuid4())

        # Create temp directory and output path
        temp_dir = tempfile.mkdtemp()
        output_path = os.path.join(temp_dir, f'{quiz.slug}_reel.mp4')

        # Initialize progress
        cache.set(f'video_progress_{task_id}', {
            'percent': 0,
            'message': 'Initializing...',
            'status': 'processing'
        }, timeout=600)

        # Get audio settings from configuration
        audio_url = Configuration.get_value('video_background_music_url', '')
        audio_volume = float(Configuration.get_value('video_background_music_volume', '0.5'))

        # Start video generation in background thread
        thread = threading.Thread(
            target=_generate_video_task,
            args=(task_id, question_data, output_path, quiz.slug, show_answer, handle_name),
            kwargs={'audio_url': audio_url, 'audio_volume': audio_volume}
        )
        thread.daemon = True
        thread.start()

        return JsonResponse({'task_id': task_id})


class VideoProgressView(LoginRequiredMixin, View):
    """Check video generation progress"""

    def get(self, request, task_id):
        progress = cache.get(f'video_progress_{task_id}')
        if not progress:
            return JsonResponse({
                'percent': 0,
                'message': 'Task not found',
                'status': 'error'
            })
        return JsonResponse(progress)


class VideoDownloadView(LoginRequiredMixin, View):
    """Download completed video"""

    def get(self, request, task_id):
        video_data = cache.get(f'video_file_{task_id}')
        if not video_data:
            return JsonResponse({'error': 'Video not found or expired'}, status=404)

        # Clear from cache after download
        cache.delete(f'video_file_{task_id}')
        cache.delete(f'video_progress_{task_id}')

        response = HttpResponse(video_data['content'], content_type='video/mp4')
        response['Content-Disposition'] = f'attachment; filename="{video_data["filename"]}"'
        response['Content-Length'] = len(video_data['content'])

        return response


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
# Admin Approval Views
# =============================================================================

class StaffPendingApprovalsView(StaffRequiredMixin, View):
    """List quizzes pending approval"""
    template_name = 'staff/pending-approvals.html'

    def get(self, request):
        pending_quizzes = Quiz.objects.filter(status='pending').select_related('created_by', 'category').order_by('created_at')
        return render(request, self.template_name, {
            'pending_quizzes': pending_quizzes,
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
