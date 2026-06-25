# 设计规格:Layer2 可插拔 agent 调度后端(`AgentBackend`)

- **日期**:2026-06-25
- **状态**:Draft(待评审)
- **所属项目**:AgentSAST(`/home/atituiset/Projects/AgentSAST`)
- **前置**:`docs/superpowers/specs/2026-06-25-gen-auto-sarif-bridge-design.md`(§5.7 引入 `McpLspBackend`)、`docs/superpowers/plans/2026-06-25-layer2-backend-mcp.md`
- **外部依赖**:`isaacphi/mcp-language-server`(Go,clangd via MCP)、`openai` SDK(已为 Layer3 依赖)

---

## 1. 背景与动机

AgentSAST 的 Layer2 切片引擎通过 `ProgramUnderstandingBackend` 协议(`src/agentsast/layer2/backend.py:20`)获取 caller/callee,目前有两个实现:

- `TreeSitterBackend`(默认,语法级,零依赖)
- `McpLspBackend`(clangd via MCP,语义级)

`McpLspBackend` 当前是**程序化直连**:`Slicer` 在 `src/agentsast/layer2/slicer.py:312/338` 硬编码调用 `find_callers`/`find_callees`,backend 内部直接 `call_tool("callers", {...})` 查 mcp-language-server(`src/agentsast/layer2/mcp_lsp_backend.py:58-70`)。**决策者是代码,不是模型。**

这种方式确定、快速,但对**复杂 source→sink 路径**(跨文件间接调用、宏包装、函数指针、回调注册)召回不足——它只做机械的 callers/callees 遍历,不会"看源码判断这个 caller 是否真的把污点传了过去"。

本设计在**不破坏现有接口、不改动 Slicer**的前提下,新增第三档后端 `AgentBackend`:让一个 LLM agent 把 mcp-language-server 的 `callers`/`callees`/`definition` 当作工具自主调度,探索式地回答查询,以提升复杂路径的召回。形态上 `AgentBackend` 是 `McpLspBackend` 的**超集**:LLM 是增强层,任何 LLM 环节的缺失或失败都优雅退化到程序化 McpLsp 行为——这正对应"既可以用自己挂着(程序化),也可以适配 agent 调用(LLM)"。

## 2. 设计目标与非目标

### 目标
1. **新增 `AgentBackend`**:实现 `ProgramUnderstandingBackend` 协议,内部用 LLM agent(tool-calling loop)驱动 mcp-language-server 查询。
2. **接口稳定**:不改动 `ProgramUnderstandingBackend` 协议,`Slicer` 与 `pipeline` 零改动。
3. **可插拔选择**:`--l2-backend` 增第三档 `mcp-lsp-agent`,默认仍 `treesitter`。
4. **优雅降级**:LLM 不可用(`--skip-llm`/无 key)/调用失败/超 `max_iters`/输出解析失败时,自动 fallback 到程序化 McpLsp 查询,保证基本可用与确定性。
5. **零新依赖**:复用 Layer3 已有的 `openai` SDK 与 `--llm-*` 配置,不引入 agent 框架。
6. **配套消除重复**:提取 mcp 连接 + async→sync 逻辑为共享 helper,`McpLspBackend` 与 `AgentBackend` 共用(行为等价重构)。

### 非目标(本期不做)
- 不引入 agent 框架(OpenAI Agents SDK / LangGraph 等)。
- 不改 `ProgramUnderstandingBackend` 协议、不改 `Slicer`、不把切片改成 agent loop。
- 不新增 `--l2-agent-model` 等独立 LLM 参数(复用 `--llm-*`)。
- 不做 agent 决策轨迹的持久化 trace(YAGNI,先 logger;需审计时再加)。
- 不解决 mcp-language-server/clangd 真实集成未验证问题(属既有 I3 follow-up,本设计同样受其约束,真实联调随 I3 推进)。

## 3. 核心设计决策(含理由)

| # | 决策 | 理由 |
|---|---|---|
| D1 | 形态 = **接口不变 + 新增 `AgentBackend`** | `Slicer`/`pipeline` 已面向 Protocol 编程,新增实现零侵入;边界清晰、可独立测试 |
| D2 | agent loop = **原生 OpenAI tool-calling** | 复用 Layer3 的 `OpenAI` client 模式(`judge.py:7,37,51`),零新依赖;loop 完全可控、好 mock |
| D3 | LLM 配置 = **复用 `--llm-*`** | 不增 CLI 表面;与 `LLMJudge` 一套 `openai` 兼容客户端 |
| D4 | 降级 = **fallback 到程序化 McpLsp 查询** | 既要 agent 灵活又要程序化确定;`AgentBackend` 退化为 `McpLspBackend` 行为,实现成本低(本就持有 mcp 连接) |
| D5 | 工具集 = `callers`/`callees`/`definition` + `read_source` | 前 3 个转发 mcp-language-server;`read_source` 读函数源码——agent 判断间接调用/污点传递常需看代码 |
| D6 | 提取共享 `_mcp_client` helper | `AgentBackend` 与 `McpLspBackend` 共用 mcp 连接 + async→sync + `parse_refs`,消除重复;`McpLspBackend` 改为组合(行为等价) |
| D7 | `skip_llm`/无 key 时 **直接走程序化** | `AgentBackend` = `McpLspBackend` 超集,LLM 是增强层;无 LLM 时不应失败,而应退化为程序化 |
| D8 | `max_iters` 默认 8,**暂不加 CLI 参数** | YAGNI;需要时再加 `--l2-agent-max-iters` |

## 4. 总体架构

```
                     ProgramUnderstandingBackend (Protocol, 不变)
                     └─ find_callers / find_callees
                          │
          ┌───────────────┼─────────────────────┐
          ▼               ▼                     ▼
   TreeSitterBackend  McpLspBackend         AgentBackend (新增)
   (默认,语法级)      (程序化直连)          (LLM agent 调度)
                          │                     │
                          │              ┌──────┴──────┐
                          │              ▼             ▼
                          │        openai tool-calling   fallback
                          │        loop (复用 Layer3       (退化到
                          │        OpenAI client)       程序化查询)
                          │              │
                          ▼              ▼
                   ┌──────────────────────────┐
                   │  _mcp_client (共享 helper) │  ◄── D6 提取
                   │  McpLspConnection         │
                   │   · server_params()       │
                   │   · call_tool(t,a)->str   │  (async→sync)
                   │  parse_refs(text,name)    │
                   └────────────┬─────────────┘
                                │ stdio 子进程
                                ▼
                     mcp-language-server --lsp clangd
                                │
                                ▼
                            clangd (需 compile_commands)
```

`--l2-backend` 三档:`treesitter`(默认)/ `mcp-lsp`(程序化)/ `mcp-lsp-agent`(agent 调度)。

## 5. 组件设计

### 5.1 共享 helper:`layer2/_mcp_client.py`(新增,D6)

从 `McpLspBackend` 提取,行为等价:

```python
# IS_AVAILABLE / try: import mcp ... (从 mcp_lsp_backend.py 顶部移此)
# _LOC_RE (从 mcp_lsp_backend.py 移此)

class McpLspConnection:
    """持有 mcp-language-server 连接参数,封装 async→sync 的 call_tool。"""
    def __init__(self, workspace=None, compile_commands_dir=None,
                 mcp_binary="mcp-language-server", lsp="clangd"): ...
    def is_available(self) -> bool: ...          # IS_AVAILABLE
    def server_params(self) -> StdioServerParameters: ...   # 现 _server_params
    def call_tool(self, tool: str, args: dict) -> str: ...  # 现 _call_tool(_async)

def parse_refs(text: str, default_name: str) -> list[FunctionRef]: ...  # 现 _parse_refs
```

`McpLspBackend` 改为**组合** `McpLspConnection`:`find_callers` = `conn.call_tool("callers", {...})` → `parse_refs(...)`。行为与现状完全等价(配套调整 `tests/layer2/test_mcp_lsp_backend.py` 的 mock 目标,从 `_call_tool_async` 改为 `McpLspConnection.call_tool`,断言不变)。构造签名增加可选 `connection: McpLspConnection | None = None`(注入则复用,否则内部自建),供 `AgentBackend` 复用同一连接。

### 5.2 `AgentBackend`:`layer2/agent_backend.py`(新增)

```python
class AgentBackend:
    """LLM agent 驱动的程序理解后端。AgentSAST 作 MCP client + LLM tool-calling host。
    LLM 不可用/失败时 fallback 到程序化 McpLsp 查询(D4/D7)。"""
    def __init__(self, workspace=None, compile_commands_dir=None,
                 llm_model="gpt-4o", llm_api_key=None, llm_base_url=None,
                 skip_llm=False, max_iters=8,
                 mcp_binary="mcp-language-server", lsp="clangd"):
        self._conn = McpLspConnection(workspace, compile_commands_dir, mcp_binary, lsp)
        self._direct = McpLspBackend(connection=self._conn)  # 复用同一连接,专司 fallback + 程序化
        # key 解析对齐 LLMJudge(judge.py:30-31):显式优先,回退环境变量
        key = llm_api_key or os.environ.get("OPENAI_API_KEY", "")
        url = llm_base_url or os.environ.get("OPENAI_BASE_URL", None)
        self._skip_llm = skip_llm or not key  # 无 key → 直接程序化(D7)
        self._max_iters = max_iters
        if not self._skip_llm:
            client_kwargs = {"api_key": key}
            if url:
                client_kwargs["base_url"] = url
            self._client = OpenAI(**client_kwargs)  # 同 LLMJudge 构造(judge.py:33-37)

    def is_available(self) -> bool: return self._conn.is_available()

    def find_callers(self, func_name, loc, project_root=None) -> list[FunctionRef]:
        if not self.is_available(): warn; return []
        if self._skip_llm:
            return self._direct.find_callers(func_name, loc, project_root)  # D7
        try:
            return self._agent_query("callers", func_name, loc, project_root)
        except Exception:
            logger.exception(...); return self._direct.find_callers(func_name, loc, project_root)  # D4 fallback

    def find_callees(self, func_name, loc) -> list[FunctionRef]: ...  # 同上,query="callees"
```

`_agent_query` 即 tool-calling loop(见 §6)。fallback 路径直接复用 `self._direct`(一个 `McpLspBackend`),保证退化行为与 `mcp-lsp` 档**完全一致**。

### 5.3 工具 schema(OpenAI function calling)

| 工具 | 参数 | 实现 | 用途 |
|------|------|------|------|
| `callers` | `symbolName, filePath, line, column` | `conn.call_tool("callers", args)` | 查谁调用了本函数 |
| `callees` | `symbolName, filePath, line, column` | `conn.call_tool("callees", args)` | 查本函数调用了谁 |
| `definition` | `symbolName, filePath, line, column` | `conn.call_tool("definition", args)` | 跳转到定义(解析符号) |
| `read_source` | `filePath, startLine, endLine` | 本地读文件指定行范围 | 看函数体判断间接调用/污点 |

## 6. 数据流(以 `find_callers` 为例)

```
Slicer.find_callers(func, loc)
  └─► AgentBackend.find_callers
        ├─ skip_llm? ──yes──► self._direct.find_callers (程序化) ──► list[FunctionRef]
        └─ _agent_query("callers", func, loc):
             messages = [system(你是调用图分析助手,用工具找出 X 的所有 callers,
                                最终只输出 JSON: [{"name","file","line"}, ...]),
                         user(目标函数名 + file:line:col)]
             for _ in range(max_iters):
                 resp = client.chat.completions.create(model, messages, tools=TOOLS,
                                                       temperature=0)
                 msg = resp.choices[0].message; messages.append(msg)
                 if not msg.tool_calls:
                     return parse_final_json(msg.content)   # → list[FunctionRef]
                 for tc in msg.tool_calls:
                     result = dispatch(tc.function.name, json.loads(tc.function.arguments))
                     messages.append({role:"tool", tool_call_id:tc.id, content:result})
             # 触顶 max_iters
             raise AgentLoopExhausted   # → 被 find_callers 的 except 捕获 → fallback
```

`dispatch`:
- `callers`/`callees`/`definition` → `self._conn.call_tool(name, args)`(单次 tool 异常 → 回填错误文本给 LLM 让其自纠,消耗 1 iter,不直接 fallback)。
- `read_source` → 读文件 `[startLine, endLine]`,返回源码文本(文件缺失/越界 → 回填错误文本)。

`parse_final_json`:剥离 ```` ```json ```` 围栏后 `json.loads`,逐项构造 `FunctionRef`(`name`/`file`/`line`,`end_line` 暂取 `line`)。解析失败 → 抛异常 → fallback。

`temperature=0`:降低 run-to-run 方差(D2 风险缓解)。

## 7. 错误处理与降级矩阵

| 情形 | 处理 | 结果 |
|------|------|------|
| mcp SDK 未装 / mcp-language-server 缺失 | `is_available()` False → warn | 返回 `[]`(同 `McpLspBackend`) |
| `--skip-llm` 或无 `llm_api_key` | `skip_llm=True`,不构造 LLM client | 直接走 `self._direct`(程序化)——D7 |
| LLM API 异常(网络/鉴权/限流) | `except` 捕获 → log | fallback 程序化查询 |
| 触顶 `max_iters` 未收敛 | `AgentLoopExhausted` | fallback 程序化查询 |
| 最终 JSON 解析失败 | 抛异常 | fallback 程序化查询 |
| 单个 tool 执行异常 | 回填错误文本给 LLM | agent 自纠(消耗 1 iter),不直接 fallback |
| fallback 本身也失败(mcp 不可用) | `self._direct` 内部 `except` | 返回 `[]` |

**核心保证**:只要 mcp 可用,`mcp-lsp-agent` 档的最坏行为 = `mcp-lsp` 档;只有 mcp 本身不可用时才返回空。

## 8. CLI / 配置接入

### 8.1 `src/agentsast/cli.py:108`
```python
@click.option("--l2-backend",
              type=click.Choice(["treesitter", "mcp-lsp", "mcp-lsp-agent"]),
              default="treesitter", help="Layer2 program-understanding backend")
```

### 8.2 `src/agentsast/pipeline/engine.py:88-100`(backend 构造分支)
```python
if self.l2_backend == "mcp-lsp":
    from ..layer2.mcp_lsp_backend import McpLspBackend
    backend = McpLspBackend(workspace=target,
                            compile_commands_dir=self.compile_db.parent if self.compile_db else None)
elif self.l2_backend == "mcp-lsp-agent":
    from ..layer2.agent_backend import AgentBackend
    backend = AgentBackend(
        workspace=target,
        compile_commands_dir=self.compile_db.parent if self.compile_db else None,
        llm_model=self.llm_model, llm_api_key=self.llm_api_key,
        llm_base_url=self.llm_base_url, skip_llm=self.skip_llm,
    )
```
`Pipeline` 已持有 `llm_model`/`llm_api_key`/`llm_base_url`/`skip_llm`(`engine.py:49-64`),直接透传,无需新参数。

### 8.3 运行前提
`mcp-lsp-agent` 档仍需:`pip install -e ".[layer2-mcp]"` + `mcp-language-server` 二进制 + `clangd` + `compile_commands.json`(与 `mcp-lsp` 档相同);额外需 LLM 可用(否则自动退化为 `mcp-lsp` 行为)。

## 9. 测试策略(不依赖真实 LLM/clangd)

新增 `tests/layer2/test_agent_backend.py`,mock 双侧:

| 测试 | mock | 断言 |
|------|------|------|
| `test_loop_success` | LLM client:第 1 轮返回 `callers` tool_call,第 2 轮返回最终 JSON;mcp `call_tool` 返回固定位置文本 | 返回正确 `list[FunctionRef]`;`call_tool` 被以正确参数调用 |
| `test_read_source_tool` | LLM 调 `read_source` | 读到指定行范围源码并回填 |
| `test_fallback_on_max_iters` | LLM 每轮都返回 tool_call(不收敛) | 触顶后 fallback,返回 `self._direct` 的结果 |
| `test_fallback_on_parse_failure` | LLM 最终返回非 JSON | fallback |
| `test_fallback_on_llm_error` | LLM client 抛异常 | fallback |
| `test_skip_llm_uses_direct` | `skip_llm=True` | 不构造 client,直接 `self._direct.find_callers` |
| `test_unavailable_no_mcp` | mcp SDK 未装(`IS_AVAILABLE=False`) | `is_available()` False,`find_callers` 返回 `[]` |
| `test_tool_exception_self_correct` | 某次 `call_tool` 抛异常 | 错误回填给 LLM,不直接 fallback |

配套:`tests/layer2/test_mcp_lsp_backend.py` 的 mock 目标从 `_call_tool_async` 改为 `McpLspConnection.call_tool`,断言不变(验证 D6 重构行为等价)。

## 10. 风险

| 风险 | 级别 | 缓解 |
|------|------|------|
| LLM 非确定性 → 切片 run-to-run 不一致 | 🟡 | `temperature=0`;fallback 兜底保证下限 |
| LLM 成本/延迟(每 anchor 多轮调用) | 🟡 | `max_iters=8` 上限;复用用户自选的 `--llm-model`(可选便宜模型) |
| D6 重构引入回归 | 🟡 | 行为等价;`test_mcp_lsp_backend.py` 断言不变,仅改 mock 目标 |
| mcp/clangd 真实集成未验证(既有 I3) | 🔴 | 本设计同样受约束;真实联调随 I3 推进,单测全用 mock 不阻塞 |

## 11. 验收标准
1. `--l2-backend mcp-lsp-agent` 可选,默认 `treesitter` 行为完全不变。
2. 现有测试全绿;`test_mcp_lsp_backend.py` 经 D6 调整后断言等价通过。
3. `tests/layer2/test_agent_backend.py` 覆盖 §9 全部用例(loop 成功 / 4 类 fallback / skip_llm / unavailable / tool 自纠)。
4. `mcp-lsp-agent` 档在 LLM 不可用时,行为与 `mcp-lsp` 档一致(集成级,可 mock LLM 验证)。
5. `ProgramUnderstandingBackend` 协议、`Slicer`、`Pipeline` 签名零改动。
