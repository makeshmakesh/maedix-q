# Generated manually

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('instagram', '0009_add_button_template_node_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flownode',
            name='node_type',
            field=models.CharField(choices=[('comment_reply', 'Comment Reply'), ('message_text', 'Text Message'), ('message_quick_reply', 'Quick Reply Message'), ('message_button_template', 'Button Template'), ('message_link', 'Link Message'), ('condition_follower', 'Follower Check'), ('collect_data', 'Collect Data')], max_length=30),
        ),
    ]
