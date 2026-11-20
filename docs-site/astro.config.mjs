// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://simwork.vercel.app',
  integrations: [
    starlight({
      title: 'SimWork',
      description:
        'Simulate AI-app functionality first — before spending real LLM or world API calls. Every run costs $0.',
      logo: {
        src: './src/assets/logo.svg',
        alt: 'SimWork',
      },
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/SRogDev/SimWork',
        },
      ],
      editLink: {
        baseUrl: 'https://github.com/SRogDev/SimWork/edit/main/docs-site/',
      },
      sidebar: [
        { label: 'Getting Started', slug: 'getting-started' },
        {
          label: 'Guides',
          items: [
            { label: 'Routing & simulate mode', slug: 'guides/routing' },
            { label: 'Scenario files', slug: 'guides/scenarios' },
            { label: 'API mocks', slug: 'guides/api-mocks' },
            { label: 'Evals & the $0 gate', slug: 'guides/evals' },
            { label: 'AI configuration prompt', slug: 'guides/ai-prompt' },
            { label: 'Scale: 1,000 runs', slug: 'guides/scale' },
            { label: 'Polygrow pilot', slug: 'guides/polygrow-pilot' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'CLI reference', slug: 'reference/cli' },
            { label: 'Design decisions', slug: 'reference/decisions' },
          ],
        },
      ],
    }),
  ],
});
