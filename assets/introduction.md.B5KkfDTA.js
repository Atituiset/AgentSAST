import{_ as n,o as s,c as e,a3 as t}from"./chunks/framework.B49jkbEp.js";const h=JSON.parse('{"title":"AgentSAST — AI-Augmented Static Analysis for C/C++","description":"","frontmatter":{},"headers":[],"relativePath":"introduction.md","filePath":"introduction.md","lastUpdated":1791637873000}'),p={name:"introduction.md"};function l(i,a,r,o,c,d){return s(),e("div",null,[...a[0]||(a[0]=[t(`<h1 id="agentsast-—-ai-augmented-static-analysis-for-c-c" tabindex="-1">AgentSAST — AI-Augmented Static Analysis for C/C++ <a class="header-anchor" href="#agentsast-—-ai-augmented-static-analysis-for-c-c" aria-label="Permalink to &quot;AgentSAST — AI-Augmented Static Analysis for C/C++&quot;">​</a></h1><h2 id="项目定位" tabindex="-1">项目定位 <a class="header-anchor" href="#项目定位" aria-label="Permalink to &quot;项目定位&quot;">​</a></h2><p>AgentSAST 是一款面向 C/C++ 内存安全漏洞的 <strong>AI 增强静态分析工具</strong>。它采用三层漏斗架构，将传统 SAST 的高召回率与 LLM 的高精确率结合，解决传统工具误报泛滥的问题：</p><div class="language- vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang"></span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span>Layer 1: SAST 锚点识别  →  高召回，广撒网</span></span>
<span class="line"><span>Layer 2: 程序切片引擎    →  精准上下文提取</span></span>
<span class="line"><span>Layer 3: LLM 判定裁判    →  高精确率判定真伪</span></span></code></pre></div><h2 id="核心价值" tabindex="-1">核心价值 <a class="header-anchor" href="#核心价值" aria-label="Permalink to &quot;核心价值&quot;">​</a></h2><table tabindex="0"><thead><tr><th>传统 SAST</th><th>AgentSAST</th></tr></thead><tbody><tr><td>误报率 30-90%</td><td>LLM 二次裁定显著降低误报</td></tr><tr><td>只报位置，无法判断真伪</td><td>给出 VULNERABLE / SAFE / UNCERTAIN 三级裁定</td></tr><tr><td>人工 review 成本高</td><td>结构化 CoT 推理 + 置信度评分</td></tr><tr><td>单一工具覆盖有限</td><td>多工具融合 (Semgrep + Flawfinder + 内置模式)</td></tr></tbody></table><h2 id="设计哲学" tabindex="-1">设计哲学 <a class="header-anchor" href="#设计哲学" aria-label="Permalink to &quot;设计哲学&quot;">​</a></h2><ol><li><strong>SAST 为锚，LLM 为裁</strong> — L1 保证召回率，L3 保证精确率，L2 是桥梁</li><li><strong>不依赖编译</strong> — MVP 阶段无需编译目标代码，基于文本匹配 + AST 解析</li><li><strong>切片而非全量</strong> — 程序切片将上下文窗口从全文件压缩到关键数据流，2 层深度覆盖 92% 场景</li><li><strong>反幻觉提示</strong> — 结构化系统提示 + CoT 强制推理链 + 代码行引用约束，最大限度抑制 LLM 幻觉</li><li><strong>OpenAI 兼容</strong> — 支持 GPT-4o / Qwen / DeepSeek / 本地模型，任何 OpenAI 兼容 API 即可接入</li></ol><h2 id="技术栈" tabindex="-1">技术栈 <a class="header-anchor" href="#技术栈" aria-label="Permalink to &quot;技术栈&quot;">​</a></h2><ul><li><strong>Python ≥3.10</strong>，venv 隔离</li><li><strong>Tree-sitter</strong> — C/C++ AST 解析 (替代 Joern，无 JVM 依赖)</li><li><strong>Semgrep</strong> — 语义化模式匹配 SARIF 输出</li><li><strong>Flawfinder</strong> — 危险函数字典扫描</li><li><strong>OpenAI SDK</strong> — 兼容所有 OpenAI API 格式的 LLM 服务</li><li><strong>SARIF v2.1.0</strong> — 统一 L1 输出格式</li></ul><h2 id="项目结构" tabindex="-1">项目结构 <a class="header-anchor" href="#项目结构" aria-label="Permalink to &quot;项目结构&quot;">​</a></h2><div class="language- vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang"></span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span>AgentSAST/</span></span>
<span class="line"><span>├── src/agentsast/</span></span>
<span class="line"><span>│   ├── layer1/          # SAST 锚点识别</span></span>
<span class="line"><span>│   │   ├── models.py    # Anchor, Location, Severity</span></span>
<span class="line"><span>│   │   ├── scanner.py   # 统一扫描入口 + SARIF 通用解析</span></span>
<span class="line"><span>│   │   ├── semgrep.py   # Semgrep SARIF 输出解析</span></span>
<span class="line"><span>│   │   └── flawfinder.py # Flawfinder + 内置模式扫描器</span></span>
<span class="line"><span>│   ├── layer2/          # 程序切片引擎</span></span>
<span class="line"><span>│   │   ├── models.py    # CodeSlice, SlicingResult</span></span>
<span class="line"><span>│   │   ├── parser.py    # Tree-sitter C/C++ AST 解析器</span></span>
<span class="line"><span>│   │   └── slicer.py    # SlicingEngine (后向切片/调用图/结构体提取)</span></span>
<span class="line"><span>│   ├── layer3/          # LLM 裁判</span></span>
<span class="line"><span>│   │   ├── models.py    # Verdict, LLMResult</span></span>
<span class="line"><span>│   │   ├── prompt.py    # 反幻觉系统提示 + 结构化负载构建</span></span>
<span class="line"><span>│   │   └── judge.py     # OpenAI API 客户端 + JSON 响应解析</span></span>
<span class="line"><span>│   ├── pipeline/</span></span>
<span class="line"><span>│   │   └── engine.py    # 三层 Pipeline 编排</span></span>
<span class="line"><span>│   └── cli.py           # Click CLI + Rich 终端输出</span></span>
<span class="line"><span>├── samples/</span></span>
<span class="line"><span>│   ├── vulnerable_server.c</span></span>
<span class="line"><span>│   └── safe_server.c</span></span>
<span class="line"><span>├── tests/</span></span>
<span class="line"><span>│   └── test_pipeline.py</span></span>
<span class="line"><span>├── pyproject.toml</span></span>
<span class="line"><span>└── book/                # 本文档 (mdBook)</span></span></code></pre></div>`,12)])])}const A=n(p,[["render",l]]);export{h as __pageData,A as default};
