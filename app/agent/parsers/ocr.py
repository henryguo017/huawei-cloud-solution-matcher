"""
OCR 引擎封装（阶段1）

硬约束：DeepSeek 为纯文本模型、无视觉能力，图片必须走 OCR 提取文字后再喂模型。
当前使用免费本地 pytesseract（中文 chi_sim + 英文）。
若后续需要更高精度，可在此层切换到云 OCR API（仅改本文件，不影响上层）。
"""
import logging

logger = logging.getLogger(__name__)

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except Exception as e:  # 缺失依赖时不崩溃，仅 OCR 不可用
    OCR_AVAILABLE = False
    logger.warning(f"OCR 引擎不可用（pytesseract/Pillow 未安装）: {e}")


def ocr_image(path: str) -> str:
    """对图片文件做 OCR，返回识别文字。失败返回 Error: 前缀字符串。"""
    if not OCR_AVAILABLE:
        return "Error: OCR 引擎未安装（需 pytesseract 与 Pillow，且系统已装 tesseract）"
    try:
        img = Image.open(path)
        return pytesseract.image_to_string(img, lang="chi_sim+eng")
    except Exception as e:
        return f"Error: OCR 识别失败: {e}"


def ocr_pil(pil_image) -> str:
    """对 PIL 图像对象做 OCR（供 PDF 页面渲染后识别复用）。"""
    if not OCR_AVAILABLE:
        return ""
    try:
        return pytesseract.image_to_string(pil_image, lang="chi_sim+eng")
    except Exception:
        return ""
