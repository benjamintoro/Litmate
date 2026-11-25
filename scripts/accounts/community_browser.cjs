const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(path.join(process.env.USERPROFILE,
    '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const [origin, output, reportFile, catalogueId, mode] = process.argv.slice(2);
const root = process.cwd();
const checks = [];
const errors = [];
const password = 'Synthetic-Community-64-Only!';
const statePath = path.join(output, 'browser_state.json');

(async () => {
    const browser = await chromium.launch({
        executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        args: ['--host-resolver-rules=MAP litmate.example.test 127.0.0.1', '--no-proxy-server']
    });
    const contexts = [];
    const reader = async () => {
        const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1366, height: 1000 } });
        contexts.push(context);
        const page = await context.newPage();
        page.on('pageerror', error => errors.push(error.message));
        return page;
    };
    const go = async (page, route) => {
        const response = await page.goto(origin + route, { waitUntil: 'domcontentloaded' });
        if (!response.ok()) throw Error(route + ': HTTP ' + response.status());
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
    const status = async (page, route) => page.evaluate(async route =>
        (await fetch(route, { cache: 'no-store' })).status, route);
    const capture = async (page, name) => {
        await page.screenshot({ path: path.join(output, name + '.png'), fullPage: true, animations: 'disabled' });
    };
    const submit = async (page, form, expectedPath) => {
        await Promise.all([
            page.waitForURL(url => url.pathname === expectedPath, { timeout: 15000 }),
            form.locator('button').last().click()
        ]);
    };
    const register = async (page, username) => {
        await go(page, '/registro/');
        const form = page.locator('#registerForm');
        await form.locator('[name=username]').fill(username);
        await form.locator('[name=email]').fill(username + '@example.invalid');
        await form.locator('[name=password]').fill(password);
        await form.locator('[name=password_confirm]').fill(password);
        await submit(page, form, '/suscripciones/planes/');
        const free = page.locator('form[action="/cuenta/activar-gratis/"]');
        await Promise.all([
            page.waitForURL(url => url.pathname === '/chat/'),
            free.locator('button').click()
        ]);
    };
    const login = async (page, username) => {
        await go(page, '/login/');
        const form = page.locator('#loginForm');
        await form.locator('[name=username_or_email]').fill(username);
        await form.locator('[name=password]').fill(password);
        await form.locator('button[type=submit]').click();
        await page.waitForURL(url => url.pathname !== '/login/');
    };
    const edit = async (page, alias, name, images) => {
        await go(page, '/cuenta/perfil-literario/');
        await page.locator('[name=display_name]').fill(name);
        await page.locator('[name=alias]').fill(alias);
        await page.locator('[name=biography]').fill('Leo para encontrar otras formas de mirar el mundo. Me gusta conversar sobre personajes y descubrimientos literarios.');
        await page.locator('[name=genres]').fill('Ciencia ficción · Clásicos · Fantasía');
        await page.locator('[name=favorite_author]').fill('Mary Shelley');
        await page.locator('[name=favorite_book]').fill('Frankenstein');
        await page.locator('[name=annual_goal]').fill('24');
        await page.locator('[name=published]').check();
        if (images) {
            await page.locator('[name=photo]').setInputFiles(path.join(process.env.LITMATE_COMMUNITY_TEST_IMAGES, 'avatar.jpg'));
            await page.locator('[name=cover]').setInputFiles(path.join(process.env.LITMATE_COMMUNITY_TEST_IMAGES, 'cover.jpg'));
            await page.locator('[name=share_avatar]').check();
            await page.locator('[name=share_cover]').check();
            await page.locator('[name=share_stats]').check();
            await capture(page, '02-edicion');
        }
        await submit(page, page.locator('[data-profile-form]'), '/perfil/');
    };
    const create = async (page, body, visibility, attach = false) => {
        await go(page, '/cuenta/publicaciones/nueva/');
        if (attach) {
            await page.locator('#book-search').fill('Frankenstein');
            await page.locator('#book-search').press('Enter');
            await page.waitForURL('**/*q=Frankenstein');
            await page.locator('[data-choose-book="' + catalogueId + '"]').click();
            check('catalogue_selected_from_existing_book', await page.locator('[name=catalogue_id]').inputValue() === catalogueId);
        }
        await page.locator('[name=body]').fill(body);
        await page.locator('[name=visibility]').selectOption(visibility);
        await page.locator('[data-submit-once] button').click();
        await page.waitForURL('**/comunidad/publicacion/*/');
        return new URL(page.url()).pathname;
    };
    const postApi = async (page, route, values) => page.evaluate(async ({ route, values }) => {
        const token = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
            document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1];
        const response = await fetch(route, { method: 'POST', headers: {
            'X-CSRFToken': token, 'Content-Type': 'application/json'
        }, body: JSON.stringify(values) });
        return { status: response.status, text: await response.text() };
    }, { route, values });

    try {
        const a = await reader();
        if (mode === 'restart') {
            const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
            await login(a, 'elena-demo');
            await go(a, '/perfil/');
            check('profile_persisted_after_restart', (await a.locator('.lm-social').innerText()).includes('Elena Ríos'));
            await go(a, state.publicPost);
            check('post_persisted_after_restart', (await a.locator('.lm-post').innerText()).includes('responsabilidad científica'));
            await go(a, '/cuenta/biblioteca/');
            check('library_persisted_after_restart', (await a.locator('.lm-social').innerText()).includes('Terminado'));
            await go(a, state.profile);
            await a.waitForFunction(() => {
                const image = document.querySelector('.lm-profile-cover img');
                return image && image.complete && image.naturalWidth > 0;
            });
            check('images_persisted_after_restart', true);
        } else {
            await register(a, 'elena-demo');
            await edit(a, 'elena-lee', 'Elena Ríos', true);
            check('profile_saved', (await a.locator('h1').innerText()) === 'Elena Ríos');
            const profile = await a.getByRole('link', { name: 'Ver perfil público', exact: true }).getAttribute('href');
            const publicPost = await create(a,
                'Acabo de terminar Frankenstein y me impresionó la forma en que aborda la responsabilidad científica. ¿Hasta dónde llega la responsabilidad de quien crea algo nuevo?',
                'public', true);
            check('post_created_with_book', (await a.locator('.lm-post').innerText()).includes('Mary Shelley'));
            await capture(a, '03-publicacion');
            const privatePost = await create(a, 'MI DIARIO PRIVADO. Esta reflexión queda solo para mí.', 'private');
            await go(a, '/perfil/');
            await capture(a, '01-mi-perfil');

            const b = await reader();
            await register(b, 'marcos-demo');
            await edit(b, 'marcos-lector', 'Marcos lector', false);
            await go(b, profile);
            check('public_profile_private_post_hidden', !(await b.locator('.lm-social').innerText()).includes('MI DIARIO PRIVADO'));
            check('public_profile_owner_controls_hidden', !(await b.locator('.lm-social').innerText()).includes('Editar perfil'));
            await b.getByRole('button', { name: 'Seguir', exact: true }).click();
            await b.getByRole('button', { name: 'Dejar de seguir', exact: true }).waitFor();
            check('following_worked', true);
            await capture(b, '04-perfil-visitado');
            await go(b, publicPost);
            await b.getByRole('button', { name: 'Me gusta', exact: true }).click();
            await b.getByRole('button', { name: 'Quitar Me gusta', exact: true }).waitFor();
            check('like_worked', true);
            await b.locator('[name=body]').fill('Me interesa esa tensión entre el deseo de conocer y el cuidado de los demás.');
            await b.getByRole('button', { name: 'Comentar', exact: true }).click();
            await b.getByText('Me interesa esa tensión', { exact: false }).waitFor();
            check('comment_worked', true);
            await capture(b, '05-comentario');
            check('private_post_denied', await status(b, privatePost) === 404);
            check('foreign_edit_denied', await status(b, publicPost.replace('/comunidad/publicacion/', '/cuenta/publicaciones/') + 'editar/') === 404);

            await go(a, '/perfil/');
            const bookData = { google_id: 'community-frankenstein', titulo: 'Frankenstein', autores: 'Mary Shelley' };
            check('favorite_existing_endpoint', (await postApi(a, '/favoritos/agregar/', bookData)).status === 200);
            check('reading_existing_endpoint', (await postApi(a, '/api/estado-lectura/', { ...bookData, estado: 'leyendo' })).status === 200);
            await go(a, '/cuenta/biblioteca/');
            const stateForm = a.locator('#lm-leyendo form[action="/api/estado-lectura/"]');
            await stateForm.locator('select').selectOption('completado');
            await stateForm.getByRole('button', { name: 'Guardar estado' }).click();
            await a.locator('#lm-completado .lm-book').waitFor();
            check('reading_state_changed_by_visible_form', true);
            await capture(a, '06-biblioteca');
            await go(b, profile + '?seccion=biblioteca');
            check('library_private_by_default', await b.locator('.lm-book').count() === 0);
            const sharing = a.locator('#lm-completado details');
            await sharing.locator('summary').click();
            await sharing.locator('[name=confirm]').check();
            await sharing.getByRole('button', { name: 'Compartir en mi perfil' }).click();
            check('confirmed_reading_share', true);
            await go(b, profile + '?seccion=biblioteca');
            check('shared_book_visible_to_other_reader', (await b.locator('.lm-social').innerText()).includes('Frankenstein'));

            await go(b, profile);
            await b.locator('.lm-tabs a').first().focus();
            await b.keyboard.press('Tab');
            check('profile_tabs_keyboard_accessible', await b.evaluate(() => Boolean(document.activeElement.closest('.lm-tabs'))));
            for (const width of [320, 390, 768, 1366]) {
                await b.setViewportSize({ width, height: 950 });
                await b.waitForTimeout(180);
                const layout = await b.evaluate(() => ({
                    viewport: innerWidth, scrollWidth: document.documentElement.scrollWidth,
                    offenders: Array.from(document.querySelectorAll('body *')).filter(el => {
                        const box = el.getBoundingClientRect();
                        return box.width && box.right > innerWidth + 1;
                    }).slice(0, 12).map(el => ({ tag: el.tagName, class: el.className, right: el.getBoundingClientRect().right }))
                }));
                checks.push({ case: 'responsive_width_' + width, passed: layout.scrollWidth <= width + 1, layout });
                if (width === 390) await capture(b, '07-perfil-movil');
            }
            await go(b, '/comunidad/');
            check('feed_lists_public_post', (await b.locator('.lm-social').innerText()).includes('responsabilidad científica'));
            check('feed_hides_private_post', !(await b.locator('.lm-social').innerText()).includes('MI DIARIO PRIVADO'));
            await capture(b, '08-comunidad');
            await go(a, '/cuenta/perfil-literario/');
            await a.locator('[name=published]').uncheck();
            await submit(a, a.locator('[data-profile-form]'), '/perfil/');
            check('profile_revoked_for_other_user', await status(b, profile) === 404);
            check('post_revoked_with_profile', await status(b, publicPost) === 404);
            await go(a, '/cuenta/perfil-literario/');
            await a.locator('[name=published]').check();
            await submit(a, a.locator('[data-profile-form]'), '/perfil/');
            fs.writeFileSync(statePath, JSON.stringify({ profile, publicPost, privatePost }));
        }
    } catch (error) {
        errors.push(error.message.split('\n').slice(0, 4).join('\n'));
    } finally {
        const report = { passed: checks.length > 0 && checks.every(c => c.passed) && errors.length === 0,
                         syntheticAccounts: true, realBrowser: 'Edge Chromium', publicProduction: false,
                         checks, errors };
        fs.writeFileSync(reportFile, JSON.stringify(report, null, 2));
        await browser.close();
        console.log(JSON.stringify({ passed: report.passed, checks: checks.length, errors }));
        if (!report.passed) process.exitCode = 1;
    }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
