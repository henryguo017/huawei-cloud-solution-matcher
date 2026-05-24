import os
import re
import time
from datetime import datetime
from typing import Dict, Any, List
from pathlib import Path

from app.models.export_models import (
    ExportFormat, TaskStatus, ReportType, 
    ExportTask, ExportResult, ReportContent
)
from app.utils.word_generator import WordGenerator
from app.config import APP_NAME


class ReportGeneratorService:
    """报告生成服务"""
    
    def __init__(self):
        self.export_dir = Path("data/exports")
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
        self.tasks: Dict[str, ExportTask] = {}
    
    def _parse_markdown_content(self, content: str) -> List[Dict[str, Any]]:
        """解析Markdown内容为章节结构"""
        chapters = []
        lines = content.split('\n')
        current_chapter = None
        current_content = []
        
        for line in lines:
            if line.startswith('## '):
                if current_chapter:
                    current_chapter['content'] = '\n'.join(current_content)
                    chapters.append(current_chapter)
                
                current_chapter = {
                    'title': line[3:].strip(),
                    'content': '',
                    'sections': []
                }
                current_content = []
            elif line.startswith('### '):
                if current_content and current_chapter:
                    current_chapter['content'] = '\n'.join(current_content)
                    current_content = []
                
                if current_chapter:
                    current_chapter['sections'].append({
                        'title': line[4:].strip(),
                        'content': ''
                    })
            else:
                if current_chapter and current_chapter.get('sections'):
                    current_chapter['sections'][-1]['content'] += line + '\n'
                else:
                    current_content.append(line)
        
        if current_chapter:
            current_chapter['content'] = '\n'.join(current_content)
            chapters.append(current_chapter)
        
        return chapters
    
    def _generate_solution_report(self, content: str, 
                                  metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成解决方案报告数据结构"""
        metadata = metadata or {}
        
        chapters = self._parse_markdown_content(content)
        
        if not chapters:
            chapters = [{
                'title': '解决方案分析',
                'content': content,
                'sections': []
            }]
        
        return {
            'title': metadata.get('title', '华为云解决方案建议书'),
            'subtitle': '智能匹配生成报告',
            'create_date': datetime.now().strftime('%Y年%m月%d日'),
            'customer_name': metadata.get('customer', ''),
            'chapters': chapters,
            'appendix': []
        }
    
    def _generate_competitor_report(self, content: str,
                                    metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """生成竞争对手分析报告数据结构"""
        metadata = metadata or {}
        
        chapters = self._parse_markdown_content(content)
        
        if not chapters:
            chapters = [{
                'title': '竞争分析',
                'content': content,
                'sections': []
            }]
        
        competitor = metadata.get('competitor', '竞争对手')
        industry = metadata.get('industry', '行业')
        
        return {
            'title': f'华为云 vs {competitor} 竞争分析报告',
            'subtitle': f'{industry}行业',
            'create_date': datetime.now().strftime('%Y年%m月%d日'),
            'customer_name': '',
            'chapters': chapters,
            'appendix': []
        }
    
    def generate_report(self, report_type: ReportType, 
                        content: str, 
                        format: ExportFormat = ExportFormat.WORD,
                        metadata: Dict[str, Any] = None) -> ExportTask:
        """生成报告"""
        task = ExportTask(
            format=format,
            report_type=report_type
        )
        
        self.tasks[task.task_id] = task
        
        try:
            task.status = TaskStatus.PROCESSING
            
            start_time = time.time()
            
            if report_type == ReportType.SOLUTION:
                report_data = self._generate_solution_report(content, metadata)
                file_prefix = "solution_report"
            else:
                report_data = self._generate_competitor_report(content, metadata)
                file_prefix = "competitor_report"
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if format == ExportFormat.WORD:
                file_name = f"{file_prefix}_{timestamp}.docx"
                file_path = self.export_dir / file_name
                
                generator = WordGenerator()
                doc = generator.generate_report(report_data)
                generator.save(str(file_path))
            else:
                file_name = f"{file_prefix}_{timestamp}.pdf"
                file_path = self.export_dir / file_name
                self._generate_pdf(report_data, str(file_path))
            
            file_size = file_path.stat().st_size
            generation_time = int((time.time() - start_time) * 1000)
            
            task.status = TaskStatus.COMPLETED
            task.complete_time = datetime.now()
            task.file_path = str(file_path)
            task.file_name = file_name
            task.file_size = file_size
            task.download_url = f"/api/export/download/{task.task_id}"
            
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error_message = str(e)
        
        return task
    
    def _generate_pdf(self, report_data: Dict[str, Any], file_path: str):
        """生成PDF报告（使用reportlab）"""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            
            pdfmetrics.registerFont(TTFont('SimSun', 'simsun.ttc'))
            
            doc = SimpleDocTemplate(file_path, pagesize=A4)
            styles = getSampleStyleSheet()
            
            title_style = ParagraphStyle(
                'Title',
                parent=styles['Title'],
                fontName='SimSun',
                fontSize=24
            )
            
            body_style = ParagraphStyle(
                'Body',
                parent=styles['Normal'],
                fontName='SimSun',
                fontSize=12
            )
            
            story = []
            
            story.append(Paragraph(report_data.get('title', ''), title_style))
            story.append(Spacer(1, 20))
            
            for chapter in report_data.get('chapters', []):
                story.append(Paragraph(chapter.get('title', ''), body_style))
                story.append(Spacer(1, 10))
                
                content = chapter.get('content', '')
                for para in content.split('\n'):
                    if para.strip():
                        story.append(Paragraph(para.strip(), body_style))
            
            doc.build(story)
            
        except Exception as e:
            raise Exception(f"PDF生成失败: {str(e)}")
    
    def get_task(self, task_id: str) -> ExportTask:
        """获取任务状态"""
        return self.tasks.get(task_id)
    
    def get_file_path(self, task_id: str) -> str:
        """获取文件路径"""
        task = self.tasks.get(task_id)
        if task and task.status == TaskStatus.COMPLETED:
            return task.file_path
        return None
