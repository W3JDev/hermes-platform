const { chromium } = require('playwright');
const CHROME_PATH = 'C:/Users/W3jde/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe';

async function getHermesToken() {
  const browser = await chromium.launch({ executablePath: CHROME_PATH, headless: true });
  const context = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await context.newPage();

  console.log('Navigating to https://dashboard.34.29.199.131.nip.io/login ...');
  await page.goto('https://dashboard.34.29.199.131.nip.io/login', { waitUntil: 'networkidle', timeout: 15000 });
  
  const userField = page.locator("input[name='username']");
  const passField = page.locator("input[name='password']");
  if (await userField.count() > 0) {
    await userField.fill('admin');
    await passField.fill('6728');
    await Promise.all([
      page.waitForNavigation({ waitUntil: 'networkidle', timeout: 15000 }).catch(() => {}),
      page.locator("button[type='submit']").click()
    ]);
  }
  await page.waitForTimeout(2000);
  console.log('Logged in URL:', page.url());

  const cookies = await context.cookies();
  console.log('Cookies:', cookies.map(c => `${c.name}=${c.value}`));

  const storage = await page.evaluate(() => {
    return {
      localStorage: { ...localStorage },
      sessionStorage: { ...sessionStorage }
    };
  });
  console.log('Storage:', JSON.stringify(storage));

  await browser.close();
}
getHermesToken().catch(console.error);
