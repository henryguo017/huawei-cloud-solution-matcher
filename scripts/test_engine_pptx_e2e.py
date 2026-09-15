# -*- coding: utf-8 -*-
"""E2E：generate_report_from_json(format=PPTX) 真实跑引擎管线，产出 12 页 pptx"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_generator import get_report_generator
from app.models.export_models import ReportType, ExportFormat

CHAPTERS = [
    {'title': '项目背景与建设目标',
     'content': '某省级制造集团现有 3 个园区、380 余家入驻企业、8 套存量 IT 系统，'
                '面临资源分散、运维成本高、数据孤岛三大问题。集团计划 2026 年整体上云，'
                '建设目标为：核心业务系统 100% 迁移、综合 IT 成本压降 25%、等保三级合规。',
     'sections': [{'title': '建设目标', 'content': 'G1 核心系统迁移 100%；G2 成本压降 25%；'
                   'G3 等保三级 12 周内通过测评。'}]},
    {'title': '现状与核心痛点',
     'content': '现状痛点集中在四个方面：P1 资源利用率不足 30%，扩容周期长达 6 周；'
                'P2 运维人力 12 人仍疲于奔命，故障平均恢复时长 4 小时；'
                'P3 8 套系统数据孤岛，跨系统对账靠人工 Excel；'
                'P4 安全设备各自为政，等保测评连续两年未通过。',
     'sections': []},
    {'title': '总体方案架构',
     'content': '方案采用华为云四层架构：接入层 WAF+ELB 统一入口；应用层 ECS c7.2xlarge.4 × 4 弹性承载；'
                '数据层 RDS r7.2xlarge 高可用 + OBS 1TB 数据湖；安全层含 DBSS 数据库审计与 HSS 主机安全。'
                '五大设计要点：高可用、弹性伸缩、数据融合、安全合规、平滑迁移。',
     'sections': []},
    {'title': '方案对比与成本',
     'content': '对比自建 IDC：华为云路线 3 年 TCO 约 18.3 万元/月口径，自建约 26.9 万元，'
                '且自建需一次性投入 300 万机房建设。华为云按量弹性，扩容分钟级，'
                '含 SLA 99.95% 赔付承诺，综合成本优势约 32%。',
     'sections': []},
]

COST_REF = {
    'view_mode': 'month', 'annual_discount': 0.85, 'industry': '制造',
    'rows': [
        {'product': 'ECS 弹性云服务器', 'spec': 'c7.2xlarge.4 | 8vCPU/32GB', 'qty': 4,
         'unit_price': 640, 'billing': '包年包月', 'unit_label': '台', 'verified': True},
        {'product': 'RDS 云数据库', 'spec': 'r7.2xlarge | 主备高可用', 'qty': 2,
         'unit_price': 1200, 'billing': '包年包月', 'unit_label': '套', 'verified': True},
        {'product': 'EVS 云硬盘', 'spec': '500GB SSD', 'qty': 4,
         'unit_price': 400, 'billing': '包年包月', 'verified': True},
        {'product': 'EIP 弹性公网IP', 'spec': '50Mbps', 'qty': 2,
         'unit_price': 300, 'billing': '包年包月', 'verified': True},
        {'product': 'OBS 对象存储', 'spec': '1TB 标准存储', 'qty': 1,
         'unit_price': 120, 'billing': '按量付费', 'verified': True},
        {'product': 'DBSS 数据库审计', 'spec': '标准版', 'business_only': True,
         'note': '商务报价，请咨询华为云销售'},
    ],
}


def main():
    svc = get_report_generator()
    task = svc.generate_report_from_json(
        report_type=ReportType.SOLUTION,
        chapters=CHAPTERS,
        format=ExportFormat.PPTX,
        metadata={'title': '制造集团数字化上云解决方案建议书', 'customer': '某省级制造集团'},
        cost_reference=COST_REF,
    )
    print('status:', task.status)
    print('file:', task.file_name)
    print('size:', task.file_size)
    if task.error_message:
        print('error:', task.error_message)
    assert task.status.value == 'completed' or task.status == 'completed', task.error_message
    # 页数核验
    from pptx import Presentation
    prs = Presentation(task.file_path)
    print('slides:', len(prs.slides.__iter__.__self__._sldIdLst))
    print('E2E OK ->', task.file_path)


if __name__ == '__main__':
    main()
