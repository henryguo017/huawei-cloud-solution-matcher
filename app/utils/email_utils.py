import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, FRONTEND_URL, RESET_TOKEN_EXPIRE_MINUTES
import logging

logger = logging.getLogger(__name__)

def smtp_configured() -> bool:
    """SMTP 是否已配置（SMTP_USER/SMTP_PASS 非空）。供上层在查库前快速失败，统一报错不泄露邮箱是否存在。"""
    return bool(SMTP_USER and SMTP_PASS)

def _smtp_send(email: str, subject: str, html_body: str) -> bool:
    """通用 SMTP 发送（SSL 465 / STARTTLS 兼容）。成功 True，任何失败 False（日志留痕）。"""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = email
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logger.error(f"❌ 邮件发送失败（{subject}）→ {email}: {e}")
        return False

def _email_shell(title: str, inner_html: str) -> str:
    """邮件统一外壳（与既有重置邮件同款式）。"""
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="color: white; margin: 0;">华为云解决方案匹配系统</h1>
            </div>
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                {inner_html}
                <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                <p style="color: #888; font-size: 12px;">此邮件由系统自动发送，请勿回复。</p>
            </div>
        </div>
    </body>
    </html>
    """

def send_reset_email(email: str, token: str) -> bool:
    """
    发送密码重置邮件
    :param email: 收件人邮箱
    :param token: 重置 token
    :return: 是否发送成功
    """
    # SMTP 未配置时显式告警；上层（forgot_password）在查库前用 smtp_configured() 快速失败，
    # 这里兜底返回 False 并留服务端日志。
    if not smtp_configured():
        logger.error(
            "[reset] SMTP 未配置（SMTP_USER/SMTP_PASS 为空），密码重置邮件无法发送！"
            "请在服务器 .env 配置 SMTP_USER/SMTP_PASS 后重启服务。"
        )
        return False

    reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
    inner = f"""
        <h2 style="color: #333;">密码重置请求</h2>
        <p>您好，</p>
        <p>我们收到了您的密码重置请求。请点击下面的按钮重置密码：</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 15px 30px; text-decoration: none; border-radius: 25px; font-weight: bold;">重置密码</a>
        </div>
        <p>或者复制以下链接到浏览器：</p>
        <p style="background: #eee; padding: 10px; border-radius: 5px; word-break: break-all;">{reset_url}</p>
        <p><strong>注意：</strong>此链接将在 {RESET_TOKEN_EXPIRE_MINUTES} 分钟后过期。</p>
        <p>如果您没有请求密码重置，请忽略此邮件。</p>
    """
    ok = _smtp_send(email, "华为云解决方案匹配系统 - 密码重置", _email_shell("密码重置", inner))
    if ok:
        logger.info(f"✅ 重置密码邮件已发送到 {email}")
    return ok

def send_email_code(email: str, code: str, minutes: int) -> bool:
    """
    发送邮箱改绑验证码邮件（6位数字码）。
    :param minutes: 验证码有效期（分钟），用于邮件文案
    :return: 是否发送成功
    """
    if not smtp_configured():
        logger.error("[email-code] SMTP 未配置，验证码邮件无法发送！")
        return False

    inner = f"""
        <h2 style="color: #333;">邮箱绑定验证码</h2>
        <p>您好，</p>
        <p>您正在将账号邮箱变更为 <strong>{email}</strong>。请使用下面的验证码完成确认：</p>
        <div style="text-align: center; margin: 30px 0;">
            <span style="display: inline-block; background: #eee; padding: 15px 30px; border-radius: 10px; font-size: 28px; font-weight: bold; letter-spacing: 8px; color: #333;">{code}</span>
        </div>
        <p><strong>注意：</strong>验证码将在 {minutes} 分钟后过期；请勿泄露给任何人。</p>
        <p>如果您没有发起邮箱绑定，请忽略此邮件。</p>
    """
    ok = _smtp_send(email, "华为云解决方案匹配系统 - 邮箱绑定验证码", _email_shell("邮箱绑定", inner))
    if ok:
        logger.info(f"✅ 邮箱绑定验证码已发送到 {email}")
    return ok
