import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.utils import timezone
from django.contrib import messages
from django.db.models import Count, Sum, Q
from django.urls import reverse
from .models import Category, WordBank, GameSession, PlayerStats, Leaderboard

logger = logging.getLogger(__name__)


class GamesHomeView(View):
    """Games hub page"""
    template_name = 'games/home.html'

    def get(self, request):
        context = {
            'games': [
                {
                    'name': 'Code Word',
                    'slug': 'codeword',
                    'description': 'Guess the 5-letter tech term in 6 tries',
                    'icon': 'bi-puzzle',
                    'color': '#10b981',
                },
            ]
        }
        return render(request, self.template_name, context)


class CodeWordHomeView(View):
    """Category selection page for Code Word"""
    template_name = 'games/codeword/home.html'

    def get(self, request):
        # Get active categories with word counts
        categories = Category.objects.filter(is_active=True).annotate(
            word_count=Count('words', filter=Q(words__is_active=True))
        ).order_by('order', 'name')

        categories_with_counts = []
        for cat in categories:
            categories_with_counts.append({
                'code': cat.slug,
                'name': cat.name,
                'count': cat.word_count,
                'icon': cat.icon,
                'color': cat.color,
            })

        # Get total word count
        total_words = WordBank.objects.filter(is_active=True).count()

        # Get user stats if logged in
        player_stats = None
        if request.user.is_authenticated:
            player_stats, _ = PlayerStats.objects.get_or_create(user=request.user)

        context = {
            'categories': categories_with_counts,
            'total_words': total_words,
            'player_stats': player_stats,
        }
        return render(request, self.template_name, context)


class CodeWordPlayView(LoginRequiredMixin, View):
    """Main Code Word game page"""
    template_name = 'games/codeword/play.html'
    login_url = '/users/login/'

    def get(self, request):
        category_slug = request.GET.get('category', 'all')

        # Check for active game
        active_query = GameSession.objects.filter(
            user=request.user,
            is_completed=False
        )
        if category_slug != 'all':
            active_query = active_query.filter(category__slug=category_slug)

        active_session = active_query.first()

        if active_session:
            # Resume existing game
            session = active_session
        else:
            # Start new game
            # Get words the user has already played recently to avoid repeats
            recent_word_ids = GameSession.objects.filter(
                user=request.user
            ).order_by('-started_at')[:50].values_list('word_id', flat=True)

            word = WordBank.get_random_word(
                category_slug=category_slug if category_slug != 'all' else None,
                exclude_ids=list(recent_word_ids)
            )

            if not word:
                categories = Category.objects.filter(is_active=True).order_by('order', 'name')
                return render(request, 'games/codeword/no-word.html', {
                    'category': category_slug,
                    'categories': categories,
                })

            session = GameSession.objects.create(
                user=request.user,
                word=word,
                category=word.category,
            )

        # Get player stats
        player_stats, _ = PlayerStats.objects.get_or_create(user=request.user)

        # Get category name for display
        category_name = session.category.name if session.category else 'General'

        context = {
            'session': session,
            'player_stats': player_stats,
            'word_length': len(session.word.word),
            'max_attempts': 6,
            'category': session.category.slug if session.category else 'all',
            'category_name': category_name,
        }
        return render(request, self.template_name, context)


class CodeWordGuessView(LoginRequiredMixin, View):
    """Handle guess submission"""
    login_url = '/users/login/'

    def post(self, request):
        try:
            data = json.loads(request.body)
            guess = data.get('guess', '').strip().upper()
            session_id = data.get('session_id')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid request'}, status=400)

        if not guess or len(guess) != 5:
            return JsonResponse({'error': 'Please enter a 5-letter word'}, status=400)

        if not session_id:
            return JsonResponse({'error': 'No active game'}, status=400)

        # Get the game session
        try:
            session = GameSession.objects.get(
                id=session_id,
                user=request.user
            )
        except GameSession.DoesNotExist:
            return JsonResponse({'error': 'Game not found'}, status=404)

        if session.is_completed:
            return JsonResponse({
                'error': 'Game already completed',
                'completed': True,
                'won': session.is_won
            }, status=400)

        # Process guess
        result, error = session.add_guess(guess)

        if error:
            return JsonResponse({'error': error}, status=400)

        # Update player stats if game completed
        if session.is_completed:
            player_stats, _ = PlayerStats.objects.get_or_create(user=request.user)
            category_slug = session.category.slug if session.category else 'general'
            player_stats.record_game(
                won=session.is_won,
                attempts=session.attempts_used,
                category=category_slug,
                xp_earned=session.xp_earned
            )

            # XP is already tracked in PlayerStats via record_game()

        response_data = {
            'guess': guess,
            'result': result,
            'attempt_number': session.attempts_used,
            'completed': session.is_completed,
            'won': session.is_won,
            'xp_earned': session.xp_earned if session.is_completed else 0,
        }

        if session.is_completed and not session.is_won:
            response_data['answer'] = session.word.word

        return JsonResponse(response_data)


class CodeWordResultsView(LoginRequiredMixin, View):
    """Show game results with share options"""
    template_name = 'games/codeword/results.html'
    login_url = '/users/login/'

    def get(self, request, session_id):
        session = get_object_or_404(
            GameSession,
            id=session_id,
            user=request.user
        )

        if not session.is_completed:
            return redirect('codeword_play')

        player_stats, _ = PlayerStats.objects.get_or_create(user=request.user)

        context = {
            'session': session,
            'player_stats': player_stats,
            'share_text': session.get_share_text(),
        }
        return render(request, self.template_name, context)


class CodeWordStatsView(LoginRequiredMixin, View):
    """User's Code Word statistics"""
    template_name = 'games/codeword/stats.html'
    login_url = '/users/login/'

    def get(self, request):
        player_stats, _ = PlayerStats.objects.get_or_create(user=request.user)

        # Get recent games
        recent_games = GameSession.objects.filter(
            user=request.user,
            is_completed=True
        ).select_related('word', 'category').order_by('-completed_at')[:10]

        # Get category breakdown from player stats
        categories = Category.objects.filter(is_active=True)
        category_breakdown = []
        for cat in categories:
            stats = player_stats.category_stats.get(cat.slug, {})
            if stats.get('played', 0) > 0:
                category_breakdown.append({
                    'code': cat.slug,
                    'name': cat.name,
                    'played': stats.get('played', 0),
                    'won': stats.get('won', 0),
                    'win_rate': round((stats.get('won', 0) / stats.get('played', 1)) * 100),
                })

        context = {
            'player_stats': player_stats,
            'recent_games': recent_games,
            'category_breakdown': category_breakdown,
        }
        return render(request, self.template_name, context)


class CodeWordLeaderboardView(View):
    """Code Word leaderboard"""
    template_name = 'games/codeword/leaderboard.html'

    def get(self, request):
        category_slug = request.GET.get('category', 'all')
        period = request.GET.get('period', 'all_time')

        # Get category object if not 'all'
        category_obj = None
        if category_slug != 'all':
            category_obj = Category.objects.filter(slug=category_slug).first()

        # Get leaderboard entries
        leaderboard_query = Leaderboard.objects.filter(period=period)
        if category_slug == 'all':
            leaderboard_query = leaderboard_query.filter(category__isnull=True)
        else:
            leaderboard_query = leaderboard_query.filter(category=category_obj)

        leaderboard = leaderboard_query.select_related('user').order_by('rank')[:50]

        # If leaderboard is empty, generate it from PlayerStats
        if not leaderboard.exists():
            leaderboard = self._generate_leaderboard(category_slug, category_obj, period)

        # Get current user's rank if logged in
        user_rank = None
        if request.user.is_authenticated:
            user_query = Leaderboard.objects.filter(user=request.user, period=period)
            if category_slug == 'all':
                user_query = user_query.filter(category__isnull=True)
            else:
                user_query = user_query.filter(category=category_obj)
            user_entry = user_query.first()
            if user_entry:
                user_rank = user_entry.rank

        # Build categories list for filter
        categories = Category.objects.filter(is_active=True).order_by('order', 'name')
        category_list = [{'slug': 'all', 'name': 'All Categories'}]
        for cat in categories:
            category_list.append({'slug': cat.slug, 'name': cat.name})

        context = {
            'leaderboard': leaderboard,
            'user_rank': user_rank,
            'current_category': category_slug,
            'current_period': period,
            'categories': category_list,
            'periods': [
                ('all_time', 'All Time'),
                ('monthly', 'This Month'),
                ('weekly', 'This Week'),
            ],
        }
        return render(request, self.template_name, context)

    def _generate_leaderboard(self, category_slug, category_obj, period):
        """Generate leaderboard from PlayerStats"""
        # Get all players with games
        players = PlayerStats.objects.filter(total_games__gte=1)

        # Build leaderboard entries
        entries = []
        for stats in players:
            if category_slug != 'all':
                cat_stats = stats.category_stats.get(category_slug, {})
                games_played = cat_stats.get('played', 0)
                games_won = cat_stats.get('won', 0)
            else:
                games_played = stats.total_games
                games_won = stats.total_wins

            if games_played > 0:
                entries.append({
                    'user': stats.user,
                    'games_played': games_played,
                    'games_won': games_won,
                    'total_xp': stats.total_xp,
                    'win_rate': round((games_won / games_played) * 100, 1),
                })

        # Sort by XP
        entries.sort(key=lambda x: x['total_xp'], reverse=True)

        # Create leaderboard entries
        leaderboard_entries = []
        for i, entry in enumerate(entries[:50], 1):
            lb_entry, _ = Leaderboard.objects.update_or_create(
                user=entry['user'],
                category=category_obj,  # None for 'all'
                period=period,
                defaults={
                    'rank': i,
                    'games_won': entry['games_won'],
                    'games_played': entry['games_played'],
                    'total_xp': entry['total_xp'],
                    'win_rate': entry['win_rate'],
                }
            )
            leaderboard_entries.append(lb_entry)

        return leaderboard_entries


class CodeWordNewGameView(LoginRequiredMixin, View):
    """Start a new game (abandon current if any)"""
    login_url = '/users/login/'

    def post(self, request):
        category = request.POST.get('category', 'all')

        # Mark any incomplete games as abandoned
        GameSession.objects.filter(
            user=request.user,
            is_completed=False
        ).update(is_completed=True)

        # Redirect to play with selected category
        return redirect(f'/games/codeword/play/?category={category}')


# ============================================
# Staff Views for Code Word Management
# ============================================

class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to require staff access"""
    login_url = '/users/login/'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class StaffCodeWordDashboardView(StaffRequiredMixin, View):
    """Staff dashboard for Code Word game management"""
    template_name = 'staff/codeword/dashboard.html'

    def get(self, request):
        stats = {
            'total_categories': Category.objects.count(),
            'active_categories': Category.objects.filter(is_active=True).count(),
            'total_words': WordBank.objects.count(),
            'active_words': WordBank.objects.filter(is_active=True).count(),
            'total_games': GameSession.objects.filter(is_completed=True).count(),
            'total_players': PlayerStats.objects.count(),
        }

        # Get categories with word counts
        categories = Category.objects.annotate(
            word_count=Count('words', filter=Q(words__is_active=True))
        ).order_by('order', 'name')

        # Recent games
        recent_games = GameSession.objects.filter(
            is_completed=True
        ).select_related('user', 'word', 'category').order_by('-completed_at')[:10]

        context = {
            'stats': stats,
            'categories': categories,
            'recent_games': recent_games,
        }
        return render(request, self.template_name, context)


class StaffCodeWordCategoryListView(StaffRequiredMixin, View):
    """List all Code Word categories"""
    template_name = 'staff/codeword/category-list.html'

    def get(self, request):
        categories = Category.objects.annotate(
            word_count=Count('words', filter=Q(words__is_active=True))
        ).order_by('order', 'name')

        context = {
            'categories': categories,
        }
        return render(request, self.template_name, context)


class StaffCodeWordCategoryCreateView(StaffRequiredMixin, View):
    """Create a new Code Word category"""
    template_name = 'staff/codeword/category-form.html'

    def get(self, request):
        context = {
            'action': 'Create',
            'category': None,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        name = request.POST.get('name', '').strip()
        slug = request.POST.get('slug', '').strip().lower()
        icon = request.POST.get('icon', 'bi-puzzle').strip()
        color = request.POST.get('color', 'text-primary').strip()
        description = request.POST.get('description', '').strip()
        order = request.POST.get('order', 0)
        is_active = request.POST.get('is_active') == 'on'

        if not name or not slug:
            messages.error(request, 'Name and slug are required.')
            return redirect('staff_codeword_category_create')

        if Category.objects.filter(slug=slug).exists():
            messages.error(request, 'A category with this slug already exists.')
            return redirect('staff_codeword_category_create')

        Category.objects.create(
            name=name,
            slug=slug,
            icon=icon,
            color=color,
            description=description,
            order=int(order) if order else 0,
            is_active=is_active,
        )
        messages.success(request, f'Category "{name}" created successfully.')
        return redirect('staff_codeword_category_list')


class StaffCodeWordCategoryEditView(StaffRequiredMixin, View):
    """Edit a Code Word category"""
    template_name = 'staff/codeword/category-form.html'

    def get(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        context = {
            'action': 'Edit',
            'category': category,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)

        category.name = request.POST.get('name', '').strip()
        category.slug = request.POST.get('slug', '').strip().lower()
        category.icon = request.POST.get('icon', 'bi-puzzle').strip()
        category.color = request.POST.get('color', 'text-primary').strip()
        category.description = request.POST.get('description', '').strip()
        category.order = int(request.POST.get('order', 0) or 0)
        category.is_active = request.POST.get('is_active') == 'on'

        # Check for duplicate slug
        if Category.objects.filter(slug=category.slug).exclude(pk=pk).exists():
            messages.error(request, 'A category with this slug already exists.')
            return redirect('staff_codeword_category_edit', pk=pk)

        category.save()
        messages.success(request, f'Category "{category.name}" updated successfully.')
        return redirect('staff_codeword_category_list')


class StaffCodeWordCategoryDeleteView(StaffRequiredMixin, View):
    """Delete a Code Word category"""

    def post(self, request, pk):
        category = get_object_or_404(Category, pk=pk)
        name = category.name
        category.delete()
        messages.success(request, f'Category "{name}" deleted successfully.')
        return redirect('staff_codeword_category_list')


class StaffCodeWordWordListView(StaffRequiredMixin, View):
    """List all Code Word words"""
    template_name = 'staff/codeword/word-list.html'

    def get(self, request):
        category_filter = request.GET.get('category', '')
        difficulty_filter = request.GET.get('difficulty', '')
        search = request.GET.get('search', '').strip()

        words = WordBank.objects.select_related('category').order_by('word')

        if category_filter:
            words = words.filter(category__slug=category_filter)
        if difficulty_filter:
            words = words.filter(difficulty=difficulty_filter)
        if search:
            words = words.filter(word__icontains=search)

        categories = Category.objects.filter(is_active=True).order_by('order', 'name')

        context = {
            'words': words,
            'categories': categories,
            'current_category': category_filter,
            'current_difficulty': difficulty_filter,
            'search': search,
        }
        return render(request, self.template_name, context)


class StaffCodeWordWordCreateView(StaffRequiredMixin, View):
    """Create a new Code Word word"""
    template_name = 'staff/codeword/word-form.html'

    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by('order', 'name')
        context = {
            'action': 'Create',
            'word': None,
            'categories': categories,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        word = request.POST.get('word', '').strip().upper()
        category_id = request.POST.get('category')
        difficulty = request.POST.get('difficulty', 'medium')
        hint = request.POST.get('hint', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not word:
            messages.error(request, 'Word is required.')
            return redirect('staff_codeword_word_create')

        if len(word) != 5:
            messages.error(request, 'Word must be exactly 5 letters.')
            return redirect('staff_codeword_word_create')

        if WordBank.objects.filter(word=word).exists():
            messages.error(request, 'This word already exists.')
            return redirect('staff_codeword_word_create')

        category = None
        if category_id:
            category = Category.objects.filter(pk=category_id).first()

        WordBank.objects.create(
            word=word,
            category=category,
            difficulty=difficulty,
            hint=hint,
            is_active=is_active,
        )
        messages.success(request, f'Word "{word}" created successfully.')
        return redirect('staff_codeword_word_list')


class StaffCodeWordWordEditView(StaffRequiredMixin, View):
    """Edit a Code Word word"""
    template_name = 'staff/codeword/word-form.html'

    def get(self, request, pk):
        word = get_object_or_404(WordBank, pk=pk)
        categories = Category.objects.filter(is_active=True).order_by('order', 'name')
        context = {
            'action': 'Edit',
            'word': word,
            'categories': categories,
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        word_obj = get_object_or_404(WordBank, pk=pk)

        word = request.POST.get('word', '').strip().upper()
        category_id = request.POST.get('category')
        difficulty = request.POST.get('difficulty', 'medium')
        hint = request.POST.get('hint', '').strip()
        is_active = request.POST.get('is_active') == 'on'

        if not word:
            messages.error(request, 'Word is required.')
            return redirect('staff_codeword_word_edit', pk=pk)

        if len(word) != 5:
            messages.error(request, 'Word must be exactly 5 letters.')
            return redirect('staff_codeword_word_edit', pk=pk)

        # Check for duplicate
        if WordBank.objects.filter(word=word).exclude(pk=pk).exists():
            messages.error(request, 'This word already exists.')
            return redirect('staff_codeword_word_edit', pk=pk)

        category = None
        if category_id:
            category = Category.objects.filter(pk=category_id).first()

        word_obj.word = word
        word_obj.category = category
        word_obj.difficulty = difficulty
        word_obj.hint = hint
        word_obj.is_active = is_active
        word_obj.save()

        messages.success(request, f'Word "{word}" updated successfully.')
        return redirect('staff_codeword_word_list')


class StaffCodeWordWordDeleteView(StaffRequiredMixin, View):
    """Delete a Code Word word"""

    def post(self, request, pk):
        word = get_object_or_404(WordBank, pk=pk)
        word_text = word.word
        word.delete()
        messages.success(request, f'Word "{word_text}" deleted successfully.')
        return redirect('staff_codeword_word_list')


class StaffCodeWordImportView(StaffRequiredMixin, View):
    """Import words from JSON"""
    template_name = 'staff/codeword/import.html'

    def get(self, request):
        categories = Category.objects.filter(is_active=True).order_by('order', 'name')
        context = {
            'categories': categories,
        }
        return render(request, self.template_name, context)

    def post(self, request):
        json_data = request.POST.get('json_data', '').strip()
        default_category_id = request.POST.get('default_category', '')

        if not json_data:
            messages.error(request, 'Please provide JSON data.')
            return redirect('staff_codeword_import')

        try:
            words_data = json.loads(json_data)
        except json.JSONDecodeError as e:
            messages.error(request, f'Invalid JSON: {e}')
            return redirect('staff_codeword_import')

        if not isinstance(words_data, list):
            messages.error(request, 'JSON must be an array of words.')
            return redirect('staff_codeword_import')

        # Get default category if specified
        default_category = None
        if default_category_id:
            default_category = Category.objects.filter(pk=default_category_id).first()

        # Build category map for lookups
        category_map = {cat.slug: cat for cat in Category.objects.all()}

        added = 0
        skipped = 0
        errors = []

        for item in words_data:
            # Handle both string format and object format
            if isinstance(item, str):
                word = item.upper().strip()
                category = default_category
                difficulty = 'medium'
                hint = ''
            elif isinstance(item, dict):
                word = item.get('word', '').upper().strip()
                # Get category by slug or use default
                cat_slug = item.get('category', '')
                category = category_map.get(cat_slug, default_category)
                difficulty = item.get('difficulty', 'medium')
                hint = item.get('hint', '')
            else:
                errors.append(f'Invalid item format: {item}')
                continue

            # Validate word
            if not word:
                errors.append('Empty word found')
                skipped += 1
                continue

            if len(word) != 5:
                errors.append(f'"{word}" is not 5 letters')
                skipped += 1
                continue

            if not word.isalpha():
                errors.append(f'"{word}" contains non-letter characters')
                skipped += 1
                continue

            # Check for duplicates
            if WordBank.objects.filter(word=word).exists():
                skipped += 1
                continue

            # Create word
            WordBank.objects.create(
                word=word,
                category=category,
                difficulty=difficulty,
                hint=hint,
                is_active=True,
            )
            added += 1

        if added > 0:
            messages.success(request, f'Successfully imported {added} words.')
        if skipped > 0:
            messages.warning(request, f'Skipped {skipped} words (duplicates or invalid).')
        if errors and len(errors) <= 5:
            for error in errors:
                messages.error(request, error)
        elif errors:
            messages.error(request, f'{len(errors)} errors occurred during import.')

        return redirect('staff_codeword_word_list')
