"""Optional real-browser regressions: RUN_BROWSER_TESTS=1 pytest tests/test_browser.py."""
import os
import threading
import pytest

pytestmark=pytest.mark.skipif(os.getenv('RUN_BROWSER_TESTS')!='1', reason='Run explicitly with installed Playwright Chromium')

@pytest.fixture
def browser_student(app):
    import time
    from app.db import get_db
    from werkzeug.serving import make_server
    from playwright.sync_api import sync_playwright
    app.config['CLOCK']=time.time
    with app.app_context():
        db=get_db()
        uid=db.execute("INSERT INTO users(issuer,subject,email,role,first_name,last_name) VALUES('google','browser-student','student@student.karazin.ua','student','Ім’я','Прізвище')").lastrowid
        db.execute('UPDATE tests SET is_open=1,keys_approved=1')
    client=app.test_client()
    with client.session_transaction() as session:session['user_id']=uid
    token=client.get_cookie('testing_session').value
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    with sync_playwright() as p:
        browser=p.chromium.launch()
        context=browser.new_context(viewport={'width':390,'height':844})
        context.add_cookies([{'name':'testing_session','value':token,'domain':'127.0.0.1','path':'/','httpOnly':True,'sameSite':'Lax'}])
        page=context.new_page()
        page.goto(f'http://127.0.0.1:{server.server_port}/')
        page.locator('#accept-rules').check()
        page.locator('#start-form button').click()
        page.locator('#choices').wait_for()
        yield page
        browser.close()
    server.shutdown();thread.join()


def test_stalled_answer_recovers_before_question_expires(browser_student):
    from playwright.sync_api import expect
    page=browser_student
    held=[]
    def stall(route):held.append(route)
    page.route('**/api/attempts/*/answers',stall)
    page.locator('.choice').nth(1).click()
    page.locator('#answer-button').click()
    expect(page.locator('#choices')).to_have_attribute('disabled','')
    expect(page.locator('#choices')).not_to_have_attribute('disabled','',timeout=8000)
    assert len(held)==1
    assert 'Запитання 1' in page.locator('.question-count').inner_text()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    for route in held:
        try:route.abort()
        except Exception:pass


def test_slow_response_does_not_restart_displayed_timer(browser_student):
    from playwright.sync_api import expect
    page=browser_student
    def delayed(route):
        response=route.fetch()
        page.wait_for_timeout(1500)
        route.fulfill(response=response)
    page.route('**/api/attempts/*/answers',delayed)
    page.locator('.choice').nth(1).click()
    page.locator('#answer-button').click()
    expect(page.locator('.question-count')).to_contain_text('Запитання 2')
    assert int(page.locator('#time-value').inner_text().split(':')[1]) <= 19
