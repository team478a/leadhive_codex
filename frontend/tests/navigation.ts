import type { Page } from '@playwright/test'

export async function navigateWorkspace(page: Page, name: string) {
  const target = page.locator('.sidebar').getByRole('button', { name })
  // Login/reload renders the sidebar asynchronously. Absence is not a closed menu.
  await page.locator('.sidebar').waitFor({ state: 'visible' })
  if (!await target.isVisible()) await page.getByRole('button', { name: 'メニュー', exact: true }).click()
  await target.click()
}
