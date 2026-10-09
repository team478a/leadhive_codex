import type { Browser, WebRoute } from '@e2e-dev/web';

export function allowed(url: string, method: string, urls: Record<string, string>) {
  const parsed = new URL(url);
  return method === 'GET' && parsed.protocol === 'http:' && parsed.hostname === '127.0.0.1'
    && !parsed.username && !parsed.password && !parsed.search && !parsed.hash
    && Object.values(urls).includes(url);
}

// Never continue(): redirected requests would escape a one-shot route handler.
export async function guardedBody(url: string, method: string, urls: Record<string, string>) {
  if (!allowed(url, method, urls)) throw new Error('NETWORK_DENIED');
  const response = await fetch(url, { redirect: 'manual', signal: AbortSignal.timeout(3000) });
  if (response.status >= 300 && response.status < 400) throw new Error('REDIRECT_DENIED');
  const body = await response.text();
  if (Buffer.byteLength(body) > 64000) throw new Error('PAGE_BUDGET');
  return { status: response.status, contentType: response.headers.get('content-type') ?? 'text/plain', body };
}

export async function guard(browser: Browser, urls: Record<string, string>) {
  let requests = 0;
  let denied = 0;
  await browser.route('**/*', async (route: WebRoute) => {
    try {
      if (++requests > 30) throw new Error('REQUEST_BUDGET');
      await route.fulfill(await guardedBody(route.request.url, route.request.method, urls));
    } catch {
      denied++;
      await route.abort();
    }
  });
  return () => ({ requests, denied });
}
