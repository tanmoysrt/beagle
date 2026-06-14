import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'beagle',
  description:
    'Local, deterministic code-discovery for Python, Frappe, and their JS/TS/Vue frontends.',
  lang: 'en-US',
  // Served from https://<user>.github.io/beagle/ on GitHub Pages.
  base: '/beagle/',
  cleanUrls: true,
  lastUpdated: true,
  ignoreDeadLinks: true,

  themeConfig: {
    logo: '/logo.svg',

    nav: [
      { text: 'Guide', link: '/guide/introduction' },
      { text: 'Commands', link: '/guide/commands' },
      { text: 'Shared service', link: '/guide/shared-service' },
      { text: 'Architecture', link: '/guide/architecture' },
    ],

    sidebar: {
      '/guide/': [
        {
          text: 'Introduction',
          items: [
            { text: 'What is beagle?', link: '/guide/introduction' },
            { text: 'Installation', link: '/guide/installation' },
            { text: 'Quickstart', link: '/guide/quickstart' },
          ],
        },
        {
          text: 'Using beagle',
          items: [
            { text: 'Command reference', link: '/guide/commands' },
            { text: 'Claude Code (MCP)', link: '/guide/mcp' },
            { text: 'Shared service', link: '/guide/shared-service' },
          ],
        },
        {
          text: 'Understanding beagle',
          items: [
            { text: 'How it works', link: '/guide/how-it-works' },
            { text: 'Architecture', link: '/guide/architecture' },
            { text: 'Data model', link: '/guide/data-model' },
          ],
        },
      ],
    },

    search: { provider: 'local' },

    socialLinks: [
      { icon: 'github', link: 'https://github.com/tanmoysrt/beagle' },
    ],

    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Deterministic. Local. No LLM in the engine.',
    },
  },
})
