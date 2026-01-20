from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0004_remove_leaderboard'),
    ]

    operations = [
        migrations.AddField(
            model_name='gamesession',
            name='time_taken_seconds',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
