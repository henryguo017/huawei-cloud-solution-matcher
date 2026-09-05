import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, FRONTEND_URL, RESET_TOKEN_EXPIRE_MINUTES
import logging

logger = logging.getLogger(__name__)

def send_reset_email(email: str, token: str) -> bool:
    """
    发送密码重置邮件
    :param email: 收件人邮箱
    :param token: 重置 token
    :return: 是否发送成功
    """
    try:
        # SMTP 未配置时显式告警（.env 需配 SMTP_USER/SMTP_PASS）；
        # 返回 False 仍会被上层按"防账号枚举"语义处理，但服务端日志可定位配置缺失。
        if not SMTP_USER or not SMTP_PASS:
            logger.error(
                "[reset] SMTP 未配置（SMTP_USER/SMTP_PASS 为空），密码重置邮件无法发送！"
                "请在服务器 .env 配置 SMTP_USER/SMTP_PASS 后重启服务。"
            )
            return False
        # 构造重置链接
        reset_url = f"{FRONTEND_URL}/reset-password?token={token}"
        
        # 邮件内容
        subject = "华为云解决方案匹配系统 - 密码重置"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                    <h1 style="color: white; margin: 0;">华为云解决方案匹配系统</h1>
                </div>
                <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
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
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
                    <p style="color: #888; font-size: 12px;">此邮件由系统自动发送，请勿回复。</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        # 构造邮件
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = SMTP_USER
        msg['To'] = email
        
        # 添加 HTML 内容
        html_part = MIMEText(body, 'html', 'utf-8')
        msg.attach(html_part)
        
        # 发送邮件
        if SMTP_PORT == 465:
            # SSL
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            # STARTTLS
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()
        
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"✅ 重置密码邮件已发送到 {email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 发送重置密码邮件失败: {e}")
        return False
