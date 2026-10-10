import { defineConfig } from 'vitepress'

const base = '/AgentSAST/'

// https://vitepress.dev/reference/site-config
export default defineConfig({
  lang: 'zh-CN',
  title: 'AgentSAST',
  titleTemplate: 'AI-Augmented Static Analysis for C/C++',
  description:
    'AgentSAST：AI 增强的 C/C++ 静态分析系统——锚点识别、切片引擎与 LLM 裁判三层架构的设计与实现文档。',

  base,
  lastUpdated: true,
  cleanUrls: true,
  srcExclude: ['README.md'],

  markdown: {
    // shiki 3.x 不再内置 cuda 语法, 用 cpp 高亮兜底
    languageAlias: { cuda: 'cpp' },
  },

  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}favicon.svg` }],
    ['meta', { name: 'theme-color', content: '#2e7d5b', media: '(prefers-color-scheme: light)' }],
    ['meta', { name: 'theme-color', content: '#18191c', media: '(prefers-color-scheme: dark)' }],
    ['meta', { property: 'og:title', content: 'AgentSAST' }],
    [
      'meta',
      {
        property: 'og:description',
        content:
          'AgentSAST：AI 增强的 C/C++ 静态分析系统——锚点识别、切片引擎与 LLM 裁判三层架构的设计与实现文档。',
      },
    ],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { name: 'twitter:card', content: 'summary' }],
    // 学习笔记悬浮组件（localStorage），VitePress SPA 路由切换由 theme/index.ts 通知其重挂载
    ['script', { src: `${base}notes.js` }],
  ],

  themeConfig: {
    // https://vitepress.dev/reference/default-theme-config
    logo: '/favicon.svg',

    nav: [
      { text: '首页', link: '/' },
      { text: '简介', link: '/introduction' },
      { text: '快速开始', link: '/quick-start' },
      { text: '整体架构', link: '/architecture' },
      { text: '路线图', link: '/roadmap' },
    ],

    sidebar: [
      { text: '简介', link: '/introduction' },
      { text: '快速开始', link: '/quick-start' },
      { text: '整体架构', link: '/architecture' },
      {
        text: 'Layer 1: 锚点识别',
        link: '/layer1',
        collapsed: false,
        items: [
          { text: '数据模型', link: '/layer1-models' },
          { text: 'Semgrep 扫描器', link: '/layer1-semgrep' },
          { text: 'Flawfinder 扫描器', link: '/layer1-flawfinder' },
          { text: '统一扫描入口', link: '/layer1-scanner' },
        ],
      },
      {
        text: 'Layer 2: 切片引擎',
        link: '/layer2',
        collapsed: false,
        items: [
          { text: '数据模型', link: '/layer2-models' },
          { text: 'AST 解析器', link: '/layer2-parser' },
          { text: '切片算法', link: '/layer2-slicer' },
        ],
      },
      {
        text: 'Layer 3: LLM 裁判',
        link: '/layer3',
        collapsed: false,
        items: [
          { text: '数据模型', link: '/layer3-models' },
          { text: '反幻觉提示工程', link: '/layer3-prompt' },
          { text: 'OpenAI 兼容客户端', link: '/layer3-judge' },
        ],
      },
      { text: 'Pipeline 与 CLI', link: '/pipeline' },
      { text: '数据模型参考', link: '/data-models' },
      { text: '部署与 GitHub Pages', link: '/deployment' },
      { text: '路线图与已知局限', link: '/roadmap' },
    ],

    outline: {
      level: [2, 3],
      label: '本页大纲',
    },

    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            noResultsText: '无法找到相关结果',
            resetButtonTitle: '清除查询条件',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
      },
    },

    editLink: {
      pattern: 'https://github.com/Atituiset/AgentSAST/edit/main/docs-vitepress/:path',
      text: '在 GitHub 上编辑此页',
    },

    socialLinks: [{ icon: 'github', link: 'https://github.com/Atituiset/AgentSAST' }],

    docFooter: { prev: '上一页', next: '下一页' },

    lastUpdated: {
      text: '最后更新于',
      formatOptions: { dateStyle: 'short', timeStyle: 'short' },
    },

    returnToTopLabel: '回到顶部',
    sidebarMenuLabel: '菜单',
    darkModeSwitchLabel: '主题',
    lightModeSwitchTitle: '切换到浅色模式',
    darkModeSwitchTitle: '切换到深色模式',
    skipToContentLabel: '跳转到内容',

    footer: {
      message: 'AI-Augmented Static Analysis for C/C++',
      copyright: 'Copyright © 2026 AgentSAST',
    },
  },
})
