# -*- coding: utf-8 -*-
"""全量重建知识库（chromadb 0.4.24 兼容格式）。"""
import os
import sys
import time

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# numpy 2.x 兼容 shim（chromadb 0.4.24 用到旧别名 np.float_ 等）
import numpy as np
for _n, _v in [("float_", np.float64), ("int_", np.int64), ("uint", np.uint64),
               ("bool8", np.bool_), ("object_", object), ("complex_", np.complex128)]:
    if not hasattr(np, _n):
        setattr(np, _n, _v)

# 单线程防御：规避 sentence-transformers/torch 多线程段错误
import torch
torch.set_num_threads(1)

import asyncio as _a
async def _sync(fn, *args, **kwargs):
    return fn(*args, **kwargs)
_a.to_thread = _sync

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)

from app.services.knowledge_base import KnowledgeBaseService


def prog(done, total, stage):
    print(f"[重建] {done}/{total} {stage}", flush=True)


def main():
    t0 = time.time()
    svc = KnowledgeBaseService()
    svc.build_from_directory(use_default_dirs=True, on_progress=prog)
    print(f"[重建完成] 耗时 {round(time.time()-t0,1)}s", flush=True)
    docs = svc.vector_db.similarity_search("智慧园区 安防 能耗", k=3)
    print(f"[验证] 检索到 {len(docs)} 篇", flush=True)
    for d in docs[:3]:
        print("  -", (d.page_content or "")[:60].replace("\n", " "), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
