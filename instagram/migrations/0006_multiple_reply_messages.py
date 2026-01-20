# Generated manually for multiple reply/DM messages feature

from django.db import migrations, models


def migrate_single_to_list(apps, schema_editor):
    """Convert existing single text messages to JSON lists"""
    InstagramAutomation = apps.get_model('instagram', 'InstagramAutomation')
    InstagramAccount = apps.get_model('instagram', 'InstagramAccount')

    # Migrate InstagramAutomation records
    for automation in InstagramAutomation.objects.all():
        # Convert comment_reply to list
        if hasattr(automation, 'comment_reply') and automation.comment_reply:
            automation.comment_replies = [automation.comment_reply]
        else:
            automation.comment_replies = []

        # Convert followup_dm to list
        if hasattr(automation, 'followup_dm') and automation.followup_dm:
            automation.followup_dms = [automation.followup_dm]
        else:
            automation.followup_dms = []

        automation.save()

    # Migrate InstagramAccount records
    for account in InstagramAccount.objects.all():
        # Convert account_comment_reply to list
        if hasattr(account, 'account_comment_reply') and account.account_comment_reply:
            account.account_comment_replies = [account.account_comment_reply]
        else:
            account.account_comment_replies = []

        # Convert account_followup_dm to list
        if hasattr(account, 'account_followup_dm') and account.account_followup_dm:
            account.account_followup_dms = [account.account_followup_dm]
        else:
            account.account_followup_dms = []

        account.save()


def migrate_list_to_single(apps, schema_editor):
    """Reverse: Convert JSON lists back to single text (take first item)"""
    InstagramAutomation = apps.get_model('instagram', 'InstagramAutomation')
    InstagramAccount = apps.get_model('instagram', 'InstagramAccount')

    for automation in InstagramAutomation.objects.all():
        if automation.comment_replies:
            automation.comment_reply = automation.comment_replies[0]
        else:
            automation.comment_reply = ''

        if automation.followup_dms:
            automation.followup_dm = automation.followup_dms[0]
        else:
            automation.followup_dm = ''

        automation.save()

    for account in InstagramAccount.objects.all():
        if account.account_comment_replies:
            account.account_comment_reply = account.account_comment_replies[0]
        else:
            account.account_comment_reply = ''

        if account.account_followup_dms:
            account.account_followup_dm = account.account_followup_dms[0]
        else:
            account.account_followup_dm = ''

        account.save()


class Migration(migrations.Migration):

    dependencies = [
        ('instagram', '0005_remove_instagramaccount_account_follow_request_message_and_more'),
    ]

    operations = [
        # Step 1: Add new JSON fields to InstagramAutomation
        migrations.AddField(
            model_name='instagramautomation',
            name='comment_replies',
            field=models.JSONField(default=list, help_text='List of reply messages (1-5). One will be randomly selected.'),
        ),
        migrations.AddField(
            model_name='instagramautomation',
            name='followup_dms',
            field=models.JSONField(blank=True, default=list, help_text='List of follow-up DM messages (0-5). One will be randomly selected. Empty = no DM.'),
        ),

        # Step 2: Add new JSON fields to InstagramAccount
        migrations.AddField(
            model_name='instagramaccount',
            name='account_comment_replies',
            field=models.JSONField(blank=True, default=list, help_text='List of reply messages (1-5). One will be randomly selected.'),
        ),
        migrations.AddField(
            model_name='instagramaccount',
            name='account_followup_dms',
            field=models.JSONField(blank=True, default=list, help_text='List of follow-up DM messages (1-5). One will be randomly selected.'),
        ),

        # Step 3: Migrate existing data
        migrations.RunPython(migrate_single_to_list, migrate_list_to_single),

        # Step 4: Remove old text fields from InstagramAutomation
        migrations.RemoveField(
            model_name='instagramautomation',
            name='comment_reply',
        ),
        migrations.RemoveField(
            model_name='instagramautomation',
            name='followup_dm',
        ),

        # Step 5: Remove old text fields from InstagramAccount
        migrations.RemoveField(
            model_name='instagramaccount',
            name='account_comment_reply',
        ),
        migrations.RemoveField(
            model_name='instagramaccount',
            name='account_followup_dm',
        ),
    ]
