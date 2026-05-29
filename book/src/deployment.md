# 部署与 GitHub Pages

## 本地构建文档

### 安装 mdBook

```bash
# 使用 cargo (Rust 包管理器)
cargo install mdbook

# 或使用预编译二进制
# https://github.com/rust-lang/mdBook/releases
```

### 构建与预览

```bash
cd book

# 构建 HTML 到 book/dist/
mdbook build

# 本地预览 (自动刷新)
mdbook serve
# 浏览器访问 http://localhost:3000
```

## GitHub Pages 自动部署

### 配置步骤

1. 在仓库中创建 `.github/workflows/book.yml`：

```yaml
name: Deploy Book
on:
  push:
    branches: [main]
    paths: ["book/**"]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install mdBook
        run: cargo install mdbook
      - name: Build book
        run: cd book && mdbook build
      - name: Upload artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: book/dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - name: Deploy to GitHub Pages
        id: deployment
        uses: actions/deploy-pages@v4
```

2. 在 GitHub 仓库设置中：
   - Settings → Pages → Source: **GitHub Actions**
   - 触发一次 push 到 `main` 分支的 `book/` 目录变更

3. 访问地址：`https://<username>.github.io/AgentSAST/`

### book.toml 配置说明

```toml
[book]
title = "AgentSAST"
language = "zh-CN"          # 中文文档
src = "src"                  # Markdown 源文件目录

[build]
build-dir = "dist"           # 输出目录 (GitHub Actions 使用)

[output.html]
default-theme = "navy"       # 深色主题
git-repository-url = "https://github.com/atituiset/AgentSAST"
```

## 自定义域名 (可选)

1. 在 `book/src/` 下创建 `CNAME` 文件，内容为自定义域名
2. 在 DNS 服务商添加 CNAME 记录指向 `<username>.github.io`
3. 在 GitHub Settings → Pages → Custom domain 填入域名

## 其他部署方式

| 方式 | 命令 | 说明 |
|------|------|------|
| Netlify | 直接链接仓库 | 自动识别 mdBook |
| Cloudflare Pages | `cd book && mdbook build` | 输出目录 `dist` |
| 本地静态服务 | `python -m http.server -d book/dist` | 快速分享 |
