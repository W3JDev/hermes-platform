const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/W3jde/.gemini/antigravity/brain/98773ba9-1b8d-409c-b639-2365c6058fa1';
const CHROME_PATH = 'C:/Users/W3jde/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe';

async function testChatTurn() {
  console.log('--- Testing Live Chat Turn in Hermes Muse ---');
  const browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
  });

  const page = await browser.newPage({
    viewport: { width: 420, height: 880 }, // Phone size
  });

  page.on('console', msg => console.log(`[Browser Console ${msg.type()}]: ${msg.text()}`));
  page.on('pageerror', err => console.log(`[Page Error]: ${err.message}`));

  await page.goto('http://localhost:8081', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // Click on one of the quick suggestions or type in the input
  const suggestion = await page.$('text=Find cool things on Hacker News');
  if (suggestion) {
    console.log('Found suggestion button, clicking it...');
    await suggestion.click();
  } else {
    console.log('Suggestion not found, typing into input...');
    const input = await page.$('input, textarea');
    if (input) {
      await input.fill('What can you do?');
      await page.keyboard.press('Enter');
    }
  }

  console.log('Waiting for response generation...');
  // Wait up to 10 seconds for response cards / text to appear
  await page.waitForTimeout(7000);

  const screenshotPath = path.join(ARTIFACT_DIR, 'hermes_muse_live_chat_turn.png');
  await page.screenshot({ path: screenshotPath, fullPage: false });
  console.log(`Saved Live Chat Turn Screenshot to: ${screenshotPath}`);

  await browser.close();
}

testChatTurn().catch(err => {
  console.error('Chat turn test failed:', err);
  process.exit(1);
});
