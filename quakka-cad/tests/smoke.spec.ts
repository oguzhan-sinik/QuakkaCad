import { test } from '@playwright/test';

test('open bbc', async ({ page }) => {
  await page.goto('https://www.bbc.co.uk');
  await page.waitForTimeout(5000);
});
