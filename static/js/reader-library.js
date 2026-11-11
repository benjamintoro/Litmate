/* Controles personales: sólo endpoints propios, sin herramientas de escritura del LLM. */
(() => {
    'use strict';
    const authenticated = document.currentScript?.dataset.authenticated === 'true';
    const entries = new Map();
    const busy = new Set();
    const queued = new Set();
    let timer = null;
    const cookie = name => document.cookie.split('; ').find(row => row.startsWith(name + '='))?.split('=').slice(1).join('=') || '';
    function notice(text) {
        let live = document.getElementById('reader-library-notice');
        if (!live) {
            live = document.createElement('div'); live.id = 'reader-library-notice';
            live.className = 'container my-2'; live.setAttribute('role', 'status');
            live.setAttribute('aria-live', 'polite'); document.body.appendChild(live);
        }
        live.textContent = text;
        if (window.showToast) window.showToast(text, 'info');
    }
    async function api(path, data) {
        const response = await fetch(path, data === undefined ? {cache: 'no-store'} : {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken')},
            body: JSON.stringify(data)
        });
        const body = await response.json();
        if (!response.ok) throw new Error(body.msg || 'No pudimos actualizar tu biblioteca. Vuelve a iniciar sesión si ha caducado.');
        return body;
    }
    function paint(id) {
        const entry = entries.get(id);
        for (const {button, detail} of entry.controls) {
            const saved = Number.isInteger(entry.favorite_id);
            button.disabled = busy.has(id);
            button.setAttribute('aria-pressed', String(saved));
            button.title = saved ? 'Quitar de favoritos' : 'Guardar en favoritos';
            button.setAttribute('aria-label', button.title + ': ' + entry.book.titulo);
            button.classList.toggle('btn-danger', saved);
            button.classList.toggle('btn-outline-danger', !saved);
            const label = button.querySelector('[data-favorite-label]');
            if (label) {
                label.textContent = saved ? 'Quitar de favoritos' : 'Guardar en favoritos';
                button.querySelector('[aria-hidden]').textContent = saved ? '♥' : '♡';
            }
            if (detail) detail.hidden = !saved;
        }
    }
    async function toggle(id) {
        if (!authenticated) { location.href = '/login/'; return; }
        if (busy.has(id)) return;
        const entry = entries.get(id);
        entry.version += 1;
        busy.add(id); paint(id);
        try {
            if (Number.isInteger(entry.favorite_id)) {
                await api('/favoritos/eliminar/' + entry.favorite_id + '/', {});
                entry.favorite_id = null;
                notice('Libro quitado de favoritos.');
            } else {
                const result = await api('/favoritos/agregar/', entry.book);
                entry.favorite_id = result.id;
                notice(result.msg || 'Libro guardado en favoritos.');
            }
        } catch (error) { notice(error.message); }
        finally { busy.delete(id); paint(id); }
    }
    async function flush() {
        timer = null;
        const ids = [...queued].slice(0, 50);
        ids.forEach(id => queued.delete(id));
        if (!ids.length || !authenticated) return;
        const versions = new Map(ids.map(id => [id, entries.get(id).version]));
        try {
            const data = await api('/api/biblioteca/estado/?' + ids.map(id => 'id=' + encodeURIComponent(id)).join('&'));
            for (const id of ids) {
                if (busy.has(id) || entries.get(id).version !== versions.get(id)) continue;
                entries.get(id).favorite_id = data.books[id]?.favorite_id ?? null;
                paint(id);
            }
        } catch (_) { notice('No pudimos consultar el estado de tus favoritos. Puedes volver a intentarlo.'); }
        if (queued.size) timer = setTimeout(flush, 50);
    }
    function attach(button, book, detail = null) {
        if (!book.google_id || book.google_id.length > 100 || button.dataset.libraryReady) return;
        button.dataset.libraryReady = 'true';
        let entry = entries.get(book.google_id);
        if (!entry) { entry = {book, favorite_id: null, controls: [], version: 0}; entries.set(book.google_id, entry); }
        entry.controls.push({button, detail});
        button.addEventListener('click', event => { event.preventDefault(); void toggle(book.google_id); });
        paint(book.google_id);
        queued.add(book.google_id);
        if (timer === null && authenticated) timer = setTimeout(flush, 25);
    }
    window.LitmateLibrary = {
        decorate(card, book) {
            if (!book.id || card.querySelector('[data-library-ready]')) return;
            const tools = document.createElement('div'); tools.className = 'lm-chat-book-links';
            const button = document.createElement('button'); button.type = 'button';
            button.className = 'btn btn-sm btn-outline-danger'; button.textContent = '♥';
            const detail = document.createElement('a'); detail.textContent = 'Ver en mi biblioteca';
            detail.className = 'lm-chat-book-link';
            detail.href = '/cuenta/libro/?id=' + encodeURIComponent(book.id); detail.hidden = true;
            tools.append(button, detail); card.appendChild(tools);
            attach(button, {google_id: book.id, titulo: book.title, autores: book.author, imagen_url: book.image_url || ''}, detail);
        }
    };
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.btn-fav').forEach(button => attach(button, {
            google_id: button.dataset.googleId || '', titulo: button.dataset.titulo || '',
            autores: button.dataset.autores || '', imagen_url: button.dataset.imagen || ''
        }));
    });
})();
