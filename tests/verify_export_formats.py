#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
导出格式枚举回归测试（P2-D4 PPTX / PDF 分支守门）

背景（真实事故）：
    `ExportFormat` 枚举一度只有 WORD / PDF，而 report_generator._render_and_save
    中存在 `elif format == ExportFormat.PPTX:`。Python 枚举访问不存在的成员会抛
    AttributeError，导致：
      1) PPTX 导出直接失败；
      2) **PDF 导出也连带失败** —— 因为判定链是 `if WORD -> elif PPTX -> else PDF`，
         elif 抛异常时根本走不到 else 分支。
    该缺陷被 try/except 吞成 FAILED 任务，/api/export/report 则返回 500，
    静默且不易察觉。

本测试用「按文件路径加载」的方式绕开 app/__init__.py 的重依赖链（httpx/numpy 等），
可在任何 Python 环境下独立运行。

运行：python tests/verify_export_formats.py
"""
import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_MODELS = os.path.join(ROOT, "app", "models", "export_models.py")
REPORT_GENERATOR = os.path.join(ROOT, "app", "services", "report_generator.py")


def _load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main():
    ok = True

    em = _load_by_path("_em_under_test", EXPORT_MODELS)
    EF = em.ExportFormat

    # 1) 三个成员必须齐全
    values = {e.value for e in EF}
    for v in ("word", "pdf", "pptx"):
        if v not in values:
            print(f"[FAIL] ExportFormat 缺少成员 {v}")
            ok = False
        else:
            print(f"[OK]   ExportFormat 含 {v}")

    # 2) 判定链路由正确（镜像 report_generator._render_and_save 的分支）
    def route(fmt):
        if fmt == EF.WORD:
            return "docx"
        elif fmt == EF.PPTX:   # 此行在枚举缺失 PPTX 时会抛 AttributeError
            return "pptx"
        else:
            return "pdf"

    expect = {"word": "docx", "pdf": "pdf", "pptx": "pptx"}
    for val, want in expect.items():
        try:
            got = route(EF(val))
        except AttributeError as e:
            print(f"[FAIL] 路由 {val} 抛 AttributeError: {e}")
            ok = False
            continue
        if got != want:
            print(f"[FAIL] 路由 {val} -> {got}，期望 {want}")
            ok = False
        else:
            print(f"[OK]   路由 {val} -> {got}")

    # 3) 源码层面：生成器必须同时存在 PPTX 分支与 PDF 兜底分支，
    #    防止将来有人加了 PPTX 却把 PDF 的 else 删掉（或反之）。
    src = open(REPORT_GENERATOR, encoding="utf-8").read()
    if "ExportFormat.PPTX" not in src:
        print("[FAIL] report_generator.py 未引用 ExportFormat.PPTX（PPTX 分支丢失）")
        ok = False
    else:
        print("[OK]   report_generator.py 含 ExportFormat.PPTX 分支")
    if ".pdf\"" not in src:
        print("[FAIL] report_generator.py 未找到 PDF 生成分支")
        ok = False
    else:
        print("[OK]   report_generator.py 含 PDF 分支")

    # 4) PDF 不得再硬编码 Windows 字体 'simsun.ttc'
    #    （Linux 无此文件 → "Can't open file"，PDF 导出 100% 失败）
    #    注意：必须剥掉注释行再匹配，否则会因事故说明注释里引用了旧写法而误报。
    code_only = "\n".join(
        ln for ln in src.splitlines() if not ln.strip().startswith("#")
    )
    if re.search(r"TTFont\(\s*['\"]SimSun['\"]", code_only):
        print("[FAIL] _generate_pdf 仍硬编码 TTFont('SimSun', ...)，Linux 上必然失败")
        ok = False
    else:
        print("[OK]   _generate_pdf 未硬编码 SimSun（已排除注释行）")
    if "_resolve_pdf_cjk_font" not in src:
        print("[FAIL] 缺少跨平台字体解析 _resolve_pdf_cjk_font")
        ok = False
    else:
        print("[OK]   含跨平台字体解析 _resolve_pdf_cjk_font")
    # 兜底分支必须存在，否则无字体环境下会整体失败
    if "STSong-Light" not in src:
        print("[FAIL] 缺少 CID 兜底字体 STSong-Light")
        ok = False
    else:
        print("[OK]   含 CID 兜底字体 STSong-Light")

    # 5) Agent 工具侧引用同样不能 404
    tools = os.path.join(ROOT, "app", "agent", "tools.py")
    if os.path.exists(tools):
        tsrc = open(tools, encoding="utf-8").read()
        if "ExportFormat.PPTX" in tsrc:
            print("[OK]   agent/tools.py 的 ExportFormat.PPTX 引用可用")
        else:
            print("[WARN] agent/tools.py 未引用 ExportFormat.PPTX（若已下线属正常）")

    print("\n结果:", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
