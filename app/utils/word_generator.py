from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
import os
from datetime import datetime
from typing import Dict, Any, List, Optional


class WordGenerator:
    """Word文档生成器"""
    
    def __init__(self):
        self.doc = Document()
        self._setup_chinese_fonts()
    
    def _setup_chinese_fonts(self):
        """配置中文字体支持"""
        styles = self.doc.styles
        
        for style in styles:
            if style.type == WD_STYLE_TYPE.PARAGRAPH:
                try:
                    style.font.name = 'SimSun'
                    style._element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
                except:
                    pass
    
    def generate_cover(self, title: str, subtitle: str = None, 
                       date: str = None, customer: str = None):
        """生成封面页"""
        self.doc.add_paragraph()
        self.doc.add_paragraph()
        
        title_para = self.doc.add_paragraph()
        title_run = title_para.add_run(title)
        title_run.font.size = Pt(28)
        title_run.font.bold = True
        title_run.font.name = 'SimHei'
        title_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'SimHei')
        title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_paragraph()
        
        if subtitle:
            sub_para = self.doc.add_paragraph()
            sub_run = sub_para.add_run(subtitle)
            sub_run.font.size = Pt(18)
            sub_run.font.name = 'SimSun'
            sub_run._element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
            sub_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_paragraph()
        self.doc.add_paragraph()
        
        if date:
            date_para = self.doc.add_paragraph()
            date_run = date_para.add_run(f"生成日期：{date}")
            date_run.font.size = Pt(12)
            date_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        if customer:
            cust_para = self.doc.add_paragraph()
            cust_run = cust_para.add_run(f"客户：{customer}")
            cust_run.font.size = Pt(12)
            cust_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_page_break()
    
    def generate_toc(self, chapters: List[Dict]):
        """生成目录页"""
        toc_title = self.doc.add_paragraph()
        toc_run = toc_title.add_run("目 录")
        toc_run.font.size = Pt(18)
        toc_run.font.bold = True
        toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        self.doc.add_paragraph()
        
        for idx, chapter in enumerate(chapters, 1):
            toc_item = self.doc.add_paragraph()
            toc_text = f"{idx}. {chapter.get('title', '未命名章节')}"
            toc_item.add_run(toc_text)
        
        self.doc.add_page_break()
    
    def generate_chapter(self, title: str, content: str, level: int = 1):
        """生成章节内容"""
        heading = self.doc.add_heading(title, level=level)
        
        paragraphs = content.split('\n')
        for para_text in paragraphs:
            if para_text.strip():
                para = self.doc.add_paragraph()
                run = para.add_run(para_text.strip())
                run.font.size = Pt(11)
                run.font.name = 'SimSun'
                run._element.rPr.rFonts.set(qn('w:eastAsia'), 'SimSun')
    
    def generate_report(self, report_data: Dict[str, Any]) -> Document:
        """生成完整报告"""
        title = report_data.get('title', '华为云解决方案报告')
        subtitle = report_data.get('subtitle', '')
        date = report_data.get('create_date', datetime.now().strftime('%Y-%m-%d'))
        customer = report_data.get('customer_name', '')
        chapters = report_data.get('chapters', [])
        appendix = report_data.get('appendix', [])
        
        self.generate_cover(title, subtitle, date, customer)
        
        if chapters:
            self.generate_toc(chapters)
        
        for chapter in chapters:
            ch_title = chapter.get('title', '')
            ch_content = chapter.get('content', '')
            self.generate_chapter(ch_title, ch_content)
            
            sub_sections = chapter.get('sections', [])
            for sub in sub_sections:
                sub_title = sub.get('title', '')
                sub_content = sub.get('content', '')
                self.generate_chapter(sub_title, sub_content, level=2)
        
        if appendix:
            self.doc.add_page_break()
            self.doc.add_heading("附 录", level=1)
            for item in appendix:
                app_title = item.get('title', '')
                app_content = item.get('content', '')
                self.generate_chapter(app_title, app_content, level=2)
        
        return self.doc
    
    def save(self, file_path: str):
        """保存文档"""
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        self.doc.save(file_path)
