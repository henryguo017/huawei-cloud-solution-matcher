# -*- coding: utf-8 -*-
"""MCP 客户端（P2-3 拉伸项 · 真实实现）。

通过 stdio JSON-RPC 2.0 连接外部 MCP Server，并把远端工具注册进本地 ToolRegistry，
使 Agent 可直接调用远端工具（与 app/agent/mcp_server.py 暴露的标准 MCP 互相对接）。

设计要点（与项目铁律对齐）：
  - 纯标准库（asyncio.subprocess + JSON-RPC 2.0），零新依赖；
  - 默认关闭：AGENT_MCP_CLIENT=0 时 register_remote_tools 直接返回 0，不拉起任何子进程、无副作用；
  - 优雅降级：任一 Server 连接/握手失败只记 warning 并跳过，绝不拖垮主链路；
  - 远端工具名加前缀 `mcp__<label>__<tool>`，避免与本地工具重名冲突；
  - 远端工具的参数完全由远端 JSON Schema（inputSchema）定义，原样透传，不被本地签名归一化丢弃；
  - 懒加载：stdio 传输层（MCPClient）不依赖任何 app 模块，可在无 chromadb/langchain 的环境单独测试；
    仅 register_remote_tools 真正注册时才按需 import 本地 Tool 基类（部署环境已具备）。

启动外部 Server 的约定（MCP_SERVERS 配置项）：
  MCP_SERVERS='[{"command":["python","-m","app.agent.mcp_server"],"label":"self"}]'
  command 为可执行命令（列表）；label 用于命名空间，缺省取 command 首个 token。
"""
import json
import logging
import os
import subprocess
import asyncio
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# MCP 协议常量
PROTOCOL_VERSION = "2024-11-05"
CLIENT_INFO = {"name": "huawei-cloud-agent", "version": "1.0"}

# 模块级缓存：已建立的 MCPClient（长期存活，按需复用），用于关闭回收
_CLIENTS: List["MCPClient"] = []
_REGISTERED_NAMES: List[str] = []


def _format_tool_result(result: Any) -> str:
    """把 MCP tools/call 的 result 规整成给 LLM 看的文本字符串。"""
    if result is None:
        return "(工具无返回内容)"
    if isinstance(result, str):
        return result
    # MCP 标准：{"content":[{"type":"text","text":"..."}], "isError":bool}
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False, default=str))
            text = "\n".join(p for p in parts if p)
            if result.get("isError"):
                return f"Error: {text}" if text else "(工具返回错误，无详情)"
            return text or "(工具无返回内容)"
        # 退化：直接序列化整个 result
        return json.dumps(result, ensure_ascii=False, default=str)
    return json.dumps(result, ensure_ascii=False, default=str)


class MCPClient:
    """单个 stdio MCP Server 的 JSON-RPC 2.0 客户端（长期存活，纯标准库）。"""

    def __init__(self, command: List[str], timeout: float = 30.0, label: str = ""):
        self.command = list(command)
        self.timeout = timeout
        self.label = label or (command[0] if command else "mcp")
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._req_id = 0
        self._tools: List[Dict[str, Any]] = []

    async def connect(self) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except (FileNotFoundError, PermissionError, OSError) as e:
            raise RuntimeError(f"无法启动 MCP Server 进程 {self.command}: {e}")

        # 1) initialize 握手
        init_result = await self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        if not init_result:
            raise RuntimeError("MCP initialize 无响应（进程可能已退出）")
        # 2) 通知服务端已初始化（部分 server 要求后再响应 tools/list）
        await self._rpc("notifications/initialized", {}, notify=True)
        # 3) 拉取工具清单
        self._tools = await self.list_tools()
        if not self._tools:
            logger.warning(f"[MCP] Server「{self.label}」未暴露任何工具")

    async def _rpc(self, method: str, params: Dict[str, Any], notify: bool = False) -> Dict[str, Any]:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("MCPClient 未连接")
        self._req_id += 1
        req_id = self._req_id
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": req_id}
        self._proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()
        if notify:
            return {}
        return await self._read_response(req_id)

    async def _read_response(self, expected_id: int) -> Dict[str, Any]:
        """读取一行 JSON-RPC 响应，跳过通知（无 id）与不匹配的行，直到命中 expected_id。"""
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            try:
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=self.timeout)
            except asyncio.TimeoutError:
                raise RuntimeError(f"MCP 读取响应超时（>{self.timeout}s），method 可能未响应")
            if not line:
                # EOF：进程退出
                raise RuntimeError("MCP 连接已断开（stdout EOF）")
            s = line.decode("utf-8", errors="replace").strip()
            if not s:
                continue
            try:
                msg = json.loads(s)
            except json.JSONDecodeError:
                # 容忍非 JSON 噪声行（如某些 server 往 stdout 打日志）
                continue
            if not isinstance(msg, dict):
                continue
            # 通知类（无 id 或是 notifications/* 方法）直接跳过
            if "id" not in msg or msg.get("id") is None:
                continue
            if msg.get("id") == expected_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP 错误响应: {msg['error']}")
                return msg.get("result", {})
            # id 不匹配（理论单并发不该发生）继续读

    async def list_tools(self) -> List[Dict[str, Any]]:
        resp = await self._rpc("tools/list", {})
        return resp.get("tools", []) if resp else []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        # _read_response 已返回 MCP 内层 result（{content:[...], isError:...}），此处直接透传
        resp = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if not resp:
            return "(工具调用无响应)"
        return resp

    async def close(self) -> None:
        if self._proc is None:
            return
        try:
            # 先发 shutdown 通知，再终止
            try:
                await self._rpc("shutdown", {}, notify=True)
            except Exception:
                pass
            if self._proc.returncode is None:
                self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
        except Exception as e:
            logger.warning(f"[MCP] 关闭 Server「{self.label}」异常（忽略）: {e}")
        finally:
            self._proc = None


class MCPHttpClient:
    """单个 HTTP(S) MCP Server 的 Streamable HTTP 客户端（纯标准库，长期存活）。

    传输：POST {url}，Accept: application/json, text/event-stream；维护 Mcp-Session-Id；
    响应可能是 JSON 或 SSE（data: 行），统一解析按 id 匹配。
    与 MCPClient（stdio）暴露相同接口：connect() / list_tools() / call_tool() / close() / _tools，
    因此 register_remote_tools 对两种传输一视同仁（仅构造不同 client）。
    """

    def __init__(self, url: str, timeout: float = 30.0, label: str = ""):
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.label = label or "mcp"
        self._req_id = 0
        self._session_id = None
        self._tools: List[Dict[str, Any]] = []
        self._lock = None  # 延迟到 async 上下文创建（避免同步构造时新建循环）

    async def connect(self) -> None:
        self._lock = asyncio.Lock()
        init_result = await self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        if not init_result:
            raise RuntimeError("MCP HTTP initialize 无响应")
        await self._rpc("notifications/initialized", {}, notify=True)
        self._tools = await self.list_tools()
        if not self._tools:
            logger.warning(f"[MCP] HTTP Server「{self.label}」未暴露任何工具")

    async def _rpc(self, method: str, params: Dict[str, Any], notify: bool = False) -> Dict[str, Any]:
        async with self._lock:
            self._req_id += 1
            req_id = self._req_id
            payload = {"jsonrpc": "2.0", "method": method, "params": params}
            if not notify:
                payload["id"] = req_id
            body = await asyncio.to_thread(self._http_post, payload)
            if notify:
                return {}
            return self._parse_response(body, req_id)

    def _http_post(self, payload: Dict[str, Any]) -> str:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.url,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
        )
        if self._session_id:
            req.add_header("Mcp-Session-Id", self._session_id)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self._session_id = sid
                return resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            try:
                return e.read().decode("utf-8", "replace")
            except Exception:
                raise RuntimeError(f"MCP HTTP 错误: {e.code} {e.reason}")

    @staticmethod
    def _parse_response(body: str, expected_id: int) -> Dict[str, Any]:
        """解析 JSON 或 SSE（data: 行）响应，返回匹配 expected_id 的 result。"""
        body = (body or "").strip()
        if not body:
            return {}
        try:
            msg = json.loads(body)
            if isinstance(msg, dict):
                if "error" in msg:
                    raise RuntimeError(f"MCP 错误响应: {msg['error']}")
                if msg.get("id") == expected_id:
                    return msg.get("result", {})
                return {}
        except json.JSONDecodeError:
            pass
        result: Dict[str, Any] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk:
                continue
            try:
                msg = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("id") == expected_id:
                if "error" in msg:
                    raise RuntimeError(f"MCP 错误响应: {msg['error']}")
                result = msg.get("result", {})
        return result

    async def list_tools(self) -> List[Dict[str, Any]]:
        resp = await self._rpc("tools/list", {})
        return resp.get("tools", []) if resp else []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        resp = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if not resp:
            return "(工具调用无响应)"
        return resp

    async def close(self) -> None:
        if not self._session_id:
            return
        try:
            await self._rpc("notifications/exit", {}, notify=True)
        except Exception:
            pass
        self._session_id = None


def _sanitize_label(label: str) -> str:
    """命名空间只允许安全字符，避免注入到工具名。"""
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in (label or ""))
    return cleaned or "mcp"


def _load_servers_from_config(config_value: Optional[str]) -> List[Dict[str, Any]]:
    """解析 MCP_SERVERS 配置（JSON 数组）。非法则回退空表。"""
    if not config_value:
        return []
    try:
        data = json.loads(config_value)
    except json.JSONDecodeError:
        logger.warning("[MCP] MCP_SERVERS 不是合法 JSON，已忽略")
        return []
    if not isinstance(data, list):
        logger.warning("[MCP] MCP_SERVERS 应为数组，已忽略")
        return []
    servers = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cmd = item.get("command")
        url = item.get("url")
        if isinstance(cmd, list) and cmd:
            servers.append({"command": cmd, "label": item.get("label", "")})
        elif isinstance(url, str) and url:
            # P1-B：HTTP+SSE 传输（远端托管工具服务，不占本地子进程）
            servers.append({"url": url, "label": item.get("label", "")})
        else:
            logger.warning(f"[MCP] 跳过无效 server 配置（需 command 或 url）: {item}")
    return servers


def _create_remote_tool(client: "MCPClient", original_name: str, full_name: str,
                        description: str, parameters: Dict[str, Any]):
    """构造一个继承本地 Tool 的远端工具包装（懒加载 Tool 基类，避免无 chromadb 环境导入失败）。"""
    from app.agent.tools import Tool

    class RemoteTool(Tool):
        def __init__(self):
            self._client = client
            self._remote_name = original_name
            super().__init__(name=full_name, description=description,
                             parameters=parameters, func=self._placeholder)

        async def _placeholder(self, **kwargs):
            return ""

        def _normalize_args(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
            # 远端工具参数完全由远端 inputSchema 定义，原样透传，避免被 base 按函数签名丢弃
            return kwargs

        async def execute(self, **kwargs) -> str:
            try:
                result = await self._client.call_tool(self._remote_name, kwargs)
                return _format_tool_result(result)
            except Exception as e:
                logger.error(f"[MCP] 远端工具 {full_name} 调用失败: {e}")
                return f"Error: {str(e)}"

    return RemoteTool()


def _project_root() -> str:
    """app/agent/mcp_client.py → 上溯三级到仓库根（用于定位 data/mcp_servers.json）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _server_key(srv: Dict[str, Any]) -> tuple:
    """去重键：url 形态用 url，stdio 形态用 command 元组。"""
    if srv.get("url"):
        return ("url", srv["url"])
    return ("cmd", tuple(srv.get("command") or []))


def load_mcp_servers() -> List[Dict[str, Any]]:
    """合并 MCP_SERVERS 环境变量与 data/mcp_servers.json manifest（env 优先，manifest 补漏）。

    - 环境变量非空时仍生效；manifest 中不与 env 重复的条目追加（丢文件即接入，免改环境变量）。
    - manifest 不存在/非法则忽略（优雅降级）。
    """
    env_list = _load_servers_from_config(os.getenv("MCP_SERVERS", ""))
    merged: List[Dict[str, Any]] = list(env_list)
    seen = {_server_key(s) for s in env_list}
    manifest_path = os.path.join(_project_root(), "data", "mcp_servers.json")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for srv in _load_servers_from_config(json.dumps(data)):
                    k = _server_key(srv)
                    if k not in seen:
                        merged.append(srv)
                        seen.add(k)
            else:
                logger.warning("[MCP] mcp_servers.json 不是数组，已忽略")
        except Exception as e:
            logger.warning("[MCP] 读取 mcp_servers.json 失败（已忽略）: %s", e)
    return merged


async def register_remote_tools(tool_registry, servers: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """把若干 MCP Server 暴露的工具注册进本地 ToolRegistry。

    返回成功注册的工具名列表（带 mcp__<label>__ 前缀）。
    - 任一声道失败只记 warning 并跳过，不影响其它 Server 与主链路；
    - 同一个 label 下的重名远端工具会被跳过（不覆盖本地工具）。
    """
    servers = servers or []
    registered: List[str] = []
    for srv in servers:
        command = srv.get("command") or []
        label = _sanitize_label(srv.get("label") or (command[0] if command else (srv.get("url") or "mcp")))
        # P1-B：url → HTTP+SSE 传输；command → stdio 传输。接口一致，register 逻辑共用。
        if srv.get("url"):
            client = MCPHttpClient(url=srv["url"], label=label)
        else:
            client = MCPClient(command=command, label=label)
        try:
            logger.info(f"[MCP] 正在连接 Server「{label}」: {command}")
            await asyncio.wait_for(client.connect(), timeout=client.timeout + 5)
        except Exception as e:
            logger.warning(f"[MCP] 连接 Server「{label}」失败，已跳过: {e}")
            await client.close()
            continue
        _CLIENTS.append(client)
        for t in client._tools:
            remote_name = t.get("name")
            if not remote_name:
                continue
            full_name = f"mcp__{label}__{remote_name}"
            if tool_registry.get(full_name):
                logger.warning(f"[MCP] 工具名冲突，跳过: {full_name}")
                continue
            if tool_registry.get(remote_name):
                # 远端未加前缀的原始名与本地冲突，跳过避免覆盖
                logger.warning(f"[MCP] 远端工具「{remote_name}」与本地工具重名，已用前缀跳过")
                continue
            desc = t.get("description", f"远端工具（来自 MCP Server {label}）")
            params = t.get("inputSchema") or {"type": "object", "properties": {}}
            tool = _create_remote_tool(client, remote_name, full_name, desc, params)
            tool_registry.register(tool)
            registered.append(full_name)
            logger.info(f"[MCP] 已注册远端工具: {full_name}")
    if registered:
        _REGISTERED_NAMES.extend(registered)
        logger.info(f"[MCP] 共注册 {len(registered)} 个远端工具")
    return registered


async def shutdown_all() -> None:
    """关闭所有已建立的 MCP Server 子进程（应用退出时调用）。"""
    for client in _CLIENTS:
        await client.close()
    _CLIENTS.clear()
    _REGISTERED_NAMES.clear()


def get_registered_names() -> List[str]:
    return list(_REGISTERED_NAMES)
