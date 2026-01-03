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
from dateutil.relativedelta import relativedelta
from .models import Plan, ContactMessage, Configuration, Subscription, Transaction
from .forms import ContactForm

logger = logging.getLogger(__name__)


class HomePage(View):
    """Landing page"""
    template_name = 'core/home.html'

    def get(self, request):
        return render(request, self.template_name)


class AboutPage(View):
    """About us page"""
    template_name = 'core/about.html'

    def get(self, request):
        return render(request, self.template_name)


class PricingPage(View):
    """Pricing plans page"""
    template_name = 'core/pricing.html'

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by('order', 'price_monthly')

        # Get user's current plan if logged in
        current_plan = None
        if request.user.is_authenticated:
            subscription = Subscription.objects.filter(
                user=request.user,
                status='active'
            ).select_related('plan').first()
            if subscription:
                current_plan = subscription.plan

        return render(request, self.template_name, {
            'plans': plans,
            'current_plan': current_plan,
        })


class ContactPage(View):
    """Contact us page"""
    template_name = 'core/contact.html'

    def get(self, request):
        form = ContactForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = ContactForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your message has been sent successfully!')
            return redirect('contact')
        return render(request, self.template_name, {'form': form})


class TermsPage(View):
    """Terms of service page"""
    template_name = 'core/terms.html'

    def get(self, request):
        return render(request, self.template_name)


class PrivacyPolicyPage(View):
    """Privacy policy page"""
    template_name = 'core/privacy-policy.html'

    def get(self, request):
        return render(request, self.template_name)


class RefundPolicyPage(View):
    """Refund policy page"""
    template_name = 'core/refund-policy.html'

    def get(self, request):
        return render(request, self.template_name)


class CheckoutView(LoginRequiredMixin, View):
    """Checkout page with Razorpay integration"""
    template_name = 'core/checkout.html'
    login_url = '/users/login/'

    def get(self, request):
        plan_slug = request.GET.get('plan')
        billing = request.GET.get('billing', 'monthly')

        if not plan_slug:
            messages.error(request, 'Please select a plan.')
            return redirect('pricing')

        try:
            plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            messages.error(request, 'Invalid plan selected.')
            return redirect('pricing')

        # Don't allow checkout for free plan
        if plan.plan_type == 'free':
            messages.info(request, 'Free plan does not require payment.')
            return redirect('pricing')

        # Get price based on billing cycle
        is_yearly = billing == 'yearly'
        price = plan.price_yearly if is_yearly else plan.price_monthly
        currency = 'INR'
        currency_symbol = '₹'

        # Create Razorpay order
        try:
            import razorpay

            razorpay_key = Configuration.get_value('razorpay_api_key')
            razorpay_secret = Configuration.get_value('razorpay_api_secret')

            if not razorpay_key or not razorpay_secret:
                messages.error(request, 'Payment system not configured. Please contact support.')
                return redirect('pricing')

            client = razorpay.Client(auth=(razorpay_key, razorpay_secret))

            # Amount in paise (smallest unit)
            amount_paise = int(price * 100)

            razorpay_order = client.order.create({
                'amount': amount_paise,
                'currency': currency,
                'notes': {
                    'user_id': str(request.user.id),
                    'plan_slug': plan_slug,
                    'billing': billing,
                }
            })

            context = {
                'plan': plan,
                'price': price,
                'billing': billing,
                'is_yearly': is_yearly,
                'currency': currency,
                'currency_symbol': currency_symbol,
                'amount_paise': amount_paise,
                'order_id': razorpay_order['id'],
                'razorpay_key_id': razorpay_key,
            }
            return render(request, self.template_name, context)

        except Exception as e:
            logger.error(f"Error creating Razorpay order: {e}")
            messages.error(request, f'Error creating order. Please try again.')
            return redirect('pricing')


class PaymentSuccessView(LoginRequiredMixin, View):
    """Handle successful payment verification"""
    login_url = '/users/login/'

    def post(self, request):
        razorpay_payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        razorpay_signature = request.POST.get('razorpay_signature')
        plan_slug = request.POST.get('plan_slug')
        billing = request.POST.get('billing', 'monthly')

        try:
            plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            messages.error(request, 'Invalid plan.')
            return redirect('pricing')

        is_yearly = billing == 'yearly'
        price = plan.price_yearly if is_yearly else plan.price_monthly

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
                logger.error(f"Payment signature verification failed for user {request.user.id}")
                messages.error(request, 'Payment verification failed. Please contact support.')
                return redirect('pricing')

            # Create transaction record
            transaction = Transaction.objects.create(
                user=request.user,
                amount=Decimal(str(price)),
                currency='INR',
                status='success',
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature,
                metadata={
                    'plan_slug': plan_slug,
                    'billing': billing,
                }
            )

            # Calculate subscription dates
            now = timezone.now()
            if is_yearly:
                end_date = now + relativedelta(years=1)
                next_reset = now + relativedelta(months=1)
            else:
                end_date = now + relativedelta(months=1)
                next_reset = end_date

            # Create or update subscription
            subscription, created = Subscription.objects.update_or_create(
                user=request.user,
                defaults={
                    'plan': plan,
                    'status': 'active',
                    'start_date': now,
                    'end_date': end_date,
                    'is_yearly': is_yearly,
                    'usage_data': {},  # Reset usage on new subscription
                    'last_reset_date': now,
                    'next_reset_date': next_reset,
                }
            )

            # Link transaction to subscription
            transaction.subscription = subscription
            transaction.save()

            # Store success data in session
            request.session['payment_success_data'] = {
                'transaction_id': transaction.id,
                'subscription_id': subscription.id,
            }

            messages.success(request, 'Payment successful! Your subscription is now active.')
            return redirect('payment_success_page')

        except Exception as e:
            logger.error(f"Payment verification error for user {request.user.id}: {e}")
            messages.error(request, f'Payment verification error. Please contact support.')
            return redirect('pricing')


class PaymentSuccessPageView(LoginRequiredMixin, View):
    """Display payment success page"""
    template_name = 'core/payment-success.html'
    login_url = '/users/login/'

    def get(self, request):
        payment_data = request.session.get('payment_success_data')

        if not payment_data:
            messages.warning(request, 'No payment information found.')
            return redirect('quiz_home')

        # Clear session data
        del request.session['payment_success_data']

        try:
            transaction = Transaction.objects.get(
                id=payment_data['transaction_id'],
                user=request.user
            )
            subscription = Subscription.objects.get(
                id=payment_data['subscription_id'],
                user=request.user
            )
        except (Transaction.DoesNotExist, Subscription.DoesNotExist):
            messages.warning(request, 'Transaction not found.')
            return redirect('quiz_home')

        context = {
            'transaction': transaction,
            'subscription': subscription,
            'plan': subscription.plan,
        }
        return render(request, self.template_name, context)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentFailedView(View):
    """Handle payment failure"""

    def post(self, request):
        try:
            data = json.loads(request.body)
            logger.warning(f"Payment failed: {data}")

            if request.user.is_authenticated:
                Transaction.objects.create(
                    user=request.user,
                    amount=Decimal('0.00'),
                    currency='INR',
                    status='failed',
                    razorpay_order_id=data.get('order_id', ''),
                    razorpay_payment_id=data.get('payment_id', ''),
                    metadata={
                        'error_code': data.get('error_code'),
                        'error_description': data.get('error_description'),
                    }
                )

            return JsonResponse({'status': 'logged'})

        except Exception as e:
            logger.error(f"Error logging payment failure: {e}")
            return JsonResponse({'status': 'error'}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class PaymentWebhookView(View):
    """Razorpay webhook handler for subscription events"""

    def post(self, request):
        try:
            payload = json.loads(request.body)
            event = payload.get('event')

            logger.info(f"Received Razorpay webhook: {event}")

            # Verify webhook signature
            webhook_secret = Configuration.get_value('razorpay_webhook_secret')
            if webhook_secret:
                received_signature = request.headers.get('X-Razorpay-Signature', '')
                expected_signature = hmac.new(
                    webhook_secret.encode(),
                    request.body,
                    hashlib.sha256
                ).hexdigest()

                if received_signature != expected_signature:
                    logger.error("Webhook signature verification failed")
                    return JsonResponse({'status': 'invalid_signature'}, status=400)

            # Handle different events
            if event == 'payment.captured':
                # Payment was successful
                payment = payload.get('payload', {}).get('payment', {}).get('entity', {})
                logger.info(f"Payment captured: {payment.get('id')}")

            elif event == 'payment.failed':
                # Payment failed
                payment = payload.get('payload', {}).get('payment', {}).get('entity', {})
                logger.warning(f"Payment failed: {payment.get('id')}")

            elif event == 'subscription.activated':
                # Subscription activated
                subscription = payload.get('payload', {}).get('subscription', {}).get('entity', {})
                logger.info(f"Subscription activated: {subscription.get('id')}")

            elif event == 'subscription.cancelled':
                # Subscription cancelled
                subscription_data = payload.get('payload', {}).get('subscription', {}).get('entity', {})
                razorpay_sub_id = subscription_data.get('id')

                try:
                    subscription = Subscription.objects.get(razorpay_subscription_id=razorpay_sub_id)
                    subscription.status = 'cancelled'
                    subscription.save()
                    logger.info(f"Subscription cancelled: {razorpay_sub_id}")
                except Subscription.DoesNotExist:
                    logger.warning(f"Subscription not found: {razorpay_sub_id}")

            return JsonResponse({'status': 'ok'})

        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return JsonResponse({'status': 'error'}, status=500)
