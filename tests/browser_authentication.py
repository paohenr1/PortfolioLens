"""Optional browser acceptance; never adds test accounts to the development DB."""

import select
import subprocess
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

PASSWORD = "fixture-only-sapphire-river-82"
NEW_PASSWORD = "fixture-only-garden-sunrise-91"


@contextmanager
def authentication_application():
    root = Path(__file__).resolve().parent.parent
    with TemporaryDirectory(prefix="stock-authentication-") as directory:
        with Path("/tmp/stock-authentication-server.log").open("a") as diagnostics:
            process = subprocess.Popen(
                [
                    str(root / ".venv/bin/python"),
                    str(root / "tests/authentication_server.py"),
                    str(Path(directory) / "accounts.sqlite3"),
                ],
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=diagnostics,
                text=True,
            )
            try:
                if not select.select([process.stdout], [], [], 15)[0]:
                    raise RuntimeError("The isolated authentication server did not start.")
                port = int(process.stdout.readline().strip())
                yield f"http://127.0.0.1:{port}"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def register(page, base, username):
    page.goto(base + "/register/")
    page.get_by_label("Username:", exact=True).fill(username)
    page.get_by_label("Password:", exact=True).fill(PASSWORD)
    page.get_by_label("Password confirmation:", exact=True).fill(PASSWORD)
    page.get_by_role("button", name="Create account", exact=True).click()
    page.get_by_role("heading", name="My account", exact=True).wait_for()
    assert f"Signed in as {username}." in page.locator("main").inner_text()


def main():
    from playwright.sync_api import sync_playwright

    with authentication_application() as base, sync_playwright() as driver:
        browser = driver.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        contexts = []
        errors, requests = [], []
        try:
            for width, height in ((1280, 900), (390, 844)):
                context = browser.new_context(viewport={"width": width, "height": height})
                contexts.append(context)
                context.on("request", lambda request: requests.append(request.url))
            alice, bob = [context.new_page() for context in contexts]
            for page in (alice, bob):
                page.on("pageerror", lambda error: errors.append(str(error)))

            alice.goto(base + "/account/")
            assert "/sign-in/?next=" in alice.url
            register(alice, base, "browser-alice")
            register(bob, base, "browser-bob")
            bob.goto(base + "/account/?username=browser-alice&user_id=1")
            assert "Signed in as browser-bob." in bob.locator("main").inner_text()
            assert "browser-alice" not in bob.locator("main").inner_text()

            for name, page in (("desktop", alice), ("mobile", bob)):
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(
                    path=f"/tmp/stock-authentication-account-{name}.png", full_page=True
                )
                page.get_by_role("link", name="Change password", exact=True).click()
                page.get_by_label("Old password:", exact=True).focus()
                assert page.get_by_label("Old password:", exact=True).evaluate(
                    "el => el === document.activeElement"
                )
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                page.screenshot(
                    path=f"/tmp/stock-authentication-password-{name}.png", full_page=True
                )

            alice.get_by_label("Old password:", exact=True).fill(PASSWORD)
            alice.get_by_label("New password:", exact=True).fill(NEW_PASSWORD)
            alice.get_by_label("New password confirmation:", exact=True).fill(NEW_PASSWORD)
            alice.get_by_role("button", name="Change password", exact=True).click()
            alice.get_by_role("heading", name="Password changed", exact=True).wait_for()
            alice.get_by_role("link", name="Back to my account", exact=True).click()
            alice.get_by_role("button", name="Sign out", exact=True).click()
            alice.goto(base + "/account/")
            assert "/sign-in/?next=" in alice.url
            alice.get_by_label("Username:", exact=True).fill("browser-alice")
            alice.get_by_label("Password:", exact=True).fill(PASSWORD)
            alice.get_by_role("button", name="Sign in", exact=True).click()
            assert (
                "Please enter a correct username and password" in alice.locator("main").inner_text()
            )
            assert alice.get_by_label("Password:", exact=True).input_value() == ""
            alice.get_by_label("Password:", exact=True).fill(NEW_PASSWORD)
            alice.get_by_role("button", name="Sign in", exact=True).click()
            alice.get_by_role("heading", name="My account", exact=True).wait_for()
            assert "Signed in as browser-alice." in alice.locator("main").inner_text()

            bob.get_by_role("button", name="Sign out", exact=True).click()
            bob.goto(base + "/register/")
            bob.get_by_label("Username:", exact=True).fill("invalid-test-user")
            bob.get_by_label("Password:", exact=True).fill("12345678")
            bob.get_by_label("Password confirmation:", exact=True).fill("12345678")
            bob.get_by_role("button", name="Create account", exact=True).click()
            assert "This password is entirely numeric." in bob.locator("main").inner_text()
            assert bob.get_by_label("Password:", exact=True).input_value() == ""
            assert (
                bob.get_by_label("Password confirmation:", exact=True).get_attribute("aria-invalid")
                == "true"
            )
            assert bob.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            bob.screenshot(path="/tmp/stock-authentication-validation-mobile.png", full_page=True)

            assert not errors
            assert all(urlsplit(url).hostname == "127.0.0.1" for url in requests)
            assert not any("/stocks/" in url or "intrinio" in url for url in requests)
            print(
                "Isolated account workflow: registration, two-user identity isolation, "
                "password change/re-login, POST sign-out, validation, "
                "desktop/mobile and keyboard controls PASS"
            )
        finally:
            for context in contexts:
                context.close()
            browser.close()


if __name__ == "__main__":
    main()
