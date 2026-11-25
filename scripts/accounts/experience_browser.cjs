const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.join(process.env.USERPROFILE,
    '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const [origin, output, reportPath, bookId, mode] = process.argv.slice(2);
const password = 'Synthetic-Reader-64-Only!';
const statePath = path.join(path.dirname(process.env.LITMATE_COMMUNITY_TEST_IMAGES), 'experience-browser-state.json');
const checks = [], errors = [], interactions = [];
const check = (name, passed) => { checks.push({ name, passed: Boolean(passed) }); if (!passed) throw Error(name); };
(async () => {
    const browser = await chromium.launch({ executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        headless: true, args: ['--no-proxy-server', '--host-resolver-rules=MAP litmate.example.test 127.0.0.1'] });
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1365, height: 920 },
        ...(mode === 'restart' ? { storageState: statePath } : {}) });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('response', async response => {
        if (response.url().includes('/me-gusta/')) interactions.push({status: response.status(),
            body: (await response.text()).slice(0, 600)});
    });
    const go = async route => {
        const response = await page.goto(origin + route, { waitUntil: 'domcontentloaded' });
        if (!response.ok()) throw Error(route + ' HTTP ' + response.status());
        const banner = page.locator('#cookieConsentBanner');
        if (await banner.isVisible()) {
            await page.locator('#btnRejectCookies').click();
            await banner.waitFor({ state: 'hidden' });
        }
    };
    const api = async (route, data, json = false) => page.evaluate(async ({ route, data, json }) => {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
            document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.slice(10);
        const response = await fetch(route, data === undefined ? { cache: 'no-store' } : {
            method: 'POST', headers: { 'X-CSRFToken': csrf,
                'Content-Type': json ? 'application/json' : 'application/x-www-form-urlencoded' },
            body: json ? JSON.stringify(data) : new URLSearchParams(data) });
        return { status: response.status, text: await response.text() };
    }, { route, data, json });
    const capture = name => page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
    const send = async question => {
        await page.waitForFunction(() => !document.querySelector('#send-btn').disabled);
        const count = await page.locator('.chat-message.user').count();
        await page.locator('#chat-input').fill(question);
        await page.locator('#send-btn').click();
        await page.waitForFunction(n => !document.querySelector('#send-btn').disabled &&
            document.querySelectorAll('.chat-message.user').length > n, count, { timeout: 45000 });
    };
    try {
        if (mode === 'restart') {
            await go('/chat/');
            await page.waitForFunction(() => !document.querySelector('#send-btn').disabled);
            check('chat_visible_after_server_restart', await page.locator('.chat-message.user').count() === 1);
            check('chat_persisted_after_server_restart', JSON.parse((await api('/api/chat/actual/')).text).messages.length === 2);
            await go('/comunidad/');
            check('public_post_after_restart', (await page.locator('.lm-post').innerText()).includes('Lectura de demostración'));
        } else {
            await go('/registro/');
            const form = page.locator('#registerForm');
            await form.locator('[name=username]').fill('experience-demo');
            await form.locator('[name=email]').fill('experience-demo@example.invalid');
            await form.locator('[name=password]').fill(password);
            await form.locator('[name=password_confirm]').fill(password);
            await form.locator('button[type=submit]').click();
            await page.waitForURL('**/suscripciones/planes/');
            await page.locator('form[action="/cuenta/activar-gratis/"] button').click();
            await page.waitForURL('**/chat/');
            await page.waitForFunction(() => !document.querySelector('#send-btn').disabled);
            check('chat_loaded', true);
            await go('/cuenta/perfil-literario/');
            await page.locator('[name=display_name]').fill('Lector de prueba · Demo');
            await page.locator('[name=alias]').fill('experience_demo');
            await page.locator('[name=biography]').fill('Cuenta ficticia para verificar la interfaz.');
            await page.locator('[name=published]').check();
            await page.locator('[data-profile-form] button[type=submit], [data-profile-form] button:not([type])').last().click();
            await page.waitForURL('**/perfil/');
            check('synthetic_public_profile', true);
            const saved = await api('/favoritos/agregar/', { google_id: 'db_' + bookId, titulo: 'Frankenstein',
                autores: 'Mary Shelley', imagen_url: '' }, true);
            check('favorite_saved', saved.status === 200);
            await go('/cuenta/libro/?id=db_' + bookId);
            const favorite = page.locator('.reader-book .btn-fav');
            await favorite.waitFor();
            await page.waitForFunction(() => document.querySelector('.reader-book .btn-fav').getAttribute('aria-pressed') === 'true');
            const box = await favorite.boundingBox();
            check('favorite_button_fits_text', box.width > 170 && box.height >= 40);
            check('cover_fallback', await page.getByText('Sin portada disponible').isVisible());
            await capture('biblioteca-ficha-escritorio');
            await page.setViewportSize({ width: 390, height: 844 });
            check('book_mobile_no_overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
            await capture('biblioteca-ficha-movil');
            await page.setViewportSize({ width: 1365, height: 920 });
            await favorite.click();
            await page.waitForFunction(() => document.querySelector('.btn-fav').getAttribute('aria-pressed') === 'false');
            check('favorite_removed', true);
            await favorite.click();
            await page.waitForFunction(() => document.querySelector('.btn-fav').getAttribute('aria-pressed') === 'true');
            await go('/cuenta/publicaciones/nueva/');
            await page.locator('[name=body]').fill('Lectura de demostración. Me gustaría conversar sobre Frankenstein y la responsabilidad de su protagonista.');
            await page.locator('[name=visibility]').selectOption('public');
            await page.locator('[data-submit-once] button').click();
            await page.waitForURL('**/comunidad/publicacion/*/');
            const postPath = new URL(page.url()).pathname;
            await go('/comunidad/');
            const heart = page.locator('[data-like-form] button').first();
            await heart.click();
            await page.waitForFunction(() => document.querySelector('[data-like-form] button').getAttribute('aria-pressed') === 'true');
            check('feed_heart_without_navigation', new URL(page.url()).pathname === '/comunidad/');
            await heart.click();
            await page.waitForFunction(() => document.querySelector('[data-like-form] button').getAttribute('aria-pressed') === 'false');
            check('heart_can_be_removed', true);
            await capture('comunidad-corazones');
            await go(postPath);
            await page.locator('#comment-form [name=body]').fill('Comentario sintético para abrir el hilo.');
            await page.locator('#comment-form button').click();
            await page.waitForURL('**/comunidad/publicacion/*/');
            await page.locator('[data-reply-to]').first().click();
            check('reply_prefills_mention', (await page.locator('#comment-form [name=body]').inputValue()).startsWith('@Lector de prueba'));
            await page.locator('#comment-form [name=body]').fill('@Lector de prueba · Demo Podemos comparar nuestras interpretaciones.');
            await page.locator('#comment-form button').click();
            await page.waitForURL('**/comunidad/publicacion/*/');
            check('thread_comments_persisted', await page.locator('.lm-comment').count() === 2);
            await capture('hilo-comentarios');
            await go('/about/');
            check('team_names_only', await page.locator('#team img').count() === 0 && await page.locator('.lm-team-member').count() === 4);
            check('navbar_search_removed', await page.locator('#navCmdSearchBtn').count() === 0);
            await page.waitForFunction(() => /lector.*conectado/.test(document.querySelector('#litmate-online-count').textContent));
            check('real_presence_visible', true);
            await capture('equipo-y-conectados');
            await go('/chat/');
            await send('Hola');
            await send('Muéstrame mis favoritos');
            const active = JSON.parse((await api('/api/chat/actual/')).text);
            check('question_and_answer_saved', active.messages.length === 4);
            await go('/comunidad/');
            await go('/chat/');
            await page.waitForFunction(() => !document.querySelector('#send-btn').disabled);
            check('chat_restored_after_navigation', await page.locator('.chat-message.user').count() === 2);
            check('restored_answer_contains_favorite', (await page.locator('#chat-body-page').innerText()).includes('Frankenstein'));
            await capture('chat-retomado');
            const quotaBefore = JSON.parse((await api('/api/cuota-ia/')).text).cuota.usadas;
            await page.locator('#clear-chat-btn').click();
            check('delete_confirmation_visible', await page.locator('#clear-chat-dialog').isVisible());
            await capture('confirmacion-borrado');
            await page.locator('#cancel-clear-chat').click();
            check('cancel_keeps_conversation', await page.locator('.chat-message.user').count() === 2);
            await page.locator('#clear-chat-btn').click();
            await page.locator('#confirm-clear-chat').click();
            await page.locator('#clear-chat-dialog').waitFor({ state: 'hidden' });
            check('chat_deleted', await page.locator('.chat-message.user').count() === 0);
            check('history_deleted', (await api('/cuenta/conversaciones/' + active.conversation_id + '/')).status === 404);
            check('quota_preserved_after_delete', JSON.parse((await api('/api/cuota-ia/')).text).cuota.usadas === quotaBefore);
            await page.reload();
            await page.waitForFunction(() => !document.querySelector('#send-btn').disabled);
            check('deleted_messages_stay_deleted', await page.locator('.chat-message.user').count() === 0);
            await send('Hola');
            await context.storageState({ path: statePath });
            await page.setViewportSize({ width: 390, height: 844 });
            for (const route of ['/chat/', '/comunidad/', '/perfil/', '/cuenta/biblioteca/']) {
                await go(route);
                check('mobile_no_overflow_' + route, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
            }
        }
        check('no_javascript_exceptions', errors.length === 0);
    } catch (error) {
        errors.push(String(error));
        const notice = await page.locator('#reader-library-notice').textContent().catch(() => '');
        if (notice) errors.push(notice);
        await capture('fallo-' + path.basename(reportPath, '.json')).catch(() => {});
    }
    finally {
        await browser.close();
        const report = { checks, errors, interactions, passed: errors.length === 0 && checks.every(item => item.passed) };
        fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
        console.log(JSON.stringify(report));
        process.exitCode = report.passed ? 0 : 1;
    }
})().catch(error => { console.error(String(error)); process.exitCode = 1; });
