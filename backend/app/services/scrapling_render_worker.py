"""Disposable offline Scrapling DynamicFetcher renderer; no live fetch fallback."""

import json
import socket
import sys

GUARD = """
window.fetch = () => Promise.reject(new Error('OFFLINE_REPLAY'));
window.XMLHttpRequest = window.WebSocket = window.EventSource = window.Worker =
    window.SharedWorker = class { constructor() { throw new Error('OFFLINE_REPLAY'); } };
navigator.sendBeacon = () => false;
window.open = () => null;
HTMLFormElement.prototype.submit = HTMLFormElement.prototype.requestSubmit = () => {};
document.addEventListener('submit', e => e.preventDefault(), true);
"""


def render(url: str, html: str) -> dict:
    from scrapling.fetchers import DynamicFetcher

    state = {"setup": False, "served": False, "blocked": 0}
    # Owned blackhole proxy is also a fail-closed backup if upstream swallows
    # page_setup exceptions. It accepts no requests and cannot forward traffic.
    with socket.socket() as blackhole:
        blackhole.bind(("127.0.0.1", 0))
        blackhole.listen(1)
        port = blackhole.getsockname()[1]

        def setup(page):
            context = page.context

            def route(request_route):
                request = request_route.request
                if (
                    request.method == "GET"
                    and request.url == url
                    and request.is_navigation_request()
                    and not state["served"]
                ):
                    state["served"] = True
                    request_route.fulfill(
                        status=200, content_type="text/html; charset=utf-8", body=html
                    )
                else:
                    state["blocked"] += 1
                    request_route.abort()

            context.route("**/*", route)
            context.route_web_socket("**/*", lambda ws: ws.close())
            context.add_init_script(GUARD)
            context.on("page", lambda popup: popup.close() if popup != page else None)
            state["setup"] = True

        response = DynamicFetcher.fetch(
            url,
            page_setup=setup,
            headless=True,
            google_search=False,
            useragent="LeadHiveScraplingOfflineProbe/1.0",
            timeout=5000,
            wait=200,
            retries=1,
            network_idle=False,
            load_dom=True,
            selector_config={"adaptive": False},
            proxy=f"http://127.0.0.1:{port}",
            additional_args={"service_workers": "block", "accept_downloads": False},
            extra_flags=[
                "--proxy-bypass-list=<-loopback>",
                "--host-resolver-rules=MAP * ~NOTFOUND",
                "--disable-background-networking",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
            ],
        )
    if not state["setup"] or not state["served"] or response.url != url:
        raise ValueError("RENDER_INCOMPLETE")
    return {"html": response.body.decode("utf-8"), "blocked_requests": state["blocked"]}


if __name__ == "__main__":
    try:
        value = json.loads(sys.stdin.buffer.read(2_100_000))
        result = render(value["url"], value["html"])
        sys.stdout.write(json.dumps(result))
    except Exception:
        # Never expose HTML, URL, cookies, credentials or library exception text.
        sys.exit(1)
