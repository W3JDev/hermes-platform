const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/W3jde/.gemini/antigravity/brain/98773ba9-1b8d-409c-b639-2365c6058fa1';
const CHROME_PATH = 'C:/Users/W3jde/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe';

async function testCleanChat() {
  console.log('--- Starting Clean Chat Turn Test with HermesAdapter ---');
  const browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
  });

  const context = await browser.newContext({
    viewport: { width: 390, height: 844 }, // Mobile PWA layout
    isMobile: true,
    hasTouch: true,
  });

  const page = await context.newPage();

  page.on('console', msg => {
    if (msg.type() === 'error') {
      console.log(`[Browser Console ERROR]: ${msg.text()}`);
    }
  });

  await page.goto('http://localhost:8081', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // Clear any existing localStorage or cache
  await page.evaluate(() => {
    try {
      localStorage.clear();
      sessionStorage.clear();
    } catch (e) {}
  });

  // Reload to ensure fresh state
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  console.log('Page loaded. Checking for input field...');
  const input = await page.$('input, textarea');
  if (input) {
    console.log('Filling input with: "Hello Hermes Muse! Tell me what you can do."');
    await input.fill('Hello Hermes Muse! Tell me what you can do.');
    await page.waitForTimeout(500);

    // Look for send button (the arrow button next to mic)
    const buttons = await page.$$('div[role="button"], button');
    console.log(`Found ${buttons.length} clickable button candidates.`);

    // Press Enter to submit
    await page.keyboard.press('Enter');
    console.log('Pressed Enter. Waiting 6 seconds for streaming response...');
    await page.waitForTimeout(6000);
  }

  const screenshotPath = path.join(ARTIFACT_DIR, 'hermes_muse_clean_chat.png');
  await page.screenshot({ path: screenshotPath, fullPage: false });
  console.log(`Saved screenshot to: ${screenshotPath}`);

  await context.close();
  await browser.close();
}

testCleanChat().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
