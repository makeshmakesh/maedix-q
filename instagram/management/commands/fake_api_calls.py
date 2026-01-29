"""
Management command to insert fake API call logs for testing rate limiting.

Usage:
    python manage.py fake_api_calls --email user@example.com --count 200
    python manage.py fake_api_calls --email user@example.com --count 200 --clear
"""
from django.core.management.base import BaseCommand
from instagram.models import APICallLog, InstagramAccount


class Command(BaseCommand):
    help = 'Insert fake API call logs for testing rate limiting'

    def add_arguments(self, parser):
        parser.add_argument(
            '--email',
            type=str,
            required=True,
            help='Email of the user whose Instagram account to use'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=200,
            help='Number of fake API calls to insert (default: 200)'
        )
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing API call logs for this account first'
        )

    def handle(self, *args, **options):
        email = options['email']
        count = options['count']
        clear = options['clear']

        # Find the Instagram account
        try:
            account = InstagramAccount.objects.get(user__email=email)
        except InstagramAccount.DoesNotExist:
            self.stderr.write(self.style.ERROR(f'No Instagram account found for user: {email}'))
            return

        self.stdout.write(f'Found Instagram account: @{account.username}')

        # Clear existing logs if requested
        if clear:
            deleted_count = APICallLog.objects.filter(account=account).delete()[0]
            self.stdout.write(self.style.WARNING(f'Cleared {deleted_count} existing API call logs'))

        # Check current count
        current_count = APICallLog.get_calls_last_hour(account)
        self.stdout.write(f'Current API calls in last hour: {current_count}')

        # Insert fake logs
        logs_to_create = []
        for i in range(count):
            logs_to_create.append(APICallLog(
                account=account,
                call_type='dm',
                endpoint='/me/messages',
                recipient_id=f'fake_test_{i}',
                success=True
            ))

        APICallLog.objects.bulk_create(logs_to_create)
        self.stdout.write(self.style.SUCCESS(f'Inserted {count} fake API call logs'))

        # Show new count
        new_count = APICallLog.get_calls_last_hour(account)
        self.stdout.write(self.style.SUCCESS(f'Total API calls in last hour: {new_count}'))
