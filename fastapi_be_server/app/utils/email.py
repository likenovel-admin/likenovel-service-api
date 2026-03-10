import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from urllib.parse import urlencode

from app.const import settings

import logging

logger = logging.getLogger(__name__)


def _send_email_sync(to_email: str, subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM_EMAIL))
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM_EMAIL, to_email, msg.as_string())


async def send_email(to_email: str, subject: str, html_body: str):
    await asyncio.to_thread(_send_email_sync, to_email, subject, html_body)


async def send_password_reset_email(to_email: str, token: str):
    subject = "[라이크노벨] 비밀번호 재설정"
    params = urlencode({"email": to_email, "token": token})
    reset_url = f"{settings.SERVICE_FRONTEND_URL}/reset-password?{params}"

    html_body = f"""
    <div style="max-width:480px;margin:0 auto;font-family:'Apple SD Gothic Neo',sans-serif;">
        <div style="padding:40px 30px;background:#fff;border:1px solid #e5e7eb;border-radius:16px;">
            <h2 style="margin:0 0 8px;font-size:20px;color:#111317;">비밀번호 재설정</h2>
            <p style="margin:0 0 32px;font-size:14px;color:#6b7280;">
                아래 버튼을 눌러 비밀번호를 재설정해주세요.<br>
                링크는 5분간 유효합니다.
            </p>
            <div style="text-align:center;">
                <a href="{reset_url}"
                   style="display:inline-block;padding:14px 40px;background:#111317;color:#fff;
                          font-size:16px;font-weight:600;text-decoration:none;border-radius:10px;">
                    비밀번호 재설정
                </a>
            </div>
            <p style="margin:24px 0 0;font-size:12px;color:#9ca3af;">
                본인이 요청하지 않았다면 이 메일을 무시해주세요.
            </p>
        </div>
    </div>
    """
    await send_email(to_email, subject, html_body)
