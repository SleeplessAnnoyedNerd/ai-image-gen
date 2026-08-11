"""Browser tests for the prompt-history dropdown in templates/index.html.

The JS there has no other coverage: pytest alone cannot see focus/blur
ordering, the native undo stack, or whether `change` fires on arrow keys.
These drive a real headless Firefox against the real app.

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
from selenium.webdriver.support.ui import Select, WebDriverWait
from werkzeug.serving import make_server

from app import create_app

pytestmark = pytest.mark.browser

_TEXTAREA = (By.CSS_SELECTOR, "textarea[name='prompt']")
_SUBMIT = (By.CSS_SELECTOR, "button[value='image']")
_WRAP_ID = "prompt-history-wrap"
_SELECT_ID = "prompt-history"

# Longer than the 40-char label trim, so tests can tell the label from the value.
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
    """Option values, excluding the placeholder at index 0."""
    options = driver.find_elements(By.CSS_SELECTOR, f"#{_SELECT_ID} option")
    return [o.get_attribute("value") for o in options[1:]]


def _labels(driver):
    options = driver.find_elements(By.CSS_SELECTOR, f"#{_SELECT_ID} option")
    return [o.text for o in options[1:]]


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
# Checklist items 1-3: visibility and freshness without a page reload     #
# --------------------------------------------------------------------- #

def test_wrapper_is_hidden_on_a_fresh_install(page):
    wrap = page.find_element(By.ID, _WRAP_ID)
    assert not wrap.is_displayed()
    # The select still exists — the JS depends on it and on its placeholder.
    assert _values(page) == []


def test_dropdown_appears_after_first_submit_without_a_reload(page):
    page.execute_script("window.__sameDocument = true;")

    _submit(page, "a sunset over water")

    assert page.execute_script("return window.__sameDocument === true"), \
        "the page reloaded — the client-side prepend is not doing the work"
    assert page.find_element(By.ID, _WRAP_ID).is_displayed()
    assert _values(page) == ["a sunset over water"]
    assert _js_errors(page) == []


def test_second_prompt_goes_to_the_top(page):
    _submit(page, "first prompt")
    _submit(page, "second prompt")
    assert _values(page) == ["second prompt", "first prompt"]
    assert _js_errors(page) == []


def test_resubmitting_moves_to_top_without_duplicating(page):
    _submit(page, "first prompt")
    _submit(page, "second prompt")
    _submit(page, "first prompt")
    assert _values(page) == ["first prompt", "second prompt"]


# --------------------------------------------------------------------- #
# Checklist items 4-6: selecting                                         #
# --------------------------------------------------------------------- #

def test_selecting_fills_the_textarea_with_the_full_text_not_the_label(page):
    _submit(page, _LONG)
    _textarea(page).clear()

    Select(page.find_element(By.ID, _SELECT_ID)).select_by_index(1)

    assert _labels(page)[0] != _LONG, "label should be trimmed"
    assert _labels(page)[0].startswith(_LONG[:40])
    assert _textarea(page).get_attribute("value") == _LONG
    assert _js_errors(page) == []


def test_selecting_the_same_entry_twice_still_fills(page):
    _submit(page, _LONG)
    select = Select(page.find_element(By.ID, _SELECT_ID))

    select.select_by_index(1)
    assert _textarea(page).get_attribute("value") == _LONG

    _textarea(page).clear()
    assert _textarea(page).get_attribute("value") == ""

    # ta.focus() in the change handler already blurred the select, so the
    # reset has run and re-picking fires `change` again.
    Select(page.find_element(By.ID, _SELECT_ID)).select_by_index(1)
    assert _textarea(page).get_attribute("value") == _LONG


def test_picking_moves_focus_to_the_textarea(page):
    """ta.focus() is what puts the replacement on the native undo stack."""
    _submit(page, _LONG)
    _textarea(page).clear()

    Select(page.find_element(By.ID, _SELECT_ID)).select_by_index(1)

    assert page.execute_script(
        "return document.activeElement === document.querySelector('textarea[name=prompt]')"
    )
    # And the blur that focus() triggered reset the select to its placeholder.
    assert page.execute_script(f"return document.getElementById('{_SELECT_ID}').selectedIndex") == 0


# --------------------------------------------------------------------- #
# Checklist item 7: the open question — does undo recover typed text?     #
# --------------------------------------------------------------------- #

def test_undo_after_picking_restores_typed_text(page):
    _submit(page, _LONG)
    field = _textarea(page)
    field.clear()
    field.send_keys("something I was in the middle of writing")

    Select(page.find_element(By.ID, _SELECT_ID)).select_by_index(1)
    assert _textarea(page).get_attribute("value") == _LONG

    _textarea(page).send_keys(Keys.CONTROL, "z")

    assert _textarea(page).get_attribute("value") == "something I was in the middle of writing", (
        "setRangeText did not land on the native undo stack — picking a history "
        "entry destroys in-progress text irrecoverably"
    )


# --------------------------------------------------------------------- #
# Checklist item 8: hostile input                                         #
# --------------------------------------------------------------------- #

def test_quotes_and_angle_brackets_survive_a_round_trip(page):
    hostile = 'a " onmouseover="alert(1)" <script>x</script> prompt'

    _submit(page, hostile)
    _textarea(page).clear()
    Select(page.find_element(By.ID, _SELECT_ID)).select_by_index(1)

    assert _textarea(page).get_attribute("value") == hostile
    assert _js_errors(page) == []
    # The payload stayed inert: no <script> was injected by it, and the
    # onmouseover fragment did not become a real attribute on the select.
    assert page.execute_script(
        "return document.querySelectorAll('script').length === window.__scriptCount"
    ), "the hostile prompt injected a <script> element"
    assert page.find_element(By.ID, _SELECT_ID).get_attribute("onmouseover") is None
    injected = page.find_elements(By.CSS_SELECTOR, "#prompt-history option[onmouseover]")
    assert injected == []


def test_multiline_prompt_label_is_flattened_but_value_is_not(page):
    _submit(page, "line one\nline two")

    assert "\n" not in _labels(page)[0]
    assert "line one line two" in _labels(page)[0]
    assert _values(page) == ["line one\nline two"]


# --------------------------------------------------------------------- #
# The known residual, pinned so a future change has to acknowledge it      #
# --------------------------------------------------------------------- #

def test_arrowing_a_closed_select_reaches_only_the_most_recent_entry(page):
    """Documents accepted behaviour, not an aspiration.

    `change` fires on every arrow-key press on a closed select, and the handler
    calls ta.focus(), which blurs the select and resets it to the placeholder.
    So arrowing a closed select always lands on entry 1. Opening the listbox
    and committing a choice reaches all entries — that is the supported path.
    """
    _submit(page, "older prompt")
    _submit(page, "newer prompt")
    _textarea(page).clear()

    select = page.find_element(By.ID, _SELECT_ID)
    select.send_keys(Keys.ARROW_DOWN)
    assert _textarea(page).get_attribute("value") == "newer prompt"

    _textarea(page).clear()
    page.find_element(By.ID, _SELECT_ID).send_keys(Keys.ARROW_DOWN)
    assert _textarea(page).get_attribute("value") == "newer prompt", \
        "closed-select arrowing now reaches further — update this test and the spec"
