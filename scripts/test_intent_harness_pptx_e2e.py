# -*- coding: utf-8 -*-
"""集成 E2E：意图正则 → harness export 分支 → SSE doc_generated → 引擎 PPTX。
覆盖真实用户链路："给我生成一个PPT"（不经 /tool_generate_doc 直调）。
前置：harness._last_draft 预置终稿（模拟上一轮已生成方案）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.tools import create_default_tools
from app.agent.memory import ConversationMemory
from app.agent.harness import AgentHarness
from test_agent_pptx_e2e import DRAFT

OUT_DIR = Path(__file__).resolve().parents[1] / 'data' / 'exports'


async def main():
    harness = AgentHarness(
        tools=create_default_tools(),
        memory=ConversationMemory(max_history_turns=5),
        timeout=300.0, verbose=False,
    )
    harness._last_draft = DRAFT  # 模拟上一轮已生成方案

    events = []

    async def cb(ev):
        events.append(ev)

    result = await harness.run(
        user_input='给我生成一个PPT',
        session_id='e2e-ppt-intent',
        user_id=2,
        event_callback=cb,
    )

    types = [e.get('type') for e in events]
    print('事件序列:', types)
    print('intent:', getattr(harness, '_intent', '?'))
    print('answer:', (result.get('answer') or '')[:120])

    doc = next((e for e in events if e.get('type') == 'doc_generated'), None)
    assert doc, f'缺少 doc_generated 事件，实际事件: {types}'
    # 事件字段为 fmt（前端 agent_workspace L2390 同名消费）
    assert doc.get('fmt') == 'pptx', f'fmt 错误: {doc.get("fmt")}'
    fname = doc.get('file_name') or ''
    print('doc_generated:', {k: doc.get(k) for k in ('format', 'file_name', 'download_url')})

    p = OUT_DIR / fname
    if not p.exists():
        # report_generator.export_dir 是 CWD 相对路径——从 scripts/ 运行时会落在 scripts/data/exports
        alt = Path(__file__).resolve().parent / 'data' / 'exports' / fname
        p = alt if alt.exists() else p
    assert p.exists(), f'文件不存在: {p}'
    from pptx import Presentation
    slides = list(Presentation(str(p)).slides)
    print('slides:', len(slides))
    assert len(slides) == 12, f'页数 {len(slides)} ≠ 12（降级 legacy?）'
    print('INTENT->HARNESS->ENGINE 集成 E2E OK ->', p)


if __name__ == '__main__':
    asyncio.run(main())
