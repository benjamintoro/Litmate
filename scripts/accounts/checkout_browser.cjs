const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const [origin, pictures, output, bookId, mode] = process.argv.slice(2);
const checks = [], errors = [];
const password = 'Synthetic-Community-64-Only!';
const stateFile = path.join(pictures, 'checkout_state.json');

(async () => {
    const browser = await chromium.launch({
        executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        args: ['--host-resolver-rules=MAP litmate.example.test 127.0.0.1', '--no-proxy-server']
    });
    const reader = async () => {
        const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 950 } });
        const page = await context.newPage();
        page.on('pageerror', e => errors.push(e.message));
        return page;
    };
    const go = async (page, route) => {
        const response = await page.goto(origin + route, { waitUntil: 'domcontentloaded' });
        if (!response.ok()) throw Error(route + ' HTTP ' + response.status());
        const banner = page.locator('#cookieConsentBanner');
        if (await banner.isVisible()) {
            await page.locator('#btnRejectCookies').click({ timeout: 2500 });
            await banner.waitFor({ state: 'hidden', timeout: 2000 });
        }
    };
    const check = (name, passed) => {
        checks.push({ case: name, passed: Boolean(passed) });
        if (!passed) throw Error(name);
    };
    const capture = async (page, name) => {
        await page.screenshot({ path: path.join(pictures, name + '.png'), fullPage: true, animations: 'disabled' });
    };
    const quota = page => page.evaluate(async () => (await (await fetch('/api/cuota-ia/')).json()).cuota);
    const login = async (page, name) => {
        await go(page, '/login/');
        await page.locator('[name=username_or_email]').fill(name);
        await page.locator('[name=password]').fill(password);
        await page.locator('#loginForm button[type=submit]').click();
        await page.waitForURL(url => url.pathname !== '/login/');
    };
    const checkout = async (page, slug, method, scenario = 'approved', captures = false, renew = false) => {
        await go(page, '/suscripciones/checkout/' + slug + '/');
        if (captures) await capture(page, 'p02-resumen');
        await page.getByRole('link', { name: 'Continuar', exact: true }).click();
        await page.locator('[name=method][value="' + method + '"]').check();
        if (renew) await page.locator('[name=renew]').check();
        await page.locator('[name=scenario]').selectOption(scenario);
        check('no_banking_inputs_' + slug + '_' + method + '_' + scenario,
            await page.locator('input[name*=cvv],input[name*=card_number],input[name*=iban]').count() === 0);
        if (captures) await capture(page, 'p03-metodo');
        await page.getByRole('button', { name: 'Revisar confirmación' }).click();
        await page.waitForURL('**/suscripciones/pedido/*/');
        const order = new URL(page.url()).pathname;
        if (captures) await capture(page, 'p04-confirmacion');
        await page.getByRole('button', { name: 'Confirmar contratación simulada' }).click();
        if (scenario === 'temporary') {
            await page.getByRole('button', { name: 'Reintentar el mismo pedido' }).waitFor();
            await capture(page, 'p10-error-temporal');
            await page.getByRole('button', { name: 'Reintentar el mismo pedido' }).click();
        }
        await page.waitForURL('**/suscripciones/comprobante/*/');
        check('result_' + slug + '_' + method + '_' + scenario, (await page.locator('.lm-result').innerText()) ===
            (scenario === 'rejected' ? 'Rechazada' : 'Aprobada'));
        if (captures) {
            await capture(page, 'p05-aprobado');
            await capture(page, 'p06-comprobante');
            await page.pdf({ path: path.join(pictures, 'comprobante_sintetico.pdf'), format: 'Letter', printBackground: true });
        }
        if (scenario === 'rejected') await capture(page, 'p09-rechazado');
        return { order, receipt: new URL(page.url()).pathname };
    };
    try {
        const a = await reader();
        await login(a, 'elena-demo');
        const community = JSON.parse(fs.readFileSync(path.join(pictures, 'browser_state.json'), 'utf8'));
        if (mode === 'restart') {
            const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
            await go(a, '/suscripciones/mi-suscripcion/');
            check('cancelled_plan_persists_after_restart', (await a.locator('.lm-checkout').innerText()).includes('Cancelación registrada'));
            await go(a, state.aReceipt);
            check('receipt_persists_after_restart', (await a.locator('.lm-result').innerText()) === 'Aprobada');
            await go(a, '/cuenta/biblioteca/');
            check('library_persists_after_restart', (await a.locator('.lm-social').innerText()).includes('Frankenstein'));
            await go(a, '/perfil/');
            check('social_post_persists_after_restart', (await a.locator('.lm-social').innerText()).includes('responsabilidad científica'));
            const b = await reader();
            await login(b, 'marcos-demo');
            check('vip_quota_persists_after_restart', (await quota(b)).es_ilimitado === true);
        } else {
            await go(a, '/chat/');
            await a.locator('#chat-input').fill('Hola');
            await a.locator('#send-btn').click();
            await a.waitForFunction(() => !document.querySelector('#send-btn').disabled && document.querySelectorAll('#chat-body-page .chat-message.bot').length > 1);
            const before = await quota(a);
            check('free_chat_consumption_recorded', before.usadas === 1);
            await go(a, '/suscripciones/planes/');
            await capture(a, 'p01-planes');
            check('plan_buttons_enabled', await a.getByRole('link', { name: 'Contratar plan', exact: true }).count() === 2);
            const pro = await checkout(a, 'pro', 'debit', 'approved', true);
            const after = await quota(a);
            check('pro_backend_quota_100_consumption_kept', after.limite === 100 && after.usadas === before.usadas);
            await go(a, '/suscripciones/mi-suscripcion/');
            await capture(a, 'p07-mi-suscripcion');
            check('pro_active_in_private_area', (await a.locator('.lm-checkout').innerText()).includes('Lector Pro'));
            const confirmationStatus = await a.evaluate(async route => {
                const csrf = document.cookie.split('; ').find(v => v.startsWith('csrftoken='))?.split('=')[1];
                return (await fetch(route + 'confirmar/', { method: 'POST', headers: { 'X-CSRFToken': csrf } })).status;
            }, pro.order);
            check('duplicate_confirmation_returns_existing_receipt', confirmationStatus === 200);
            await checkout(a, 'pro', 'transfer', 'approved', false, true);
            check('transfer_renews_pro', (await quota(a)).limite === 100);
            await checkout(a, 'vip', 'credit', 'rejected');
            check('rejected_upgrade_preserves_pro', (await quota(a)).limite === 100);
            const upgraded = await checkout(a, 'vip', 'credit', 'temporary');
            check('temporary_retry_activates_vip_once', (await quota(a)).es_ilimitado === true);
            await go(a, '/suscripciones/simulada/cancelar/');
            await a.locator('[name=confirm]').check();
            await capture(a, 'p08-cancelacion');
            await a.getByRole('button', { name: 'Confirmar cancelación' }).click();
            await a.waitForURL('**/suscripciones/mi-suscripcion/');
            check('cancellation_preserves_paid_access', (await quota(a)).es_ilimitado === true);

            const b = await reader();
            await login(b, 'marcos-demo');
            const vip = await checkout(b, 'vip', 'credit');
            check('free_to_vip_effective', (await quota(b)).es_ilimitado === true);
            await go(b, '/suscripciones/mi-suscripcion/');
            const endText = await b.locator('.lm-order-summary').innerText();
            await go(b, vip.receipt);
            const until = await b.locator('[data-access-until]').getAttribute('datetime');
            const renewAt = new Date(new Date(until).getTime() + 2000).toISOString();
            await go(b, community.profile);
            const publicText = await b.locator('.lm-social').innerText();
            check('public_profile_hides_commercial_data', !/Mi suscripción|Comprobante|Historial de operaciones/.test(publicText));
            check('community_post_and_follow_survive_purchase', publicText.includes('responsabilidad científica') &&
                await b.getByRole('button', { name: 'Dejar de seguir', exact: true }).count() === 1);
            check('foreign_receipt_denied', await b.evaluate(async route => (await fetch(route)).status, pro.receipt) === 404);
            await b.setViewportSize({ width: 390, height: 844 });
            await go(b, '/suscripciones/checkout/pro/');
            check('mobile_summary_no_overflow', await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
            await capture(b, 'p11-checkout-movil');
            await b.getByRole('link', { name: 'Continuar', exact: true }).click();
            await b.locator('[name=method][value=transfer]').check();
            await b.getByRole('button', { name: 'Revisar confirmación' }).click();
            await b.waitForURL('**/suscripciones/pedido/*/');
            check('mobile_confirmation_no_overflow', await b.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
            await b.getByRole('button', { name: 'Cancelar pedido', exact: true }).click();
            await b.waitForURL('**/suscripciones/comprobante/*/');
            check('mobile_abandoned_order_cancelled', (await b.locator('.lm-result').innerText()) === 'Cancelada');
            fs.writeFileSync(stateFile, JSON.stringify({ aReceipt: upgraded.receipt, bReceipt: vip.receipt, renewAt }));
        }
    } catch (error) {
        errors.push(error.message.split('\n').slice(0, 4).join('\n'));
    } finally {
        const report = { passed: checks.length > 0 && checks.every(c => c.passed) && errors.length === 0,
            syntheticAccounts: true, publicProduction: false, checks, errors };
        fs.writeFileSync(output, JSON.stringify(report, null, 2));
        await browser.close();
        console.log(JSON.stringify({ passed: report.passed, checks: checks.length, errors }));
        if (!report.passed) process.exitCode = 1;
    }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
