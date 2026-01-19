# Generated migration to convert from daily word to unlimited play

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Remove unique_together constraint first
        migrations.AlterUniqueTogether(
            name='gameattempt',
            unique_together=set(),
        ),

        # Step 2: Delete models in correct order (dependent models first)
        migrations.DeleteModel(
            name='CodeWordVideoExport',
        ),
        migrations.DeleteModel(
            name='GameAttempt',
        ),
        migrations.DeleteModel(
            name='DailyWord',
        ),
        migrations.DeleteModel(
            name='GameStreak',
        ),

        # Step 3: Update WordBank - remove old field and add new fields
        migrations.RemoveField(
            model_name='wordbank',
            name='used_as_daily',
        ),
        migrations.AddField(
            model_name='wordbank',
            name='times_played',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='wordbank',
            name='times_solved',
            field=models.IntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='wordbank',
            name='category',
            field=models.CharField(
                choices=[
                    ('web', 'Web Development'),
                    ('database', 'Database'),
                    ('programming', 'Programming'),
                    ('devops', 'DevOps'),
                    ('security', 'Security'),
                    ('data', 'Data Structures'),
                    ('mobile', 'Mobile'),
                    ('systems', 'Systems'),
                    ('tools', 'Tools'),
                    ('general', 'General Tech'),
                ],
                default='general',
                max_length=50
            ),
        ),

        # Step 4: Create new models
        migrations.CreateModel(
            name='GameSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('category', models.CharField(
                    choices=[
                        ('web', 'Web Development'),
                        ('database', 'Database'),
                        ('programming', 'Programming'),
                        ('devops', 'DevOps'),
                        ('security', 'Security'),
                        ('data', 'Data Structures'),
                        ('mobile', 'Mobile'),
                        ('systems', 'Systems'),
                        ('tools', 'Tools'),
                        ('general', 'General Tech'),
                    ],
                    max_length=50
                )),
                ('guesses', models.JSONField(default=list)),
                ('is_completed', models.BooleanField(default=False)),
                ('is_won', models.BooleanField(default=False)),
                ('attempts_used', models.IntegerField(default=0)),
                ('xp_earned', models.IntegerField(default=0)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
                ('word', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to='games.wordbank'
                )),
            ],
            options={
                'ordering': ['-started_at'],
            },
        ),
        migrations.CreateModel(
            name='PlayerStats',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('total_games', models.IntegerField(default=0)),
                ('total_wins', models.IntegerField(default=0)),
                ('total_xp', models.IntegerField(default=0)),
                ('current_streak', models.IntegerField(default=0)),
                ('longest_streak', models.IntegerField(default=0)),
                ('last_played_at', models.DateTimeField(blank=True, null=True)),
                ('guess_distribution', models.JSONField(default=dict)),
                ('category_stats', models.JSONField(default=dict)),
                ('user', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'verbose_name_plural': 'Player stats',
            },
        ),
        migrations.CreateModel(
            name='Leaderboard',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(
                    choices=[
                        ('all', 'All'),
                        ('web', 'Web Development'),
                        ('database', 'Database'),
                        ('programming', 'Programming'),
                        ('devops', 'DevOps'),
                        ('security', 'Security'),
                        ('data', 'Data Structures'),
                        ('mobile', 'Mobile'),
                        ('systems', 'Systems'),
                        ('tools', 'Tools'),
                        ('general', 'General Tech'),
                    ],
                    default='all',
                    max_length=50
                )),
                ('period', models.CharField(
                    choices=[
                        ('all_time', 'All Time'),
                        ('monthly', 'Monthly'),
                        ('weekly', 'Weekly'),
                    ],
                    default='all_time',
                    max_length=20
                )),
                ('rank', models.IntegerField(default=0)),
                ('games_won', models.IntegerField(default=0)),
                ('games_played', models.IntegerField(default=0)),
                ('total_xp', models.IntegerField(default=0)),
                ('win_rate', models.FloatField(default=0)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    to=settings.AUTH_USER_MODEL
                )),
            ],
            options={
                'ordering': ['rank'],
                'unique_together': {('user', 'category', 'period')},
            },
        ),
    ]
