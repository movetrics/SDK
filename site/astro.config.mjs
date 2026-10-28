// Movetrics developer docs. Astro + Starlight, the same stack as the planned movetrics.com relaunch.
// Served at developers.movetrics.com (decided 28 Oct 2026) from GitHub Pages of the public movetrics/sdk repository.
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://developers.movetrics.com',
  integrations: [
    starlight({
      title: 'Movetrics for developers',
      description: 'Get force plate data into Excel, Python, MATLAB, OpenSim, LSL and your own code.',
      // Movetrics Vector identity: outlined lockup (light/dark masters from movetrics-ci), brand favicon, self-hosted fonts.
      logo: { light: './src/assets/lockup-primary.svg', dark: './src/assets/lockup-inverse.svg', alt: 'Movetrics', replacesTitle: true },
      favicon: '/favicon.svg',
      head: [
        { tag: 'link', attrs: { rel: 'icon', type: 'image/png', sizes: '32x32', href: '/favicon-32.png' } },
        { tag: 'link', attrs: { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' } },
        { tag: 'link', attrs: { rel: 'preload', href: '/fonts/IBMPlexSans-wdth-wght.woff2', as: 'font', type: 'font/woff2', crossorigin: '' } },
        { tag: 'link', attrs: { rel: 'preload', href: '/fonts/Manrope-wght.woff2', as: 'font', type: 'font/woff2', crossorigin: '' } },
      ],
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/movetrics/sdk' }],
      customCss: ['./src/styles/movetrics.css'],
      sidebar: [
        { label: 'Start here', items: [
          { label: 'Which path is mine?', slug: 'index' },
          { label: 'The SDK in two minutes', slug: 'start/two-minutes' },
          { label: 'Build with an AI assistant', slug: 'start/build-with-ai' },
          { label: 'Excel in 5 minutes', slug: 'start/excel' },
          { label: 'Python in 5 minutes', slug: 'start/python' },
          { label: 'MATLAB in 5 minutes', slug: 'start/matlab' },
          { label: 'Record with EMG and cameras', slug: 'start/emg-and-cameras' },
          { label: 'OpenSim and Pose2Sim', slug: 'start/opensim' },
          { label: 'Ask Claude or ChatGPT', slug: 'start/ai-assistants' },
          { label: 'Build without an FDT', slug: 'start/simulator' },
        ] },
        { label: 'Concepts', items: [
          { label: 'Names, units and axes', slug: 'concepts/units-and-axes' },
          { label: 'Time, gaps and sync', slug: 'concepts/time-and-sync' },
          { label: 'Why you can trust it', slug: 'concepts/tested' },
        ] },
        { label: 'Cloud API', link: '/api/', attrs: { target: '_self' } },
        { label: 'Reference', collapsed: true, items: [{ autogenerate: { directory: 'reference' } }] },
      ],
    }),
  ],
});
