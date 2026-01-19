import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone


class Category(models.Model):
    """Categories for Code Word game - manageable by staff"""
    name = models.CharField(max_length=50)
    slug = models.SlugField(max_length=50, unique=True)
    icon = models.CharField(max_length=50, default='bi-puzzle', help_text='Bootstrap icon class (e.g., bi-globe)')
    color = models.CharField(max_length=20, default='text-primary', help_text='CSS color class')
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name

    @classmethod
    def get_choices(cls):
        """Return category choices for forms"""
        return [(cat.slug, cat.name) for cat in cls.objects.filter(is_active=True)]


class WordBank(models.Model):
    """Bank of valid 5-letter tech/programming words"""
    word = models.CharField(max_length=10, unique=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='words'
    )
    difficulty = models.CharField(
        max_length=20,
        choices=[('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')],
        default='medium'
    )
    hint = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    times_played = models.IntegerField(default=0)
    times_solved = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['word']

    def __str__(self):
        cat_name = self.category.name if self.category else 'Uncategorized'
        return f"{self.word.upper()} ({cat_name})"

    def save(self, *args, **kwargs):
        self.word = self.word.upper()
        super().save(*args, **kwargs)

    @property
    def solve_rate(self):
        if self.times_played == 0:
            return 0
        return round((self.times_solved / self.times_played) * 100)

    @classmethod
    def get_random_word(cls, category_slug=None, exclude_ids=None):
        """Get a random word, optionally filtered by category slug"""
        queryset = cls.objects.filter(is_active=True)

        if category_slug and category_slug != 'all':
            queryset = queryset.filter(category__slug=category_slug)

        if exclude_ids:
            queryset = queryset.exclude(id__in=exclude_ids)

        return queryset.order_by('?').first()


class GameSession(models.Model):
    """A single game session - user playing one word"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True  # Allow anonymous play
    )
    word = models.ForeignKey(WordBank, on_delete=models.CASCADE)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='game_sessions'
    )
    guesses = models.JSONField(default=list)
    is_completed = models.BooleanField(default=False)
    is_won = models.BooleanField(default=False)
    attempts_used = models.IntegerField(default=0)
    xp_earned = models.IntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        user_str = self.user.email if self.user else 'Anonymous'
        return f"{user_str} - {self.word.word}"

    def add_guess(self, guess):
        """Add a guess and return the result"""
        guess = guess.upper()
        target = self.word.word.upper()

        if len(guess) != len(target):
            return None, "Invalid word length"

        if self.is_completed:
            return None, "Game already completed"

        result = self._check_guess(guess, target)

        self.guesses.append({
            'word': guess,
            'result': result,
            'attempt': self.attempts_used + 1
        })
        self.attempts_used += 1

        # Check if won
        if guess == target:
            self.is_won = True
            self.is_completed = True
            self.completed_at = timezone.now()
            self._calculate_xp()
            self._update_word_stats(won=True)
        elif self.attempts_used >= 6:
            self.is_completed = True
            self.completed_at = timezone.now()
            self._update_word_stats(won=False)

        self.save()
        return result, None

    def _check_guess(self, guess, target):
        """Check guess against target word"""
        result = ['absent'] * len(guess)
        target_chars = list(target)

        # First pass: mark correct positions
        for i, char in enumerate(guess):
            if char == target[i]:
                result[i] = 'correct'
                target_chars[i] = None

        # Second pass: mark present (wrong position)
        for i, char in enumerate(guess):
            if result[i] == 'absent' and char in target_chars:
                result[i] = 'present'
                target_chars[target_chars.index(char)] = None

        return result

    def _calculate_xp(self):
        """Calculate XP based on attempts used"""
        if self.is_won:
            xp_map = {1: 100, 2: 80, 3: 60, 4: 40, 5: 25, 6: 15}
            self.xp_earned = xp_map.get(self.attempts_used, 10)

    def _update_word_stats(self, won):
        """Update word play statistics"""
        self.word.times_played += 1
        if won:
            self.word.times_solved += 1
        self.word.save()

    def get_share_text(self):
        """Generate shareable result text"""
        emoji_map = {
            'correct': '🟩',
            'present': '🟨',
            'absent': '⬜'
        }

        cat_name = self.category.name if self.category else 'General'
        lines = [f"Code Word - {cat_name}"]
        lines.append(f"{'🎉' if self.is_won else '😢'} {self.attempts_used}/6")
        lines.append("")

        for guess in self.guesses:
            line = ''.join(emoji_map[r] for r in guess['result'])
            lines.append(line)

        lines.append("")
        lines.append("Play at maedix.com/games/codeword")

        return '\n'.join(lines)


class PlayerStats(models.Model):
    """Track user's overall game statistics"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    total_games = models.IntegerField(default=0)
    total_wins = models.IntegerField(default=0)
    total_xp = models.IntegerField(default=0)
    current_streak = models.IntegerField(default=0)
    longest_streak = models.IntegerField(default=0)
    last_played_at = models.DateTimeField(null=True, blank=True)
    guess_distribution = models.JSONField(default=dict)  # {"1": 5, "2": 10, ...}
    category_stats = models.JSONField(default=dict)  # {"web": {"played": 10, "won": 8}, ...}

    class Meta:
        verbose_name_plural = "Player stats"

    def __str__(self):
        return f"{self.user.email} - {self.total_wins}/{self.total_games} wins"

    @property
    def win_rate(self):
        if self.total_games == 0:
            return 0
        return round((self.total_wins / self.total_games) * 100)

    @property
    def average_attempts(self):
        if self.total_wins == 0:
            return 0
        total_attempts = sum(
            int(k) * v for k, v in self.guess_distribution.items()
        )
        return round(total_attempts / self.total_wins, 1)

    def record_game(self, won, attempts, category, xp_earned):
        """Record a completed game"""
        self.total_games += 1
        self.total_xp += xp_earned

        if won:
            self.total_wins += 1
            # Update guess distribution
            key = str(attempts)
            dist = self.guess_distribution or {}
            dist[key] = dist.get(key, 0) + 1
            self.guess_distribution = dist

            # Update streak
            self.current_streak += 1
            if self.current_streak > self.longest_streak:
                self.longest_streak = self.current_streak
        else:
            self.current_streak = 0

        # Update category stats
        cat_stats = self.category_stats or {}
        if category not in cat_stats:
            cat_stats[category] = {'played': 0, 'won': 0}
        cat_stats[category]['played'] += 1
        if won:
            cat_stats[category]['won'] += 1
        self.category_stats = cat_stats

        self.last_played_at = timezone.now()
        self.save()


class Leaderboard(models.Model):
    """Leaderboard entries - updated periodically"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='leaderboard_entries',
        help_text='Null means all categories'
    )
    period = models.CharField(
        max_length=20,
        choices=[
            ('all_time', 'All Time'),
            ('monthly', 'Monthly'),
            ('weekly', 'Weekly'),
        ],
        default='all_time'
    )
    rank = models.IntegerField(default=0)
    games_won = models.IntegerField(default=0)
    games_played = models.IntegerField(default=0)
    total_xp = models.IntegerField(default=0)
    win_rate = models.FloatField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'category', 'period']
        ordering = ['rank']

    def __str__(self):
        cat_name = self.category.name if self.category else 'All'
        return f"#{self.rank} {self.user.email} ({cat_name})"
