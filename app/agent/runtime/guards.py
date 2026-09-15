# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 守卫（guards.py）

职责（单一）：**硬边界保护**。轮次 / token / 墙钟三条预算，超限时的行为是：
  1) 先注入一条"预算将尽，请收口"的 advisory 系统消息 —— **决策权仍归模型**；
  2) 到硬上限才熔断，把控制权交回上层（回退 legacy 管线或交付已有草稿）。

本模块**不做任何任务决策**：不判断该不该调某工具、不判断任务是否完成。
「该收手了吗」是模型的判断；「能不能继续烧钱」才是宿主的边界。
"""

import time
from typing import Any, Dict, Optional, Tuple


class RunGuards:
    """单次运行的预算守卫。实例随运行创建，不跨请求复用。"""

    def __init__(
        self,
        turns_max: int,
        token_budget: int,
        wall_budget: float,
        advisory_at: float = 0.8,
        start_time: Optional[float] = None,
    ):
        self.turns_max = max(1, int(turns_max))
        self.token_budget = max(1, int(token_budget))
        self.wall_budget = float(wall_budget)
        self.advisory_at = min(max(float(advisory_at), 0.1), 0.99)
        self.start_time = start_time if start_time is not None else time.time()
        self.turns = 0
        self.tokens = 0
        self._advisory_sent = False
        self.stopped_by: str = ""

    # ---- 累计 ----

    def tick_turn(self) -> int:
        self.turns += 1
        return self.turns

    def add_usage(self, usage: Optional[Dict[str, Any]]) -> None:
        """累计 token（provider 返回的 usage.total_tokens；缺失时按 0 计，不阻塞）。"""
        if not isinstance(usage, dict):
            return
        try:
            self.tokens += int(usage.get("total_tokens") or 0)
        except (TypeError, ValueError):
            pass

    def elapsed(self) -> float:
        return time.time() - self.start_time

    # ---- 判定 ----

    def _ratios(self) -> Tuple[float, float, float]:
        r_turn = self.turns / float(self.turns_max)
        r_tok = self.tokens / float(self.token_budget)
        r_wall = self.elapsed() / float(self.wall_budget) if self.wall_budget > 0 else 0.0
        return r_turn, r_tok, r_wall

    def check(self) -> Tuple[str, Optional[str]]:
        """返回 (state, advisory_message)。

        state ∈ {"ok", "advisory", "stop"}：
          - stop     → 已达硬上限，调用方必须收尾（熔断）；
          - advisory → 预算消耗过半/逼近上限，返回一条**建议性**系统消息（一次性）。
        """
        r_turn, r_tok, r_wall = self._ratios()
        if self.turns >= self.turns_max:
            self.stopped_by = "turns"
            return "stop", None
        if self.tokens >= self.token_budget:
            self.stopped_by = "tokens"
            return "stop", None
        if self.wall_budget > 0 and self.elapsed() >= self.wall_budget:
            self.stopped_by = "wall"
            return "stop", None
        if (not self._advisory_sent) and max(r_turn, r_tok, r_wall) >= self.advisory_at:
            self._advisory_sent = True
            return "advisory", (
                "【宿主预算提示】本次任务的可用预算（轮次/token/时长）已消耗约"
                f"{int(max(r_turn, r_tok, r_wall) * 100)}%。"
                "请优先收口：基于已获得的资料给出完整答案，或明确指出还缺什么；"
                "不要开启新的探索性检索。"
            )
        return "ok", None

    def snapshot(self) -> Dict[str, Any]:
        r_turn, r_tok, r_wall = self._ratios()
        return {
            "turns": self.turns,
            "turns_max": self.turns_max,
            "tokens": self.tokens,
            "token_budget": self.token_budget,
            "elapsed": round(self.elapsed(), 2),
            "wall_budget": self.wall_budget,
            "budget_ratio": round(max(r_turn, r_tok, r_wall), 4),
            "stopped_by": self.stopped_by,
        }
