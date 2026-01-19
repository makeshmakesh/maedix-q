# Generated migration to add Category model and convert CharField to ForeignKey

import django.db.models.deletion
from django.db import migrations, models


def create_categories(apps, schema_editor):
    """Create initial categories from predefined list"""
    Category = apps.get_model('games', 'Category')

    categories = [
        ('web', 'Web Development', 'bi-globe', 'text-primary', 1),
        ('database', 'Database', 'bi-database', 'text-success', 2),
        ('programming', 'Programming', 'bi-code-slash', 'text-info', 3),
        ('devops', 'DevOps', 'bi-gear', 'text-warning', 4),
        ('security', 'Security', 'bi-shield-lock', 'text-danger', 5),
        ('data', 'Data Structures', 'bi-diagram-3', 'text-purple', 6),
        ('mobile', 'Mobile', 'bi-phone', 'text-teal', 7),
        ('systems', 'Systems', 'bi-cpu', 'text-secondary', 8),
        ('tools', 'Tools', 'bi-tools', 'text-orange', 9),
        ('general', 'General Tech', 'bi-puzzle', 'text-muted', 10),
    ]

    for slug, name, icon, color, order in categories:
        Category.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name,
                'icon': icon,
                'color': color,
                'order': order,
                'is_active': True,
            }
        )


def migrate_wordbank_categories(apps, schema_editor):
    """Migrate WordBank category string to ForeignKey"""
    Category = apps.get_model('games', 'Category')
    WordBank = apps.get_model('games', 'WordBank')

    # Build a mapping of slug to Category object
    category_map = {cat.slug: cat for cat in Category.objects.all()}

    for word in WordBank.objects.all():
        if word.category_old and word.category_old in category_map:
            word.category = category_map[word.category_old]
            word.save()


def migrate_gamesession_categories(apps, schema_editor):
    """Migrate GameSession category string to ForeignKey"""
    Category = apps.get_model('games', 'Category')
    GameSession = apps.get_model('games', 'GameSession')

    category_map = {cat.slug: cat for cat in Category.objects.all()}

    for session in GameSession.objects.all():
        if session.category_old and session.category_old in category_map:
            session.category = category_map[session.category_old]
            session.save()


def migrate_leaderboard_categories(apps, schema_editor):
    """Migrate Leaderboard category string to ForeignKey"""
    Category = apps.get_model('games', 'Category')
    Leaderboard = apps.get_model('games', 'Leaderboard')

    category_map = {cat.slug: cat for cat in Category.objects.all()}

    for entry in Leaderboard.objects.all():
        # 'all' means null for the ForeignKey
        if entry.category_old and entry.category_old != 'all' and entry.category_old in category_map:
            entry.category = category_map[entry.category_old]
            entry.save()


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0002_convert_to_unlimited_play'),
    ]

    operations = [
        # Step 1: Create Category model
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50)),
                ('slug', models.SlugField(max_length=50, unique=True)),
                ('icon', models.CharField(default='bi-puzzle', help_text='Bootstrap icon class (e.g., bi-globe)', max_length=50)),
                ('color', models.CharField(default='text-primary', help_text='CSS color class', max_length=20)),
                ('description', models.CharField(blank=True, max_length=200)),
                ('is_active', models.BooleanField(default=True)),
                ('order', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name_plural': 'Categories',
                'ordering': ['order', 'name'],
            },
        ),

        # Step 2: Populate categories
        migrations.RunPython(create_categories, migrations.RunPython.noop),

        # Step 3: Remove Leaderboard unique_together constraint BEFORE renaming
        migrations.AlterUniqueTogether(
            name='leaderboard',
            unique_together=set(),
        ),

        # Step 4: Rename old category fields
        migrations.RenameField(
            model_name='wordbank',
            old_name='category',
            new_name='category_old',
        ),
        migrations.RenameField(
            model_name='gamesession',
            old_name='category',
            new_name='category_old',
        ),
        migrations.RenameField(
            model_name='leaderboard',
            old_name='category',
            new_name='category_old',
        ),

        # Step 5: Add new ForeignKey fields
        migrations.AddField(
            model_name='wordbank',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='words',
                to='games.category'
            ),
        ),
        migrations.AddField(
            model_name='gamesession',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='game_sessions',
                to='games.category'
            ),
        ),
        migrations.AddField(
            model_name='leaderboard',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='leaderboard_entries',
                help_text='Null means all categories',
                to='games.category'
            ),
        ),

        # Step 6: Migrate data
        migrations.RunPython(migrate_wordbank_categories, migrations.RunPython.noop),
        migrations.RunPython(migrate_gamesession_categories, migrations.RunPython.noop),
        migrations.RunPython(migrate_leaderboard_categories, migrations.RunPython.noop),

        # Step 7: Remove old fields
        migrations.RemoveField(
            model_name='wordbank',
            name='category_old',
        ),
        migrations.RemoveField(
            model_name='gamesession',
            name='category_old',
        ),
        migrations.RemoveField(
            model_name='leaderboard',
            name='category_old',
        ),

        # Step 8: Re-add unique_together for Leaderboard with new category field
        migrations.AlterUniqueTogether(
            name='leaderboard',
            unique_together={('user', 'category', 'period')},
        ),
    ]
