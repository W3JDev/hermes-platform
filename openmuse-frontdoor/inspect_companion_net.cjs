const { chromium } = require('playwright');
const CHROME_PATH = 'C:/Users/W3jde/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe';

async function inspectNet() {
  const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true });
  const page = await browser.newPage();
  page.on('request', req => {
    if (req.url().includes('api') || req.url().includes('chat') || req.url().includes('ws') || req.url().includes('token')) {
      console.log('REQ:', req.method(), req.url());
      if (req.postData()) console.log('DATA:', req.postData().slice(0, 200));
      console.log('HEADERS:', JSON.stringify(req.headers()));
    }
  });
  await page.goto('http://companion.34.29.199.131.nip.io', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  const composer = await page.$('textarea, input, [contenteditable="true"]');
  if (composer) {
    await composer.fill('ping');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(4000);
  }
  await browser.close();
}
inspectNet().catch(console.error);
