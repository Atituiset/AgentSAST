# 部署与 GitHub Pages

## 本地构建文档

### 安装依赖

文档站点位于 `docs-vitepress/`，基于 [VitePress](https://vitepress.dev/) 构建，需要 Node.js 18+（推荐 22）。

```bash
cd docs-vitepress
npm install
```

### 构建与预览

```bash
cd docs-vitepress

# 本地开发（自动刷新）
npm run docs:dev
# 浏览器访问 http://localhost:5173

# 构建 HTML 到 docs-vitepress/.vitepress/dist/
npm run docs:build

# 预览构建产物
npm run docs:preview
```

## GitHub Pages 自动部署

### 配置步骤

仓库已内置 `.github/workflows/book.yml`：

```yaml
name: Deploy Book

on:
  push:
    branches: [main]
    paths: ["docs-vitepress/**"]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 22

      - name: Install dependencies
        run: npm ci --prefix docs-vitepress

      - name: Build site
        run: npm run docs:build --prefix docs-vitepress

      - name: Deploy to gh-pages branch
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: docs-vitepress/.vitepress/dist
          publish_branch: gh-pages
          force_orphan: true
```

1. 在 GitHub 仓库设置中：
   - Settings → Pages → Source: **Deploy from a branch**，选择 `gh-pages` 分支
   - 触发一次 push 到 `main` 分支的 `docs-vitepress/` 目录变更

2. 访问地址：`https://<username>.github.io/AgentSAST/`

### 站点配置说明

VitePress 配置位于 `docs-vitepress/.vitepress/config.mts`，关键点：

- `base`：站点基础路径。部署到 `<username>.github.io/AgentSAST/` 时需设为 `'/AgentSAST/'`；自定义域名或独立站点用 `'/'`
- `srcExclude`：排除 `README.md` 等不参与构建的文件
- `themeConfig.sidebar`：侧边栏目录，由章节结构手工维护

## 自定义域名 (可选)

1. 在 `docs-vitepress/public/` 下创建 `CNAME` 文件，内容为自定义域名
2. 在 DNS 服务商添加 CNAME 记录指向 `<username>.github.io`
3. 在 GitHub Settings → Pages → Custom domain 填入域名
4. 使用自定义域名后，`base` 应保持为 `'/'`

## 其他部署方式

| 方式 | 构建命令 | 输出目录 |
|------|----------|----------|
| Netlify | `npm ci --prefix docs-vitepress && npm run docs:build --prefix docs-vitepress` | `docs-vitepress/.vitepress/dist` |
| Cloudflare Pages | 同上 | 同上 |
| 本地静态服务 | `python -m http.server -d docs-vitepress/.vitepress/dist` | 快速分享 |
