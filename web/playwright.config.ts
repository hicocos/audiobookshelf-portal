import { defineConfig, devices } from '@playwright/test';

const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;
const serverPort = process.env.PLAYWRIGHT_PORT || '3009';
const baseURL = externalBaseUrl || `http://127.0.0.1:${serverPort}`;

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: {
    baseURL,
    trace: 'on-first-retry',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chromium', use: { ...devices['Pixel 7'] } },
  ],
  webServer: externalBaseUrl ? undefined : {
    command: process.env.CI
      ? `npx next start -H 127.0.0.1 -p ${serverPort}`
      : `npx next dev -H 127.0.0.1 -p ${serverPort}`,
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
