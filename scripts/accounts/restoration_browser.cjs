const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.join(process.env.USERPROFILE,
    '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const [origin, output, reportFile, bookId, mode] = process.argv.slice(2);
const password = 'Synthetic-Reader-64-Only!';
const checks = [], errors = [];
const stateFile = path.join(output, 'restoration_state.json');

(async () => {
    const browser = await chromium.launch({
        executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        headless: true,
        args: ['--no-proxy-server', '--host-resolver-rules=MAP litmate.example.test 127.0.0.1']
    });
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1365, height: 920 } });
    const page = await context.newPage();
    page.on('pageerror', e => errors.push(e.message));
    const check = (name, passed) => {
        checks.push({ case: name, passed: Boolean(passed) });
        if (!passed) throw Error(name);
    };
    const go = async route => {
        const response = await page.goto(origin + route, { waitUntil: 'domcontentloaded' });
        if (!response.ok()) throw Error(route + ' HTTP ' + response.status());
        const banner = page.locator('#cookieConsentBanner');
        if (await banner.isVisible()) {
            await page.locator('#btnRejectCookies').click();
            await banner.waitFor({ state: 'hidden' });
        }
    };
    const post = async (route, data) => page.evaluate(async ({ route, data }) => {
        const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
            document.cookie.split('; ').find(c => c.startsWith('csrftoken='))?.split('=')[1];
        const response = await fetch(route, {
            method: 'POST', headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams(data)
        });
        return { status: response.status, body: await response.text() };
    }, { route, data });
    const login = async name => {
        if (page.url().startsWith(origin)) await post('/logout/', {});
        await go('/login/');
        await page.locator('[name=username_or_email]').fill(name);
        await page.locator('[name=password]').fill(password);
        await page.locator('#loginForm button[type=submit]').click();
        await page.waitForURL(url => url.pathname !== '/login/');
    };
    const capture = name => page.screenshot({ path: path.join(output, name + '.png'), fullPage: true });
    try {
        if (mode === 'restart') {
            await login('restoration-demo');
            const saved = JSON.parse(fs.readFileSync(stateFile));
            await go(saved.conversation);
            check('saved_question_after_restart', (await page.locator('body').innerText()).includes('¿Quién escribió Frankenstein?'));
            check('saved_answer_after_restart', (await page.locator('body').innerText()).includes('Mary Shelley'));
            check('clarification_after_restart', (await page.locator('body').innerText()).includes('Recuerdo un libro sobre aliens'));
            await go('/perfil/');
            check('profile_after_restart', await page.locator('.lm-profile').count() === 1);
        } else {
            await go('/contact/');
            check('contact_original_fields', await page.locator('[name=name],[name=email],[name=phone],[name=message]').count() === 4);
            await capture('contacto-escritorio');
            await page.locator('[name=name]').fill('Contacto sintético');
            await page.locator('[name=email]').fill('reader@example.invalid');
            await page.locator('[name=message]').fill('Consulta de prueba del formulario restaurado.');
            await page.getByRole('button', { name: 'Enviar mensaje' }).click();
            await page.getByText('Tu mensaje quedó registrado', { exact: false }).waitFor();
            check('contact_saved_confirmation', true);
            await capture('contacto-confirmacion');
            const invalid = await post('/contact/', { name: 'Lector', email: 'mal', message: 'Texto que debe conservarse' });
            check('contact_validation_preserves_input', invalid.status === 400 && invalid.body.includes('Texto que debe conservarse'));
            for (const width of [390, 768]) {
                await page.setViewportSize({ width, height: 844 });
                await go('/contact/');
                check('contact_no_overflow_' + width, await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
                await capture('contacto-' + width);
            }
            await page.setViewportSize({ width: 1365, height: 920 });
            await go('/registro/');
            const registered = await post('/registro/', { username: 'restoration-demo', email: 'restoration@example.invalid', password, password_confirm: password });
            check('register', registered.status === 200);
            await go('/suscripciones/planes/');
            check('activate_free', (await post('/cuenta/activar-gratis/', { plan: 'gratis' })).status === 200);
            await go('/perfil/');
            check('new_profile_layout', await page.locator('.lm-profile').count() === 1);
            await capture('perfil-vacio');
            for (const width of [390, 768]) {
                await page.setViewportSize({ width, height: 844 });
                check('profile_no_overflow_' + width, await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
                if (width === 390) {
                    check('mobile_assistant_does_not_cover_posts',
                        await page.locator('#floating-chat-wrapper').evaluate(el => getComputedStyle(el).position !== 'fixed'));
                    await capture('perfil-movil-final');
                }
            }
            await page.setViewportSize({ width: 1365, height: 920 });
            await go('/chat/');
            for (const question of ['¿Quién escribió Frankenstein?', 'Recuerdo un libro sobre aliens']) {
                const before = await page.locator('.chat-message.bot').count();
                await page.locator('#chat-input').fill(question);
                await page.locator('#send-btn').click();
                await page.waitForFunction(n => !document.querySelector('#send-btn').disabled &&
                    document.querySelectorAll('.chat-message.bot').length > n, before, { timeout: 45000 });
                const text = await page.locator('.chat-message.bot').last().innerText();
                check('completed_' + question, question.startsWith('¿') ? text.includes('Mary Shelley') : text.includes('pistas'));
            }
            await go('/perfil/?seccion=configuracion');
            const conversation = await page.locator('a[href*="/cuenta/conversaciones/"][href$="/ver/"]').first().getAttribute('href');
            await go(conversation);
            check('completed_chat_saved', (await page.locator('body').innerText()).includes('Mary Shelley'));
            check('clarification_saved', (await page.locator('body').innerText()).includes('Recuerdo un libro sobre aliens'));
            await capture('historial-persistente');
            fs.writeFileSync(stateFile, JSON.stringify({ conversation }));
            await post('/logout/', {});
            await login('other-private');
            check('foreign_history_denied', (await page.goto(origin + conversation)).status() === 404);
            await login('synthetic-operator');
            await go('/operacion/core/mensajecontacto/');
            check('protected_contact_inbox', (await page.locator('body').innerText()).includes('Contacto sintético'));
            await capture('bandeja-contacto-prueba');
        }
        check('no_javascript_exceptions', errors.length === 0);
    } catch (error) {
        errors.push(String(error));
    } finally {
        await browser.close();
        const result = { passed: errors.length === 0 && checks.every(c => c.passed), syntheticOnly: true, checks, errors };
        fs.writeFileSync(reportFile, JSON.stringify(result, null, 2));
        console.log(JSON.stringify(result));
        process.exitCode = result.passed ? 0 : 1;
    }
})();
