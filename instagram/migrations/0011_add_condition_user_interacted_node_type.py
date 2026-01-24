# Generated manually for adding condition_user_interacted node type

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('instagram', '0010_remove_media_message_node_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='flownode',
            name='node_type',
            field=models.CharField(choices=[('comment_reply', 'Comment Reply'), ('message_text', 'Text Message'), ('message_quick_reply', 'Quick Reply Message'), ('message_button_template', 'Button Template'), ('message_link', 'Link Message'), ('condition_follower', 'Follower Check'), ('condition_user_interacted', 'Returning User Check'), ('collect_data', 'Collect Data')], max_length=30),
        ),
    ]
