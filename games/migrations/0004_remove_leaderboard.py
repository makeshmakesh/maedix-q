from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('games', '0003_add_category_model'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Leaderboard',
        ),
    ]
