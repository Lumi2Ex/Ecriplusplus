from playwright.sync_api import sync_playwright
import os

def getHar(String(website)):
    os.makedirs("requests", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            record_har_path="requests/output.har"
        )

        page = context.new_page()
        page.goto(website)

        context.close()
        browser.close()