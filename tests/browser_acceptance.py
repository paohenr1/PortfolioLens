"""Browser acceptance helpers; pace requests without changing production quotas."""

import time


class RequestPacer:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.window = None
        self.spent = 0

    def before(self, maximum_requests):
        if not 1 <= maximum_requests <= 10:
            raise ValueError("Acceptance actions must fit the existing client allowance.")
        window = int(self.clock()) // 60
        if window != self.window:
            self.window, self.spent = window, 0
        if self.spent + maximum_requests > 10:
            print("Acceptance pacing: waiting for the existing client request window.", flush=True)
            wait_for_window(self.window, clock=self.clock)
            self.window, self.spent = int(self.clock()) // 60, 0
        self.spent += maximum_requests


def wait_for_window(window, *, clock=time.monotonic):
    # Local tests share the host monotonic clock; the local PostgreSQL counter
    # uses the same host's wall clock. Wait in short chunks in the matching mode;
    # never reset application counters or manufacture another client address.
    while int(clock()) // 60 == window:
        remaining = (window + 1) * 60 - clock()
        time.sleep(min(20, max(0.05, remaining + 0.05)))


def responsive(page, *, screenshots=None, name="acceptance"):
    for label, width, height in (("desktop", 1280, 900), ("mobile", 390, 844)):
        page.set_viewport_size({"width": width, "height": height})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if screenshots:
            page.screenshot(path=f"/tmp/{name}-{label}.png", full_page=True)
