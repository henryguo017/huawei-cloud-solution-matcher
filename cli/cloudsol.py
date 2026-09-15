#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloudsol CLI v1 —— 薄客户端（纯新增，零服务器改动）。

设计要点（2026-09-15 拍板）：
  - 命令名 cloudsol；六命令：login / ask / solve / ppt / client / status
  - 所有智能在生产 API（默认 https://cloudsol.cn），本地只做 HTTP 客户端
  - rich 可选：未安装自动降级纯文本流式输出（v1 不用 Live 渲染，保证 input() 权限确认安全）
  - 认证：login 拉验证码图自动打开人眼识别；token 存 ~/.cloudsol/config.json；
    401 自动 refresh 一次，再失败提示重新 login（绝不自动重试登录，防锁定）
  - 权限：SSE permission_request 事件 → 终端 [y/N] → POST /agent/permission/{id}；
    CRM 写操作无视 --yes 强制确认
  - 退出码：0 成功 / 1 用法错误 / 2 认证 / 3 超时 / 4 HTTP / 5 网络

运行：venv/Scripts/python.exe cli/cloudsol.py <命令>
"""
import argparse
import base64
import json
import os
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

import requests

try:
    from rich.console import Console
    from rich.json import JSON as RichJSON
    from rich.panel import Panel
    RICH = True
except ImportError:  # 降级：无 rich 也能全功能跑
    RICH = False

DEFAULT_BASE = "https://cloudsol.cn"
CONFIG_PATH = Path.home() / ".cloudsol" / "config.json"
CONNECT_TIMEOUT = 20
READ_TIMEOUT = 900          # 对齐 Agent 单次最长窗口（与钉钉 bot 一致）

EXIT_OK, EXIT_USAGE, EXIT_AUTH, EXIT_TIMEOUT, EXIT_HTTP, EXIT_NET = 0, 1, 2, 3, 4, 5

# CRM 写操作工具名特征：无视 --yes 一律终端确认
CRM_WRITE_MARKS = ("client_add", "client_update", "client_delete", "crm")

console = Console() if RICH else None


# ───────────────────────── 基础设施 ─────────────────────────

def _utf8_stdio():
    """Windows 控制台 UTF-8 兜底（老 cmd 默认 GBK）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(msg: str = ""):
    print(msg, flush=True)


def perr(msg: str):
    print(msg, file=sys.stderr, flush=True)


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_config(cfg: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 尽力收紧文件权限（Windows 上为 best-effort）
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def make_session(token: str) -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 与探针一致：忽略系统代理，直连
    s.headers.update({"Authorization": f"Bearer {token}",
                      "Content-Type": "application/json"})
    return s


def _refresh_token(base: str, cfg: dict) -> str | None:
    """用当前仍有效的 JWT 滑动续期；API Key（ck_ 前缀）不支持续期；失败返回 None。"""
    if cfg.get("token", "").startswith("ck_"):
        return None  # API Key 无续期语义：过期/吊销需到网页重新签发
    try:
        r = make_session(cfg.get("token", "")).post(
            f"{base}/api/auth/refresh", timeout=(CONNECT_TIMEOUT, 30))
        if r.status_code == 200:
            tok = r.json().get("access_token")
            if tok:
                cfg["token"] = tok
                save_config(cfg)
                return tok
    except requests.RequestException:
        pass
    return None


def client(base: str, cfg: dict, allow_refresh: bool = True) -> requests.Session:
    """带 401 自动续期一次的会话工厂；续期失败走 SystemExit(2)。"""
    s = make_session(cfg.get("token", ""))
    try:
        probe = s.get(f"{base}/api/auth/me", timeout=(CONNECT_TIMEOUT, 30))
    except requests.RequestException as e:
        perr(f"[网络] 无法连接 {base}：{e}")
        raise SystemExit(EXIT_NET)
    if probe.status_code == 401 and allow_refresh:
        if cfg.get("token", "").startswith("ck_"):
            perr("[认证] API Key 无效/已吊销/已过期，请到网页重新签发后 "
                 "执行：cloudsol login --token <新Key>")
            raise SystemExit(EXIT_AUTH)
        new_tok = _refresh_token(base, cfg)
        if new_tok:
            return make_session(new_tok)
        perr("[认证] token 已失效且无法续期，请执行：cloudsol login")
        raise SystemExit(EXIT_AUTH)
    if probe.status_code != 200:
        perr(f"[认证] /api/auth/me 返回 {probe.status_code}：{probe.text[:200]}")
        raise SystemExit(EXIT_AUTH)
    return s


def _fail_http(resp: requests.Response):
    perr(f"[HTTP] {resp.status_code}：{resp.text[:300]}")
    raise SystemExit(EXIT_HTTP)


# ───────────────────────── login ─────────────────────────

def cmd_login(args) -> int:
    base = args.base_url.rstrip("/")
    cfg = load_config()
    cfg["base_url"] = base

    if args.token:  # 直接灌 token（脚本/调试场景）
        cfg["token"] = args.token.strip()
        save_config(cfg)
        say(f"✓ token 已写入 {CONFIG_PATH}")
        return EXIT_OK

    username = args.username or input("用户名: ").strip()
    password = args.password or input("密码: ").strip()
    if not username or not password:
        perr("[登录] 用户名/密码不能为空")
        return EXIT_USAGE

    # 1. 拉验证码 → 存图 → 自动打开，人眼识别（不烧 AI、不烧登录次数）
    s = requests.Session(); s.trust_env = False
    try:
        cap = s.get(f"{base}/api/auth/captcha", timeout=(CONNECT_TIMEOUT, 30)).json()
    except requests.RequestException as e:
        perr(f"[网络] 拉取验证码失败：{e}")
        return EXIT_NET
    img_b64 = cap["captcha_image"].split(",", 1)[-1]
    cap_path = Path(tempfile.gettempdir()) / "cloudsol_captcha.png"
    cap_path.write_bytes(base64.b64decode(img_b64))
    say(f"验证码图片已保存：{cap_path}")
    try:
        if sys.platform == "win32":
            os.startfile(str(cap_path))  # noqa: S606
        else:
            webbrowser.open(f"file://{cap_path}")
    except Exception:
        say("（未能自动打开图片，请手动查看上方路径）")
    captcha_value = input("请输入图中验证码: ").strip()

    # 2. 登录
    try:
        r = s.post(f"{base}/api/auth/login", timeout=(CONNECT_TIMEOUT, 30), json={
            "username": username, "password": password,
            "captcha_key": cap["captcha_key"], "captcha_value": captcha_value,
        })
    except requests.RequestException as e:
        perr(f"[网络] 登录请求失败：{e}")
        return EXIT_NET
    if r.status_code != 200:
        perr(f"[登录] 失败（{r.status_code}）：{r.text[:200]}\n提示：验证码错误需重新拉取，再执行一次 login。")
        return EXIT_AUTH
    cfg["token"] = r.json().get("access_token", "")
    if not cfg["token"]:
        perr("[登录] 响应中没有 access_token")
        return EXIT_AUTH
    save_config(cfg)
    say(f"✓ 登录成功，token 已写入 {CONFIG_PATH}（6 小时有效，401 时自动续期）")
    return EXIT_OK


# ───────────────────────── 对话核心（ask/solve/ppt 共用） ─────────────────────────

def _confirm_permission(tool: str, inp: str, reason: str, yes: bool) -> bool:
    """终端权限确认；CRM 写操作无视 --yes。"""
    is_crm = any(m in tool for m in CRM_WRITE_MARKS)
    if yes and not is_crm:
        say(f"  [自动放行] {tool}（--yes）")
        return True
    say("─" * 60)
    say(f"⚙ 工具请求执行：{tool}")
    if reason:
        say(f"  理由：{reason}")
    if inp:
        say(f"  入参：{inp[:300]}")
    if is_crm:
        say("  （CRM 写操作：--yes 不生效，必须人工确认）")
    ans = input("  允许执行？[y/N] ").strip().lower()
    return ans == "y"


def _download_docs(base: str, s: requests.Session, docs: list, out_dir: Path) -> list:
    saved = []
    for d in docs:
        url = d.get("download_url") or ""
        name = d.get("file_name") or f"doc_{int(time.time())}.{d.get('fmt') or 'bin'}"
        if not url:
            continue
        full = url if url.startswith("http") else base + (url if url.startswith("/") else "/" + url)
        try:
            r = s.get(full, timeout=(CONNECT_TIMEOUT, 120))
            if r.status_code != 200:
                say(f"  ✗ 下载失败 {name}（HTTP {r.status_code}）")
                continue
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / name
            dest.write_bytes(r.content)
            say(f"  ✓ 已保存：{dest}")
            saved.append(dest)
        except requests.RequestException as e:
            say(f"  ✗ 下载失败 {name}：{e}")
    return saved


def run_chat(args, message: str) -> int:
    base = args.base_url.rstrip("/")
    cfg = load_config()
    if not cfg.get("token"):
        perr("[认证] 未登录，请先执行：cloudsol login")
        return EXIT_AUTH
    s = client(base, cfg)

    session_id = args.session or f"cli_{time.strftime('%Y%m%d_%H%M%S')}"
    runtime = "legacy" if args.legacy else "fc"
    payload = {
        "message": message,
        "session_id": session_id,
        "runtime": runtime,
        "autonomy": "high",
        "tool_permissions": {"generate_doc": "allow", "run_python": "allow"},
        "disable_web_search": bool(args.no_web),
    }

    out_dir = Path(args.out) if args.out else Path("cloudsol_out") / time.strftime("%Y%m%d_%H%M%S")
    say(f"会话：{session_id}  引擎：{runtime}" + ("  （续聊）" if args.session else ""))
    say(f"输出目录：{out_dir}")
    say("─" * 60)

    spinner = console.status("思考中…", spinner="dots") if RICH else None
    try:
        if spinner:
            spinner.start()
        r = s.post(f"{base}/api/agent/chat", json=payload,
                   timeout=(CONNECT_TIMEOUT, READ_TIMEOUT), stream=True)
        if r.status_code == 401:
            new_tok = _refresh_token(base, cfg)
            if not new_tok:
                perr("[认证] token 失效且续期失败，请重新 login")
                return EXIT_AUTH
            if spinner:
                spinner.stop()
            say("[认证] token 已自动续期，重试请求…")
            args.session = session_id  # 保持同一会话重试
            return run_chat(args, message)
        if r.status_code != 200:
            _fail_http(r)
        r.encoding = "utf-8"

        first_event = True
        docs, final, answer_len = [], {}, 0
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            try:
                ev = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            if first_event and spinner:
                spinner.stop()
                first_event = False
            if etype == "delta":
                text = ev.get("text", "")
                sys.stdout.write(text); sys.stdout.flush()
                answer_len += len(text)
            elif etype == "permission_request":
                if spinner:
                    spinner.stop()
                allow = _confirm_permission(ev.get("tool", ""), ev.get("input") or "",
                                            ev.get("reason") or "", args.yes)
                s.post(f"{base}/api/agent/permission/{ev.get('request_id','')}",
                       json={"decision": "allow" if allow else "deny"},
                       timeout=(CONNECT_TIMEOUT, 30))
                say(f"  → 已回传决策：{'允许' if allow else '拒绝'}")
            elif etype == "doc_generated":
                docs.append(ev)
                say(f"\n📄 生成文档：{ev.get('file_name')}（{ev.get('fmt')}）")
            elif etype == "result":
                final = ev  # 终事件：type=result，含 runtime/success/fc_meta/elapsed/answer
        if spinner and spinner.status is not None:
            try:
                spinner.stop()
            except Exception:
                pass
    except requests.Timeout:
        perr(f"\n[超时] {READ_TIMEOUT}s 未完成（部分内容可用 --session {session_id} 续聊）")
        return EXIT_TIMEOUT
    except requests.RequestException as e:
        perr(f"\n[网络] 请求中断：{e}")
        say(f"部分内容已产出，可 --session {session_id} 续聊")
        return EXIT_NET

    saved = _download_docs(base, s, docs, out_dir) if docs else []

    # ── 结果摘要 ──
    say("─" * 60)
    if final:
        fcm = final.get("fc_meta") or {}
        say(f"引擎={final.get('runtime')}  成功={final.get('success')}"
            f"  轮数={fcm.get('turns')}  tokens={fcm.get('tokens')}"
            f"  收尾={fcm.get('stopped_by')}  耗时={final.get('elapsed') or '-'}s")
    say(f"会话 ID：{session_id}（续聊加 --session {session_id}）")
    if not final and answer_len == 0 and not docs:
        perr("[警告] 未收到任何有效输出")
        return EXIT_HTTP
    return EXIT_OK


def cmd_ask(args) -> int:
    return run_chat(args, args.message)


def cmd_solve(args) -> int:
    return run_chat(args, args.message)


def cmd_ppt(args) -> int:
    if not args.session and ("整理" in args.message or "PPT" in args.message.upper()) \
            and len(args.message) < 30:
        say("[提示] 空会话里没有方案可整理。建议：先用 solve 出方案拿到会话 ID，"
            "再 ppt \"把方案整理成 PPT\" --session <会话ID>；或直接给完整需求让 Agent 一步到位。")
    return run_chat(args, args.message)


# ───────────────────────── client ─────────────────────────

STAGES = ["初步接触", "需求调研", "方案报价", "商务谈判", "已成交", "已流失"]


def cmd_client(args) -> int:
    base = args.base_url.rstrip("/")
    cfg = load_config()
    s = client(base, cfg)

    if args.action == "list":
        r = s.get(f"{base}/api/clients", timeout=(CONNECT_TIMEOUT, 30))
        if r.status_code != 200:
            _fail_http(r)
        data = r.json()
        rows = data if isinstance(data, list) else (data.get("clients") or data.get("items") or [])
        if not rows:
            say("（客户档案为空）")
            return EXIT_OK
        say(f"共 {len(rows)} 个客户：")
        for c in rows:
            say(f"  #{c.get('id')}  {c.get('name')}  ｜ {c.get('industry') or '-'}"
                f"  ｜ {c.get('stage') or '-'}  ｜ {c.get('budget') or '-'}")
        return EXIT_OK

    if args.action == "add":
        name = args.name or input("客户名称（必填）: ").strip()
        industry = args.industry or input("所属行业（必填，须为系统支持行业）: ").strip()
        if not name or not industry:
            perr("[建档] name / industry 为必填")
            return EXIT_USAGE
        payload = {"name": name, "industry": industry}
        for key, prompt, default in [
            ("stage", f"商机阶段 {'/'.join(STAGES)}", ""),
            ("budget", "预算范围", ""),
            ("note", "备注", ""),
        ]:
            val = getattr(args, key, None) or input(f"{prompt}（可回车跳过）: ").strip()
            if val:
                payload[key] = val
        # CRM 写：完整 payload 展示 + 强制确认（--yes 不生效，已拍板）
        say("─" * 60)
        say("即将写入客户档案：")
        say(json.dumps(payload, ensure_ascii=False, indent=2))
        if input("确认写入？[y/N] ").strip().lower() != "y":
            say("已取消，未写入。")
            return EXIT_OK
        r = s.post(f"{base}/api/clients", json=payload, timeout=(CONNECT_TIMEOUT, 60))
        if r.status_code not in (200, 201):
            _fail_http(r)
        say(f"✓ 已建档：{json.dumps(r.json(), ensure_ascii=False)[:200]}")
        return EXIT_OK

    perr("[用法] client 子命令仅支持 list / add")
    return EXIT_USAGE


# ───────────────────────── status ─────────────────────────

def cmd_status(args) -> int:
    base = args.base_url.rstrip("/")
    cfg = load_config()
    s = client(base, cfg)

    say(f"═══ cloudsol 生产体检 · {args.date or '今天'} ═══")
    r = s.get(f"{base}/api/agent/gray-summary",
              params={"date": args.date or ""}, timeout=(CONNECT_TIMEOUT, 30))
    if r.status_code != 200:
        _fail_http(r)
    g = r.json()
    keys = ["total_runs", "fc_runs", "legacy_runs", "fallback_rate", "stopped_by",
            "a11_rate", "avg_turns_fc", "avg_tokens_fc", "avg_elapsed_fc", "success_rate_fc"]
    for k in keys:
        if k in g:
            say(f"  {k:18} {g[k]}")
    try:
        r2 = s.get(f"{base}/api/knowledge/stats", timeout=(CONNECT_TIMEOUT, 30))
        if r2.status_code == 200:
            ks = r2.json()
            say("  ── 知识库 ──")
            for k in ("total_documents", "total_chunks", "industries", "competitors"):
                if k in ks:
                    say(f"  {k:18} {ks[k]}")
    except requests.RequestException:
        pass
    return EXIT_OK


# ───────────────────────── key（API Key 自助管理） ─────────────────────────

def cmd_key(args) -> int:
    base = args.base_url.rstrip("/")
    cfg = load_config()
    if not cfg.get("token"):
        perr("[认证] 未登录。签发 Key 需要 JWT 身份：先 cloudsol login（账号密码），"
             "再用得到的 Key 作为日常凭证（cloudsol login --token ck_...）")
        return EXIT_AUTH
    if cfg.get("token", "").startswith("ck_"):
        perr("[权限] 当前登录身份是 API Key，Key 不能管理 Key。"
             "请先用账号密码 cloudsol login（JWT）再操作。")
        return EXIT_AUTH
    s = client(base, cfg)

    if args.action == "create":
        name = args.name or input("Key 备注名（可回车跳过）: ").strip()
        r = s.post(f"{base}/api/auth/api-key", json={"name": name},
                   timeout=(CONNECT_TIMEOUT, 30))
        if r.status_code != 200:
            _fail_http(r)
        d = r.json()
        say("─" * 60)
        say(f"✓ 已签发（明文仅此一次显示，立即保存）：\n  {d['key']}")
        say(f"  前缀 {d['key_prefix']} ｜ 配额 {d['daily_limit']} 次/天")
        say(f"  启用：cloudsol login --token {d['key']}")
        return EXIT_OK

    if args.action == "list":
        r = s.get(f"{base}/api/auth/api-keys", timeout=(CONNECT_TIMEOUT, 30))
        if r.status_code != 200:
            _fail_http(r)
        keys = r.json().get("keys", [])
        if not keys:
            say("（尚无 API Key）")
            return EXIT_OK
        for k in keys:
            state = "已吊销" if k["revoked"] else f"今日 {k['today_used']}/{k['daily_limit']}"
            say(f"  #{k['id']}  {k['key_prefix']}…  ｜ {k['name'] or '-'}"
                f"  ｜ {k['created_at'][:16] if k['created_at'] else '-'}  ｜ {state}")
        return EXIT_OK

    if args.action == "revoke":
        r = s.get(f"{base}/api/auth/api-keys", timeout=(CONNECT_TIMEOUT, 30))
        if r.status_code != 200:
            _fail_http(r)
        keys = [k for k in r.json().get("keys", []) if not k["revoked"]]
        for k in keys:
            say(f"  #{k['id']}  {k['key_prefix']}…  ｜ {k['name'] or '-'}")
        kid = args.key_id or input("要吊销的 Key 编号（#号后数字）: ").strip().lstrip("#")
        if not kid.isdigit():
            perr("[用法] 需要数字编号")
            return EXIT_USAGE
        r = s.delete(f"{base}/api/auth/api-key/{kid}", timeout=(CONNECT_TIMEOUT, 30))
        if r.status_code != 200:
            _fail_http(r)
        say(f"✓ #{kid} 已吊销")
        return EXIT_OK

    perr("[用法] key 子命令仅支持 create / list / revoke")
    return EXIT_USAGE



# ───────────────────────── 入口 ─────────────────────────

def build_parser() -> argparse.ArgumentParser:
    # 公共参数（--base-url/--yes）在主命令与子命令后均可出现：
    # 主/子两级都挂 parents，子级 default=SUPPRESS 防止覆盖主级已解析值。
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=argparse.SUPPRESS,
                        help=f"服务地址（默认 {DEFAULT_BASE}）")
    common.add_argument("--yes", action="store_true", default=argparse.SUPPRESS,
                        help="非 CRM 写操作自动放行（CRM 写仍强制确认）")
    p = argparse.ArgumentParser(prog="cloudsol", parents=[common],
                                description="cloudsol.cn 售前 AI Agent 命令行客户端")
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("login", parents=[common], help="登录（验证码人眼识别 / token / API Key）")
    lp.add_argument("--username"); lp.add_argument("--password")
    lp.add_argument("--token", help="直接写入已有凭证：JWT 或 API Key（ck_ 开头）")
    lp.set_defaults(fn=cmd_login)

    def add_chat_args(sp):
        sp.add_argument("message", help="需求/问题文本")
        sp.add_argument("--session", help="续聊会话 ID")
        sp.add_argument("--legacy", action="store_true", help="走 legacy 引擎（默认 fc）")
        sp.add_argument("--no-web", action="store_true", help="禁用联网搜索")
        sp.add_argument("--out", help="输出目录（默认 ./cloudsol_out/<时间戳>/）")

    ap = sub.add_parser("ask", parents=[common], help="单轮问答")
    add_chat_args(ap); ap.set_defaults(fn=cmd_ask)

    sp_ = sub.add_parser("solve", parents=[common], help="Agent 出方案正文（落盘）")
    add_chat_args(sp_); sp_.set_defaults(fn=cmd_solve)

    pp = sub.add_parser("ppt", parents=[common], help="方案整理成 PPT（建议配 --session 续会话）")
    add_chat_args(pp); pp.set_defaults(fn=cmd_ppt)

    cp = sub.add_parser("client", parents=[common], help="客户档案 list / add")
    cp.add_argument("action", choices=["list", "add"])
    cp.add_argument("--name"); cp.add_argument("--industry")
    cp.add_argument("--stage"); cp.add_argument("--budget"); cp.add_argument("--note")
    cp.set_defaults(fn=cmd_client)

    st = sub.add_parser("status", parents=[common], help="生产体检：灰度观测 + 知识库统计")
    st.add_argument("--date", help="查询日期 YYYY-MM-DD（默认今天）")
    st.set_defaults(fn=cmd_status)

    kp = sub.add_parser("key", parents=[common], help="API Key 自助管理（签发需 JWT 登录）")
    kp.add_argument("action", choices=["create", "list", "revoke"])
    kp.add_argument("--name", help="create：Key 备注名")
    kp.add_argument("--key-id", help="revoke：要吊销的 Key 编号")
    kp.set_defaults(fn=cmd_key)
    return p


def main(argv=None) -> int:
    _utf8_stdio()
    args = build_parser().parse_args(argv)
    # SUPPRESS 缺省兜底：主/子任一级都没给时落默认值
    if getattr(args, "base_url", None) is None:
        args.base_url = DEFAULT_BASE
    args.yes = getattr(args, "yes", False)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        say("\n（已中断）")
        return 130


if __name__ == "__main__":
    sys.exit(main())
