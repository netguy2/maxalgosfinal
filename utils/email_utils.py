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
from email.utils import formataddr

from database.settings_db import get_email_from_address, get_smtp_settings
from utils.config import get_host_server
from utils.logging import get_logger

logger = get_logger(__name__)


class EmailSendError(Exception):
    """Custom exception for email sending errors"""

    pass


# ─────────────────────────────────────────────────────────────────────────
# Shared brand shell for every transactional/security email below.
#
# Colors are exact hex conversions of the dark-theme OKLCH tokens in
# frontend/src/index.css's `.dark {}` block (not approximated) -- so an
# email opened next to the app UI actually matches instead of using a
# generic near-black/amber palette that happened to look plausible:
#   --background            oklch(0.145 0.005 260)  -> #090a0c
#   --card                  oklch(0.19  0.006 260)  -> #121417
#   --secondary / --muted   oklch(0.255 0.008 260)  -> #212327
#   --brand (dark)          oklch(0.828 0.161 84.43) -> #f7bc28
#   --brand-foreground      oklch(0.22  0.06  84)    -> #271700
#   --profit (dark)         oklch(0.72  0.17  152)   -> #35c26d
#   --loss (dark)           oklch(0.7   0.19  25)    -> #ff645f
#   --muted-foreground      oklch(0.708 0    0)      -> #a1a1a1
#
# The logo is the actual brand mark (frontend/public/logo.png, the gold
# Sri-Yantra emblem used in the app sidebar), referenced by absolute URL --
# email clients strip/mistrust inline base64 images and CID attachments are
# fragile across providers, so a hosted URL via HOST_SERVER is the reliable
# choice, same approach as the reset-link/verify-link URLs already use.
# ─────────────────────────────────────────────────────────────────────────

_EMAIL_BG = "#090a0c"
_EMAIL_CARD = "#121417"
_EMAIL_MUTED_BG = "#1a1c20"
_EMAIL_BORDER = "#25282e"
_EMAIL_BRAND = "#f7bc28"
_EMAIL_BRAND_DARK = "#d99f14"
_EMAIL_BRAND_FOREGROUND = "#271700"
_EMAIL_PROFIT = "#35c26d"
_EMAIL_LOSS = "#ff645f"
_EMAIL_TEXT = "#f5f5f6"
_EMAIL_TEXT_MUTED = "#a1a1a1"
_EMAIL_TEXT_DIM = "#6b6f76"

# Display names Gmail/Outlook show in the inbox list next to each category's
# From address -- previously every email sent with a bare address (e.g.
# "security@maxalgos.com") and no name at all, since message["From"] was set
# to the raw address with nothing wrapping it in email.utils.formataddr.
_SENDER_NAMES = {
    "default": "Max Algos",
    "security": "Max Algos Security",
    "verification": "Max Algos",
    "billing": "Max Algos Billing",
    "notifications": "Max Algos",
}


def _format_from_address(email_address: str, purpose: str = "default") -> str:
    """RFC 2822 'Display Name <address>' From header value for `purpose`.
    Falls back to the plain address if it's already an empty/invalid value
    (formataddr with an empty address would produce a broken header)."""
    if not email_address:
        return email_address
    name = _SENDER_NAMES.get(purpose, _SENDER_NAMES["default"])
    return formataddr((name, email_address))


def _logo_url() -> str:
    return f"{get_host_server().rstrip('/')}/logo.png"


def _email_shell(
    *,
    preheader: str,
    icon_bg: str,
    icon_glyph: str,
    title: str,
    intro_html: str,
    body_html: str,
    footer_note_html: str = "",
) -> str:
    """Shared branded wrapper every email below renders into. `body_html`
    is the category-specific middle section (a details card, a CTA button,
    etc.) -- everything else (header logo, wordmark, footer) is identical
    across every email so the brand reads consistently regardless of which
    one lands in an inbox."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark">
<meta name="supported-color-schemes" content="dark">
<title>{title}</title>
</head>
<body style="margin:0; padding:0; background-color:{_EMAIL_BG}; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<!-- Preheader: hidden preview text shown next to the subject in the inbox list -->
<div style="display:none; max-height:0; overflow:hidden; opacity:0; mso-hide:all;">{preheader}</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:{_EMAIL_BG};">
<tr>
<td align="center" style="padding:32px 20px;">
<table role="presentation" width="100%" style="max-width:480px;">

  <!-- Brand header (logo + wordmark), outside the card -->
  <tr>
    <td style="padding:0 0 24px 0; text-align:center;">
      <img src="{_logo_url()}" width="40" height="40" alt="Max Algos" style="display:inline-block; vertical-align:middle; border-radius:8px;">
      <span style="display:inline-block; vertical-align:middle; margin-left:10px; font-size:18px; font-weight:700; letter-spacing:0.5px; color:{_EMAIL_TEXT};">MAX<span style="color:{_EMAIL_BRAND};">ALGOS</span></span>
    </td>
  </tr>

  <!-- Card -->
  <tr>
    <td style="background-color:{_EMAIL_CARD}; border-radius:16px; border:1px solid {_EMAIL_BORDER}; overflow:hidden;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
        <tr>
          <td style="padding:36px 36px 20px 36px; text-align:center;">
            <div style="width:52px; height:52px; background:{icon_bg}; border-radius:14px; margin:0 auto 20px auto;">
              <table role="presentation" width="100%" height="100%"><tr><td align="center" valign="middle" style="font-size:22px; line-height:52px;">{icon_glyph}</td></tr></table>
            </div>
            <h1 style="margin:0; font-size:21px; font-weight:600; color:{_EMAIL_TEXT}; letter-spacing:-0.3px;">{title}</h1>
            <p style="margin:10px 0 0 0; font-size:14px; color:{_EMAIL_TEXT_MUTED}; line-height:1.5;">{intro_html}</p>
          </td>
        </tr>
        {body_html}
      </table>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="padding:24px 12px 0 12px; text-align:center;">
      {f'<p style="margin:0 0 12px 0; font-size:12px; color:{_EMAIL_TEXT_DIM}; line-height:1.6;">{footer_note_html}</p>' if footer_note_html else ""}
      <p style="margin:0; font-size:12px; color:{_EMAIL_TEXT_DIM};">Max Algos &middot; Algorithmic Trading Platform</p>
    </td>
  </tr>

</table>
</td>
</tr>
</table>
</body>
</html>"""


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
        security_display = "TLS/SSL Enabled" if smtp_settings.get("smtp_use_tls") else "No Encryption"
        sent_at = datetime.now().strftime("%B %d, %Y at %H:%M UTC")

        def _detail_row(label, value, value_color=_EMAIL_TEXT, border=True):
            border_style = f"border-bottom:1px solid {_EMAIL_BORDER};" if border else ""
            return f"""<tr><td style="padding:10px 0; {border_style}">
              <span style="font-size:12px; color:{_EMAIL_TEXT_MUTED}; text-transform:uppercase; letter-spacing:0.5px;">{label}</span><br>
              <span style="font-size:14px; color:{value_color}; font-weight:500;">{value}</span>
            </td></tr>"""

        body_html = f"""
        <tr>
          <td style="padding:4px 36px 32px 36px;">
            <table role="presentation" width="100%" style="background-color:{_EMAIL_MUTED_BG}; border-radius:12px; border:1px solid {_EMAIL_BORDER};" cellpadding="0" cellspacing="0">
              <tr><td style="padding:16px 20px;">
                <table role="presentation" width="100%">
                  {_detail_row("Server", f"{smtp_settings['smtp_server']}:{smtp_settings['smtp_port']}")}
                  {_detail_row("Security", security_display, value_color=_EMAIL_PROFIT)}
                  {_detail_row("Sent to", recipient_email, border=False)}
                </table>
              </td></tr>
            </table>
          </td>
        </tr>"""

        html_content = _email_shell(
            preheader="Your SMTP configuration is working correctly.",
            icon_bg=_EMAIL_PROFIT,
            icon_glyph=f'<span style="color:{_EMAIL_BG};">&#10003;</span>',
            title="Connection verified",
            intro_html="Your SMTP configuration is working correctly.",
            body_html=body_html,
            footer_note_html=f"Sent {sent_at}",
        )

        # Create plain text version
        text_content = f"""SMTP Configuration Test - Success

Your Max Algos SMTP configuration is working correctly.

Server: {smtp_settings["smtp_server"]}:{smtp_settings["smtp_port"]}
Security: {security_display}
Sent to: {recipient_email}

Date: {sent_at}

--
Max Algos
"""

        # Send the email
        result = send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=sender_address,
            from_purpose="default",
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

        body_html = f"""
        <tr>
          <td style="padding:4px 36px 28px 36px; text-align:center;">
            <a href="{reset_link}" style="display:inline-block; background-color:{_EMAIL_BRAND}; color:{_EMAIL_BRAND_FOREGROUND}; padding:13px 32px; text-decoration:none; border-radius:10px; font-size:15px; font-weight:600; letter-spacing:0.2px;">Reset Password</a>
          </td>
        </tr>
        <tr><td style="padding:0 36px;"><div style="height:1px; background-color:{_EMAIL_BORDER};"></div></td></tr>
        <tr>
          <td style="padding:20px 36px;">
            <p style="margin:0 0 10px 0; font-size:13px; color:{_EMAIL_TEXT_MUTED};">&#9201;&nbsp; Link expires in 1 hour</p>
            <p style="margin:0; font-size:13px; color:{_EMAIL_TEXT_MUTED};">&#128274;&nbsp; Never share this link with anyone</p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 36px 24px 36px;">
            <p style="margin:0 0 8px 0; font-size:12px; color:{_EMAIL_TEXT_DIM};">If the button doesn't work, copy this link:</p>
            <p style="margin:0; font-size:12px; color:{_EMAIL_BRAND}; word-break:break-all; background-color:{_EMAIL_MUTED_BG}; padding:12px; border-radius:8px; border:1px solid {_EMAIL_BORDER};">{reset_link}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 36px 32px 36px; text-align:center;">
            <p style="margin:0; font-size:12px; color:{_EMAIL_TEXT_DIM};">Didn't request this? You can safely ignore this email.</p>
          </td>
        </tr>"""

        html_content = _email_shell(
            preheader=f"We received a request to reset your Max Algos password, {user_name}.",
            icon_bg=_EMAIL_BRAND,
            icon_glyph=f'<span style="color:{_EMAIL_BRAND_FOREGROUND};">&#128274;</span>',
            title="Reset your password",
            intro_html=f"Hi {user_name}, we received a request to reset your password.",
            body_html=body_html,
        )

        text_content = f"""Reset your password

Hi {user_name},

We received a request to reset your Max Algos password. Click the link below to set a new password:

{reset_link}

This link expires in 1 hour. Never share this link with anyone.

If you didn't request this, you can safely ignore this email.

--
Max Algos
"""

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=get_email_from_address("security"),
            from_purpose="security",
        )

    except Exception as e:
        error_msg = f"Failed to send password reset email: {str(e)}"
        logger.exception(error_msg)
        return {"success": False, "message": error_msg}


def send_new_device_login_email(
    recipient_email,
    user_name="User",
    device_info="",
    ip_address="",
    login_time_str="",
    browser_display="",
    location_display="",
):
    """
    Send a security alert when the account is accessed from a new device/IP.

    Args:
        recipient_email (str): Email address of the account holder
        user_name (str): Display name / username
        device_info (str): User-Agent string of the new device (fallback
            display when browser_display isn't available)
        ip_address (str): Remote IP of the new device
        login_time_str (str): Human-readable login timestamp
        browser_display (str): Parsed "Chrome 139 on Windows 11" style
            label from Session Intelligence (services/
            session_intelligence_service.py), preferred over the raw UA
            string when available -- see blueprints/auth.py's call site.
        location_display (str): "City, Region, Country" from GeoIP
            (services/geoip_service.py), blank if GeoIP is disabled/
            unconfigured or the IP is private.

    Returns:
        dict: Result with success status and message
    """
    try:
        smtp_settings = get_smtp_settings()
        if not smtp_settings:
            return {"success": False, "message": "SMTP not configured"}

        subject = "New device login detected — Max Algos"

        device_display = browser_display or (device_info or "Unknown browser / device")[:120]
        ip_display = ip_address or "Unknown"
        time_display = login_time_str or "just now"

        def _detail_row(label, value, border=True):
            border_style = f"border-bottom:1px solid {_EMAIL_BORDER};" if border else ""
            return f"""<tr><td style="padding:10px 16px; {border_style}">
              <span style="font-size:12px; color:{_EMAIL_TEXT_MUTED}; text-transform:uppercase; letter-spacing:0.5px;">{label}</span><br>
              <span style="font-size:14px; color:{_EMAIL_TEXT};">{value}</span>
            </td></tr>"""

        rows = [_detail_row("Time", time_display), _detail_row("Device", device_display)]
        if location_display:
            rows.append(_detail_row("Location", location_display))
        rows.append(_detail_row("IP Address", f'<span style="font-family:monospace;">{ip_display}</span>', border=False))

        body_html = f"""
        <tr>
          <td style="padding:4px 36px 28px 36px;">
            <table role="presentation" width="100%" style="background-color:{_EMAIL_MUTED_BG}; border-radius:12px; border:1px solid {_EMAIL_BORDER};" cellpadding="0" cellspacing="0">
              <tr><td><table role="presentation" width="100%">{"".join(rows)}</table></td></tr>
            </table>
          </td>
        </tr>
        <tr><td style="padding:0 36px;"><div style="height:1px; background-color:{_EMAIL_BORDER};"></div></td></tr>
        <tr>
          <td style="padding:20px 36px 32px 36px;">
            <p style="margin:0 0 10px 0; font-size:13px; color:{_EMAIL_PROFIT};">&#9989;&nbsp; If this was you, no action is needed.</p>
            <p style="margin:0; font-size:13px; color:{_EMAIL_LOSS};">&#9888;&nbsp; If this wasn't you, change your password immediately and log out all other devices from your Active Sessions page.</p>
          </td>
        </tr>"""

        html_content = _email_shell(
            preheader=f"Your Max Algos account was accessed from a new device ({device_display}).",
            icon_bg=_EMAIL_BRAND,
            icon_glyph=f'<span style="color:{_EMAIL_BRAND_FOREGROUND};">&#128272;</span>',
            title="New device login",
            intro_html=f"Hi {user_name}, your account was just accessed from a device we haven't seen before.",
            body_html=body_html,
        )

        location_line = f"Location:   {location_display}\n" if location_display else ""
        text_content = f"""New device login detected — Max Algos

Hi {user_name},

Your Max Algos account was just accessed from a device we haven't seen before.

Time:       {time_display}
Device:     {device_display}
{location_line}IP Address: {ip_display}

If this was you, no action is needed.
If this wasn't you, change your password immediately and log out all other devices from your Active Sessions page.

--
Max Algos
"""

        from database.settings_db import get_email_from_address

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=get_email_from_address("security"),
            from_purpose="security",
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

        body_html = f"""
        <tr>
          <td style="padding:4px 36px 28px 36px; text-align:center;">
            <a href="{verify_link}" style="display:inline-block; background-color:{_EMAIL_BRAND}; color:{_EMAIL_BRAND_FOREGROUND}; padding:13px 32px; text-decoration:none; border-radius:10px; font-size:15px; font-weight:600; letter-spacing:0.2px;">Verify Email</a>
          </td>
        </tr>
        <tr><td style="padding:0 36px;"><div style="height:1px; background-color:{_EMAIL_BORDER};"></div></td></tr>
        <tr>
          <td style="padding:20px 36px 4px 36px;">
            <p style="margin:0; font-size:13px; color:{_EMAIL_TEXT_MUTED};">&#9201;&nbsp; Link expires in 24 hours</p>
          </td>
        </tr>
        <tr>
          <td style="padding:16px 36px 24px 36px;">
            <p style="margin:0 0 8px 0; font-size:12px; color:{_EMAIL_TEXT_DIM};">If the button doesn't work, copy this link:</p>
            <p style="margin:0; font-size:12px; color:{_EMAIL_BRAND}; word-break:break-all; background-color:{_EMAIL_MUTED_BG}; padding:12px; border-radius:8px; border:1px solid {_EMAIL_BORDER};">{verify_link}</p>
          </td>
        </tr>
        <tr>
          <td style="padding:0 36px 32px 36px; text-align:center;">
            <p style="margin:0; font-size:12px; color:{_EMAIL_TEXT_DIM};">Didn't create this account? You can safely ignore this email.</p>
          </td>
        </tr>"""

        html_content = _email_shell(
            preheader=f"Confirm your email to activate your Max Algos account, {user_name}.",
            icon_bg=_EMAIL_PROFIT,
            icon_glyph=f'<span style="color:{_EMAIL_BG};">&#9993;</span>',
            title="Verify your account",
            intro_html=f"Hi {user_name}, confirm your email to activate your Max Algos account.",
            body_html=body_html,
        )

        text_content = f"""Verify your account

Hi {user_name},

Confirm your email to activate your Max Algos account:

{verify_link}

This link expires in 24 hours.

If you didn't create this account, you can safely ignore this email.

--
Max Algos
"""

        return send_email(
            recipient_email=recipient_email,
            subject=subject,
            text_content=text_content,
            html_content=html_content,
            smtp_settings=smtp_settings,
            from_email=get_email_from_address("verification"),
            from_purpose="verification",
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
    from_purpose="default",
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
        from_purpose (str): Which _SENDER_NAMES display name to attach to
            the From header (e.g. "security" -> "Max Algos Security").
            Previously every email sent with a bare address and no display
            name at all, so Gmail/Outlook showed the raw address instead of
            a recognizable brand name in the inbox list.

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
        message["From"] = _format_from_address(sender_address, from_purpose)
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
