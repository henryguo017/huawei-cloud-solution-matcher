# -*- coding: utf-8 -*-
"""华为红售前 PPT 引擎 — 设计 token（v9 样张拍板版，唯一色彩/字体/尺寸来源）

色彩纪律（硬约束，check_ppt_sample.py 有断言）：
- 深色填充块全篇清零，INK 仅用于文字；
- 红色占比 <10%：kicker / 小节头红方块 / hero 数字 / 图表主系列 / 每页至多一处红填充；
- 渐变仅限品牌内单色系（红→深红）；幽灵字 alpha 4-8%。
"""
from pptx.util import Inches
from pptx.dml.color import RGBColor

# ---- 色彩 ----
RED      = RGBColor(0xC7, 0x00, 0x0B)   # 唯一强调色
RED_SOFT = RGBColor(0xFB, 0xEE, 0xEF)   # 表格合计行 / 浅红命名块
RED_DEEP = RGBColor(0xA5, 0x00, 0x09)   # 渐变深端 / 结尾页左边缘
INK      = RGBColor(0x1A, 0x1C, 0x20)   # 仅文字（禁作填充）
BODY     = RGBColor(0x33, 0x37, 0x3D)   # 正文
MUTE     = RGBColor(0x8A, 0x8F, 0x98)   # 注释/次要
GRAY_BAR = RGBColor(0x9E, 0xA3, 0xAB)   # 图表对比系列
FAINT    = RGBColor(0xF6, 0xF7, 0xF9)   # 表格隔行
RULE     = RGBColor(0xE4, 0xE6, 0xEA)   # 发丝线
THEAD    = RGBColor(0xE9, 0xEB, 0xEE)   # 表头（浅灰底 + INK 字，去黑色量）
TAG      = RGBColor(0xB9, 0xBE, 0xC6)   # 备用浅标签（深底已禁用）
WHITE    = RGBColor(0xFF, 0xFF, 0xFF)

# ---- 字体 / 字阶（6 级，禁混用他值） ----
FONT = '微软雅黑'          # 中文（ea）；西文/数字固定 Arial（primitives 锁定）
SZ_PAGE_TITLE = 22         # 页标题
SZ_HERO       = 16         # hero 数字 / 要点卡值
SZ_BLOCK      = 11.5       # 块标题
SZ_BODY       = 9          # 正文
SZ_TABLE      = 8          # 表格
SZ_NOTE       = 7.5        # 注释

# ---- 版面 ----
SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MX = Inches(0.45)          # 页边距
CW = Inches(12.433)        # 内容全宽
TOTAL_PAGES = 12           # 样张 12 页；引擎按 deck 页数动态覆盖

# ---- 固定品牌水印（所有出稿页脚） ----
FOOTER_LEFT = '华为云解决方案智能匹配 · 自动生成'
FOOTER_RIGHT = 'cloudsol.cn'
