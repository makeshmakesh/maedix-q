from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from instagram.models import InstagramAccount, APICallLog


class Command(BaseCommand):
    help = 'Backfill DM and comment counts from APICallLog to InstagramAccount'

    def handle(self, *args, **options):
        # Get counts grouped by account and call_type
        stats = APICallLog.objects.filter(success=True).values(
            'account_id', 'call_type'
        ).annotate(count=Count('id'))

        # Build a dict: {account_id: {'dm': count, 'comment_reply': count}}
        account_counts = {}
        for stat in stats:
            account_id = stat['account_id']
            if account_id not in account_counts:
                account_counts[account_id] = {'dm': 0, 'comment_reply': 0}
            account_counts[account_id][stat['call_type']] = stat['count']

        # Update each account
        updated = 0
        for account_id, counts in account_counts.items():
            InstagramAccount.objects.filter(id=account_id).update(
                total_dms_sent=counts['dm'],
                total_comments_replied=counts['comment_reply']
            )
            updated += 1
            self.stdout.write(
                f"Account {account_id}: {counts['dm']} DMs, {counts['comment_reply']} comments"
            )

        self.stdout.write(
            self.style.SUCCESS(f'Backfilled {updated} accounts')
        )
