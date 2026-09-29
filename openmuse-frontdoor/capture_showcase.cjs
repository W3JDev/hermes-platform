const { chromium } = require('playwright');
const path = require('path');

const ARTIFACT_DIR = 'C:/Users/W3jde/.gemini/antigravity/brain/98773ba9-1b8d-409c-b639-2365c6058fa1';
const CHROME_PATH = 'C:/Users/W3jde/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe';

async function capture() {
  const browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
  });

  // 1. Mobile PWA View
  console.log('Capturing Mobile PWA View...');
  const mobileContext = await browser.newContext({
    viewport: { width: 400, height: 850 },
    isMobile: true,
    hasTouch: true,
  });
  const mobilePage = await mobileContext.newPage();
  await mobilePage.goto('http://localhost:8081', { waitUntil: 'networkidle' });
  await mobilePage.waitForTimeout(2000);

  const mobilePath = path.join(ARTIFACT_DIR, 'hermes_muse_showcase_mobile.png');
  await mobilePage.screenshot({ path: mobilePath });
  console.log('Saved:', mobilePath);

  // Send a message to show conversation in action
  const input = await mobilePage.$('input, textarea');
  if (input) {
    await input.fill('Hi Hermes Muse! Can you summarize what tools and capabilities you have ready?');
    await mobilePage.keyboard.press('Enter');
    console.log('Sent prompt, waiting for response...');
    await mobilePage.waitForTimeout(5000);
  }

  const convoPath = path.join(ARTIFACT_DIR, 'hermes_muse_showcase_chat.png');
  await mobilePage.screenshot({ path: convoPath });
  console.log('Saved:', convoPath);

  await mobileContext.close();

  // 2. Desktop View
  console.log('Capturing Desktop View...');
  const deskContext = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });
  const deskPage = await deskContext.newPage();
  await deskPage.goto('http://localhost:8081', { waitUntil: 'networkidle' });
  await deskPage.waitForTimeout(2000);

  const deskPath = path.join(ARTIFACT_DIR, 'hermes_muse_showcase_desktop.png');
  await deskPage.screenshot({ path: deskPath });
  console.log('Saved:', deskPath);

  await deskContext.close();
  await browser.close();
  console.log('All showcase screenshots captured successfully!');
}

capture().catch(console.error);
