import{_ as n,o as s,c as e,a3 as t}from"./chunks/framework.B49jkbEp.js";const u=JSON.parse('{"title":"Layer 3: LLM 裁判","description":"","frontmatter":{},"headers":[],"relativePath":"layer3.md","filePath":"layer3.md","lastUpdated":1791637873000}'),l={name:"layer3.md"};function p(o,a,d,r,i,c){return s(),e("div",null,[...a[0]||(a[0]=[t(`<h1 id="layer-3-llm-裁判" tabindex="-1">Layer 3: LLM 裁判 <a class="header-anchor" href="#layer-3-llm-裁判" aria-label="Permalink to &quot;Layer 3: LLM 裁判&quot;">​</a></h1><p>Layer 3 是 AgentSAST 漏斗的最后一层，职责是 <strong>用 LLM 对 L2 切片上下文进行精确判定</strong>，输出 VULNERABLE / SAFE / UNCERTAIN 三级裁定。</p><h2 id="核心挑战" tabindex="-1">核心挑战 <a class="header-anchor" href="#核心挑战" aria-label="Permalink to &quot;核心挑战&quot;">​</a></h2><p>LLM 裁判面临两个核心挑战：</p><ol><li><strong>幻觉问题</strong> — LLM 可能&quot;脑补&quot;代码中不存在的安全检查</li><li><strong>一致性</strong> — 同一漏洞，不同提示可能导致不同判定</li></ol><p>AgentSAST 的解决方案：</p><ul><li>反幻觉系统提示 (4 条硬约束)</li><li>强制 Chain-of-Thought 推理链 (4 步分析流程)</li><li>结构化 JSON 输出 + 置信度阈值</li></ul><h2 id="三级裁定" tabindex="-1">三级裁定 <a class="header-anchor" href="#三级裁定" aria-label="Permalink to &quot;三级裁定&quot;">​</a></h2><table tabindex="0"><thead><tr><th>裁定</th><th>含义</th><th>条件</th></tr></thead><tbody><tr><td><code>VULNERABLE</code></td><td>确认真漏洞</td><td><code>is_vulnerable=true</code> 且 <code>confidence≥0.3</code></td></tr><tr><td><code>SAFE</code></td><td>确认误报</td><td><code>is_vulnerable=false</code> 且 <code>confidence≥0.3</code></td></tr><tr><td><code>UNCERTAIN</code></td><td>无法判定</td><td><code>confidence&lt;0.3</code> 或 API 失败</td></tr></tbody></table><p><strong>置信度阈值</strong>: <code>confidence &lt; 0.3</code> 时强制为 UNCERTAIN，防止低信心误判。</p><h2 id="数据流" tabindex="-1">数据流 <a class="header-anchor" href="#数据流" aria-label="Permalink to &quot;数据流&quot;">​</a></h2><div class="language- vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang"></span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span>Anchor + SlicingResult</span></span>
<span class="line"><span>    │</span></span>
<span class="line"><span>    ▼</span></span>
<span class="line"><span>build_payload()          ← 构建结构化负载</span></span>
<span class="line"><span>    │</span></span>
<span class="line"><span>    ▼</span></span>
<span class="line"><span>build_user_prompt()      ← 生成用户提示</span></span>
<span class="line"><span>    │</span></span>
<span class="line"><span>    ▼</span></span>
<span class="line"><span>OpenAI API 调用          ← system_prompt + user_prompt</span></span>
<span class="line"><span>    │</span></span>
<span class="line"><span>    ▼</span></span>
<span class="line"><span>_parse_response()        ← 解析 JSON + 置信度阈值</span></span>
<span class="line"><span>    │</span></span>
<span class="line"><span>    ▼</span></span>
<span class="line"><span>LLMResult</span></span></code></pre></div>`,12)])])}const _=n(l,[["render",p]]);export{u as __pageData,_ as default};
