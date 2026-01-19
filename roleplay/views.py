import hmac
import hashlib
import json
import logging
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from core.models import Configuration
from .models import RolePlayBot, RoleplaySession, CreditTransaction

logger = logging.getLogger(__name__)

# Credit package configuration
CREDIT_PACKAGES = [
    {
        'id': 'starter',
        'name': 'Starter Pack',
        'credits': 100,
        'price_inr': 99,
        'description': '~10 minutes of voice roleplay',
    },
]


class RoleplayHomeView(LoginRequiredMixin, View):
    """List available roleplay bots"""
    template_name = 'roleplay/home.html'
    login_url = '/users/login/'

    def get(self, request):
        bots = RolePlayBot.objects.filter(is_active=True)

        # Get user's credit balance
        credits = 0
        if hasattr(request.user, 'profile'):
            credits = request.user.profile.credits

        # Get recent sessions
        recent_sessions = RoleplaySession.objects.filter(
            user=request.user
        ).select_related('bot')[:5]

        context = {
            'bots': bots,
            'credits': credits,
            'recent_sessions': recent_sessions,
        }
        return render(request, self.template_name, context)


class RoleplayStartView(LoginRequiredMixin, View):
    """Start a new roleplay session"""
    login_url = '/users/login/'

    def get(self, request, bot_id):
        bot = get_object_or_404(RolePlayBot, id=bot_id, is_active=True)

        # Check if user has enough credits
        if not hasattr(request.user, 'profile'):
            messages.error(request, 'Profile not found. Please contact support.')
            return redirect('roleplay:home')

        if not request.user.profile.has_credits(bot.required_credits):
            messages.warning(request, f'You need at least {bot.required_credits} credits to start. Please buy credits first.')
            return redirect('purchase_credits')

        # Create a new session
        session = RoleplaySession.objects.create(
            user=request.user,
            bot=bot,
            status='in_progress',
        )

        return redirect('roleplay:session', session_id=session.id)


class RoleplaySessionView(LoginRequiredMixin, View):
    """Roleplay session page with WebSocket connection"""
    template_name = 'roleplay/session.html'
    login_url = '/users/login/'

    def get(self, request, session_id):
        session = get_object_or_404(
            RoleplaySession,
            id=session_id,
            user=request.user
        )

        # Get user's credit balance
        credits = 0
        if hasattr(request.user, 'profile'):
            credits = request.user.profile.credits

        # Get WebSocket URL
        ws_scheme = 'wss' if request.is_secure() else 'ws'
        ws_url = f"{ws_scheme}://{request.get_host()}/ws/roleplay/{session.id}/"

        context = {
            'session': session,
            'bot': session.bot,
            'credits': credits,
            'ws_url': ws_url,
        }
        return render(request, self.template_name, context)


class RoleplayEndSessionView(LoginRequiredMixin, View):
    """End a roleplay session"""
    login_url = '/users/login/'

    def post(self, request, session_id):
        session = get_object_or_404(
            RoleplaySession,
            id=session_id,
            user=request.user,
            status='in_progress'
        )

        # Update session
        session.status = 'completed'
        session.completed_at = timezone.now()
        session.save()

        messages.success(request, 'Session ended successfully!')
        return redirect('roleplay:home')


class PurchaseCreditsView(LoginRequiredMixin, View):
    """Display credit packages for purchase"""
    template_name = 'roleplay/purchase_credits.html'
    login_url = '/users/login/'

    def get(self, request):
        # Get user's current credits
        credits = 0
        if hasattr(request.user, 'profile'):
            credits = request.user.profile.credits

        # Get recent transactions
        transactions = CreditTransaction.objects.filter(
            user=request.user,
            status='completed'
        )[:5]

        context = {
            'packages': CREDIT_PACKAGES,
            'credits': credits,
            'transactions': transactions,
        }
        return render(request, self.template_name, context)


class CreditCheckoutView(LoginRequiredMixin, View):
    """Create Razorpay order for credit purchase"""
    login_url = '/users/login/'

    def post(self, request):
        package_id = request.POST.get('package_id')

        # Find the package
        package = None
        for p in CREDIT_PACKAGES:
            if p['id'] == package_id:
                package = p
                break

        if not package:
            return JsonResponse({'error': 'Invalid package'}, status=400)

        try:
            import razorpay

            razorpay_key = Configuration.get_value('razorpay_api_key')
            razorpay_secret = Configuration.get_value('razorpay_api_secret')

            if not razorpay_key or not razorpay_secret:
                return JsonResponse({'error': 'Payment system not configured'}, status=500)

            client = razorpay.Client(auth=(razorpay_key, razorpay_secret))

            # Amount in paise
            amount_paise = int(package['price_inr'] * 100)

            razorpay_order = client.order.create({
                'amount': amount_paise,
                'currency': 'INR',
                'notes': {
                    'user_id': str(request.user.id),
                    'package_id': package_id,
                    'credits': package['credits'],
                    'type': 'roleplay_credits',
                }
            })

            # Create pending transaction
            transaction = CreditTransaction.objects.create(
                user=request.user,
                credits=package['credits'],
                amount=Decimal(str(package['price_inr'])),
                currency='INR',
                status='pending',
                razorpay_order_id=razorpay_order['id'],
            )

            return JsonResponse({
                'order_id': razorpay_order['id'],
                'amount': amount_paise,
                'currency': 'INR',
                'key_id': razorpay_key,
                'package_name': package['name'],
                'credits': package['credits'],
            })

        except Exception as e:
            logger.error(f"Error creating credit order: {e}")
            return JsonResponse({'error': str(e)}, status=500)


class CreditPaymentSuccessView(LoginRequiredMixin, View):
    """Verify payment and add credits"""
    login_url = '/users/login/'

    def post(self, request):
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')

        try:
            # Find the pending transaction
            transaction = CreditTransaction.objects.get(
                razorpay_order_id=razorpay_order_id,
                user=request.user,
                status='pending'
            )
        except CreditTransaction.DoesNotExist:
            messages.error(request, 'Transaction not found.')
            return redirect('purchase_credits')

        # Verify signature
        try:
            razorpay_secret = Configuration.get_value('razorpay_api_secret')

            sign_string = f"{razorpay_order_id}|{razorpay_payment_id}"
            expected_signature = hmac.new(
                razorpay_secret.encode(),
                sign_string.encode(),
                hashlib.sha256
            ).hexdigest()

            if expected_signature != razorpay_signature:
                logger.error(f"Credit payment signature verification failed for user {request.user.id}")
                messages.error(request, 'Payment verification failed. Please contact support.')
                return redirect('purchase_credits')

            # Update transaction
            transaction.status = 'completed'
            transaction.razorpay_payment_id = razorpay_payment_id
            transaction.razorpay_signature = razorpay_signature
            transaction.save()

            # Add credits to user
            if hasattr(request.user, 'profile'):
                request.user.profile.add_credits(transaction.credits)
                messages.success(request, f'Successfully added {transaction.credits} credits to your account!')
            else:
                messages.error(request, 'Profile not found. Please contact support.')
                return redirect('purchase_credits')

            return redirect('roleplay:home')

        except Exception as e:
            logger.error(f"Credit payment verification error for user {request.user.id}: {e}")
            messages.error(request, 'Payment verification error. Please contact support.')
            return redirect('purchase_credits')


@method_decorator(csrf_exempt, name='dispatch')
class CreditPaymentFailedView(View):
    """Handle credit payment failure"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.warning(f"Credit payment failed: {data}")

            order_id = data.get('order_id', '')
            if order_id and request.user.is_authenticated:
                try:
                    transaction = CreditTransaction.objects.get(
                        razorpay_order_id=order_id,
                        user=request.user,
                        status='pending'
                    )
                    transaction.status = 'failed'
                    transaction.save()
                except CreditTransaction.DoesNotExist:
                    pass

            return JsonResponse({'status': 'logged'})

        except Exception as e:
            logger.error(f"Error logging credit payment failure: {e}")
            return JsonResponse({'status': 'error'}, status=400)
