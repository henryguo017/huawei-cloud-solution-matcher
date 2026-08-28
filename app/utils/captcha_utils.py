import random
import string
import uuid
import base64
from io import BytesIO
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
from app.config import CAPTCHA_LENGTH, CAPTCHA_EXPIRE_MINUTES
from app.utils.db_init import get_db_connection

def generate_captcha() -> tuple[str, str, str]:
    captcha_key = str(uuid.uuid4())
    captcha_value = ''.join(random.choices(string.ascii_uppercase + string.digits, k=CAPTCHA_LENGTH))
    
    image = Image.new('RGB', (120, 40), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font = ImageFont.load_default()
    
    colors = [(199, 0, 11), (74, 144, 226), (51, 51, 51), (82, 196, 26)]
    for i, char in enumerate(captcha_value):
        x = 15 + i * 26
        y = random.randint(8, 12)
        color = random.choice(colors)
        draw.text((x, y), char, fill=color, font=font)
    
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    captcha_image = base64.b64encode(buffer.getvalue()).decode()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    expires_at = datetime.now() + timedelta(minutes=CAPTCHA_EXPIRE_MINUTES)
    
    cursor.execute("""
        INSERT INTO captchas (captcha_key, captcha_value, expires_at)
        VALUES (?, ?, ?)
    """, (captcha_key, captcha_value, expires_at))
    
    conn.commit()
    conn.close()
    
    return captcha_key, captcha_value, captcha_image

def verify_captcha(captcha_key: str, captcha_value: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT captcha_value FROM captchas 
        WHERE captcha_key = ? AND expires_at > ?
    """, (captcha_key, datetime.now()))
    
    result = cursor.fetchone()
    
    cursor.execute("DELETE FROM captchas WHERE captcha_key = ?", (captcha_key,))
    conn.commit()
    conn.close()
    
    if not result:
        return False
    
    return result['captcha_value'].upper() == captcha_value.upper()

def cleanup_expired_captchas():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM captchas WHERE expires_at < ?", (datetime.now(),))
    
    conn.commit()
    conn.close()
