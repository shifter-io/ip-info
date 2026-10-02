const {defineConfig} = require('@playwright/test');
const fs = require('node:fs');
const chrome = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
module.exports = defineConfig({
  testDir: './tests/browser', timeout: 30000, workers: 1,
  outputDir: './artifacts/browser', reporter: [['list'], ['json', {outputFile:'artifacts/browser-results.json'}]],
  use: {baseURL: process.env.TEST_BASE_URL || 'http://127.0.0.1:8080',
    launchOptions: fs.existsSync(chrome) ? {executablePath:chrome} : {},
    screenshot:'only-on-failure', trace:'retain-on-failure'},
  webServer: process.env.TEST_BASE_URL ? undefined : {
    command: 'cargo run --locked', url:'http://127.0.0.1:8080/healthz', reuseExistingServer:true,
    timeout:120000, env:{BIND_ADDR:'127.0.0.1:8080'}
  }
});
