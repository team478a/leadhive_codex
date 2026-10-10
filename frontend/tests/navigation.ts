import type { Page } from '@playwright/test'

export async function navigateWorkspace(page: Page, name: string) {
  const target = page.locator('.sidebar').getByRole('button', { name })
  if (!await target.isVisible()) await page.getByRole('button', { name: 'メニュー', exact: true }).click()
  await target.click()
}
