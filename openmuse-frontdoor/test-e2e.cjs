const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/W3jde/.gemini/antigravity/brain/98773ba9-1b8d-409c-b639-2365c6058fa1';
const CHROME_PATH = 'C:/Users/W3jde/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe';

async function runTest() {
  console.log('--- Starting Hermes Muse E2E & Visual Validation ---');
  const browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
  });

  const pageErrors = [];

  // 1. Desktop Test
  console.log('\n1. Testing Desktop Viewport (1440x900)...');
  const desktopContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const desktopPage = await desktopContext.newPage();
  desktopPage.on('pageerror', err => pageErrors.push(`[Desktop Page Error] ${err.message}`));
  desktopPage.on('console', msg => {
    if (msg.type() === 'error') {
      console.log(`[Desktop Console Error]: ${msg.text()}`);
    }
  });

  await desktopPage.goto('http://localhost:8081', { waitUntil: 'networkidle' });
  await desktopPage.waitForTimeout(2000);

  const desktopTitle = await desktopPage.title();
  console.log(`Desktop Page Title: "${desktopTitle}"`);

  const desktopScreenshot = path.join(ARTIFACT_DIR, 'hermes_muse_desktop.png');
  await desktopPage.screenshot({ path: desktopScreenshot, fullPage: false });
  console.log(`Saved Desktop Screenshot to: ${desktopScreenshot}`);

  await desktopContext.close();

  // 2. Mobile PWA Test
  console.log('\n2. Testing Mobile PWA Viewport (390x844 - iPhone)...');
  const mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    isMobile: true,
    hasTouch: true,
  });
  const mobilePage = await mobileContext.newPage();
  mobilePage.on('pageerror', err => pageErrors.push(`[Mobile Page Error] ${err.message}`));

  await mobilePage.goto('http://localhost:8081', { waitUntil: 'networkidle' });
  await mobilePage.waitForTimeout(2000);

  // Check PWA meta tags & elements
  const manifestLink = await mobilePage.$eval('link[rel="manifest"]', el => el ? el.href : null).catch(() => null);
  const themeColor = await mobilePage.$eval('meta[name="theme-color"]', el => el ? el.content : null).catch(() => null);
  console.log(`PWA Manifest Link: ${manifestLink}`);
  console.log(`PWA Theme Color: ${themeColor}`);

  // Check chat input and voice button
  const inputExists = await mobilePage.$('input, textarea');
  console.log(`Input Field Present: ${!!inputExists}`);

  const mobileScreenshot = path.join(ARTIFACT_DIR, 'hermes_muse_mobile_pwa.png');
  await mobilePage.screenshot({ path: mobileScreenshot, fullPage: false });
  console.log(`Saved Mobile PWA Screenshot to: ${mobileScreenshot}`);

  // Test typing a message
  if (inputExists) {
    await inputExists.fill('Hello Hermes Muse! How are you today?');
    await mobilePage.waitForTimeout(500);
    const typedScreenshot = path.join(ARTIFACT_DIR, 'hermes_muse_mobile_typed.png');
    await mobilePage.screenshot({ path: typedScreenshot, fullPage: false });
    console.log(`Saved Mobile Typed Screenshot to: ${typedScreenshot}`);
  }

  await mobileContext.close();
  await browser.close();

  console.log('\n--- Validation Summary ---');
  console.log(`Total Uncaught Page Errors: ${pageErrors.length}`);
  if (pageErrors.length > 0) {
    pageErrors.forEach(err => console.error(err));
  } else {
    console.log('✓ Zero page errors detected! Web PWA rendered cleanly.');
  }
}

runTest().catch(err => {
  console.error('Test execution failed:', err);
  process.exit(1);
});
