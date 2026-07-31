"""
Email Utility Functions for Max Algos

This module provides email sending functionality for SMTP configuration testing
and password reset notifications.
"""

import os
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from database.settings_db import get_email_from_address, get_smtp_settings
from utils.logging import get_logger

logger = get_logger(__name__)


class EmailSendError(Exception):
    """Custom exception for email sending errors"""

    pass


def send_test_email(recipient_email, sender_name="Max Algos Admin"):
    """
    Send a test email to verify SMTP configuration.

    Args:
        recipient_email (str): Email address to send test email to
        sender_name (str): Name of the sender

    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {
                "success": False,
                "message": "SMTP settings not configured. Please configure SMTP settings first.",
            }

        # Validate required transport settings. From-address is checked
        # separately below via the same identity fallback chain (Platform
        # Email Identities' Default Sender -> legacy smtp_from_email) that
        # send_email() actually sends with -- checking smtp_from_email alone
        # here rejected setups that only filled in "Default Sender" on the
        # Platform Email Identities panel (which writes smtp_email_default,
        # not smtp_from_email) even though a real send would have resolved
        # a From address just fine.
        required_fields = [
            "smtp_server",
            "smtp_port",
            "smtp_username",
            "smtp_password",
        ]
        missing_fields = [field for field in required_fields if not smtp_settings.get(field)]

        sender_address = get_email_from_address("default")
        if not sender_address:
            missing_fields.append("from_email (set a Default Sender under Platform Email Identities)")

        if missing_fields:
            return {
                "success": False,
                "message": f"Missing required SMTP settings: {', '.join(missing_fields)}",
            }

        # Create test email content
        subject = "Max Algos - SMTP Test Successful"

        # Create modern minimalistic HTML email
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SMTP Test</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0a0a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="100%" style="max-width: 480px; background-color: #141414; border-radius: 16px; overflow: hidden; border: 1px solid #262626;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 30px 40px; text-align: center;">
                            <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); border-radius: 14px; margin: 0 auto 24px auto;">
                                <table role="presentation" width="100%" height="100%">
                                    <tr>
                                        <td align="center" valign="middle" style="font-size: 28px; color: #1a1a1a;">&#10003;</td>
                                    </tr>
                                </table>
                            </div>
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #fafafa; letter-spacing: -0.5px;">Connection Verified</h1>
                            <p style="margin: 12px 0 0 0; font-size: 15px; color: #a1a1aa;">Your SMTP configuration is working</p>
                        </td>
                    </tr>

                    <!-- Details Card -->
                    <tr>
                        <td style="padding: 0 40px 30px 40px;">
                            <table role="presentation" width="100%" style="background-color: #1c1c1c; border-radius: 12px; border: 1px solid #262626;">
                                <tr>
                                    <td style="padding: 20px;">
                                        <table role="presentation" width="100%">
                                            <tr>
                                                <td style="padding: 8px 0; border-bottom: 1px solid #262626;">
                                                    <span style="font-size: 13px; color: #71717a;">Server</span><br>
                                                    <span style="font-size: 14px; color: #e4e4e7; font-weight: 500;">{smtp_settings["smtp_server"]}:{smtp_settings["smtp_port"]}</span>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0; border-bottom: 1px solid #262626;">
                                                    <span style="font-size: 13px; color: #71717a;">Security</span><br>
                                                    <span style="font-size: 14px; color: #22c55e; font-weight: 500;">{"TLS/SSL Enabled" if smtp_settings.get("smtp_use_tls") else "No Encryption"}</span>
                                                </td>
                                            </tr>
                                            <tr>
                                                <td style="padding: 8px 0;">
                                                    <span style="font-size: 13px; color: #71717a;">Sent to</span><br>
                                                    <span style="font-size: 14px; color: #e4e4e7; font-weight: 500;">{recipient_email}</span>
                                                </td>
                                            </tr>
                                        </table>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 0 40px 40px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 13px; color: #52525b;">
                                {datetime.now().strftime("%B %d, %Y at %H:%M UTC")}
                            </p>
                            <p style="margin: 16px 0 0 0; font-size: 12px; color: #3f3f46;">
                                Sent by <span style="color: #a1a1aa;">Max Algos</span>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        # Create plain text version
        text_content = f"""
SMTP Configuration Test - Success

Your Max Algos SMTP configuration is working correctly.

Server: {smtp_settings["smtp_server"]}:{smtp_settings["smtp_port"]}
Security: {"TLS/SSL Enabled" if smtp_settings.get("smtp_use_tls") else "No Encryption"}
Sent to: {recipient_email}

Date: {datetime.now().strftime("%B %d, %Y at %H:%M UTC")}

--
Sent by Max Algos
        """

        # Send the email
        result = send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=sender_address,
        )

        if result["success"]:
            logger.info(f"Test email sent successfully to {recipient_email}")
            return {
                "success": True,
                "message": f"Test email sent successfully to {recipient_email}. Please check your inbox (and spam folder).",
            }
        else:
            return result

    except Exception as e:
        error_msg = f"Failed to send test email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


def send_password_reset_email(recipient_email, reset_link, user_name="User"):
    """
    Send password reset email.

    Args:
        recipient_email (str): Email address to send reset email to
        reset_link (str): Password reset link
        user_name (str): Name of the user

    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {"success": False, "message": "SMTP not configured"}

        subject = "Reset your Max Algos password"

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Password Reset</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0a0a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="100%" style="max-width: 480px; background-color: #141414; border-radius: 16px; overflow: hidden; border: 1px solid #262626;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 24px 40px; text-align: center;">
                            <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%); border-radius: 14px; margin: 0 auto 24px auto;">
                                <table role="presentation" width="100%" height="100%">
                                    <tr>
                                        <td align="center" valign="middle" style="font-size: 24px; color: #ffffff;">&#128274;</td>
                                    </tr>
                                </table>
                            </div>
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #fafafa; letter-spacing: -0.5px;">Reset your password</h1>
                            <p style="margin: 12px 0 0 0; font-size: 15px; color: #a1a1aa; line-height: 1.5;">Hi {user_name}, we received a request to reset your password.</p>
                        </td>
                    </tr>

                    <!-- Button -->
                    <tr>
                        <td style="padding: 8px 40px 32px 40px; text-align: center;">
                            <a href="{reset_link}" style="display: inline-block; background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); color: #ffffff; padding: 14px 32px; text-decoration: none; border-radius: 10px; font-size: 15px; font-weight: 600; letter-spacing: 0.3px;">Reset Password</a>
                        </td>
                    </tr>

                    <!-- Divider -->
                    <tr>
                        <td style="padding: 0 40px;">
                            <div style="height: 1px; background-color: #262626;"></div>
                        </td>
                    </tr>

                    <!-- Security Notice -->
                    <tr>
                        <td style="padding: 24px 40px;">
                            <table role="presentation" width="100%">
                                <tr>
                                    <td style="padding-bottom: 12px;">
                                        <span style="font-size: 13px; color: #71717a; display: flex; align-items: center;">
                                            <span style="margin-right: 8px;">&#9201;</span> Link expires in 1 hour
                                        </span>
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <span style="font-size: 13px; color: #71717a; display: flex; align-items: center;">
                                            <span style="margin-right: 8px;">&#128274;</span> Never share this link
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Link fallback -->
                    <tr>
                        <td style="padding: 0 40px 24px 40px;">
                            <p style="margin: 0 0 8px 0; font-size: 12px; color: #52525b;">If the button doesn't work, copy this link:</p>
                            <p style="margin: 0; font-size: 12px; color: #3b82f6; word-break: break-all; background-color: #1c1c1c; padding: 12px; border-radius: 8px; border: 1px solid #262626;">{reset_link}</p>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 16px 40px 32px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #3f3f46;">
                                Didn't request this? You can safely ignore this email.
                            </p>
                            <p style="margin: 16px 0 0 0; font-size: 12px; color: #3f3f46;">
                                Sent by <span style="color: #a1a1aa;">Max Algos</span>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        text_content = f"""
Reset your password

Hi {user_name},

We received a request to reset your Max Algos password. Click the link below to set a new password:

{reset_link}

This link expires in 1 hour. Never share this link with anyone.

If you didn't request this, you can safely ignore this email.

--
Sent by Max Algos
        """

        from database.settings_db import get_email_from_address

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=get_email_from_address("security"),
        )

    except Exception as e:
        error_msg = f"Failed to send password reset email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


def send_new_device_login_email(
    recipient_email, user_name="User", device_info="", ip_address="", login_time_str=""
):
    """
    Send a security alert when the account is accessed from a new device/IP.

    Args:
        recipient_email (str): Email address of the account holder
        user_name (str): Display name / username
        device_info (str): User-Agent string of the new device
        ip_address (str): Remote IP of the new device
        login_time_str (str): Human-readable login timestamp

    Returns:
        dict: Result with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {"success": False, "message": "SMTP not configured"}

        subject = "New device login detected — Max Algos"

        # Truncate the UA string so it's readable in the email
        device_display = (device_info or "Unknown browser / device")[:120]
        ip_display = ip_address or "Unknown"
        time_display = login_time_str or "just now"

        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>New Device Login</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0a0a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="100%" style="max-width: 480px; background-color: #141414; border-radius: 16px; overflow: hidden; border: 1px solid #262626;">
                    <!-- Header -->
                    <tr>
                        <td style="padding: 40px 40px 24px 40px; text-align: center;">
                            <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); border-radius: 14px; margin: 0 auto 24px auto;">
                                <table role="presentation" width="100%" height="100%">
                                    <tr>
                                        <td align="center" valign="middle" style="font-size: 24px; color: #ffffff;">&#128272;</td>
                                    </tr>
                                </table>
                            </div>
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #fafafa; letter-spacing: -0.5px;">New device login</h1>
                            <p style="margin: 12px 0 0 0; font-size: 15px; color: #a1a1aa; line-height: 1.5;">Hi {user_name}, your Max Algos account was just accessed from a device we haven't seen before.</p>
                        </td>
                    </tr>

                    <!-- Login Details -->
                    <tr>
                        <td style="padding: 8px 40px 32px 40px;">
                            <table role="presentation" width="100%" style="background-color: #1c1c1c; border-radius: 10px; border: 1px solid #262626; padding: 20px;" cellpadding="0" cellspacing="0">
                                <tr>
                                    <td style="padding: 8px 16px;">
                                        <p style="margin: 0 0 4px 0; font-size: 12px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px;">Time</p>
                                        <p style="margin: 0; font-size: 14px; color: #e4e4e7;">{time_display}</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 16px;">
                                        <p style="margin: 0 0 4px 0; font-size: 12px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px;">IP Address</p>
                                        <p style="margin: 0; font-size: 14px; color: #e4e4e7; font-family: monospace;">{ip_display}</p>
                                    </td>
                                </tr>
                                <tr>
                                    <td style="padding: 8px 16px;">
                                        <p style="margin: 0 0 4px 0; font-size: 12px; color: #71717a; text-transform: uppercase; letter-spacing: 0.5px;">Device</p>
                                        <p style="margin: 0; font-size: 13px; color: #a1a1aa; word-break: break-all;">{device_display}</p>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Divider -->
                    <tr>
                        <td style="padding: 0 40px;">
                            <div style="height: 1px; background-color: #262626;"></div>
                        </td>
                    </tr>

                    <!-- Security Notice -->
                    <tr>
                        <td style="padding: 24px 40px;">
                            <table role="presentation" width="100%">
                                <tr>
                                    <td style="padding-bottom: 12px;">
                                        <span style="font-size: 13px; color: #71717a;">
                                            <span style="margin-right: 8px;">&#9989;</span> If this was you, no action is needed.
                                        </span>
                                    </td>
                                </tr>
                                <tr>
                                    <td>
                                        <span style="font-size: 13px; color: #f87171;">
                                            <span style="margin-right: 8px;">&#9888;&#65039;</span> If this wasn't you, change your password immediately and log out all other devices from your Active Sessions page.
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="padding: 16px 40px 32px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #3f3f46;">
                                Sent by <span style="color: #a1a1aa;">Max Algos</span>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""

        text_content = f"""New device login detected — Max Algos

Hi {user_name},

Your Max Algos account was just accessed from a device we haven't seen before.

Time:       {time_display}
IP Address: {ip_display}
Device:     {device_display}

If this was you, no action is needed.
If this wasn't you, change your password immediately and log out all other devices from your Active Sessions page.

--
Sent by Max Algos
"""

        from database.settings_db import get_email_from_address

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=get_email_from_address("security"),
        )

    except Exception as e:
        error_msg = f"Failed to send new-device login email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


def send_verification_email(recipient_email, verify_link, user_name="User"):
    """
    Send self-service signup email-verification link.

    Args:
        recipient_email (str): Email address to send the verification link to
        verify_link (str): Verification link
        user_name (str): Name of the user

    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {"success": False, "message": "SMTP not configured"}

        subject = "Verify your Max Algos account"

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Verify your account</title>
</head>
<body style="margin: 0; padding: 0; background-color: #0a0a0a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="min-height: 100vh;">
        <tr>
            <td align="center" style="padding: 40px 20px;">
                <table role="presentation" width="100%" style="max-width: 480px; background-color: #141414; border-radius: 16px; overflow: hidden; border: 1px solid #262626;">
                    <tr>
                        <td style="padding: 40px 40px 24px 40px; text-align: center;">
                            <div style="width: 56px; height: 56px; background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); border-radius: 14px; margin: 0 auto 24px auto;">
                                <table role="presentation" width="100%" height="100%">
                                    <tr>
                                        <td align="center" valign="middle" style="font-size: 24px; color: #1a1a1a;">&#9993;</td>
                                    </tr>
                                </table>
                            </div>
                            <h1 style="margin: 0; font-size: 24px; font-weight: 600; color: #fafafa; letter-spacing: -0.5px;">Verify your account</h1>
                            <p style="margin: 12px 0 0 0; font-size: 15px; color: #a1a1aa; line-height: 1.5;">Hi {user_name}, confirm your email to activate your Max Algos account.</p>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 8px 40px 32px 40px; text-align: center;">
                            <a href="{verify_link}" style="display: inline-block; background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%); color: #0a0a0a; padding: 14px 32px; text-decoration: none; border-radius: 10px; font-size: 15px; font-weight: 600; letter-spacing: 0.3px;">Verify Email</a>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 0 40px;">
                            <div style="height: 1px; background-color: #262626;"></div>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 24px 40px;">
                            <span style="font-size: 13px; color: #71717a;">&#9201; Link expires in 24 hours</span>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 0 40px 24px 40px;">
                            <p style="margin: 0 0 8px 0; font-size: 12px; color: #52525b;">If the button doesn't work, copy this link:</p>
                            <p style="margin: 0; font-size: 12px; color: #22c55e; word-break: break-all; background-color: #1c1c1c; padding: 12px; border-radius: 8px; border: 1px solid #262626;">{verify_link}</p>
                        </td>
                    </tr>

                    <tr>
                        <td style="padding: 16px 40px 32px 40px; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #3f3f46;">
                                Didn't create this account? You can safely ignore this email.
                            </p>
                            <p style="margin: 16px 0 0 0; font-size: 12px; color: #3f3f46;">
                                Sent by <span style="color: #a1a1aa;">Max Algos</span>
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
        """

        text_content = f"""
Verify your account

Hi {user_name},

Confirm your email to activate your Max Algos account:

{verify_link}

This link expires in 24 hours.

If you didn't create this account, you can safely ignore this email.

--
Sent by Max Algos
        """

        from database.settings_db import get_email_from_address

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=get_email_from_address("verification"),
        )

    except Exception as e:
        error_msg = f"Failed to send verification email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


def send_email(
    recipient_email,
    subject,
    text_content,
    html_content=None,
    smtp_settings=None,
    from_email=None,
    reply_to=None,
):
    """
    Generic email sending function.

    Args:
        recipient_email (str): Recipient email address
        subject (str): Email subject
        text_content (str): Plain text content
        html_content (str, optional): HTML content
        smtp_settings (dict, optional): SMTP settings (fetched if not provided)
        from_email (str, optional): "From" address to use for this email --
            overrides smtp_settings["smtp_from_email"]. Callers should
            resolve this via database.settings_db.get_email_from_address(
            purpose) so different email categories (verification, security,
            billing, notifications) can appear to come from different
            aliases on the same underlying SMTP mailbox (see Platform Email
            Identities in Settings). Falls back to
            smtp_settings["smtp_from_email"] if not provided, so existing
            callers that don't pass this keep working unchanged.
        reply_to (str, optional): Reply-To address, independent of From.

    Returns:
        dict: Result dictionary with success status and message
    """
    try:
        if not smtp_settings:
            smtp_settings = get_smtp_settings()
            if not smtp_settings:
                return {"success": False, "message": "SMTP settings not configured"}

        sender_address = from_email or smtp_settings["smtp_from_email"]

        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = sender_address
        message["To"] = recipient_email
        if reply_to:
            message["Reply-To"] = reply_to

        # Add text content
        text_part = MIMEText(text_content, "plain")
        message.attach(text_part)

        # Add HTML content if provided
        if html_content:
            html_part = MIMEText(html_content, "html")
            message.attach(html_part)

        # Determine connection method based on port and settings
        smtp_port = smtp_settings["smtp_port"]
        use_tls = smtp_settings.get("smtp_use_tls", True)

        # Create SSL context
        context = ssl.create_default_context()
        # For Gmail relay, we might need to be less strict about certificates
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # Choose connection method based on port
        if smtp_port == 465:
            # Port 465 uses SSL from the start (SMTPS)
            logger.info(f"Using SMTP_SSL for port {smtp_port}")
            server = smtplib.SMTP_SSL(smtp_settings["smtp_server"], smtp_port, context=context)
            # Send EHLO after SSL connection
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)
        else:
            # Port 587 or others use SMTP with STARTTLS
            logger.info(f"Using SMTP with STARTTLS for port {smtp_port}")
            server = smtplib.SMTP(smtp_settings["smtp_server"], smtp_port)

            # Send initial EHLO
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)

            # Enable TLS if configured
            if use_tls:
                server.starttls(context=context)
                # MUST send EHLO again after STARTTLS
                server.ehlo(helo_hostname)

        # Optional SMTP conversation logging for diagnosing provider auth
        # failures (e.g. "535 5.7.8 Authentication failed"). Off by default.
        #
        # SECURITY: do NOT re-enable smtplib's raw set_debuglevel(1) output
        # here, even behind a redacting filter. A prior version of this code
        # tried exactly that -- filtering lines containing the literal
        # plaintext password or the substring "AUTH" -- and it leaked the
        # real mailbox password into production logs anyway: smtplib's AUTH
        # LOGIN flow sends the username and password as separate base64
        # "send:" lines (e.g. send: 'QXNkZkAxMjM0\r\n') that contain neither
        # the plaintext password nor the word "AUTH", so the filter never
        # matched them. Content-based redaction of an arbitrary debug stream
        # is inherently unreliable for this. Instead, log only smtplib's
        # numeric reply codes and server-supplied text via SMTPResponseException
        # handling below (server messages are never secret -- they're what
        # the provider chose to send back) and never touch server.set_debuglevel
        # or server._print_debug at all.
        if os.getenv("SMTP_DEBUG_LOG", "").lower() in ("1", "true", "yes"):
            logger.info(
                f"SMTP debug: connecting to {smtp_settings['smtp_server']}:{smtp_port} "
                f"as {smtp_settings['smtp_username']} (TLS={use_tls})"
            )

        # Login and send email
        server.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])
        # sendmail() does NOT raise for a recipient the server accepted the
        # connection for but then refused mid-transaction (e.g. "From"
        # address not authorized to relay, recipient rejected by policy) --
        # it returns a {recipient: (code, message)} dict for EACH refused
        # recipient instead, while every OTHER recipient (there's only one
        # here) still goes through silently. Treating a non-empty dict as
        # success was reporting "sent" for emails that were actually
        # rejected and never delivered.
        refused = server.sendmail(sender_address, recipient_email, message.as_string())
        server.quit()

        if refused:
            code, refusal_message = next(iter(refused.values()))
            error_msg = (
                f"SMTP server refused the recipient ({code}: "
                f"{refusal_message.decode() if isinstance(refusal_message, bytes) else refusal_message}). "
                "Common cause: the 'From' address doesn't match the authenticated SMTP account, "
                "or the account isn't authorized to relay mail to external addresses."
            )
            logger.error(f"Email to {recipient_email} was refused by SMTP server: {refused}")
            return {"success": False, "message": error_msg}

        logger.info(f"Email sent successfully to {recipient_email}")
        return {"success": True, "message": "Email sent successfully"}

    except smtplib.SMTPAuthenticationError as e:
        # Surface the SERVER's actual response, not a generic message. Titan,
        # M365, Gmail etc. each explain *why* auth failed in this text (SMTP
        # AUTH disabled, app-password required, sending-IP not allowed, wrong
        # mailbox password vs. control-panel password, etc.). Hiding it behind
        # "check your username and password" makes provider migration blind.
        server_code = getattr(e, "smtp_code", None)
        server_error = getattr(e, "smtp_error", b"")
        if isinstance(server_error, bytes):
            server_error = server_error.decode(errors="replace")
        error_msg = (
            f"SMTP authentication failed ({server_code}: {server_error}). "
            f"Server={smtp_settings.get('smtp_server')}, user={smtp_settings.get('smtp_username')}. "
            "Use the mailbox's own password (for Titan/GoDaddy this is the email "
            "password, NOT your GoDaddy account login), and if the mailbox has 2FA "
            "use an app-specific password. Confirm SMTP/authenticated-send is enabled "
            "for this mailbox."
        )
        logger.error(f"SMTP Auth Error: code={server_code} error={server_error}")
        return {"success": False, "message": error_msg}
    except smtplib.SMTPServerDisconnected as e:
        error_msg = (
            f"SMTP server disconnected ({e}). Check the server hostname/port are "
            f"correct (currently {smtp_settings.get('smtp_server')}:{smtp_settings.get('smtp_port')}) "
            "and that TLS matches the port (587=STARTTLS, 465=SSL)."
        )
        logger.error(f"SMTP Disconnected: {e}")
        return {"success": False, "message": error_msg}
    except smtplib.SMTPException as e:
        error_str = str(e)
        server = smtp_settings.get("smtp_server", "")
        logger.error(f"SMTP Exception ({server}): {e}")

        # Provider-agnostic guidance. The raw server message is always kept in
        # error_msg; provider-specific hints are additive, never a replacement,
        # so migrating providers (Gmail -> Titan -> M365 -> ...) never hides the
        # real cause behind a stale vendor-specific string.
        error_msg = f"SMTP error from {server or 'server'}: {error_str}"
        if "relay" in error_str.lower() or "not authorized" in error_str.lower():
            error_msg += (
                " — the 'From' address is likely not authorized to send from this "
                "mailbox. Set the Default Sender to the authenticated mailbox itself, "
                "or add the alias as a verified sending address on the mailbox."
            )
        elif "auth" in error_str.lower():
            error_msg += (
                " — use the mailbox's own password (an app-specific password if the "
                "mailbox has 2FA), and confirm authenticated SMTP is enabled for it."
            )

        return {"success": False, "message": error_msg}
    except Exception as e:
        error_msg = f"Failed to send email: {str(e)}"
        logger.exception(f"Email sending failed: {e}")
        return {"success": False, "message": error_msg}


def validate_smtp_settings(smtp_settings):
    """
    Validate SMTP settings without sending an email.

    Args:
        smtp_settings (dict): SMTP configuration

    Returns:
        dict: Validation result
    """
    try:
        required_fields = [
            "smtp_server",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_from_email",
        ]
        missing_fields = [field for field in required_fields if not smtp_settings.get(field)]

        if missing_fields:
            return {
                "success": False,
                "message": f"Missing required fields: {', '.join(missing_fields)}",
            }

        # Test connection without sending email
        smtp_port = smtp_settings["smtp_port"]
        use_tls = smtp_settings.get("smtp_use_tls", True)

        # Create SSL context
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        # Choose connection method based on port
        if smtp_port == 465:
            # Port 465 uses SSL from the start (SMTPS)
            server = smtplib.SMTP_SSL(smtp_settings["smtp_server"], smtp_port, context=context)
            # Send EHLO after SSL connection
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)
        else:
            # Port 587 or others use SMTP with STARTTLS
            server = smtplib.SMTP(smtp_settings["smtp_server"], smtp_port)

            # Send initial EHLO
            helo_hostname = smtp_settings.get("smtp_helo_hostname") or smtp_settings["smtp_server"]
            server.ehlo(helo_hostname)

            # Enable TLS if configured
            if use_tls:
                server.starttls(context=context)
                # MUST send EHLO again after STARTTLS
                server.ehlo(helo_hostname)

        server.login(smtp_settings["smtp_username"], smtp_settings["smtp_password"])
        server.quit()

        return {"success": True, "message": "SMTP connection successful"}

    except Exception as e:
        return {"success": False, "message": f"SMTP validation failed: {str(e)}"}
