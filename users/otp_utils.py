from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from .models import EmailOTP


def send_otp_email(user):
    """Generate OTP and send verification email to user"""
    # Create OTP for user
    email_otp = EmailOTP.create_for_user(user)

    # Prepare email content
    subject = 'Verify Your Maedix-Q Account'
    context = {
        'user': user,
        'otp': email_otp.otp,
        'expiry_minutes': 10,
    }

    # Render email template
    message = render_to_string('users/emails/otp-verification-email.html', context)

    # Send email
    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )

    return email_otp


def verify_otp(user, otp_code):
    """Verify OTP for user. Returns (success, message) tuple."""
    try:
        email_otp = EmailOTP.objects.filter(
            user=user,
            is_verified=False
        ).latest('created_at')
    except EmailOTP.DoesNotExist:
        return False, 'No OTP found. Please request a new one.'

    if email_otp.is_expired:
        return False, 'OTP has expired. Please request a new one.'

    if email_otp.otp != otp_code:
        return False, 'Invalid OTP. Please try again.'

    # Mark OTP as verified
    email_otp.is_verified = True
    email_otp.save()

    # Activate user
    user.is_active = True
    user.save()

    return True, 'Email verified successfully!'
