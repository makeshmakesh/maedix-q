import logging

from django.views import View
from django.shortcuts import render, redirect
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib import messages
from django.db.models import Count, Sum, Q, F
from django.http import JsonResponse
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from users.models import CustomUser, ProfileLink, ProfilePageView, ProfileLinkClick
from core.models import Plan, Subscription, Transaction
from .models import (
    InstagramAccount, APICallLog, DMFlow, FlowSession, FlowExecutionLog,
    CollectedLead, QueuedFlowTrigger, SocialAgent, AIUsageLog,
    DroppedMessage, AIConversationMessage, AICollectedData
)

logger = logging.getLogger(__name__)


class StaffRequiredMixin(UserPassesTestMixin):
    """Mixin to ensure user is staff"""
    login_url = '/users/login/'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class AdminDashboardView(StaffRequiredMixin, View):
    """Main admin dashboard with all Instagram automation metrics"""
    template_name = 'staff/admin/dashboard.html'

    def get(self, request):
        # Get time period from query param
        period = request.GET.get('period', '7d')
        start_date = self._get_start_date(period)
        today = timezone.now().date()

        context = {
            'period': period,
            'periods': [
                {'value': 'today', 'label': 'Today'},
                {'value': '7d', 'label': 'Last 7 Days'},
                {'value': '30d', 'label': 'Last 30 Days'},
                {'value': 'all', 'label': 'All Time'},
            ],
        }

        # Overview Stats
        context['overview'] = self._get_overview_stats(start_date, today)

        # User Analytics
        context['user_analytics'] = self._get_user_analytics()

        # Automation Metrics
        context['automation'] = self._get_automation_metrics(start_date)

        # API Performance
        context['api_performance'] = self._get_api_performance(start_date)

        # AI Usage
        context['ai_usage'] = self._get_ai_usage(start_date)

        # Revenue
        context['revenue'] = self._get_revenue_stats(start_date)

        # User Funnel
        context['funnel'] = self._get_user_funnel(start_date)

        # Link in Bio Metrics
        context['link_in_bio'] = self._get_link_in_bio_metrics(start_date)

        # Recent Activity
        context['recent_sessions'] = FlowSession.objects.select_related('flow').order_by('-created_at')[:10]
        context['recent_leads'] = CollectedLead.objects.select_related('user', 'flow').order_by('-created_at')[:10]
        context['recent_signups'] = CustomUser.objects.order_by('-date_joined')[:10]

        return render(request, self.template_name, context)

    def _get_start_date(self, period):
        """Get start date based on period selection"""
        now = timezone.now()
        if period == 'today':
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == '7d':
            return now - timedelta(days=7)
        elif period == '30d':
            return now - timedelta(days=30)
        else:  # all
            return None

    def _get_user_funnel(self, start_date):
        """Get user funnel: signups → IG connected → flows created → messages sent → paid"""

        # 1. Signed up
        user_qs = CustomUser.objects.all()
        if start_date:
            user_qs = user_qs.filter(date_joined__gte=start_date)
        signups = user_qs.order_by('-date_joined')
        signup_count = signups.count()
        google_count = signups.filter(password__startswith='!').count()
        password_count = signup_count - google_count
        signup_users = list(signups.values('id', 'email', 'first_name', 'last_name', 'date_joined', 'password')[:50])
        for u in signup_users:
            u['login_method'] = 'Google' if u.pop('password', '').startswith('!') else 'Email'

        # 2. Connected Instagram
        ig_qs = InstagramAccount.objects.filter(
            access_token__isnull=False
        ).exclude(access_token='').select_related('user')
        if start_date:
            ig_qs = ig_qs.filter(created_at__gte=start_date)
        ig_connected = ig_qs.order_by('-created_at')
        ig_count = ig_connected.count()
        ig_users = list(ig_connected.values(
            'user__id', 'user__email', 'username', 'created_at', 'is_active'
        )[:50])

        # 3. Created DM Flows
        flow_qs = DMFlow.objects.all()
        if start_date:
            flow_qs = flow_qs.filter(created_at__gte=start_date)
        flow_creators = flow_qs.values('user__id', 'user__email').annotate(
            flow_count=Count('id'),
            active_flows=Count('id', filter=Q(is_active=True)),
        ).order_by('-flow_count')
        flow_user_count = flow_creators.count()
        flow_users = list(flow_creators[:50])

        # 4. Messages Sent (users with DMs/comments sent)
        if start_date:
            # For period filter, use API call logs
            api_users = APICallLog.objects.filter(
                success=True, sent_at__gte=start_date
            ).values(
                'account__user__id', 'account__user__email', 'account__username'
            ).annotate(
                dms=Count('id', filter=Q(call_type='dm')),
                comments=Count('id', filter=Q(call_type='comment_reply')),
            ).order_by('-dms')
            msg_user_count = api_users.count()
            msg_users = [
                {'email': u['account__user__email'], 'username': u['account__username'],
                 'dms': u['dms'], 'comments': u['comments']}
                for u in api_users[:50]
            ]
        else:
            msg_accounts = InstagramAccount.objects.filter(
                Q(total_dms_sent__gt=0) | Q(total_comments_replied__gt=0)
            ).select_related('user').order_by('-total_dms_sent')
            msg_user_count = msg_accounts.count()
            msg_users = [
                {'email': a.user.email, 'username': a.username,
                 'dms': a.total_dms_sent, 'comments': a.total_comments_replied}
                for a in msg_accounts[:50]
            ]

        # 5. Paid Users (successful transactions)
        txn_qs = Transaction.objects.filter(status='success').select_related('user', 'subscription__plan')
        if start_date:
            txn_qs = txn_qs.filter(created_at__gte=start_date)
        paid = txn_qs.values('user__id', 'user__email').annotate(
            total_paid=Sum('amount'),
            txn_count=Count('id'),
        ).order_by('-total_paid')
        paid_count = paid.count()
        paid_users = list(paid[:50])

        # Get current plan for paid users
        for pu in paid_users:
            sub = Subscription.objects.filter(
                user_id=pu['user__id'], status='active'
            ).select_related('plan').first()
            pu['plan_name'] = sub.plan.name if sub else 'No active plan'

        return {
            'signups': {'count': signup_count, 'google_count': google_count, 'password_count': password_count, 'users': signup_users},
            'ig_connected': {'count': ig_count, 'users': ig_users},
            'flows_created': {'count': flow_user_count, 'users': flow_users},
            'messages_sent': {'count': msg_user_count, 'users': msg_users},
            'paid': {'count': paid_count, 'users': paid_users},
        }

    def _get_overview_stats(self, start_date, today):
        """Get overview statistics"""
        total_users = CustomUser.objects.count()

        if start_date:
            new_users = CustomUser.objects.filter(date_joined__gte=start_date).count()
        else:
            new_users = total_users

        active_automations = DMFlow.objects.filter(is_active=True).count()
        sessions_today = FlowSession.objects.filter(created_at__date=today).count()

        if start_date:
            leads_collected = CollectedLead.objects.filter(created_at__gte=start_date).count()
            total_revenue = Transaction.objects.filter(
                status='success',
                created_at__gte=start_date
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        else:
            leads_collected = CollectedLead.objects.count()
            total_revenue = Transaction.objects.filter(
                status='success'
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        return {
            'total_users': total_users,
            'new_users': new_users,
            'active_automations': active_automations,
            'sessions_today': sessions_today,
            'leads_collected': leads_collected,
            'total_revenue': total_revenue,
        }

    def _get_user_analytics(self):
        """Get user analytics including subscription distribution"""
        # Subscription distribution by plan
        plan_distribution = []
        plans = Plan.objects.filter(is_active=True).order_by('order')

        for plan in plans:
            count = Subscription.objects.filter(
                plan=plan,
                status='active'
            ).count()
            plan_distribution.append({
                'plan': plan,
                'count': count,
            })

        # Users without active subscription (Free tier)
        users_with_active_sub = Subscription.objects.filter(
            status='active'
        ).values_list('user_id', flat=True).distinct()
        free_users = CustomUser.objects.exclude(id__in=users_with_active_sub).count()

        # Active Instagram accounts
        active_ig_accounts = InstagramAccount.objects.filter(is_active=True).count()
        connected_ig_accounts = InstagramAccount.objects.filter(
            access_token__isnull=False
        ).exclude(access_token='').count()

        return {
            'plan_distribution': plan_distribution,
            'free_users': free_users,
            'active_ig_accounts': active_ig_accounts,
            'connected_ig_accounts': connected_ig_accounts,
        }

    def _get_automation_metrics(self, start_date):
        """Get automation metrics"""
        # Session status breakdown
        session_qs = FlowSession.objects.all()
        if start_date:
            session_qs = session_qs.filter(created_at__gte=start_date)

        status_breakdown = session_qs.values('status').annotate(
            count=Count('id')
        ).order_by('status')

        status_dict = {item['status']: item['count'] for item in status_breakdown}
        total_sessions = sum(status_dict.values())

        # Calculate completion rate
        completed = status_dict.get('completed', 0)
        completion_rate = round((completed / total_sessions * 100), 1) if total_sessions > 0 else 0

        # Flow stats
        total_flows = DMFlow.objects.count()
        active_flows = DMFlow.objects.filter(is_active=True).count()

        # Aggregated flow stats
        flow_stats = DMFlow.objects.aggregate(
            total_triggered=Sum('total_triggered'),
            total_completed=Sum('total_completed')
        )

        # Queued triggers
        queued_pending = QueuedFlowTrigger.objects.filter(status='pending').count()
        queued_failed = QueuedFlowTrigger.objects.filter(status='failed').count()

        return {
            'status_breakdown': status_dict,
            'total_sessions': total_sessions,
            'completion_rate': completion_rate,
            'total_flows': total_flows,
            'active_flows': active_flows,
            'total_triggered': flow_stats['total_triggered'] or 0,
            'total_completed': flow_stats['total_completed'] or 0,
            'queued_pending': queued_pending,
            'queued_failed': queued_failed,
        }

    def _get_api_performance(self, start_date):
        """Get API performance metrics"""
        api_qs = APICallLog.objects.all()
        if start_date:
            api_qs = api_qs.filter(sent_at__gte=start_date)

        # API calls by type
        api_by_type = api_qs.values('call_type').annotate(
            total=Count('id'),
            success_count=Count('id', filter=Q(success=True)),
            failed_count=Count('id', filter=Q(success=False))
        ).order_by('call_type')

        api_stats = []
        total_calls = 0
        total_failed = 0

        for item in api_by_type:
            total = item['total']
            success_count = item['success_count']
            failed_count = item['failed_count']
            success_rate = round((success_count / total * 100), 1) if total > 0 else 0

            api_stats.append({
                'call_type': item['call_type'],
                'call_type_display': dict(APICallLog.CALL_TYPE_CHOICES).get(item['call_type'], item['call_type']),
                'total': total,
                'success': success_count,
                'failed': failed_count,
                'success_rate': success_rate,
            })
            total_calls += total
            total_failed += failed_count

        error_rate = round((total_failed / total_calls * 100), 1) if total_calls > 0 else 0

        # Rate limit threshold from config
        rate_limit = QueuedFlowTrigger.get_rate_limit()

        return {
            'api_stats': api_stats,
            'total_calls': total_calls,
            'total_failed': total_failed,
            'error_rate': error_rate,
            'rate_limit': rate_limit,
        }

    def _get_ai_usage(self, start_date):
        """Get AI usage statistics"""
        ai_qs = AIUsageLog.objects.all()
        if start_date:
            ai_qs = ai_qs.filter(created_at__gte=start_date)

        # Aggregate AI usage
        ai_totals = ai_qs.aggregate(
            total_input_tokens=Sum('input_tokens'),
            total_output_tokens=Sum('output_tokens'),
            total_cost_usd=Sum('cost_usd'),
            total_credits=Sum('credits_charged')
        )

        # Top agents by usage
        top_agents = ai_qs.filter(agent__isnull=False).values(
            'agent__id', 'agent__name'
        ).annotate(
            total_credits=Sum('credits_charged'),
            total_calls=Count('id')
        ).order_by('-total_credits')[:5]

        # Active agents count
        active_agents = SocialAgent.objects.filter(is_active=True).count()

        return {
            'total_input_tokens': ai_totals['total_input_tokens'] or 0,
            'total_output_tokens': ai_totals['total_output_tokens'] or 0,
            'total_cost_usd': round(ai_totals['total_cost_usd'] or 0, 4),
            'total_credits': round(ai_totals['total_credits'] or 0, 2),
            'top_agents': top_agents,
            'active_agents': active_agents,
        }

    def _get_revenue_stats(self, start_date):
        """Get revenue statistics"""
        # MRR calculation
        active_subs = Subscription.objects.filter(status='active').select_related('plan')
        mrr = Decimal('0')
        subs_by_plan = {}

        for sub in active_subs:
            if sub.is_yearly:
                monthly_amount = sub.plan.price_yearly / 12
            else:
                monthly_amount = sub.plan.price_monthly

            mrr += monthly_amount

            plan_name = sub.plan.name
            if plan_name not in subs_by_plan:
                subs_by_plan[plan_name] = {
                    'count': 0,
                    'revenue': Decimal('0'),
                }
            subs_by_plan[plan_name]['count'] += 1
            subs_by_plan[plan_name]['revenue'] += monthly_amount

        # Recent transactions
        transactions_qs = Transaction.objects.select_related('user', 'subscription__plan')
        if start_date:
            transactions_qs = transactions_qs.filter(created_at__gte=start_date)
        recent_transactions = transactions_qs.order_by('-created_at')[:10]

        # Pending transactions
        pending_transactions = Transaction.objects.filter(status='pending').count()

        return {
            'mrr': mrr,
            'subs_by_plan': subs_by_plan,
            'recent_transactions': recent_transactions,
            'pending_transactions': pending_transactions,
        }


    def _get_link_in_bio_metrics(self, start_date):
        """Get Link in Bio metrics"""
        view_qs = ProfilePageView.objects.all()
        click_qs = ProfileLinkClick.objects.all()
        link_qs = ProfileLink.objects.all()
        if start_date:
            view_qs = view_qs.filter(viewed_at__gte=start_date)
            click_qs = click_qs.filter(clicked_at__gte=start_date)
            link_qs = link_qs.filter(created_at__gte=start_date)

        total_views = view_qs.count()
        total_clicks = click_qs.count()
        total_links = link_qs.count()
        total_profiles = ProfileLink.objects.values('user').distinct().count()

        # Top profiles by views
        top_profiles = view_qs.values(
            'user__username', 'user__email'
        ).annotate(
            views=Count('id')
        ).order_by('-views')[:5]

        # Top links by clicks
        top_links = click_qs.values(
            'link__title', 'link__url', 'link__user__username'
        ).annotate(
            clicks=Count('id')
        ).order_by('-clicks')[:5]

        ctr = round((total_clicks / total_views * 100), 1) if total_views > 0 else 0

        return {
            'total_profiles': total_profiles,
            'total_links': total_links,
            'total_views': total_views,
            'total_clicks': total_clicks,
            'ctr': ctr,
            'top_profiles': top_profiles,
            'top_links': top_links,
        }


class AdminQueuedFlowsView(StaffRequiredMixin, View):
    """Admin view to see all queued flows across all users"""
    template_name = 'staff/admin/queued_flows.html'

    def get(self, request):
        status_filter = request.GET.get('status', 'pending')
        account_filter = request.GET.get('account', '')
        user_search = request.GET.get('user', '').strip()

        # Get all queued triggers
        qs = QueuedFlowTrigger.objects.select_related('account', 'account__user', 'flow')

        if status_filter and status_filter != 'all':
            qs = qs.filter(status=status_filter)

        if account_filter:
            qs = qs.filter(account_id=account_filter)

        if user_search:
            qs = qs.filter(
                Q(account__username__icontains=user_search) |
                Q(account__user__email__icontains=user_search)
            )

        if status_filter == 'pending':
            qs = qs.order_by('created_at')
        else:
            qs = qs.order_by('-created_at')

        queued_flows = qs[:200]

        # Summary stats
        total_pending = QueuedFlowTrigger.objects.filter(status='pending').count()
        total_processing = QueuedFlowTrigger.objects.filter(status='processing').count()
        total_completed_24h = QueuedFlowTrigger.objects.filter(
            status='completed',
            processed_at__gte=timezone.now() - timedelta(hours=24)
        ).count()
        total_failed_24h = QueuedFlowTrigger.objects.filter(
            status='failed',
            processed_at__gte=timezone.now() - timedelta(hours=24)
        ).count()

        # Per-account breakdown for pending
        account_stats = []
        accounts_with_pending = QueuedFlowTrigger.objects.filter(
            status='pending'
        ).values('account_id', 'account__user__email', 'account__username').annotate(
            pending_count=Count('id')
        ).order_by('-pending_count')

        for acc in accounts_with_pending:
            account = InstagramAccount.objects.get(id=acc['account_id'])
            calls_last_hour = APICallLog.get_calls_last_hour(account)
            rate_limit = QueuedFlowTrigger.get_rate_limit(account.user)
            available = max(0, rate_limit - calls_last_hour)
            account_stats.append({
                'account_id': acc['account_id'],
                'username': acc['account__username'] or acc['account__user__email'],
                'pending_count': acc['pending_count'],
                'calls_last_hour': calls_last_hour,
                'rate_limit': rate_limit,
                'available': available,
                'usage_percent': round(calls_last_hour / rate_limit * 100) if rate_limit else 0,
            })

        context = {
            'queued_flows': queued_flows,
            'status_filter': status_filter,
            'account_filter': account_filter,
            'user_search': user_search,
            'total_pending': total_pending,
            'total_processing': total_processing,
            'total_completed_24h': total_completed_24h,
            'total_failed_24h': total_failed_24h,
            'account_stats': account_stats,
        }
        return render(request, self.template_name, context)


class AdminDataDeletionView(StaffRequiredMixin, View):
    """Admin panel to process Meta/Instagram user data deletion requests"""
    template_name = 'staff/admin/data_deletion.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        raw_ids = request.POST.get('user_ids', '').strip()
        if not raw_ids:
            messages.error(request, 'No user IDs provided.')
            return redirect('instagram_admin_data_deletion')

        # Parse IDs (one per line, or comma-separated)
        user_ids = [
            uid.strip() for uid in raw_ids.replace(',', '\n').split('\n')
            if uid.strip()
        ]

        if not user_ids:
            messages.error(request, 'No valid user IDs found.')
            return redirect('instagram_admin_data_deletion')

        results = []
        for uid in user_ids:
            result = self._delete_user_data(uid)
            results.append(result)

        context = {
            'results': results,
            'total': len(results),
            'deleted': sum(1 for r in results if r['found']),
            'not_found': sum(1 for r in results if not r['found']),
        }
        return render(request, self.template_name, context)

    def _delete_user_data(self, scoped_id):
        """Delete all data for an Instagram scoped user ID.

        Checks both:
        - End users (commenters/DM users) tracked by instagram_scoped_id
        - Business accounts matched by instagram_user_id on InstagramAccount
        """
        result = {
            'scoped_id': scoped_id,
            'found': False,
            'deleted': {},
        }

        # 1. Check if this is a business account (InstagramAccount owner)
        ig_account = InstagramAccount.objects.filter(
            instagram_user_id=scoped_id
        ).select_related('user').first()

        if ig_account:
            result['found'] = True
            ig_account.delete()
            result['deleted']['instagram_account'] = 1

            logger.info(f"Data deletion (business account) for user_id={scoped_id}")
            return result

        # 2. End user (commenter/DM recipient) — tracked by instagram_scoped_id
        # Delete collected leads (personal data: name, email, phone)
        leads = CollectedLead.objects.filter(instagram_scoped_id=scoped_id)
        lead_count = leads.count()
        if lead_count:
            leads.delete()
            result['found'] = True
            result['deleted']['leads'] = lead_count

        if result['found']:
            logger.info(f"Data deletion (end user) for scoped_id={scoped_id}: {result['deleted']}")
        else:
            logger.info(f"Data deletion: no data found for scoped_id={scoped_id}")

        return result
