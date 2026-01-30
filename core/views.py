#pylint: disable=all
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
from roleplay.models import CreditTransaction
from .forms import ContactForm
from .utils import get_user_country, is_indian_user, get_currency_for_user

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

        # Get user's country and currency
        user_country = get_user_country(request)
        currency_info = get_currency_for_user(request)

        # Build pricing data for each plan based on user's country
        plans_with_pricing = []
        for plan in plans:
            pricing = plan.get_pricing_for_country(user_country)
            plans_with_pricing.append({
                'plan': plan,
                'price_monthly': pricing['monthly'],
                'price_yearly': pricing['yearly'],
                'currency': pricing['currency'],
                'symbol': pricing['symbol'],
            })

        return render(request, self.template_name, {
            'plans': plans,
            'plans_with_pricing': plans_with_pricing,
            'current_plan': current_plan,
            'user_country': user_country,
            'currency': currency_info['currency'],
            'currency_symbol': currency_info['symbol'],
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


def robots_txt(request):
    """Serve robots.txt file"""
    return render(request, 'robots.txt', content_type='text/plain')


def get_valid_coupon(code: str) -> dict | None:
    """
    Validate a coupon code and return coupon details if valid.

    Coupon configuration format in Configuration model:
    Key: 'coupon_codes'
    Value: [{"code": "SAVE50", "discount_percentage": 50, "active": true}]

    Returns dict with coupon details or None if invalid.
    """
    if not code:
        return None

    code = code.strip().upper()
    coupons_json = Configuration.get_value('coupon_codes', '[]')

    try:
        coupons = json.loads(coupons_json)
        for coupon in coupons:
            if coupon.get('code', '').upper() == code and coupon.get('active', True):
                return coupon
    except (json.JSONDecodeError, TypeError):
        logger.error("Invalid coupon_codes configuration format")

    return None


class ValidateCouponView(LoginRequiredMixin, View):
    """AJAX endpoint to validate coupon code"""
    login_url = '/users/login/'

    def post(self, request):
        code = request.POST.get('code', '').strip()

        if not code:
            return JsonResponse({'valid': False, 'error': 'Please enter a coupon code'})

        coupon = get_valid_coupon(code)

        if coupon:
            return JsonResponse({
                'valid': True,
                'code': coupon['code'],
                'discount_percentage': coupon.get('discount_percentage', 0),
                'message': f"{coupon.get('discount_percentage', 0)}% discount applied!"
            })
        else:
            return JsonResponse({'valid': False, 'error': 'Invalid or expired coupon code'})


class CheckoutView(LoginRequiredMixin, View):
    """Checkout page with Razorpay integration"""
    template_name = 'core/checkout.html'
    login_url = '/users/login/'

    def get(self, request):
        plan_slug = request.GET.get('plan')
        billing = request.GET.get('billing', 'monthly')
        coupon_code = request.GET.get('coupon', '').strip()

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

        # Get user's country and pricing
        user_country = get_user_country(request)
        pricing = plan.get_pricing_for_country(user_country)

        # Get price based on billing cycle
        is_yearly = billing == 'yearly'
        original_price = Decimal(str(pricing['yearly'] if is_yearly else pricing['monthly']))
        price = original_price
        currency = pricing['currency']
        currency_symbol = pricing['symbol']

        # Apply coupon discount if valid
        applied_coupon = None
        discount_amount = Decimal('0')
        if coupon_code:
            coupon = get_valid_coupon(coupon_code)
            if coupon:
                discount_percentage = Decimal(str(coupon.get('discount_percentage', 0)))
                discount_amount = (original_price * discount_percentage / 100).quantize(Decimal('0.01'))
                price = original_price - discount_amount
                applied_coupon = coupon

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

            order_notes = {
                'user_id': str(request.user.id),
                'plan_slug': plan_slug,
                'billing': billing,
            }
            if applied_coupon:
                order_notes['coupon_code'] = applied_coupon['code']
                order_notes['discount_percentage'] = applied_coupon.get('discount_percentage', 0)

            razorpay_order = client.order.create({
                'amount': amount_paise,
                'currency': currency,
                'notes': order_notes
            })

            context = {
                'plan': plan,
                'original_price': original_price,
                'price': price,
                'discount_amount': discount_amount,
                'applied_coupon': applied_coupon,
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
        coupon_code = request.POST.get('coupon_code', '').strip()

        try:
            plan = Plan.objects.get(slug=plan_slug, is_active=True)
        except Plan.DoesNotExist:
            messages.error(request, 'Invalid plan.')
            return redirect('pricing')

        # Get user's country and pricing
        user_country = get_user_country(request)
        pricing = plan.get_pricing_for_country(user_country)
        currency = pricing['currency']

        is_yearly = billing == 'yearly'
        original_price = Decimal(str(pricing['yearly'] if is_yearly else pricing['monthly']))
        price = original_price

        # Apply coupon discount if provided
        applied_coupon = None
        if coupon_code:
            coupon = get_valid_coupon(coupon_code)
            if coupon:
                discount_percentage = Decimal(str(coupon.get('discount_percentage', 0)))
                discount_amount = (original_price * discount_percentage / 100).quantize(Decimal('0.01'))
                price = original_price - discount_amount
                applied_coupon = coupon

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

            # Create transaction record with coupon info if applied
            transaction_metadata = {
                'plan_slug': plan_slug,
                'billing': billing,
            }
            if applied_coupon:
                transaction_metadata['coupon_code'] = applied_coupon['code']
                transaction_metadata['discount_percentage'] = applied_coupon.get('discount_percentage', 0)
                transaction_metadata['original_price'] = str(original_price)

            transaction = Transaction.objects.create(
                user=request.user,
                amount=Decimal(str(price)),
                currency=currency,
                status='success',
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                razorpay_signature=razorpay_signature,
                metadata=transaction_metadata
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
            return redirect('subscription')

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
            return redirect('subscription')

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


# Credit package configuration with country-based pricing
CREDIT_PACKAGES = [
    {
        'id': 'starter',
        'name': 'Starter Pack',
        'credits': 100,
        'price_inr': 99,
        'pricing_data': {
            'default': {'price': 2.99, 'currency': 'USD', 'symbol': '$'},
        },
        'description': 'Great for trying out AI features',
    },
    {
        'id': 'popular',
        'name': 'Popular Pack',
        'credits': 500,
        'price_inr': 449,
        'pricing_data': {
            'default': {'price': 5.99, 'currency': 'USD', 'symbol': '$'},
        },
        'description': 'Best value for regular users',
    },
    {
        'id': 'pro',
        'name': 'Pro Pack',
        'credits': 1200,
        'price_inr': 999,
        'pricing_data': {
            'default': {'price': 10.99, 'currency': 'USD', 'symbol': '$'},
        },
        'description': 'For power users and creators',
    },
]


def get_credit_package_price(package, country_code):
    """Get price for a credit package based on country."""
    if country_code == 'IN':
        return {
            'price': package['price_inr'],
            'currency': 'INR',
            'symbol': '₹'
        }
    # Check for country-specific pricing
    pricing_data = package.get('pricing_data', {})
    if country_code in pricing_data:
        return pricing_data[country_code]
    # Fall back to default international pricing
    return pricing_data.get('default', {'price': package['price_inr'], 'currency': 'INR', 'symbol': '₹'})


class PurchaseCreditsView(LoginRequiredMixin, View):
    """Display credit packages for purchase"""
    template_name = 'core/purchase-credits.html'
    login_url = '/users/login/'

    def get(self, request):
        credits = 0
        if hasattr(request.user, 'profile'):
            credits = request.user.profile.credits

        transactions = CreditTransaction.objects.filter(
            user=request.user,
            status='completed'
        )[:5]

        # Get user's country for pricing
        user_country = get_user_country(request)
        currency_info = get_currency_for_user(request)

        # Build packages with country-specific pricing
        packages_with_pricing = []
        for package in CREDIT_PACKAGES:
            pricing = get_credit_package_price(package, user_country)
            packages_with_pricing.append({
                'id': package['id'],
                'name': package['name'],
                'credits': package['credits'],
                'description': package['description'],
                'price': pricing['price'],
                'currency': pricing['currency'],
                'symbol': pricing['symbol'],
            })

        context = {
            'packages': packages_with_pricing,
            'credits': credits,
            'transactions': transactions,
            'currency': currency_info['currency'],
            'currency_symbol': currency_info['symbol'],
        }
        return render(request, self.template_name, context)


class CreditCheckoutView(LoginRequiredMixin, View):
    """Create Razorpay order for credit purchase"""
    login_url = '/users/login/'

    def post(self, request):
        package_id = request.POST.get('package_id')

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

            # Get country-based pricing
            user_country = get_user_country(request)
            pricing = get_credit_package_price(package, user_country)
            price = pricing['price']
            currency = pricing['currency']

            # Amount in smallest unit (paise for INR, cents for USD)
            amount_smallest_unit = int(price * 100)

            razorpay_order = client.order.create({
                'amount': amount_smallest_unit,
                'currency': currency,
                'notes': {
                    'user_id': str(request.user.id),
                    'package_id': package_id,
                    'credits': package['credits'],
                    'type': 'credits',
                }
            })

            transaction = CreditTransaction.objects.create(
                user=request.user,
                credits=package['credits'],
                amount=Decimal(str(price)),
                currency=currency,
                status='pending',
                razorpay_order_id=razorpay_order['id'],
            )

            return JsonResponse({
                'order_id': razorpay_order['id'],
                'amount': amount_smallest_unit,
                'currency': currency,
                'key_id': razorpay_key,
                'package_name': package['name'],
                'credits': package['credits'],
                'symbol': pricing['symbol'],
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
            transaction = CreditTransaction.objects.get(
                razorpay_order_id=razorpay_order_id,
                user=request.user,
                status='pending'
            )
        except CreditTransaction.DoesNotExist:
            messages.error(request, 'Transaction not found.')
            return redirect('purchase_credits')

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

            transaction.status = 'completed'
            transaction.razorpay_payment_id = razorpay_payment_id
            transaction.razorpay_signature = razorpay_signature
            transaction.save()

            if hasattr(request.user, 'profile'):
                request.user.profile.add_credits(transaction.credits)
                messages.success(request, f'Successfully added {transaction.credits} credits to your account!')
            else:
                messages.error(request, 'Profile not found. Please contact support.')
                return redirect('purchase_credits')

            return redirect('profile')

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
