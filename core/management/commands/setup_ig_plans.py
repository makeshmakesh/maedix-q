"""
Management command to set up Instagram automation focused pricing plans.
Run with: python manage.py setup_ig_plans
"""
from django.core.management.base import BaseCommand
from core.models import Plan


class Command(BaseCommand):
    help = 'Set up Instagram automation focused pricing plans'

    def handle(self, *args, **options):
        # Define new IG-focused plans
        plans_data = [
            {
                'name': 'Free',
                'slug': 'free',
                'plan_type': 'free',
                'price_monthly': 0,
                'price_yearly': 0,
                'pricing_data': {
                    'default': {'monthly': 0, 'yearly': 0, 'currency': 'USD', 'symbol': '$'},
                },
                'description': 'Get started with Instagram automation',
                'features': [
                    {'code': 'ig_post_automation', 'limit': 3, 'description': 'Active automations (posts)'},
                    {'code': 'ig_unlimited_replies', 'description': 'Unlimited replies per post'},
                    {'code': 'ig_comment_reply', 'description': 'Auto comment replies'},
                    {'code': 'ig_auto_dm', 'description': 'Auto follow-up DMs'},
                    {'code': 'ig_keyword_triggers', 'description': 'Keyword triggers'},
                    {'code': 'ig_message_variations', 'description': 'Message variations (1-5)'},
                ],
                'is_active': True,
                'is_popular': False,
                'order': 1,
            },
            {
                'name': 'Pro',
                'slug': 'pro',
                'plan_type': 'pro',
                'price_monthly': 499,
                'price_yearly': 4999,
                'pricing_data': {
                    'default': {'monthly': 5.99, 'yearly': 59.99, 'currency': 'USD', 'symbol': '$'},
                },
                'description': 'For growing creators and businesses',
                'features': [
                    {'code': 'ig_post_automation', 'limit': 100, 'description': 'Active automations (posts)'},
                    {'code': 'ig_unlimited_replies', 'description': 'Unlimited replies per post'},
                    {'code': 'ig_comment_reply', 'description': 'Auto comment replies'},
                    {'code': 'ig_auto_dm', 'description': 'Auto follow-up DMs'},
                    {'code': 'ig_keyword_triggers', 'description': 'Keyword triggers'},
                    {'code': 'ig_message_variations', 'description': 'Message variations (1-5)'},
                    {'code': 'priority_support', 'description': 'Priority support'},
                ],
                'is_active': True,
                'is_popular': True,
                'order': 2,
            },
            {
                'name': 'Creator',
                'slug': 'creator',
                'plan_type': 'pro',
                'price_monthly': 999,
                'price_yearly': 9999,
                'pricing_data': {
                    'default': {'monthly': 10.99, 'yearly': 109.99, 'currency': 'USD', 'symbol': '$'},
                },
                'description': 'Unlimited automation for power users',
                'features': [
                    {'code': 'ig_post_automation', 'description': 'Unlimited active automations'},
                    {'code': 'ig_unlimited_replies', 'description': 'Unlimited replies per post'},
                    {'code': 'ig_account_automation', 'description': 'Account-level fallback'},
                    {'code': 'ig_comment_reply', 'description': 'Auto comment replies'},
                    {'code': 'ig_auto_dm', 'description': 'Auto follow-up DMs'},
                    {'code': 'ig_keyword_triggers', 'description': 'Keyword triggers'},
                    {'code': 'ig_message_variations', 'description': 'Message variations (1-5)'},
                    {'code': 'priority_support', 'description': 'Priority support'},
                ],
                'is_active': True,
                'is_popular': False,
                'order': 3,
            },
        ]

        for plan_data in plans_data:
            plan, created = Plan.objects.update_or_create(
                slug=plan_data['slug'],
                defaults=plan_data
            )
            action = 'Created' if created else 'Updated'
            self.stdout.write(
                self.style.SUCCESS(f'{action} plan: {plan.name}')
            )

        # Deactivate old plans that are no longer needed
        old_slugs = ['basic', 'enterprise']
        deactivated = Plan.objects.filter(slug__in=old_slugs).update(is_active=False)
        if deactivated:
            self.stdout.write(
                self.style.WARNING(f'Deactivated {deactivated} old plan(s)')
            )

        self.stdout.write(
            self.style.SUCCESS('\nDone! New Instagram automation plans are set up.')
        )
        self.stdout.write(
            self.style.NOTICE('\nPlan summary:')
        )
        self.stdout.write('  - Free: 3 post automations')
        self.stdout.write('  - Pro (₹499/mo): 100 post automations + priority support')
        self.stdout.write('  - Creator (₹999/mo): Unlimited + account-level automation')
