# -*- coding: utf-8 -*-
"""L4-P3-4 按需挂 MCP（mcp_on_demand）：Agent 运行中从**服务端白名单**挂载/卸载 MCP Server。

价值：未挂载 server 的工具不进 schema（省 token + 缩小模型可见面），需要时挂、用完卸。

安全铁律：
1. **模型不能凭空创建 server**——只能从 load_mcp_servers()（MCP_SERVERS env + data/mcp_servers.json）
   的允许清单里选 label，mount 时逐字校验；
2. mount 是 `ask` 闸门动作（弹窗确认），list/unmount 只读放行；
3. 任务结束卸载：下一次 harness.run() 启动时清掉上一任务挂载的 server（跟踪全局 mounted 集）。
   总开关 ``AGENT_MCP_ONDEMAND``（默认 0=关），回退 = 置 0 重启。
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from app.agent import mcp_client
from app.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)

# 跨任务跟踪：本进程内按需挂载过的 label（任务开始时统一卸载）
_ONDEMAND_MOUNTED: List[str] = []


def _all_server_labels() -> List[Dict[str, Any]]:
    """白名单全量（不含密钥——配置本就只有 command/url/label）。"""
    out = []
    for srv in mcp_client.load_mcp_servers():
        cmd = srv.get("command") or []
        label = mcp_client._sanitize_label(srv.get("label") or (cmd[0] if cmd else (srv.get("url") or "mcp")))
        out.append({
            "label": label,
            "transport": "http" if srv.get("url") else "stdio",
            "target": srv.get("url") or " ".join(cmd),
        })
    return out


def list_servers_state(registry: ToolRegistry) -> List[Dict[str, Any]]:
    """白名单 server 清单 + 挂载状态（mounted = registry 中已有 mcp__<label>__ 工具）。"""
    mounted_labels = set(mcp_client.registered_labels())
    out = []
    for s in _all_server_labels():
        s["mounted"] = s["label"] in mounted_labels
        out.append(s)
    return out


def find_server(label: str) -> Optional[Dict[str, Any]]:
    """按 label 在白名单中找 server 配置（mount 的唯一合法来源）。"""
    label = mcp_client._sanitize_label(label or "")
    for srv in mcp_client.load_mcp_servers():
        cmd = srv.get("command") or []
        lb = mcp_client._sanitize_label(srv.get("label") or (cmd[0] if cmd else (srv.get("url") or "mcp")))
        if lb == label:
            return srv
    return None


async def mount_server(registry: ToolRegistry, label: str) -> Tuple[bool, str]:
    """挂载白名单中的一个 server。成功后工具即刻进 registry（下一轮 schema 即见）。"""
    label = mcp_client._sanitize_label(label or "")
    srv = find_server(label)
    if srv is None:
        allowed = ", ".join(s["label"] for s in _all_server_labels()) or "（白名单为空）"
        return False, (f"server「{label}」不在允许清单里——模型不能创建 server，"
                       f"仅可从以下清单选择：{allowed}")
    if mcp_client.get_clients_by_label(label):
        already = [n for n in mcp_client.get_registered_names() if n.startswith(f"mcp__{label}__")]
        return True, (f"server「{label}」已处于挂载状态（工具：{', '.join(already) or '加载中'}），"
                      "无需重复挂载。")
    registered = await mcp_client.register_remote_tools(registry, [srv])
    if not registered:
        return False, f"server「{label}」挂载失败：连接或工具注册未成功（详见服务端日志）"
    if label not in _ONDEMAND_MOUNTED:
        _ONDEMAND_MOUNTED.append(label)
    return True, (f"已挂载 server「{label}」，注册 {len(registered)} 个工具：{', '.join(registered)}。"
                  "下一轮即可直接调用。")


async def unmount_server(registry: ToolRegistry, label: str) -> Tuple[bool, str]:
    """卸载一个 server：registry 移除其全部工具 + 关闭底层 client。"""
    label = mcp_client._sanitize_label(label or "")
    prefix = f"mcp__{label}__"
    names = [t.name for t in registry.list_tools() if t.name.startswith(prefix)]
    for n in names:
        registry.remove(n)
    closed = await mcp_client.close_clients_by_label(label)
    mcp_client.drop_registered_names_by_label(label)
    if label in _ONDEMAND_MOUNTED:
        _ONDEMAND_MOUNTED.remove(label)
    if not names and not closed:
        return False, f"server「{label}」当前未挂载，无需卸载。"
    return True, f"已卸载 server「{label}」（移除 {len(names)} 个工具，关闭 {closed} 个连接）。"


async def unload_all_mounted(registry: ToolRegistry) -> int:
    """卸载本进程所有**按需挂载**的 server（任务启动时调用——清上一任务残留）。
    启动期静态挂载的（AGENT_MCP_CLIENT=1 的）server 不受影响——它们不在 _ONDEMAND_MOUNTED。"""
    n = 0
    for label in list(_ONDEMAND_MOUNTED):
        try:
            ok, _ = await unmount_server(registry, label)
            if ok:
                n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("[mcp_on_demand] 卸载「%s」失败（忽略）: %s", label, e)
    return n


def is_mounted(label: str) -> bool:
    return label in _ONDEMAND_MOUNTED or bool(mcp_client.get_clients_by_label(label))


def fmt_servers_json(servers: List[Dict[str, Any]]) -> str:
    return json.dumps({"servers": servers}, ensure_ascii=False)
