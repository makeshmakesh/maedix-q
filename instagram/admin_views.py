from django.views import View
from django.shortcuts import render
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db.models import Count, Sum, Q
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from users.models import CustomUser
from core.models import Plan, Subscription, Transaction
from .models import (
    InstagramAccount, APICallLog, DMFlow, FlowSession,
    CollectedLead, QueuedFlowTrigger, SocialAgent, AIUsageLog
)


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
