#pylint: disable=all
import hmac
import hashlib
import json
import logging
from decimal import Decimal, ROUND_DOWN
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.utils import timezone
from django.db import transaction
from django.contrib.auth import get_user_model
from dateutil.relativedelta import relativedelta
from .models import Plan, ContactMessage, Configuration, Subscription, Transaction, CreditTransaction, LinkRedirectEvent
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

        # Check for public coupons — pick best (highest discount)
        public_coupons = get_public_coupons()
        best_coupon = max(public_coupons, key=lambda c: c.get('discount_percentage', 0), default=None) if public_coupons else None

        # Build pricing data for each plan based on user's country
        plans_with_pricing = []
        for plan in plans:
            pricing = plan.get_pricing_for_country(user_country)
            item = {
                'plan': plan,
                'price_monthly': pricing['monthly'],
                'price_yearly': pricing['yearly'],
                'currency': pricing['currency'],
                'symbol': pricing['symbol'],
            }
            # Calculate discounted prices for paid plans
            if best_coupon and pricing['monthly'] > 0:
                discount_pct = Decimal(str(best_coupon.get('discount_percentage', 0)))
                monthly = Decimal(str(pricing['monthly']))
                yearly = Decimal(str(pricing['yearly']))
                item['discounted_monthly'] = float((monthly - monthly * discount_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_DOWN))
                item['discounted_yearly'] = float((yearly - yearly * discount_pct / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_DOWN))
            plans_with_pricing.append(item)

        return render(request, self.template_name, {
            'plans': plans,
            'plans_with_pricing': plans_with_pricing,
            'current_plan': current_plan,
            'best_coupon': best_coupon,
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


def llms_txt(request):
    """Serve llms.txt file for AI/LLM crawlers"""
    return render(request, 'llms.txt', content_type='text/plain')


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


def get_public_coupons():
    """Get active coupons marked as public (for auto-display on pricing/checkout)."""
    coupons_json = Configuration.get_value('coupon_codes', '[]')
    try:
        coupons = json.loads(coupons_json)
        return [c for c in coupons if c.get('active', True) and c.get('public', False)]
    except (json.JSONDecodeError, TypeError):
        return []


def _process_successful_payment(user, plan, billing, razorpay_order_id, razorpay_payment_id,
                                amount, currency, razorpay_signature='', coupon_code='',
                                discount_percentage=None, original_price=None):
    """
    Create Transaction + Subscription for a successful payment.
    Shared by PaymentSuccessView (frontend callback) and PaymentWebhookView (webhook fallback).

    Returns (transaction, subscription) or None if already processed (idempotent).
    """
    # Idempotency check
    if Transaction.objects.filter(
        razorpay_order_id=razorpay_order_id, user=user, status='success'
    ).exists():
        return None

    with transaction.atomic():
        # Double-check inside transaction (another request may have just completed)
        if Transaction.objects.filter(
            razorpay_order_id=razorpay_order_id, user=user, status='success'
        ).exists():
            return None

        # Build metadata
        transaction_metadata = {
            'plan_slug': plan.slug,
            'billing': billing,
        }
        if coupon_code:
            transaction_metadata['coupon_code'] = coupon_code
        if discount_percentage is not None:
            transaction_metadata['discount_percentage'] = discount_percentage
        if original_price is not None:
            transaction_metadata['original_price'] = str(original_price)

        payment_txn = Transaction.objects.create(
            user=user,
            amount=Decimal(str(amount)),
            currency=currency,
            status='success',
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature,
            metadata=transaction_metadata,
        )

        # Calculate subscription dates
        now = timezone.now()
        is_yearly = billing == 'yearly'
        if is_yearly:
            end_date = now + relativedelta(years=1)
            next_reset = now + relativedelta(months=1)
        else:
            end_date = now + relativedelta(months=1)
            next_reset = end_date

        # Create or update subscription
        subscription, created = Subscription.objects.update_or_create(
            user=user,
            defaults={
                'plan': plan,
                'status': 'active',
                'start_date': now,
                'end_date': end_date,
                'is_yearly': is_yearly,
                'usage_data': {},
                'last_reset_date': now,
                'next_reset_date': next_reset,
            }
        )

        # Link transaction to subscription
        payment_txn.subscription = subscription
        payment_txn.save()

        # Reactivate system-deactivated flows up to new plan limit
        from instagram.models import DMFlow
        new_limit = plan.get_feature_limit('ig_flow_builder', 0)
        active_count = DMFlow.objects.filter(user=user, is_active=True).count()
        if new_limit is None or new_limit == 0:
            budget = float('inf')
        else:
            budget = max(0, new_limit - active_count)
        if budget > 0:
            system_deactivated = DMFlow.objects.filter(
                user=user, is_active=False, deactivated_by='system'
            ).order_by('created_at')
            if budget != float('inf'):
                system_deactivated = system_deactivated[:int(budget)]
            reactivate_ids = list(system_deactivated.values_list('id', flat=True))
            if reactivate_ids:
                DMFlow.objects.filter(id__in=reactivate_ids).update(
                    is_active=True, deactivated_by=None
                )

    return (payment_txn, subscription)


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

        # Auto-apply best public coupon if coupon param is not present at all in URL
        # (if 'coupon' key exists but is empty, user explicitly removed it — don't re-apply)
        public_coupons = get_public_coupons()
        if 'coupon' not in request.GET and public_coupons:
            best = max(public_coupons, key=lambda c: c.get('discount_percentage', 0))
            url = f"{request.path}?plan={plan_slug}&billing={billing}&coupon={best['code']}"
            return redirect(url)

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
                'public_coupons': public_coupons,
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

        # Idempotency check: If this order was already processed, redirect to success
        existing_txn = Transaction.objects.filter(
            razorpay_order_id=razorpay_order_id,
            user=request.user,
            status='success'
        ).first()
        if existing_txn:
            messages.info(request, 'This payment has already been processed.')
            if existing_txn.subscription:
                request.session['payment_success_data'] = {
                    'transaction_id': existing_txn.id,
                    'subscription_id': existing_txn.subscription.id,
                }
            return redirect('payment_success_page')

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
        discount_pct = None
        if coupon_code:
            coupon = get_valid_coupon(coupon_code)
            if coupon:
                discount_pct = Decimal(str(coupon.get('discount_percentage', 0)))
                discount_amount = (original_price * discount_pct / 100).quantize(Decimal('0.01'))
                price = original_price - discount_amount

        # Verify signature
        try:
            razorpay_secret = Configuration.get_value('razorpay_api_secret')

            sign_string = f"{razorpay_order_id}|{razorpay_payment_id}"
            expected_signature = hmac.new(
                razorpay_secret.encode(),
                sign_string.encode(),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(expected_signature, razorpay_signature):
                logger.error(f"Payment signature verification failed for user {request.user.id}")
                messages.error(request, 'Payment verification failed. Please contact support.')
                return redirect('pricing')

            result = _process_successful_payment(
                user=request.user,
                plan=plan,
                billing=billing,
                razorpay_order_id=razorpay_order_id,
                razorpay_payment_id=razorpay_payment_id,
                amount=price,
                currency=currency,
                razorpay_signature=razorpay_signature,
                coupon_code=coupon_code,
                discount_percentage=float(discount_pct) if discount_pct else None,
                original_price=original_price if discount_pct else None,
            )

            if result is None:
                messages.info(request, 'This payment has already been processed.')
                return redirect('payment_success_page')

            payment_txn, subscription = result

            # Store success data in session
            request.session['payment_success_data'] = {
                'transaction_id': payment_txn.id,
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

    def get(self, request):
        logger.info("Razorpay webhook GET ping received")
        return JsonResponse({'status': 'ok'})

    def post(self, request):
        try:
            payload = json.loads(request.body)
            event = payload.get('event')

            logger.info(f"Received Razorpay webhook: {event}")

            # Verify webhook signature (mandatory - reject if not configured)
            webhook_secret = Configuration.get_value('razorpay_webhook_secret')
            if not webhook_secret:
                logger.error("Webhook secret not configured - rejecting webhook")
                return JsonResponse({'status': 'configuration_error'}, status=500)

            received_signature = request.headers.get('X-Razorpay-Signature', '')
            expected_signature = hmac.new(
                webhook_secret.encode(),
                request.body,
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(received_signature, expected_signature):
                logger.error("Webhook signature verification failed")
                return JsonResponse({'status': 'invalid_signature'}, status=400)

            # Handle different events
            if event == 'payment.captured':
                payment = payload.get('payload', {}).get('payment', {}).get('entity', {})
                notes = payment.get('notes', {})
                razorpay_payment_id = payment.get('id', '')
                razorpay_order_id = payment.get('order_id', '')

                logger.info(f"Payment captured: {razorpay_payment_id}")

                # Skip credit purchases (handled separately)
                if notes.get('type') == 'credits':
                    logger.info(f"payment.captured: skipping credit purchase {razorpay_payment_id}")
                else:
                    user_id = notes.get('user_id')
                    plan_slug = notes.get('plan_slug')
                    billing = notes.get('billing', 'monthly')
                    coupon_code = notes.get('coupon_code', '')
                    discount_percentage = notes.get('discount_percentage')

                    if not all([user_id, plan_slug, razorpay_payment_id, razorpay_order_id]):
                        logger.warning(f"payment.captured missing required notes: {notes}")
                    else:
                        try:
                            User = get_user_model()
                            user = User.objects.get(id=user_id)
                            plan = Plan.objects.get(slug=plan_slug, is_active=True)
                        except Exception as e:
                            logger.error(f"payment.captured lookup failed: {e}")
                            return JsonResponse({'status': 'ok'})

                        # Amount from Razorpay is in paise/cents
                        amount = Decimal(str(payment.get('amount', 0))) / Decimal('100')
                        currency = payment.get('currency', 'INR')

                        # Compute original_price for metadata if discount was applied
                        original_price = None
                        if discount_percentage:
                            try:
                                dp = Decimal(str(discount_percentage))
                                if dp > 0:
                                    original_price = (amount / (1 - dp / 100)).quantize(Decimal('0.01'))
                            except Exception:
                                pass

                        try:
                            result = _process_successful_payment(
                                user=user,
                                plan=plan,
                                billing=billing,
                                razorpay_order_id=razorpay_order_id,
                                razorpay_payment_id=razorpay_payment_id,
                                amount=amount,
                                currency=currency,
                                coupon_code=coupon_code,
                                discount_percentage=float(discount_percentage) if discount_percentage else None,
                                original_price=original_price,
                            )
                            if result:
                                logger.info(
                                    f"payment.captured: created Transaction+Subscription "
                                    f"for user {user_id}, order {razorpay_order_id}"
                                )
                            else:
                                logger.info(
                                    f"payment.captured: already processed order {razorpay_order_id}"
                                )
                        except Exception as e:
                            logger.error(
                                f"payment.captured processing error for order {razorpay_order_id}: {e}"
                            )

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

        # Check if already completed (idempotency check before locking)
        if CreditTransaction.objects.filter(
            razorpay_order_id=razorpay_order_id,
            user=request.user,
            status='completed'
        ).exists():
            messages.info(request, 'This payment has already been processed.')
            return redirect('profile')

        try:
            # Use atomic transaction with row-level lock to prevent race conditions
            with transaction.atomic():
                try:
                    credit_txn = CreditTransaction.objects.select_for_update().get(
                        razorpay_order_id=razorpay_order_id,
                        user=request.user,
                        status='pending'
                    )
                except CreditTransaction.DoesNotExist:
                    messages.error(request, 'Transaction not found.')
                    return redirect('purchase_credits')

                # Verify signature
                razorpay_secret = Configuration.get_value('razorpay_api_secret')

                sign_string = f"{razorpay_order_id}|{razorpay_payment_id}"
                expected_signature = hmac.new(
                    razorpay_secret.encode(),
                    sign_string.encode(),
                    hashlib.sha256
                ).hexdigest()

                if not hmac.compare_digest(expected_signature, razorpay_signature):
                    logger.error(f"Credit payment signature verification failed for user {request.user.id}")
                    messages.error(request, 'Payment verification failed. Please contact support.')
                    return redirect('purchase_credits')

                # Update transaction and add credits within the same atomic block
                credit_txn.status = 'completed'
                credit_txn.razorpay_payment_id = razorpay_payment_id
                credit_txn.razorpay_signature = razorpay_signature
                credit_txn.save()

                if hasattr(request.user, 'profile'):
                    request.user.profile.add_credits(credit_txn.credits)
                    messages.success(request, f'Successfully added {credit_txn.credits} credits to your account!')
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


COMPETITOR_DATA = {
    'manychat': {
        'name': 'ManyChat',
        'slug': 'manychat',
        'meta_description': 'Compare Maedix vs ManyChat for Instagram automation. Maedix offers a simpler, more affordable alternative with a free plan, visual automation builder, and AI social agents.',
        'hero_subtitle': 'Looking for a simpler, more affordable Instagram automation tool? See how Maedix compares to ManyChat on features, pricing, and ease of use.',
        'pricing_subtitle': 'Maedix offers a generous free plan and lower paid tiers compared to ManyChat.',
        'quick_answer': 'Maedix vs ManyChat: Maedix is a simpler, more affordable Instagram DM automation alternative to ManyChat. Maedix offers a free plan with 1 active automation and unlimited replies ($0/month), Pro at $1.99/month, and Creator at $5.99/month with AI social agents. ManyChat starts free but charges $15+/month for pro features and scales with subscriber count. Maedix focuses on Instagram-only automation with a visual builder, while ManyChat supports multiple platforms but is more complex to set up.',
        'features': [
            {'name': 'Free plan with automations', 'icon': 'bi-gift', 'maedix': True, 'competitor': 'Limited'},
            {'name': 'Visual Automation Builder', 'icon': 'bi-window-stack', 'maedix': True, 'competitor': True},
            {'name': 'Auto Comment Replies', 'icon': 'bi-chat-dots', 'maedix': True, 'competitor': True},
            {'name': 'Auto Follow-up DMs', 'icon': 'bi-envelope', 'maedix': True, 'competitor': True},
            {'name': 'Keyword Triggers', 'icon': 'bi-hash', 'maedix': True, 'competitor': True},
            {'name': 'Quick Reply Buttons', 'icon': 'bi-ui-radios-grid', 'maedix': True, 'competitor': True},
            {'name': 'Follower Check Branching', 'icon': 'bi-person-check', 'maedix': True, 'competitor': False},
            {'name': 'AI Social Agents', 'icon': 'bi-cpu', 'maedix': True, 'competitor': 'Add-on'},
            {'name': 'Smart Queue (viral protection)', 'icon': 'bi-lightning-charge', 'maedix': True, 'competitor': False},
            {'name': 'Unlimited replies (all plans)', 'icon': 'bi-infinity', 'maedix': True, 'competitor': False},
            {'name': 'Multi-platform support', 'icon': 'bi-globe', 'maedix': False, 'competitor': True},
            {'name': 'Simple setup (< 5 min)', 'icon': 'bi-clock', 'maedix': True, 'competitor': False},
            {'name': 'Starting price', 'icon': 'bi-tag', 'maedix': 'Free', 'competitor': '$15/mo'},
        ],
        'pricing_points': [
            'Free plan — limited features, ManyChat branding',
            'Pro starts at $15/month (1,000 contacts)',
            'Price increases with subscriber count',
            'AI features cost extra',
        ],
        'reasons': [
            {'icon': 'bi-currency-dollar', 'title': 'More Affordable', 'description': 'Maedix Pro is just $1.99/month flat vs ManyChat\'s $15+/month that scales with contacts. No surprise bills.'},
            {'icon': 'bi-lightning', 'title': 'Simpler to Use', 'description': 'Maedix is built specifically for Instagram. Set up your first automation in under 5 minutes — no learning curve.'},
            {'icon': 'bi-cpu', 'title': 'AI Built In', 'description': 'AI social agents are included on the Creator plan. ManyChat charges extra for AI capabilities.'},
        ],
        'faq_comparison': 'Maedix is a simpler, Instagram-focused automation platform, while ManyChat supports multiple platforms (Instagram, Facebook, WhatsApp, SMS). If you only need Instagram automation, Maedix is easier to set up and more affordable. ManyChat is better if you need multi-platform messaging. Maedix includes AI social agents and follower check branching, which ManyChat charges extra for or doesn\'t offer.',
        'faq_pricing': 'Yes, Maedix is cheaper than ManyChat for Instagram automation. Maedix offers a free plan with 1 active automation and unlimited replies. Paid plans are $1.99/month (Pro) and $5.99/month (Creator). ManyChat\'s Pro plan starts at $15/month for 1,000 contacts and increases with your audience size.',
        'faq_switch': 'If you primarily use Instagram automation and want a simpler, more affordable tool, switching to Maedix is worth it. You can start with the free plan to test it out. Maedix offers unlimited replies on all plans, built-in AI social agents, and a visual automation builder that\'s easy to learn.',
    },
    'linkdm': {
        'name': 'LinkDM',
        'slug': 'linkdm',
        'meta_description': 'Compare Maedix vs LinkDM for Instagram automation. Maedix offers a free plan, AI social agents, and a visual automation builder at a lower price.',
        'hero_subtitle': 'Both tools automate Instagram DMs, but Maedix offers more features at a lower price point — plus a free plan to get started.',
        'pricing_subtitle': 'Maedix gives you a free tier and more features for less than LinkDM\'s flat rate.',
        'quick_answer': 'Maedix vs LinkDM: Maedix is a more feature-rich Instagram DM automation tool compared to LinkDM. Maedix offers a free plan ($0/month), Pro ($1.99/month), and Creator ($5.99/month) with AI social agents. LinkDM charges a flat $19/month with no free tier. Maedix includes a visual automation builder, follower check branching, smart queue for viral posts, and AI-powered conversations — features not available on LinkDM.',
        'features': [
            {'name': 'Free plan available', 'icon': 'bi-gift', 'maedix': True, 'competitor': False},
            {'name': 'Visual Automation Builder', 'icon': 'bi-window-stack', 'maedix': True, 'competitor': False},
            {'name': 'Auto Comment Replies', 'icon': 'bi-chat-dots', 'maedix': True, 'competitor': True},
            {'name': 'Auto Follow-up DMs', 'icon': 'bi-envelope', 'maedix': True, 'competitor': True},
            {'name': 'Keyword Triggers', 'icon': 'bi-hash', 'maedix': True, 'competitor': True},
            {'name': 'Quick Reply Buttons', 'icon': 'bi-ui-radios-grid', 'maedix': True, 'competitor': False},
            {'name': 'Follower Check Branching', 'icon': 'bi-person-check', 'maedix': True, 'competitor': False},
            {'name': 'AI Social Agents', 'icon': 'bi-cpu', 'maedix': True, 'competitor': False},
            {'name': 'Smart Queue (viral protection)', 'icon': 'bi-lightning-charge', 'maedix': True, 'competitor': False},
            {'name': 'Unlimited replies (all plans)', 'icon': 'bi-infinity', 'maedix': True, 'competitor': True},
            {'name': 'Link in Bio page', 'icon': 'bi-link-45deg', 'maedix': True, 'competitor': False},
            {'name': 'Starting price', 'icon': 'bi-tag', 'maedix': 'Free', 'competitor': '$19/mo'},
        ],
        'pricing_points': [
            'No free plan available',
            'Flat rate — $19/month',
            'No tiered pricing',
            'No AI features included',
        ],
        'reasons': [
            {'icon': 'bi-gift', 'title': 'Free Plan Available', 'description': 'Start automating for free with Maedix. LinkDM has no free tier — you pay $19/month from day one.'},
            {'icon': 'bi-diagram-3', 'title': 'Visual Automation Builder', 'description': 'Build complex conversation flows with drag-and-drop. LinkDM offers basic keyword-to-DM without branching logic.'},
            {'icon': 'bi-cpu', 'title': 'AI-Powered Agents', 'description': 'Maedix Creator plan includes AI social agents for intelligent conversations and data collection.'},
        ],
        'faq_comparison': 'Maedix offers more features than LinkDM at a lower price. Maedix includes a visual automation builder, follower check branching, quick reply buttons, AI social agents, and smart queue protection. LinkDM focuses on basic keyword-triggered DMs without advanced branching or AI capabilities. Maedix also has a free plan, while LinkDM starts at $19/month.',
        'faq_pricing': 'Yes, Maedix is more affordable. Maedix has a free plan and paid plans starting at $1.99/month. LinkDM charges a flat $19/month with no free tier. Even Maedix\'s top Creator plan ($5.99/month) offers significantly more features than LinkDM at a similar price.',
        'faq_switch': 'If you want more advanced automation features like a visual builder, AI agents, follower checking, and quick reply buttons, Maedix is a strong upgrade from LinkDM. You can try Maedix for free before committing to a paid plan.',
    },
    'replyrush': {
        'name': 'ReplyRush',
        'slug': 'replyrush',
        'meta_description': 'Compare Maedix vs ReplyRush for Instagram automation. Maedix offers a free plan, AI social agents, and a visual builder starting at $0/month.',
        'hero_subtitle': 'Both platforms automate Instagram engagement, but Maedix offers a free plan, AI-powered agents, and a visual builder at more affordable pricing.',
        'pricing_subtitle': 'Maedix gives you more value with a free plan and lower entry price.',
        'quick_answer': 'Maedix vs ReplyRush: Maedix is a more affordable Instagram automation tool compared to ReplyRush. Maedix offers a free plan ($0/month), Pro ($1.99/month), and Creator ($5.99/month) with AI social agents and a visual automation builder. ReplyRush charges $19/month with no free tier. Maedix includes smart queue for viral post protection, follower check branching, and link in bio pages.',
        'features': [
            {'name': 'Free plan available', 'icon': 'bi-gift', 'maedix': True, 'competitor': False},
            {'name': 'Visual Automation Builder', 'icon': 'bi-window-stack', 'maedix': True, 'competitor': True},
            {'name': 'Auto Comment Replies', 'icon': 'bi-chat-dots', 'maedix': True, 'competitor': True},
            {'name': 'Auto Follow-up DMs', 'icon': 'bi-envelope', 'maedix': True, 'competitor': True},
            {'name': 'Keyword Triggers', 'icon': 'bi-hash', 'maedix': True, 'competitor': True},
            {'name': 'Quick Reply Buttons', 'icon': 'bi-ui-radios-grid', 'maedix': True, 'competitor': True},
            {'name': 'Follower Check Branching', 'icon': 'bi-person-check', 'maedix': True, 'competitor': False},
            {'name': 'AI Social Agents', 'icon': 'bi-cpu', 'maedix': True, 'competitor': False},
            {'name': 'Smart Queue (viral protection)', 'icon': 'bi-lightning-charge', 'maedix': True, 'competitor': False},
            {'name': 'Unlimited replies (all plans)', 'icon': 'bi-infinity', 'maedix': True, 'competitor': True},
            {'name': 'Link in Bio page', 'icon': 'bi-link-45deg', 'maedix': True, 'competitor': False},
            {'name': 'Starting price', 'icon': 'bi-tag', 'maedix': 'Free', 'competitor': '$19/mo'},
        ],
        'pricing_points': [
            'No free plan available',
            'Flat rate — $19/month',
            'No tiered pricing options',
            'No AI agent features',
        ],
        'reasons': [
            {'icon': 'bi-currency-dollar', 'title': 'Start Free', 'description': 'Maedix offers a free plan with unlimited replies. ReplyRush requires $19/month from day one.'},
            {'icon': 'bi-cpu', 'title': 'AI Social Agents', 'description': 'Maedix Creator plan includes AI-powered conversation agents for intelligent DM interactions and data collection.'},
            {'icon': 'bi-lightning-charge', 'title': 'Smart Queue', 'description': 'When your post goes viral, Maedix\'s smart queue ensures no follower is missed. ReplyRush drops overflow messages.'},
        ],
        'faq_comparison': 'Maedix and ReplyRush both offer Instagram comment and DM automation. Maedix differentiates with a free plan, AI social agents, smart queue for viral posts, and follower check branching. ReplyRush has a $19/month flat rate with no free tier. Maedix is also more affordable with plans starting at $0 (free) and $1.99/month (Pro).',
        'faq_pricing': 'Yes, Maedix is more affordable. It offers a free plan and paid plans at $1.99/month and $5.99/month. ReplyRush charges $19/month flat with no free option. Maedix\'s Pro plan at $1.99/month includes smart queue and 5 active automations.',
        'faq_switch': 'If you\'re looking for a more affordable option with AI capabilities, Maedix is a great alternative to ReplyRush. You can start with the free plan to test the platform, then upgrade to Pro ($1.99/month) or Creator ($5.99/month) for advanced features like AI social agents and smart queue.',
    },
}


class ComparisonView(View):
    """Competitor comparison pages for SEO"""
    template_name = 'core/compare.html'

    def get(self, request, competitor_slug):
        competitor = COMPETITOR_DATA.get(competitor_slug)
        if not competitor:
            from django.http import Http404
            raise Http404("Comparison not found")
        return render(request, self.template_name, {'competitor': competitor})


class LinkRedirectView(View):
    """
    Branded redirect page for watermarked links.
    Shows Maedix branding/ad for a few seconds before redirecting.
    """
    template_name = 'core/link-redirect.html'

    def get(self, request):
        import urllib.parse

        target_url = request.GET.get('url', '').strip()

        if not target_url:
            return render(request, self.template_name, {
                'target_url': '',
                'branding_only': True,
                'adsense_pub_id': Configuration.get_value('adsense_pub_id', ''),
                'adsense_slot_id': Configuration.get_value('adsense_slot_id', ''),
            })

        # Decode URL if needed
        try:
            target_url = urllib.parse.unquote(target_url)
        except Exception:
            pass

        # Basic validation - ensure it looks like a URL
        if not target_url.startswith(('http://', 'https://')):
            target_url = 'https://' + target_url

        # Extract domain
        try:
            target_domain = urllib.parse.urlparse(target_url).netloc[:253]
        except Exception:
            target_domain = ''

        # Get IP
        ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', ''))
        if ',' in ip:
            ip = ip.split(',')[0].strip()

        # Get referrer
        referrer = request.META.get('HTTP_REFERER', '')
        if referrer:
            try:
                parsed = urllib.parse.urlparse(referrer)
                if not parsed.scheme or not parsed.netloc:
                    referrer = ''
            except Exception:
                referrer = ''

        # Log the redirect event
        event = LinkRedirectEvent.objects.create(
            target_url=target_url[:2000],
            target_domain=target_domain,
            ip_hash=LinkRedirectEvent.hash_ip(ip),
            referrer=referrer[:2000],
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:300],
        )

        return render(request, self.template_name, {
            'target_url': target_url,
            'redirect_delay': 3,  # seconds before redirect
            'event_id': event.pk,
            'adsense_pub_id': Configuration.get_value('adsense_pub_id', ''),
            'adsense_slot_id': Configuration.get_value('adsense_slot_id', ''),
        })


@method_decorator(csrf_exempt, name='dispatch')
class LinkRedirectPingView(View):
    """Receives duration/click data from the redirect page via sendBeacon."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, AttributeError):
            return JsonResponse({'error': 'bad json'}, status=400)

        event_id = data.get('event_id')
        duration_ms = data.get('duration_ms')
        clicked = data.get('clicked', False)

        if not event_id:
            return JsonResponse({'error': 'missing event_id'}, status=400)

        updated = LinkRedirectEvent.objects.filter(
            pk=event_id, duration_ms__isnull=True
        ).update(
            duration_ms=min(int(duration_ms), 600_000) if duration_ms else None,
            clicked=bool(clicked),
        )

        if not updated:
            return JsonResponse({'status': 'skipped'})

        return JsonResponse({'status': 'ok'})
