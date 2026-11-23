"""
Every page the portal's browser tests open runs under the portal's Content-Security-Policy (ADR 0038, finding F-021):
importing this module makes the program fail when Chromium refuses anything because of the policy (a script, a style
element or attribute, an image, a font, a call), which it reports on the page's console.

The tests open their pages with Browser.new_context().new_page() or Browser.new_page(); both are wrapped so that each
page reports such messages here. At the end of the program, one FAIL line per message (the first 20) and exit status 1.
Import it after Playwright is importable, before the first page is opened:

    import csp_guard  # noqa: F401  (fails the program on a Content-Security-Policy violation)
"""
import atexit
import os
import sys

from playwright.sync_api import Browser, BrowserContext

VIOLATIONS: list[str] = []
MARK = "Content Security Policy"


def watch(page):
    """Records the page's console messages about the policy."""
    def seen(message):
        if MARK in message.text:
            VIOLATIONS.append(f"{page.url}: {message.text}")
    page.on("console", seen)
    return page


_context_new_page = BrowserContext.new_page
_browser_new_page = Browser.new_page
BrowserContext.new_page = lambda self, *args, **kwargs: watch(_context_new_page(self, *args, **kwargs))
Browser.new_page = lambda self, *args, **kwargs: watch(_browser_new_page(self, *args, **kwargs))


@atexit.register
def report():
    if not VIOLATIONS:
        return
    for text in VIOLATIONS[:20]:
        print(f"FAIL Content-Security-Policy violation: {text[:400]}")
    print(f"FAIL {len(VIOLATIONS)} Content-Security-Policy violation(s) in all")
    sys.stdout.flush()
    os._exit(1)
