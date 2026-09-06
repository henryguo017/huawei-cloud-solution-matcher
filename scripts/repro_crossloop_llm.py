# -*- coding: utf-8 -*-
"""根因复现：主 loop 绑定的全局 httpx 单例 + _run_async 工作线程新 loop
= 跨 loop 使用 → 复现生产 PPTX 引擎静默降级。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import llm
from app.services.ppt_engine.generator import generate_deck

CHAPTERS = [
    {'title': '项目背景',
     'content': '某省级制造集团 3 园区、380 余家企业、8 套存量系统，计划 2026 年整体上云，'
                '目标核心系统 100% 迁移、成本压降 25%、12 周过等保三级。方案含四层架构设计。',
     'sections': []},
]


async def main():
    # 1) 主 loop 上初始化全局单例（等价于生产：match/agent 请求先跑过）
    client = llm._get_http_client()
    print('主 loop 初始化单例 client:', type(client).__name__)

    # 2) 在运行中的 loop 里直接调同步 generate_deck（等价于生产 async 导出路由的调用方式）
    try:
        deck = generate_deck(solution_chapters=CHAPTERS,
                             title='跨loop复现', customer='测试')
        print('意外成功：页数', len(deck['pages']))
    except Exception as e:
        print(f'复现成功 → {type(e).__name__}: {str(e)[:200]}')
        print('（这就是生产降级 legacy 的真因：全局 AsyncClient 跨 loop）')


if __name__ == '__main__':
    asyncio.run(main())
