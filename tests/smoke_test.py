"""Headless smoke test: serves the app, checks console errors, toggle persistence, takes screenshots.
Run: python tests/smoke_test.py   (needs: pip install playwright && python -m playwright install chromium)"""
import http.server, threading, functools, os, sys, socketserver
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, 'screenshots')
os.makedirs(SHOTS, exist_ok=True)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass

def serve():
    handler = functools.partial(Quiet, directory=ROOT)
    socketserver.ThreadingTCPServer.daemon_threads = True  # the page loads many icons in parallel
    httpd = socketserver.ThreadingTCPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

def main():
    httpd = serve(); port = httpd.server_address[1]
    url = f'http://127.0.0.1:{port}/index.html'
    errors, failed = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = ctx.new_page()
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append(f'pageerror: {e}'))
        page.on('requestfailed', lambda r: failed.append(r.url))
        page.on('response', lambda r: failed.append(f'{r.status} {r.url}') if r.status >= 400 else None)
        page.goto(url); page.wait_for_selector('#collection-cards .card')
        # 0) icons: mod icons ship in git; vanilla icons are optional (build/extract_icons.py, not committed)
        vdir = os.path.join(ROOT, 'assets', 'icons', 'vanilla')
        have_vanilla = os.path.isfile(os.path.join(vdir, 'icons.js'))
        imgs = page.evaluate("""(() => { const v = window.PZ_VANILLA_ICONS || {};
            return window.PZDATA.items.map(i => i.img || (i.ic && v[i.ic.toLowerCase()] ? 'vanilla/' + v[i.ic.toLowerCase()] : '')).filter(Boolean); })()""")
        missing_icons = [i for i in imgs if os.path.basename(i) not in os.listdir(os.path.join(ROOT, 'assets', 'icons', os.path.dirname(i)))]
        total = page.evaluate('window.PZDATA.items.length')
        if have_vanilla:
            print(f'icons: {len(imgs)} of {total} items have a real icon; missing files: {len(missing_icons)}')
        else:
            print(f'NOTE: vanilla icons not extracted (no assets/icons/vanilla/icons.js) - vanilla items use category glyphs.\n'
                  f'      Run: uv run --with pillow build/extract_icons.py   ({len(imgs)} of {total} items have a real icon)')
        # 1) skill book matrix: click first cell twice -> HAVE+READ
        cell = page.locator('[data-cell]').first
        cid = cell.get_attribute('data-cell')
        cell.click(); page.locator(f'[data-cell="{cid}"]').click()
        page.locator('[data-cell]').nth(6).click()
        page.locator('[data-cell]').nth(12).click()
        page.screenshot(path=os.path.join(SHOTS, '1-collections-skillbooks.png'), full_page=False)
        # 2) all items: search + toggle have + want + stash tag
        page.click('[data-tab="items"]')
        page.fill('#f-search', 'generator')
        page.wait_for_timeout(200)
        first = page.locator('#item-list .row').first
        fid = first.get_attribute('data-open')
        first.locator('[data-act="h"]').click()
        page.locator(f'#item-list .row[data-open="{fid}"] [data-act="w"]').click()
        page.locator(f'#item-list .row[data-open="{fid}"] .nm').click()
        page.fill('#d-stash', 'Base - Rosewood fire station')
        page.locator('#d-stash').press('Tab')
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(SHOTS, '2-items-detail.png'))
        page.click('#detail-close')
        # wishlist a couple of things for loot planner
        page.fill('#f-search', 'magazine:')
        page.wait_for_timeout(200)
        for i in range(1, 5):
            page.locator('#item-list .row').nth(i).locator('[data-act="w"]').click()
        page.click('[data-tab="loot"]')
        page.wait_for_selector('#loot-groups .rank')
        page.screenshot(path=os.path.join(SHOTS, '3-loot-planner.png'))
        page.click('[data-tab="skills"]'); page.wait_for_selector('.skillrow')
        page.locator('[data-sk][data-d="1"]').first.click()
        page.wait_for_timeout(300)
        # 3) reload and verify persistence
        page.reload(); page.wait_for_selector('.tab.active')
        state = page.evaluate('JSON.parse(localStorage.getItem("pzItemTracker.v1"))')
        ok = {
            'skillbook have+read persisted': state['items'].get(cid, {}).get('h') == 1 and state['items'].get(cid, {}).get('r') == 1,
            'item have persisted': state['items'].get(fid, {}).get('h') == 1,
            'item want persisted': state['items'].get(fid, {}).get('w') == 1,
            'stash tag persisted': state['items'].get(fid, {}).get('s') == 'Base - Rosewood fire station',
            'skill level persisted': any(v == 1 for v in state['skills'].values()),
            'tab persisted': state['ui'].get('tab') == 'skills',
            'all referenced icon files exist': not missing_icons,
        }
        page.screenshot(path=os.path.join(SHOTS, '4-skills.png'))
        # export works
        page.click('[data-tab="save"]')
        with page.expect_download() as dl:
            page.click('#btn-export')
        ok['export download'] = dl.value.suggested_filename.endswith('.json')
        # file:// mode loads too
        fpage = ctx.new_page(); ferr = []
        fpage.on('pageerror', lambda e: ferr.append(str(e)))
        fpage.goto('file://' + os.path.join(ROOT, 'index.html')); fpage.wait_for_selector('#hud-build')
        ok['file:// loads without page errors'] = not ferr
        # without extracted icons the optional icons.js is simply absent; that one 404 is expected
        if not have_vanilla:
            errors[:] = [e for e in errors if not ('Failed to load resource' in e or 'ERR_FILE_NOT_FOUND' in e)]
            failed[:] = [u for u in failed if not u.endswith('/assets/icons/vanilla/icons.js')]
        browser.close()
    httpd.shutdown()
    print('checks:'); [print(f'  {"PASS" if v else "FAIL"}  {k}') for k, v in ok.items()]
    print('console errors:', errors or 'none'); print('failed requests:', failed or 'none')
    sys.exit(0 if all(ok.values()) and not errors and not failed else 1)

if __name__ == '__main__':
    main()
