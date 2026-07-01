import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './specs',
  timeout: 60000,
  use: { headless: true, screenshot: 'only-on-failure', trace: 'on-first-retry' },
  reporter: [['html', { open: 'never', outputFolder: '../runs/latest-report' }], ['list']],
});
