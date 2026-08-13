"""Browser tests for the prompt picker in templates/index.html.

The JS there has no other coverage: pytest alone cannot see the native undo
stack, delegated click handling across htmx swaps, or whether the list
refreshes after a submit. These drive a real headless Firefox against the
real app.

Requires `selenium` (in requirements.txt). Selenium Manager fetches
geckodriver automatically on first run. The page pulls htmx from a CDN,
exactly as a real user's browser does, so these need outbound network — they
skip with a clear message rather than fail when it is unavailable.

Playwright was tried first and rejected: it ships no browser builds for
debian11-x64, which is what this host runs.
"""
import socket
import threading
from unittest.mock import patch

import pytest
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from werkzeug.serving import make_server

from app import create_app
from config import ImageBackend

pytestmark = pytest.mark.browser

_TEXTAREA = (By.CSS_SELECTOR, "textarea[name='prompt']")
_SUBMIT = (By.CSS_SELECTOR, "button[value='image']")
_RESULTS_ID = "prompt-results"
_SEARCH_ID = "prompt-search"

# Longer than the old 40-char label trim, so tests can tell the snippet from
# the full value.
_LONG = "a photorealistic lighthouse at dusk with heavy fog rolling in"


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def browser():
    """One Firefox for the whole module — launching it costs ~2s."""
    options = Options()
    options.add_argument("-headless")
    try:
        driver = webdriver.Firefox(options=options)
    except WebDriverException as exc:
        pytest.skip(f"headless Firefox unavailable: {exc}")
    driver.set_window_size(1280, 1024)
    yield driver
    driver.quit()


@pytest.fixture
def server(cfg):
    """The real app on a background thread, with generation stubbed out.

    Patching `_cache_artifact` matters: each `_submit()` fires a real
    `POST /generate`, which starts a real, unjoined daemon `_run_image_job`
    thread. `thread.join()` below only joins the server thread, not job
    threads, so a job thread can outlive the test and write to .cache/ after
    the autouse `_isolated_cwd` fixture has already unwound its chdir.
    """
    port = _free_port()
    srv = make_server("127.0.0.1", port, create_app(cfg), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    with patch("app.image_gen.generate_image", return_value=b"\x89PNG\r\n\x1a\n"), \
         patch("app._cache_artifact"):
        thread.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def dummy_server(cfg):
    """Like the regular server fixture, but does NOT patch generate_image —
    the real _generate_dummy must run for the browser to decode it.

    Still patches _cache_artifact: the server runs in a real thread with
    threaded=True, so unjoined job threads can outlive the test and write
    after _isolated_cwd has unwound.  The docstring at :65-70 explains
    the full reasoning.
    """
    cfg.image_backends["dummy"] = ImageBackend(
        name="dummy", api_url="dummy://local", api_key="dummy",
        model=["dummy/instant"], model_edit=["dummy/instant"],
        api_version="2024-02-01",
    )
    port = _free_port()
    srv = make_server("127.0.0.1", port, create_app(cfg), threaded=True)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    with patch("app._cache_artifact"):
        thread.start()
        yield f"http://127.0.0.1:{port}"
        srv.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def page(browser, server):
    """A loaded index page with a JS error collector attached."""
    browser.get(server)
    if (browser.execute_script("return typeof window.htmx") == "undefined"):
        pytest.skip("htmx did not load from its CDN — these tests need network")
    # Our handlers all run on interaction, i.e. after this point.
    browser.execute_script(
        "window.__errs = [];"
        "window.addEventListener('error', function(e) { window.__errs.push(String(e.message)); });"
        "window.__scriptCount = document.querySelectorAll('script').length;"
    )
    return browser


def _values(driver):
    """The full prompt text of every rendered row."""
    rows = driver.find_elements(By.CSS_SELECTOR, f"#{_RESULTS_ID} button[data-prompt]")
    return [row.get_attribute("data-prompt") for row in rows]


def _search(driver, query):
    box = driver.find_element(By.ID, _SEARCH_ID)
    box.clear()
    box.send_keys(query)
    return box


def _pick(driver, text):
    driver.find_element(
        By.CSS_SELECTOR, f"#{_RESULTS_ID} button[data-prompt='{text}']"
    ).click()


def _pick_first(driver):
    """Pick the first rendered row by position. Use when the prompt text
    contains characters that break CSS attribute selectors (single quotes,
    raw newlines)."""
    driver.find_element(
        By.CSS_SELECTOR, f"#{_RESULTS_ID} button[data-prompt]"
    ).click()


def _js_errors(driver):
    return driver.execute_script("return window.__errs || []")


def _textarea(driver):
    return driver.find_element(*_TEXTAREA)


def _submit(driver, text):
    field = _textarea(driver)
    field.clear()
    field.send_keys(text)
    driver.find_element(*_SUBMIT).click()
    WebDriverWait(driver, 5).until(lambda d: text in _values(d))


# --------------------------------------------------------------------- #
# Visibility and freshness without a page reload                         #
# --------------------------------------------------------------------- #

def test_picker_is_empty_on_a_fresh_install(page):
    assert _values(page) == []


def test_list_appears_after_first_submit(page):
    _submit(page, _LONG)

    assert _values(page) == [_LONG]
    assert _js_errors(page) == []


def test_second_prompt_goes_to_the_top(page):
    _submit(page, "an older prompt")
    _submit(page, _LONG)

    assert _values(page)[0] == _LONG


def test_resubmitting_moves_to_top_without_duplicating(page):
    _submit(page, "an older prompt")
    _submit(page, _LONG)
    _submit(page, "an older prompt")

    values = _values(page)
    assert values[0] == "an older prompt"
    assert values.count("an older prompt") == 1


# --------------------------------------------------------------------- #
# Selecting                                                              #
# --------------------------------------------------------------------- #

def test_picking_fills_the_textarea_with_the_full_text_not_the_snippet(page):
    _submit(page, _LONG)
    _textarea(page).clear()

    _pick(page, _LONG)

    assert _textarea(page).get_attribute("value") == _LONG
    assert _js_errors(page) == []


def test_picking_moves_focus_to_the_textarea(page):
    """ta.focus() is what puts the replacement on the native undo stack."""
    _submit(page, _LONG)
    _textarea(page).clear()

    _pick(page, _LONG)

    assert page.execute_script(
        "return document.activeElement === document.querySelector('textarea[name=prompt]')"
    )


# --------------------------------------------------------------------- #
# Undo                                                                   #
# --------------------------------------------------------------------- #

def test_undo_after_picking_restores_typed_text(page):
    _submit(page, _LONG)
    field = _textarea(page)
    field.clear()
    field.send_keys("something I was in the middle of writing")

    _pick(page, _LONG)
    assert _textarea(page).get_attribute("value") == _LONG

    _textarea(page).send_keys(Keys.CONTROL, "z")

    assert _textarea(page).get_attribute("value") == "something I was in the middle of writing", (
        "insertText did not land on the native undo stack — picking a prompt "
        "destroys in-progress text irrecoverably"
    )


# --------------------------------------------------------------------- #
# Hostile input                                                          #
# --------------------------------------------------------------------- #

def test_quotes_and_angle_brackets_survive_a_round_trip(page):
    hostile = 'a " onmouseover="alert(1)" <script>x</script> prompt'
    _submit(page, hostile)
    _textarea(page).clear()

    # Double quote breaks the attribute selector in _pick(), so pick by position.
    _pick_first(page)

    assert _textarea(page).get_attribute("value") == hostile
    assert page.find_elements(By.CSS_SELECTOR, f"#{_RESULTS_ID} [onmouseover]") == []
    assert page.execute_script("return document.querySelectorAll('script').length") \
        == page.execute_script("return window.__scriptCount")


def test_multiline_prompt_survives_a_round_trip(page):
    multiline = "line one\nline two"
    _submit(page, multiline)
    _textarea(page).clear()

    # Raw newline inside a CSS string token is a parse error, so pick by position.
    _pick_first(page)

    assert _textarea(page).get_attribute("value") == multiline


# --------------------------------------------------------------------- #
# Search                                                                 #
# --------------------------------------------------------------------- #

def test_typing_in_the_search_box_narrows_the_list(page):
    _submit(page, "a red bikini on a beach")
    _submit(page, "a blue coat in the snow")

    _search(page, "bikini")
    WebDriverWait(page, 5).until(lambda d: _values(d) == ["a red bikini on a beach"])

    assert _js_errors(page) == []


# --------------------------------------------------------------------- #
# Dummy backend browser test                                              #
# --------------------------------------------------------------------- #

def test_dummy_backend_renders_a_decodable_512x512_png(browser, dummy_server):
    """The in-process suite asserts the PNG bytes start with the right
    signature, but only a real browser can tell us whether the
    zlib-compressed hand-assembled chunks actually decode into a visible
    512x512 image.  """
    browser.get(dummy_server)
    if browser.execute_script("return typeof window.htmx") == "undefined":
        pytest.skip("htmx CDN unreachable")
    browser.execute_script(
        "window.__errs = [];"
        "window.addEventListener('error', function(e) { window.__errs.push(String(e.message)); });"
    )

    field = browser.find_element(By.CSS_SELECTOR, "textarea[name='prompt']")
    field.clear()
    field.send_keys("dummy backend smoke test")

    # Select the dummy backend from the dropdown that appears when multiple
    # backends are configured.  The adv-panel is hidden by CSS, so we
    # use JavaScript to set the value directly.
    browser.execute_script(
        "var sel = document.getElementById('image-backend-select');"
        "if (sel) { sel.value = 'dummy'; }"
    )

    browser.find_element(By.CSS_SELECTOR, "button[value='image']").click()
    # Wait for the <img> to appear and decode.
    WebDriverWait(browser, 10).until(
        lambda d: d.execute_script(
            "var img = document.querySelector('#result-area img');"
            "return img && img.naturalWidth > 0;"
        )
    )

    width = browser.execute_script(
        "var img = document.querySelector('#result-area img');"
        "return img ? img.naturalWidth : -1;"
    )
    assert width == 512, f"expected 512px wide image, got {width}"
    assert browser.execute_script("return window.__errs || []") == []
