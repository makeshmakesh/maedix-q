"""
Data migration: auto-generate usernames for users with blank/missing usernames,
resolve duplicates, then make the field unique.
"""
import re
import random
from django.db import migrations, models
import django.core.validators


def populate_usernames(apps, schema_editor):
    """Auto-generate usernames for all users who don't have one."""
    CustomUser = apps.get_model('users', 'CustomUser')
    taken = set(
        CustomUser.objects.exclude(username='')
        .values_list('username', flat=True)
    )
    # Lowercase all taken for case-insensitive dedup
    taken_lower = {u.lower() for u in taken}

    for user in CustomUser.objects.filter(username=''):
        prefix = user.email.split('@')[0]
        base = re.sub(r'[^a-zA-Z0-9_]', '', prefix).lower()
        if len(base) < 3:
            base = base + '_user'
        base = base[:24]

        candidate = base
        if candidate.lower() in taken_lower:
            for _ in range(1000):
                suffix = random.randint(100, 9999)
                candidate = f"{base}_{suffix}"
                if candidate.lower() not in taken_lower:
                    break

        user.username = candidate
        user.save(update_fields=['username'])
        taken.add(candidate)
        taken_lower.add(candidate.lower())

    # Resolve duplicates among existing non-blank usernames (case-insensitive)
    from collections import Counter
    all_users = list(
        CustomUser.objects.exclude(username='')
        .order_by('date_joined')
        .values_list('id', 'username', named=True)
    )
    seen_lower = {}
    for u in all_users:
        lower = u.username.lower()
        if lower in seen_lower:
            # Duplicate — rename this one
            base = lower[:24]
            for _ in range(1000):
                suffix = random.randint(100, 9999)
                candidate = f"{base}_{suffix}"
                if candidate not in taken_lower:
                    break
            CustomUser.objects.filter(pk=u.id).update(username=candidate)
            taken_lower.add(candidate)
        else:
            seen_lower[lower] = u.id
            # Lowercase the stored username
            if u.username != lower:
                CustomUser.objects.filter(pk=u.id).update(username=lower)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0005_alter_userprofile_credits'),
    ]

    operations = [
        # Step 1: Run data migration to populate all usernames
        migrations.RunPython(populate_usernames, noop),
        # Step 2: Alter the field to be unique with validators and new max_length
        migrations.AlterField(
            model_name='customuser',
            name='username',
            field=models.CharField(
                help_text='Letters, numbers, and underscores only. 3-30 characters.',
                max_length=30,
                unique=True,
                validators=[django.core.validators.RegexValidator(
                    message='Username may only contain letters, numbers, and underscores.',
                    regex='^[a-zA-Z0-9_]+$',
                )],
            ),
        ),
    ]
