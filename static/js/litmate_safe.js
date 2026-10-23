/* Shared browser rendering and transport. API content is always data. */
(function (root, factory) {
    const api = factory();
    if (typeof module === 'object' && module.exports) module.exports = api;
    else root.LitMateSafe = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
    'use strict';

    function escapeHTML(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[char]));
    }

    function safeURL(value, options = {}) {
        if (typeof value !== 'string' || !value || value.length > 2048 || /[<>"'`\\\x00-\x20]/.test(value)) return '';
        try {
            const base = options.base || (typeof location !== 'undefined' ? location.href : 'https://litmate.invalid/');
            const url = new URL(value, base);
            const origin = new URL(base).origin;
            if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return '';
            if (options.sameOrigin && url.origin !== origin) return '';
            if (options.image && url.protocol === 'http:' && url.origin !== origin) url.protocol = 'https:';
            return url.href;
        } catch (error) { return ''; }
    }

    function formatInlineText(text) {
        const value = String(text ?? '');
        const escapedText = fragment => escapeHTML(fragment).replace(/\*\*([^*\n]{1,500})\*\*/g, '<strong>$1</strong>');
        let output = '', previous = 0;
        for (const match of value.matchAll(/https?:\/\/[^\s]+/gi)) {
            output += escapedText(value.slice(previous, match.index));
            let candidate = match[0].replace(/[,.!?;]+$/, '');
            while (candidate.endsWith(')') && (candidate.match(/\)/g) || []).length > (candidate.match(/\(/g) || []).length) candidate = candidate.slice(0, -1);
            const url = safeURL(candidate);
            output += url
                ? '<a href="' + escapeHTML(url) + '" target="_blank" rel="noopener noreferrer">' + escapeHTML(candidate) + '</a>' + escapeHTML(match[0].slice(candidate.length))
                : escapeHTML(match[0]);
            previous = match.index + match[0].length;
        }
        return output + escapedText(value.slice(previous));
    }

    function formatMessageText(text) {
        const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n');
        let output = '', list = '';
        for (const line of lines) {
            const item = line.match(/^\s*(?:([-*•])|\d+[.)])\s+(.+)$/);
            const nextList = item ? (item[1] ? 'ul' : 'ol') : '';
            if (list && list !== nextList) { output += '</' + list + '>'; list = ''; }
            if (nextList) {
                if (!list) {
                    const number = nextList === 'ol' ? Number.parseInt(line.trim(), 10) : 1;
                    const start = Number.isSafeInteger(number) && number > 1 && number <= 100 ? ' start="' + number + '"' : '';
                    output += '<' + nextList + ' class="lm-chat-list"' + start + '>';
                    list = nextList;
                }
                output += '<li>' + formatInlineText(item[2]) + '</li>';
            } else {
                output += formatInlineText(line) + '<br>';
            }
        }
        if (list) output += '</' + list + '>';
        return output.endsWith('<br>') ? output.slice(0, -4) : output;
    }

    function element(tag, className = '', text = null) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== null) node.textContent = String(text ?? '');
        return node;
    }

    function renderMessage(node, text) {
        // Only the formatter above may create this fixed, escaped HTML structure.
        node.innerHTML = formatMessageText(text);
    }

    function getCookie(name, value = typeof document !== 'undefined' ? document.cookie : '') {
        for (const part of String(value || '').split(';')) {
            const cookie = part.trim();
            if (cookie.startsWith(name + '=')) {
                try { return decodeURIComponent(cookie.slice(name.length + 1)); }
                catch (error) { return ''; }
            }
        }
        return '';
    }

    async function readChatProblem(response) {
        let message = ({ 403: 'La sesión necesita actualizarse. Recarga la página y vuelve a intentar.',
            429: 'Has enviado demasiadas solicitudes. Espera y vuelve a intentar.',
            503: 'El asistente está ocupado o no está disponible. Vuelve a intentar en unos instantes.' })[response.status]
            || 'No pude completar la solicitud. Inténtalo nuevamente.';
        if ((response.headers.get('content-type') || '').includes('application/json')) {
            try {
                const data = await response.json();
                if (typeof data.response === 'string' && data.response.trim()) message = data.response;
                else if (typeof data.error === 'string' && /\s/.test(data.error) && data.error.length <= 1000) message = data.error;
            } catch (error) { /* Keep the useful HTTP fallback. */ }
        }
        return message;
    }

    async function readChatResponse(response, onText = () => {}, onMetadata = () => {}) {
        if (!response.ok) throw new Error(await readChatProblem(response));
        const mime = response.headers.get('content-type') || '';
        if (mime.includes('application/json')) {
            let data;
            try { data = await response.json(); } catch (error) { throw new Error('La respuesta del asistente llegó dañada. Vuelve a intentar.'); }
            if (!data || typeof data.response !== 'string' || !data.response.trim()) throw new Error('El asistente no envió una respuesta. Vuelve a intentar.');
            if (data.response.length > 64000) throw new Error('La respuesta es demasiado extensa. Prueba con una pregunta más concreta.');
            onText(data.response);
            const metadata = normalizeMetadata(data);
            if (Object.keys(metadata).length) onMetadata(metadata);
            return data.response;
        }
        if (!mime.includes('text/event-stream') || !response.body) throw new Error('El asistente envió una respuesta inesperada. Vuelve a intentar.');
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '', text = '', completed = false;
        function event(block) {
            const data = block.split(/\r?\n/).filter(line => line.startsWith('data:'))
                .map(line => line.slice(5).replace(/^ /, '')).join('\n').trim();
            if (!data) return;
            if (data === '[DONE]') { completed = true; return; }
            let parsed;
            try { parsed = JSON.parse(data); } catch (error) { throw new Error('La respuesta del asistente llegó dañada. Vuelve a intentar.'); }
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('La respuesta del asistente llegó dañada. Vuelve a intentar.');
            if (parsed.error) throw new Error(typeof parsed.response === 'string' ? parsed.response : 'El asistente no pudo completar la respuesta.');
            if (typeof parsed.token === 'string') {
                text += parsed.token;
                if (text.length > 64000) throw new Error('La respuesta es demasiado extensa. Prueba con una pregunta más concreta.');
                onText(text);
            }
            const metadata = normalizeMetadata(parsed);
            if (Object.keys(metadata).length) onMetadata(metadata);
        }
        function flush(final = false) {
            const blocks = buffer.split(/\r?\n\r?\n/);
            buffer = blocks.pop();
            for (const block of blocks) { event(block); if (completed) return; }
            if (final && buffer.trim() && !completed) { event(buffer); buffer = ''; }
        }
        try {
            while (!completed) {
                const chunk = await reader.read();
                buffer += decoder.decode(chunk.value, { stream: !chunk.done });
                if (buffer.length > 131072) throw new Error('La respuesta del asistente es demasiado extensa. Vuelve a intentar.');
                flush(chunk.done);
                if (chunk.done) break;
            }
            if (!completed) throw new Error('La conexión se interrumpió antes de completar la respuesta. Vuelve a intentar.');
            if (!text.trim()) throw new Error('El asistente no envió una respuesta. Vuelve a intentar.');
            return text;
        } finally {
            if (typeof reader.cancel === 'function') { try { await reader.cancel(); } catch (error) {} }
            if (typeof reader.releaseLock === 'function') reader.releaseLock();
        }
    }

    async function queryChat(message, onText = () => {}, onMetadata = () => {}, options = {}) {
        const env = options.environment || (typeof window !== 'undefined' ? window : globalThis);
        const controller = new env.AbortController();
        const timeout = Math.max(1, Math.min(Number(options.timeout) || 30000, 30000));
        let expired = false, timer;
        const limit = new Promise((_, reject) => {
            timer = env.setTimeout(() => {
                expired = true;
                controller.abort();
                reject(new Error('Se alcanzó el límite de 30 segundos sin recibir una respuesta completa. Vuelve a intentarlo.'));
            }, timeout);
        });
        const transport = (async () => {
            const response = await env.fetch('/chatbot_query/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
                body: JSON.stringify({ message }), signal: controller.signal
            });
            return readChatResponse(response,
                text => { if (!expired) onText(text); },
                metadata => { if (!expired) onMetadata(metadata); });
        })();
        try { return await Promise.race([transport, limit]); }
        finally { env.clearTimeout(timer); }
    }

    function storeLink(value, label) {
        const url = safeURL(value);
        if (!url) return null;
        const parsed = new URL(url);
        if (parsed.protocol !== 'https:') return null;
        const host = parsed.hostname.toLowerCase();
        const providers = [
            { label: 'Google Books', hosts: ['books.google.com', 'books.google.cl', 'books.google.es', 'play.google.com',
                'books.google.com.ar', 'books.google.com.mx', 'books.google.co.uk'] },
            { label: 'Amazon', hosts: ['amazon.com', 'www.amazon.com', 'amazon.es', 'www.amazon.es'] },
            { label: 'Buscalibre', hosts: ['buscalibre.cl', 'www.buscalibre.cl', 'buscalibre.com', 'www.buscalibre.com'] }
        ];
        const provider = providers.find(item => item.hosts.includes(host));
        if (!provider || (label && String(label).toLowerCase() !== provider.label.toLowerCase())) return null;
        return { label: provider.label, url };
    }

    function coverURL(value) {
        const url = safeURL(value, { image: true });
        if (!url) return '';
        const host = new URL(url).hostname.toLowerCase();
        const hosts = ['books.google.com', 'books.google.cl', 'books.google.es', 'play.google.com',
            'books.google.com.ar', 'books.google.com.mx', 'books.google.co.uk',
            'books.googleusercontent.com', 'covers.openlibrary.org'];
        return hosts.includes(host) || host.endsWith('.googleusercontent.com') ? url : '';
    }

    function normalizeMetadata(value) {
        const metadata = {};
        if (Array.isArray(value.books)) metadata.books = normalizeBooks(value.books);
        if (['search', 'writing', 'review'].includes(value.stage)) {
            metadata.stage = value.stage;
            if (typeof value.message === 'string') metadata.message = value.message.trim().slice(0, 240);
        }
        if (typeof value.mood === 'string' && /^[a-z_]{1,24}$/i.test(value.mood)) metadata.mood = value.mood.toLowerCase();
        return metadata;
    }

    function normalizeBooks(values) {
        if (!Array.isArray(values)) return [];
        const books = [], seen = new Set();
        for (const value of values.slice(0, 12)) {
            if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
            const title = typeof value.title === 'string' ? value.title.trim().slice(0, 255) : '';
            const author = typeof value.author === 'string' ? value.author.trim().slice(0, 255) : '';
            if (!title || !author) continue;
            const identity = (title + '\0' + author).normalize('NFKC').toLowerCase();
            if (seen.has(identity)) continue;
            const links = [], linkLabels = new Set();
            for (const raw of (Array.isArray(value.links) ? value.links : []).slice(0, 12)) {
                const link = raw && typeof raw === 'object' ? storeLink(raw.url, raw.label) : null;
                if (link && !linkLabels.has(link.label)) { links.push(link); linkLabels.add(link.label); }
            }
            const rawSynopsis = typeof value.synopsis === 'string' ? value.synopsis.slice(0, 2000).replace(/<[^>]*>/g, '').replace(/\s+/g, ' ').trim() : '';
            books.push({ id: typeof value.id === 'string' ? value.id.slice(0, 100) : '', title, author,
                synopsis: rawSynopsis.length > 500 ? rawSynopsis.slice(0, 497).trimEnd() + '…' : rawSynopsis,
                image_url: coverURL(value.image_url), links });
            seen.add(identity);
            if (books.length >= 6) break;
        }
        return books;
    }

    function renderBookCards(container, values) {
        const books = normalizeBooks(values);
        if (!books.length) return null;
        const group = element('section', 'lm-chat-books');
        group.setAttribute('aria-label', 'Libros de esta respuesta');
        group.appendChild(element('div', 'lm-chat-books-heading', 'Para seguir leyendo'));
        const grid = element('div', 'lm-chat-books-grid');
        for (const book of books) {
            const card = element('article', 'lm-chat-book-card');
            const top = element('div', 'lm-chat-book-top');
            const cover = element('div', 'lm-chat-book-cover');
            const fallback = element('span', 'lm-chat-book-cover-fallback', 'Sin portada');
            if (book.image_url) {
                const image = element('img');
                image.src = book.image_url;
                image.alt = 'Portada de ' + book.title;
                image.loading = 'lazy';
                image.decoding = 'async';
                image.referrerPolicy = 'no-referrer';
                image.addEventListener('error', () => { image.hidden = true; fallback.hidden = false; });
                cover.appendChild(image);
                fallback.hidden = true;
            }
            cover.appendChild(fallback);
            const details = element('div', 'lm-chat-book-details');
            details.appendChild(element('h3', 'lm-chat-book-title', book.title));
            details.appendChild(element('div', 'lm-chat-book-author', book.author));
            top.appendChild(cover);
            top.appendChild(details);
            card.appendChild(top);
            if (book.synopsis) card.appendChild(element('div', 'lm-chat-book-synopsis', book.synopsis));
            if (book.links.length) {
                const links = element('div', 'lm-chat-book-links');
                for (const link of book.links) {
                    const anchor = element('a', 'lm-chat-book-link', link.label);
                    anchor.href = link.url;
                    anchor.target = '_blank';
                    anchor.rel = 'noopener noreferrer';
                    anchor.setAttribute('aria-label', 'Consultar ' + book.title + ' en ' + link.label);
                    links.appendChild(anchor);
                }
                card.appendChild(links);
            }
            grid.appendChild(card);
        }
        group.appendChild(grid);
        container.appendChild(group);
        return group;
    }

    function createTypewriter(node, options = {}) {
        const env = options.environment || (typeof window !== 'undefined' ? window : globalThis);
        const reduced = options.reducedMotion ?? (typeof env.matchMedia === 'function'
            ? env.matchMedia('(prefers-reduced-motion: reduce)').matches : true);
        const schedule = options.schedule || ((callback, delay) => env.setTimeout(callback, delay));
        const unschedule = options.unschedule || (timer => env.clearTimeout(timer));
        const now = options.now || (() => Date.now());
        let target = '', visible = '', timer = null, started = null, cancelled = false;
        const waiting = [];
        function paint() { renderMessage(node, visible); if (options.onPaint) options.onPaint(); }
        function resolve() { while (waiting.length) waiting.shift()(); }
        function skip() {
            if (timer !== null) unschedule(timer);
            timer = null;
            if (!cancelled) { visible = target; paint(); }
            resolve();
        }
        function tick() {
            timer = null;
            if (cancelled) { resolve(); return; }
            if (reduced || target.length > 10000 || env.document?.hidden || now() - started >= 2500) { skip(); return; }
            const remaining = target.length - visible.length;
            const step = Math.max(1, Math.min(32, Math.ceil(remaining / 10)));
            let end = Math.min(target.length, visible.length + step);
            // Keep UTF-16 surrogate pairs together during the reveal.
            if (end < target.length && /[\uD800-\uDBFF]/.test(target[end - 1])) end++;
            visible = target.slice(0, end);
            paint();
            if (visible.length < target.length) timer = schedule(tick, 40);
            else resolve();
        }
        function push(text) {
            if (cancelled) return;
            target = String(text ?? '').slice(0, 64000);
            if (started === null) started = now();
            if (reduced || target.length > 10000) { skip(); return; }
            if (timer === null && visible !== target) timer = schedule(tick, 40);
        }
        node.addEventListener('click', skip);
        return { push, skip,
            finish() {
                if (cancelled || visible === target) return Promise.resolve();
                return new Promise(resolveFinish => { waiting.push(resolveFinish); if (timer === null) timer = schedule(tick, 0); });
            },
            cancel() { cancelled = true; if (timer !== null) unschedule(timer); timer = null; resolve(); }
        };
    }

    function avatarForText(text, mood = '') {
        const names = { happy: 'feliz.png', feliz: 'feliz.png', grateful: 'agradecida.png', agradecida: 'agradecida.png',
            sad: 'triste.png', triste: 'triste.png', fear: 'miedo.png', miedo: 'miedo.png', angry: 'enojo.png', enojo: 'enojo.png',
            surprised: 'sorprendida.png', sorprendida: 'sorprendida.png', thinking: 'pensativa.png', neutral: 'cuerpo.jpg' };
        if (Object.hasOwn(names, mood)) return names[mood];
        const value = String(text ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
        if (/\b(gracias|agradecid[oa])\b/.test(value)) return 'agradecida.png';
        if (/\b(terror|miedo|horror|espeluznante)\b/.test(value)) return 'miedo.png';
        if (/\b(triste|tragedia|duelo|melancolia)\b/.test(value)) return 'triste.png';
        if (/\b(guerra|injusticia|ira|furia)\b/.test(value)) return 'enojo.png';
        if (/\b(fantasia|magia|maravilla|increible)\b/.test(value)) return 'sorprendida.png';
        return 'feliz.png';
    }

    function createChatAvatar(node, options = {}) {
        const env = options.environment || (typeof window !== 'undefined' ? window : globalThis);
        let timer = null, sequence = 0, current = 'cuerpo.jpg';
        function show(file, description = 'Asistente de LitMate') {
            sequence++;
            if (timer !== null) env.clearTimeout(timer);
            timer = null;
            current = file;
            if (node) { node.src = '/static/assets/img/avatar/' + encodeURIComponent(file) + '?v=chat-v4'; node.alt = description; }
        }
        return {
            stage(stage) { if (node) node.classList.remove('is-speaking'); show(stage === 'writing' ? 'feliz.png' : 'pensativa.png', stage === 'writing' ? 'LitMate está escribiendo' : 'LitMate está buscando y pensando'); },
            emotion(text, mood) { show(avatarForText(text, mood)); },
            error() { show('sin conexion.png', 'LitMate no pudo completar la respuesta'); },
            speaking(active) {
                if (active) { sequence++; if (timer !== null) env.clearTimeout(timer); timer = null; }
                if (node) { if (active) node.classList.add('is-speaking'); else node.classList.remove('is-speaking'); }
            },
            resetAfter(delay = 12000) {
                if (timer !== null) env.clearTimeout(timer);
                const expected = sequence;
                timer = env.setTimeout(() => { if (sequence === expected) show('cuerpo.jpg'); }, delay);
            },
            show(file) {
                const allowed = ['cuerpo.jpg', 'feliz.png', 'agradecida.png', 'triste.png', 'miedo.png', 'enojo.png', 'sorprendida.png', 'pensativa.png', 'sin conexion.png'];
                if (allowed.includes(file)) show(file);
            },
            get current() { return current; }
        };
    }

    function createChatVoice(options = {}) {
        const env = options.environment || (typeof window !== 'undefined' ? window : globalThis);
        let volume = normalizeVolume(options.volume ?? readPreference('litmate_miku_volume', '1'));
        let previous = volume > 0 ? volume : 1, generation = 0, audio = null, utterance = null, controller = null;
        let speaking = false, pending = false, speechText = '', boundary = 0;
        const notify = error => { if (options.onChange) options.onChange({ volume, speaking, pending, enabled: volume > 0, error: error || '' }); };
        function stop() {
            generation++;
            if (controller) { controller.abort(); controller = null; }
            if (audio) { try { audio.pause(); audio.src = ''; audio.load(); } catch (error) {} audio = null; }
            if (env.speechSynthesis) { try { env.speechSynthesis.cancel(); } catch (error) {} }
            utterance = null; speaking = false; pending = false;
            notify();
            if (options.onStop) options.onStop();
        }
        function started(expected) {
            if (expected !== generation || volume === 0) return;
            pending = false; speaking = true; notify();
            if (options.onStart) options.onStart();
        }
        function ended(expected, error = '') {
            if (expected !== generation) return;
            speaking = false; pending = false; audio = null; utterance = null; notify(error);
            if (options.onEnd) options.onEnd();
        }
        function browserSpeak(text, expected) {
            if (expected !== generation || !volume) return false;
            if (!env.speechSynthesis || !env.SpeechSynthesisUtterance) { ended(expected, 'Este navegador no dispone de lectura en voz alta.'); return false; }
            speechText = text; boundary = 0;
            const reading = new env.SpeechSynthesisUtterance(text);
            reading.lang = 'es-CL'; reading.volume = volume; reading.pitch = 1.2; reading.rate = 1.03;
            const voices = env.speechSynthesis.getVoices();
            const spanish = voices.filter(voice => /^es(?:-|$)/i.test(voice.lang));
            reading.voice = spanish.find(voice => voice.lang === 'es-CL') || spanish.find(voice => voice.localService) || spanish[0] || null;
            reading.onstart = () => started(expected);
            reading.onboundary = event => { if (expected === generation && Number.isInteger(event.charIndex)) boundary = event.charIndex; };
            reading.onend = () => ended(expected);
            reading.onerror = () => ended(expected, 'La lectura en voz alta se interrumpió.');
            utterance = reading;
            try { env.speechSynthesis.speak(reading); return true; }
            catch (error) { ended(expected, 'No pude iniciar la lectura en este navegador.'); return false; }
        }
        async function speak(text) {
            stop();
            if (!volume || !text) return false;
            const clean = Array.from(String(text).replace(/\[LIBRO:.*?\]/gi, '').replace(/<[^>]*>/g, '')
                .replace(/https?:\/\/\S+/gi, '').replace(/[*#_~`\[\]()<>]/g, '').replace(/\s+/g, ' ').trim()).slice(0, 3500).join('');
            if (!clean) return false;
            const expected = generation;
            if (!options.useServer || !env.fetch || !env.Audio || !env.AbortController) return browserSpeak(clean, expected);
            let browserStarted = false;
            const fallback = () => {
                if (browserStarted) return false;
                browserStarted = true;
                return browserSpeak(clean, expected);
            };
            controller = new env.AbortController();
            const abort = controller;
            pending = true; notify();
            const timeout = env.setTimeout(() => abort.abort(), 6000);
            try {
                const response = await env.fetch('/api/miku-tts/', { method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken', env.document?.cookie) },
                    body: JSON.stringify({ text: clean }), signal: abort.signal });
                if (!response.ok) throw new Error('server_voice_unavailable');
                const data = await response.json();
                const url = safeURL(data.audio_url, { sameOrigin: true, base: env.location?.href });
                if (!url) throw new Error('invalid_audio_url');
                if (expected !== generation || !volume) return false;
                const player = new env.Audio(url);
                audio = player; player.volume = volume;
                player.onplay = () => { if (audio === player) started(expected); };
                player.onended = () => { if (audio === player) ended(expected); };
                player.onerror = () => { if (expected === generation && audio === player) { audio = null; player.pause(); fallback(); } };
                await player.play();
                return true;
            } catch (error) {
                if (expected !== generation || !volume) return false;
                if (audio) { try { audio.pause(); } catch (ignored) {} audio = null; }
                return fallback();
            } finally {
                env.clearTimeout(timeout);
                if (controller === abort) controller = null;
            }
        }
        function setVolume(value) {
            const remaining = utterance && speaking ? speechText.slice(boundary) : '';
            volume = normalizeVolume(value);
            if (volume > 0) previous = volume;
            savePreference('litmate_miku_volume', volume);
            if (!volume) stop();
            else if (audio) audio.volume = volume;
            else if (remaining) { stop(); browserSpeak(remaining, generation); }
            else if (utterance) utterance.volume = volume;
            notify();
        }
        notify();
        return { speak, stop, setVolume, toggle() { setVolume(volume > 0 ? 0 : previous); },
            get volume() { return volume; }, get speaking() { return speaking; } };
    }

    function normalizeVolume(value) {
        const parsed = Number.parseFloat(value);
        return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed)) : 1;
    }

    function readPreference(key, fallback = '') {
        try { return localStorage.getItem(key) ?? fallback; } catch (error) { return fallback; }
    }

    function savePreference(key, value) {
        try { localStorage.setItem(key, String(value)); } catch (error) { /* Private browsing may disable storage. */ }
    }

    return { escapeHTML, safeURL, element, formatMessageText, renderMessage, getCookie,
        readChatProblem, readChatResponse, queryChat, normalizeBooks, renderBookCards,
        createTypewriter, avatarForText, createChatAvatar, createChatVoice,
        normalizeVolume, readPreference, savePreference };
});
