import json
import time
import shutil
import platform
import threading
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager


# ── Configuration ──────────────────────────────────────────────────────────────

TARGET_URL  = "https://app.tests.ecriplus.fr/assessments/3538884/challenges/1"
WAIT_SECS   = 10       # seconds to wait for async requests after page load
PROXY_HOST  = "127.0.0.1"
PROXY_PORT  = 8082     # change if this port is already in use
OUTPUT_DIR  = Path("har_output")

# Optional keyword filter — leave empty [] to capture every request
URL_FILTERS: list[str] = []   # e.g. ["api", "challenge", ".json"]

SKIP_EXTENSIONS    = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                      ".woff", ".woff2", ".ttf", ".eot", ".css", ".ico", ".map"}
SKIP_MIME_PREFIXES = {"image/", "font/", "text/css"}

OUTPUT_DIR.mkdir(exist_ok=True)


# ── Firefox ESR binary detection ───────────────────────────────────────────────

def find_firefox_binary() -> str:
    """
    Find Firefox ESR (or any Firefox) binary on the current system.
    Raises RuntimeError if nothing is found.
    """
    # Check PATH first
    for name in ("firefox-esr", "firefox", "firefox-bin"):
        found = shutil.which(name)
        if found:
            return found

    # Fallback: common install locations per OS
    system = platform.system()
    if system == "Windows":
        candidates = [
            r"C:\Program Files\Mozilla Firefox ESR\firefox.exe",
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ]
    elif system == "Darwin":
        candidates = [
            "/Applications/Firefox ESR.app/Contents/MacOS/firefox",
            "/Applications/Firefox.app/Contents/MacOS/firefox",
        ]
    else:  # Linux
        candidates = [
            "/usr/bin/firefox-esr",
            "/usr/lib/firefox-esr/firefox-esr",
            "/usr/lib/firefox-esr/firefox",
            "/usr/bin/firefox",
            "/usr/lib/firefox/firefox",
            "/snap/bin/firefox",
            "/opt/firefox/firefox",
        ]

    for path in candidates:
        if Path(path).exists():
            return path

    raise RuntimeError(
        "Firefox ESR binary not found.\n"
        "Install it with:  sudo apt install firefox-esr\n"
        "Or set the path manually in find_firefox_binary()."
    )


# ── mitmproxy HAR recorder ─────────────────────────────────────────────────────

class HarRecorder:
    def __init__(self) -> None:
        self.entries: list[dict] = []
        self._lock = threading.Lock()

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            return
        req, resp = flow.request, flow.response
        entry = {
            "startedDateTime": datetime.now(timezone.utc).isoformat(),
            "request": {
                "method":      req.method,
                "url":         req.pretty_url,
                "headers":     [{"name": k, "value": v}
                                for k, v in req.headers.items()],
                "queryString": [{"name": k, "value": v}
                                for k, v in req.query.items()],
            },
            "response": {
                "status":     resp.status_code,
                "statusText": resp.reason,
                "headers":    [{"name": k, "value": v}
                               for k, v in resp.headers.items()],
                "content": {
                    "mimeType": resp.headers.get("content-type", ""),
                    "size":     len(resp.content),
                },
            },
        }
        with self._lock:
            self.entries.append(entry)

    def clear(self) -> None:
        with self._lock:
            self.entries.clear()

    def build_har(self) -> dict:
        with self._lock:
            return {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "ecri_har_capture", "version": "3.0"},
                    "entries": list(self.entries),
                }
            }


def start_proxy(recorder: HarRecorder, ready: threading.Event) -> None:
    async def _run() -> None:
        opts = Options(
            listen_host=PROXY_HOST,
            listen_port=PROXY_PORT,
            ssl_insecure=True,
        )
        master = DumpMaster(opts, with_termlog=False, with_dumper=False)
        master.addons.add(recorder)
        ready.set()
        await master.run()
    asyncio.run(_run())


# ── Firefox driver ─────────────────────────────────────────────────────────────

def build_driver(binary_path: str) -> webdriver.Firefox:
    options = FirefoxOptions()
    options.binary_location = binary_path

    # Route all traffic through mitmproxy
    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.http",      PROXY_HOST)
    options.set_preference("network.proxy.http_port", PROXY_PORT)
    options.set_preference("network.proxy.ssl",       PROXY_HOST)
    options.set_preference("network.proxy.ssl_port",  PROXY_PORT)
    options.set_preference("network.proxy.no_proxies_on", "")
    # Accept mitmproxy's self-signed certificate
    options.set_preference("network.stricttransportsecurity.preloadlist", False)
    options.set_preference("security.cert_pinning.enforcement_level", 0)
    options.accept_insecure_certs = True
    # options.add_argument("--headless")  # uncomment to run without a window

    return webdriver.Firefox(
        service=FirefoxService(GeckoDriverManager().install()),
        options=options,
    )


# ── HAR helpers ────────────────────────────────────────────────────────────────

def extract_api_urls(har: dict) -> list[str]:
    urls: list[str] = []
    for entry in har["log"]["entries"]:
        url   = entry["request"]["url"]
        mtype = entry["response"]["content"]["mimeType"]
        path  = url.split("?")[0].lower()
        if any(path.endswith(ext) for ext in SKIP_EXTENSIONS):
            continue
        if any(mtype.startswith(pfx) for pfx in SKIP_MIME_PREFIXES):
            continue
        if URL_FILTERS and not any(kw in url for kw in URL_FILTERS):
            continue
        urls.append(url)
    return urls


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n ECRI+ HAR Capture — launching own Firefox ESR instance")
    print(f" Target : {TARGET_URL}\n")

    # 1. Find Firefox ESR
    try:
        binary = find_firefox_binary()
        print(f"[BROWSER] Found Firefox binary → {binary}")
    except RuntimeError as e:
        print(f"[ERROR] {e}")
        return

    # 2. Start mitmproxy
    print(f"[PROXY]   Starting mitmproxy on {PROXY_HOST}:{PROXY_PORT} ...")
    recorder = HarRecorder()
    ready    = threading.Event()
    threading.Thread(target=start_proxy, args=(recorder, ready),
                     daemon=True).start()
    ready.wait(timeout=10)
    print("[PROXY]   Ready.\n")

    # 3. Launch Firefox and navigate
    print("[BROWSER] Launching Firefox ESR ...")
    driver = build_driver(binary)

    print(f"[BROWSER] Navigating to target URL ...")
    recorder.clear()
    driver.get(TARGET_URL)

    print(f"[BROWSER] Waiting {WAIT_SECS}s for async requests ...")
    time.sleep(WAIT_SECS)

    # 4. Collect and save results
    har_data  = recorder.build_har()
    entries   = har_data["log"]["entries"]
    api_urls  = extract_api_urls(har_data)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"\n[CAPTURE] {len(entries)} total requests")
    print(f"[CAPTURE] {len(api_urls)} API/XHR URLs\n")
    for e in entries:
        print(f"  [{e['request']['method']:<6}] "
              f"{e['response']['status']} → {e['request']['url']}")

    har_path  = OUTPUT_DIR / f"firefox-esr_capture_{timestamp}.har"
    req_path  = OUTPUT_DIR / f"firefox-esr_requests_{timestamp}.json"
    urls_path = OUTPUT_DIR / f"firefox-esr_api_urls_{timestamp}.txt"

    har_path.write_text(json.dumps(har_data, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    req_path.write_text(json.dumps(
        [{"url":    e["request"]["url"],
          "method": e["request"]["method"],
          "status": e["response"]["status"],
          "type":   e["response"]["content"]["mimeType"]}
         for e in entries],
        indent=2, ensure_ascii=False), encoding="utf-8")
    urls_path.write_text("\n".join(api_urls), encoding="utf-8")

    print(f"\n[SAVED] HAR      → {har_path}")
    print(f"[SAVED] Requests → {req_path}")
    print(f"[SAVED] API URLs → {urls_path}")
    print(f"\n Output: {OUTPUT_DIR.resolve()}\n")

    driver.quit()


if __name__ == "__main__":
    main()