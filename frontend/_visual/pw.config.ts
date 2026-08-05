import { defineConfig, devices } from '@playwright/test'
export default defineConfig({
  testDir: '.',
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  timeout: 60000,
  use: { baseURL: 'http://localhost:5173', screenshot: 'off', trace: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  outputDir: './out',
})
