#!/usr/bin/env python3
"""Install the host-driven Deep Research Agent for Codex, Claude Code and DSH.

Run once with Python 3.11+: python Install_Deep_Research_Agent.py
Then open your host and say: 帮我调用 deep-research-agent 深度研究某个问题。
No separate language-model API key is needed. Existing host web tools or an
optional search-provider key are still needed to retrieve live information.
"""
import argparse
import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tomllib
import zlib

PAYLOAD = "__RESEARCH_PAYLOAD__"
PAYLOAD_SHA256 = "__RESEARCH_SHA256__"
NAME = "deep-research-agent"


def payload_files():
    raw = zlib.decompress(base64.b64decode(PAYLOAD))
    if hashlib.sha256(raw).hexdigest() != PAYLOAD_SHA256:
        raise ValueError("Installer payload digest mismatch")
    files = json.loads(raw)
    allowed = {"SKILL.md", "agents/openai.yaml", "references/tools.md", "scripts/research.py", "scripts/research_reader.py", "scripts/research_providers.py", "references/providers.md", "assets/icon.svg", "scripts/research_catalog.py", "references/source-registry.json", "references/sources.md", "scripts/research_reading.py", "references/reading.md"}
    if set(files) != allowed or any(not isinstance(v,str) for v in files.values()):
        raise ValueError("Installer payload file set mismatch")
    return files


def backed_write(path, text, changes, dry_run=False):
    path = Path(path)
    if path.exists() and path.is_symlink():
        raise ValueError("Refusing to replace a symbolic-link configuration: " + str(path))
    old = path.read_text(encoding="utf-8-sig") if path.exists() else None
    if old == text:
        return
    changes.append(str(path))
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if old is not None:
        suffix = ".backup-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        shutil.copy2(path, path.with_name(path.name + suffix))
    temp = path.with_name(path.name + ".deep-research-tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush(); os.fsync(stream.fileno())
    temp.replace(path)


def codex_config(old, entry):
    begin, end = "# BEGIN deep-research-agent managed section", "# END deep-research-agent managed section"
    if begin in old:
        if end not in old or old.count(begin) != 1 or old.count(end) != 1:
            raise ValueError("Existing managed Codex configuration is malformed")
        before, _, rest = old.partition(begin)
        _, _, after = rest.partition(end)
        old = before.rstrip() + "\n" + after.lstrip("\n")
    parsed = tomllib.loads(old)
    if "deep_research" in parsed.get("mcp_servers", {}):
        raise ValueError("An unmanaged Codex MCP server named deep_research exists; rename it or use --without-mcp")
    block = [begin, "[mcp_servers.deep_research]", "command = " + json.dumps(entry["command"]),
        "args = " + json.dumps(entry["args"]), "startup_timeout_sec = 20", "tool_timeout_sec = 120", end]
    text = old.rstrip() + "\n\n" + "\n".join(block) + "\n"
    tomllib.loads(text)
    return text


def claude_config(old, entry):
    obj = json.loads(old) if old.strip() else {}
    if not isinstance(obj, dict) or not isinstance(obj.get("mcpServers", {}), dict):
        raise ValueError("Claude MCP configuration must be a JSON object")
    servers = obj.setdefault("mcpServers", {})
    existing = servers.get("deep_research")
    # Do not silently hijack another user's server at the same name.
    if existing and existing != entry:
        args = existing.get("args", []) if isinstance(existing,dict) else []
        if not any("research.py" in str(x) for x in args):
            raise ValueError("An unrelated Claude server named deep_research exists; rename it or use --without-mcp")
    servers["deep_research"] = entry
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def install(home, project=None, hosts=("codex","claude","dsh"), mcp=True, dry_run=False):
    files = payload_files()
    home = Path(home).expanduser().resolve()
    project = Path(project).expanduser().resolve() if project else None
    base = project/".deep-research" if project else home/".local/share/deep-research-agent"
    shared = (project/".agents/skills" if project else home/".agents/skills")/NAME
    claude_skill = (project/".claude/skills" if project else home/".claude/skills")/NAME
    dsh_home = Path(os.environ.get("DSH_HOME", str(home/".dsh"))).expanduser().resolve()
    dsh_skill = (project/".dsh/skills" if project else dsh_home/"skills")/NAME
    destinations = []
    if "codex" in hosts: destinations.append(shared)
    if "claude" in hosts: destinations.append(claude_skill)
    if "dsh" in hosts: destinations.append(dsh_skill)
    env_file = base/"research.env"
    runtime = base/"runtime"
    args = [str(runtime/"research.py"), "serve", "--root", str(base/"runs"), "--env", str(env_file)]
    entry = {"type":"stdio", "command":sys.executable, "args":args}
    changes = []
    writes = []
    for target in destinations:
        writes += [(target/relative, text) for relative,text in files.items()]
    for name in ["research.py","research_reader.py","research_providers.py","research_catalog.py","research_reading.py"]:
        writes.append((runtime/name, files["scripts/"+name]))
    writes.append((runtime/"references/source-registry.json",files["references/source-registry.json"]))
    env_defaults = {"RESEARCH_SEARCH_PROVIDER":"auto", "RESEARCH_STRATEGY":"balanced",
        "PERPLEXITY_API_KEY":"", "TAVILY_API_KEY":"", "EXA_API_KEY":"", "FIRECRAWL_API_KEY":"",
        "LINKUP_API_KEY":"", "PARALLEL_API_KEY":"", "SERPSEARCH_API_KEY":"", "KEENABLE_API_KEY":"",
        "ANYSEARCH_API_KEY":"", "SERPAPI_API_KEY":"", "RESEARCH_PROVIDER_ORDER":"",
        "RESEARCH_DISABLED_PROVIDERS":"", "RESEARCH_MAX_ATTEMPTS":"3",
        "RESEARCH_MAX_API_REQUESTS":"", "RESEARCH_CACHE_TTL":"3600", "RESEARCH_ALLOW_KEYLESS_KEENABLE":"false"}
    old_env = env_file.read_text(encoding="utf-8-sig") if env_file.exists() else "# Native host tools first. Optional retrieval only; no separate LLM key.\n"
    present = {line.strip().partition("=")[0] for line in old_env.splitlines() if line.strip() and not line.lstrip().startswith("#")}
    missing = [key+"="+value for key,value in env_defaults.items() if key not in present]
    if missing:
        writes.append((env_file, old_env.rstrip()+"\n"+"\n".join(missing)+"\n"))
    if "claude" in hosts:
        agent_path = (project/".claude/agents" if project else home/".claude/agents")/(NAME+".md")
        prompt = ('---\nname: deep-research-agent\ndescription: "Deep research specialist. Use when asked to 调用 deep-research-agent or research a topic in depth with sources."\nmodel: inherit\n---\n\n'
            'Read and follow the research workflow at '+str(claude_skill/"SKILL.md")+'.\n'
            'Use your inherited host model and available tools. Do not require a separate model API key.\n'
            'The workflow helper is '+str(claude_skill/"scripts/research.py")+'.\n'
            'Use original sources, iterate over gaps, review claims and publish only grounded conclusions.\n')
        writes.append((agent_path, prompt))
    if mcp and "codex" in hosts:
        codex_home = Path(os.environ.get("CODEX_HOME", str(home/".codex"))).expanduser().resolve()
        path = project/".codex/config.toml" if project else codex_home/"config.toml"
        old = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        writes.append((path, codex_config(old, entry)))
    if mcp and "claude" in hosts:
        path = project/".mcp.json" if project else home/".claude.json"
        old = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        writes.append((path, claude_config(old, entry)))
    if "dsh" in hosts:
        snippet = ("# Optional: import this entry into the intended DSH Cordis scope.\n"
            "# The installed skill already works through the terminal fallback.\n"
            "- id: mcp-deep-research\n  name: '@deepseek-ai/dsh-mcp-client'\n  config:\n"
            "    serverName: deep_research\n    transport: stdio\n    command: "+json.dumps(sys.executable)+"\n"
            "    args: "+json.dumps(args)+"\n    toolCallTimeoutMs: 120000\n")
        writes.append((base/"dsh-mcp.yaml", snippet))
    setup_note = f"""# 深度研究 Agent 已安装

在所选宿主中新建一个会话，然后说：

帮我调用 deep-research-agent，深度研究某个问题，核对原文并生成带引用的报告。

Codex 显式入口：$deep-research-agent 深度研究某个问题。
Claude Code 显式入口：/deep-research-agent 某个问题；或请求调用同名 agent。
DSH：请求调用 deep-research-agent。其 profile 需要已启用 skill 和终端工具。

使用当前宿主模型完成规划、阅读、分析和写作，不另外调用语言模型 API。
联网资料依赖宿主已有的搜索/阅读工具；若缺少，可在 {env_file} 配置检索服务 Key。
检索服务可能收费，宿主自身模型额度也照常消耗。
默认 native → Perplexity → 按任务选择已配置 API；可在 env 填任意几个 Key，其他留空。
升级会保留已有 Key 和偏好。旧版如设置 RESEARCH_SEARCH_PROVIDER=perplexity/tavily，
请改为 auto 才启用全部渠道自动路由。RESEARCH_STRATEGY 可选 balanced/quality/economy。
运行 runtime/research.py doctor --env research.env 查看渠道可用性；doctor 不联网、不显示 Key。
请勿把 Key 发到聊天、README 或 GitHub。Keenable 免 Key 端点须显式开启；Parallel REST 需 Key。

报告与检查点默认保存到 {base/'runs'}。使用 CLI 回退时，宿主可指定自己的报告目录。
DSH 另有 dsh-deep-research-agent 标准 bundle 安装方式，见发行包 DSH_PUBLISHING.md。
此 Python 安装方式默认走已安装工作流与终端；可选 MCP 注册示例：{base/'dsh-mcp.yaml'}。
没有自动修改 DSH 的 Cordis composition，避免破坏现有 profile。

如宿主没有发现新入口，重新打开其会话或刷新工具列表。宿主仍可能要求信任项目和批准工具调用。
本安装器不更改自动批准规则，不安装 Python，不绕过联网权限。
Windows、WSL 和远程容器是不同环境；在运行宿主的那个环境分别安装。

现有配置先解析再修改，改动文件旁保留带时间戳备份。不要公开 research.env 或包含私人资料的研究目录。

方法限制：正文来源可由宿主工具导入，真实性由该读取路径负责。服务端检查原文匹配与引用完整性，
语义判断仍由宿主模型执行，不是独立人工验证。部分报告会明确标注缺口。
"""
    writes.append((base/"START_HERE.md", setup_note))
    # Parse/plan all configuration changes before making any mutation.
    for path,text in writes:
        if path.exists() and path.is_symlink():
            raise ValueError("Refusing symbolic-link destination: "+str(path))
    for path,text in writes:
        backed_write(path,text,changes,dry_run)
    if not dry_run and os.name != "nt" and env_file.exists():
        env_file.chmod(0o600)
    return {"hosts":list(hosts),"scope":"project" if project else "user", "root":str(base),
        "changed_files":changes,"dry_run":dry_run,"mcp_codex_claude":mcp,
        "dsh_mcp_auto_configured":False,"start_here":str(base/"START_HERE.md")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="为 Codex、Claude Code 和 DSH 安装一句话触发的深度研究工作流")
    parser.add_argument("--project",help="只安装到此项目；省略时安装为当前用户全局入口")
    parser.add_argument("--hosts",default="codex,claude,dsh",help="逗号分隔：codex,claude,dsh")
    parser.add_argument("--without-mcp",action="store_true",help="仅安装工作流及本地工具，不修改宿主 MCP 配置")
    parser.add_argument("--dry-run",action="store_true",help="只列出拟修改文件")
    args = parser.parse_args(argv)
    hosts=tuple(x.strip() for x in args.hosts.split(",") if x.strip())
    if not hosts or any(x not in {"codex","claude","dsh"} for x in hosts):
        parser.error("--hosts 只能是 codex、claude、dsh")
    try:
        result=install(Path.home(),args.project,hosts,not args.without_mcp,args.dry_run)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if not args.dry_run:
            print("\n安装文件已写入。重新打开宿主会话后说：帮我调用 deep-research-agent 深度研究……")
    except Exception as exc:
        print("安装未完成："+str(exc),file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":raise SystemExit(main())
