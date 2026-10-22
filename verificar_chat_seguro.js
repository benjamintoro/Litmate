// node verificar_chat_seguro.js: regresiones sin navegador, npm, Django o red.
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const Safe = require('./static/js/litmate_safe.js');
let checks = 0;
function check(value, message) { assert(value, message); checks++; }

class MockNode {
    constructor(tag = 'div') {
        this.tagName = tag.toUpperCase(); this.children = []; this.handlers = {}; this.attributes = {};
        this.style = { setProperty(name, value) { this[name] = value; } };
        this.value = ''; this.disabled = false; this.textContent = ''; this.innerHTML = ''; this.className = '';
        this.classList = { add: (...names) => { this.className += ' ' + names.join(' '); }, remove() {}, replace() {} };
    }
    addEventListener(event, handler) { this.handlers[event] = handler; }
    appendChild(node) { this.children.push(node); return node; }
    setAttribute(name, value) { this.attributes[name] = String(value); }
    focus() {}
    querySelector() { return null; }
    querySelectorAll() { return []; }
}
function descendants(node) { return [node, ...node.children.flatMap(descendants)]; }
const CARD = { id: 'dune-id', title: 'Dune', author: 'Frank Herbert', synopsis: 'Una historia sobre poder, ecología y el desierto.',
    image_url: 'https://covers.openlibrary.org/b/id/123-M.jpg', links: [
        { label: 'Google Books', url: 'https://books.google.com/books?id=dune-id' },
        { label: 'Amazon', url: 'https://www.amazon.com/s?k=Dune+Frank+Herbert' },
        { label: 'Buscalibre', url: 'https://www.buscalibre.cl/libros/search?q=Dune+Frank+Herbert' }
    ] };

function clock() {
    let now = 0, nextId = 0;
    const tasks = new Map();
    return { now: () => now, schedule(callback, delay) { const id = ++nextId; tasks.set(id, { callback, time: now + delay }); return id; },
        clear(id) { tasks.delete(id); },
        next() {
            if (!tasks.size) return false;
            const [id, task] = [...tasks].sort((a, b) => a[1].time - b[1].time)[0];
            tasks.delete(id); now = task.time; task.callback(); return true;
        },
        get pending() { return tasks.size; }
    };
}

function voiceEnvironment(mode = 'browser') {
    const spoken = [], players = [], changes = [];
    let cancels = 0;
    const env = { setTimeout, clearTimeout, AbortController, document: { cookie: 'csrftoken=voice-token' },
        location: { href: 'https://litmate.example/chat/' },
        SpeechSynthesisUtterance: function (text) { this.text = text; },
        speechSynthesis: { getVoices: () => [{ lang: 'en-US' }, { lang: 'es-CL', localService: true }],
            cancel() { cancels++; }, speak(reading) { spoken.push(reading); reading.onstart(); } },
        fetch: async () => ({ ok: mode !== 'unavailable', json: async () => ({ audio_url: '/media/voice.mp3' }) })
    };
    env.Audio = class {
        constructor(url) { this.src = url; this.paused = false; players.push(this); }
        pause() { this.paused = true; }
        load() {}
        async play() { if (mode === 'audio-error') { this.onerror(); throw Error('audio failed'); } this.onplay(); }
    };
    return { env, spoken, players, changes, get cancels() { return cancels; } };
}

function streaming(chunks, mime = 'text/event-stream') {
    let index = 0;
    const state = { reads: 0, cancelled: false, released: false };
    const reader = {
        async read() { state.reads++; return index < chunks.length ? { value: chunks[index++], done: false } : { done: true }; },
        async cancel() { state.cancelled = true; },
        releaseLock() { state.released = true; }
    };
    return { response: { ok: true, status: 200, headers: { get: () => mime }, body: { getReader: () => reader } }, state };
}
const bytes = value => new TextEncoder().encode(value);

async function clientRequest(file, status = 200, books = []) {
    const isPage = file === 'chatbot.js';
    const formId = isPage ? 'chat-form' : 'floating-chat-form';
    const inputId = isPage ? 'chat-input' : 'floating-chat-input';
    const bodyId = isPage ? 'chat-body-page' : 'floating-chat-body';
    const sendId = isPage ? 'send-btn' : 'floating-send-btn';
    const nodes = Object.fromEntries([formId, inputId, bodyId, sendId, 'floating-chat-trigger', 'floating-chat-window', 'floating-chat-close',
        'tts-toggle-btn', 'tts-icon', 'tts-volume-slider', 'tts-volume-label', 'floating-tts-btn', 'floating-tts-icon', 'floating-header-avatar', 'main-avatar'].map(id => [id, new MockNode()]));
    let ready;
    const calls = [];
    const document = { cookie: 'csrftoken=token%20csrf',
        getElementById: id => nodes[id] || null, querySelector: selector => selector === '#chat-character-page img' ? nodes['main-avatar'] : null, querySelectorAll: () => [],
        createElement: tag => new MockNode(tag), addEventListener: (event, handler) => { if (event === 'DOMContentLoaded') ready = handler; }
    };
    const voice = voiceEnvironment('unavailable');
    const browser = { document, URL, TextDecoder, AbortController, setTimeout: () => 0, clearTimeout() {},
        console: { error() {}, warn() {} }, location: { href: 'https://litmate.example/chat/' },
        getComputedStyle: node => ({ display: node.style.display || 'none' }),
        fetch: async (url, options) => {
            calls.push({ url, options });
            if (url !== '/chatbot_query/') return { ok: false, status: 503, headers: { get: () => 'application/json' }, json: async () => ({ response: 'Voz no disponible' }) };
            return status === 200
                ? streaming([bytes('data: {"token":"Lectura & <segura>"}\n\ndata: ' + JSON.stringify({ token: '', books }) + '\n\ndata: [DONE]\n\n')]).response
                : { ok: false, status, headers: { get: () => 'application/json' }, json: async () => ({ response: 'La IA está ocupada. <script>alert(1)</script>' }) };
        }
    };
    browser.SpeechSynthesisUtterance = voice.env.SpeechSynthesisUtterance;
    browser.speechSynthesis = voice.env.speechSynthesis;
    browser.Audio = voice.env.Audio;
    browser.window = browser;
    vm.createContext(browser);
    vm.runInContext(fs.readFileSync(path.join(__dirname, 'static/js/litmate_safe.js'), 'utf8'), browser);
    vm.runInContext(fs.readFileSync(path.join(__dirname, 'static/js', file), 'utf8'), browser);
    ready();
    nodes[inputId].value = '<script>alert(1)</script> Libros';
    const event = { preventDefault() {}, stopPropagation() {} };
    const pending = nodes[formId].handlers.submit(event);
    check(nodes[bodyId].children[1].children[1].children[1].textContent === 'Buscando entre libros...', file + ': estado visible mientras espera');
    check(nodes[isPage ? 'main-avatar' : 'floating-header-avatar'].src.includes('pensativa.png'), file + ': avatar pensativo antes de recibir texto');
    nodes[inputId].value = 'Segundo envío';
    await nodes[formId].handlers.submit(event);
    await pending;
    await Promise.resolve();
    const chatCalls = calls.filter(call => call.url === '/chatbot_query/');
    check(chatCalls.length === 1, file + ': evita envíos concurrentes');
    check(chatCalls[0].options.method === 'POST' && chatCalls[0].options.headers['X-CSRFToken'] === 'token csrf', file + ': CSRF en petición real del cliente');
    check(JSON.parse(chatCalls[0].options.body).message.includes('Libros'), file + ': cuerpo JSON');
    check(nodes[sendId].disabled === false, file + ': restaura botón tras respuesta');
    const bot = nodes[bodyId].children[1].children[0];
    check(!bot.innerHTML.includes('<script>') && bot.innerHTML.includes(status === 200 ? '&lt;segura&gt;' : 'ocupada'), file + ': texto o error renderizado de forma segura');
    const avatar = nodes[isPage ? 'main-avatar' : 'floating-header-avatar'];
    check(avatar.src.includes(status === 200 ? 'feliz.png' : 'sin%20conexion.png'), file + ': avatar al responder o fallar');
    check(nodes[bodyId].children[1].children[1].hidden === true, file + ': oculta estado de búsqueda al terminar');
    if (status === 200) {
        check(voice.spoken.length === 1 && voice.spoken[0].lang === 'es-CL', file + ': lectura automática en español y respaldo del navegador');
        const oldCancels = voice.cancels;
        nodes[isPage ? 'tts-toggle-btn' : 'floating-tts-btn'].handlers.click(event);
        check(voice.cancels > oldCancels && nodes[isPage ? 'tts-icon' : 'floating-tts-icon'].className.includes('xmark'), file + ': silenciar cancela la lectura real');
    }
    const cards = descendants(nodes[bodyId]).filter(node => node.className === 'lm-chat-book-card');
    check(cards.length === (status === 200 ? books.length : 0), file + ': tarjetas junto a la respuesta terminada');
    if (cards.length) {
        const links = descendants(cards[0]).filter(node => node.tagName === 'A');
        check(links.length === 3 && links.every(node => node.rel === 'noopener noreferrer'), file + ': tres enlaces seguros');
        check(descendants(cards[0]).some(node => node.tagName === 'IMG' && node.src === CARD.image_url), file + ': portada de la ficha');
    }
    if (!isPage && cards.length) {
        nodes['floating-chat-close'].handlers.click(event);
        nodes['floating-chat-trigger'].handlers.click(event);
        check(descendants(nodes[bodyId]).filter(node => node.className === 'lm-chat-book-card').length === cards.length, file + ': conserva tarjetas al reabrir');
    }
}

async function main() {
    const attacks = [
        '<img src=x onerror=alert(1)>', '<script>alert(1)</script>',
        'https://example.org/" onclick="alert(1)', "https://example.org/'onmouseover='alert(1)",
        '[LIBRO: <iframe src=x>|Autor|$100]', 'javascript:alert(1)',
        'https://usuario:clave@example.org/', '&lt;img src=x onerror=alert(1)&gt;',
        'https://example.org/`onfocus=`alert(1)', 'data:text/html,<script>alert(1)</script>'
    ];
    for (const attack of attacks) {
        const html = Safe.formatMessageText(attack);
        check(!/<(?:script|img|iframe)\b/i.test(html), 'etiqueta activa');
        check(!/<a\b[^>]*\son(?:click|mouseover|error|focus)\s*=/i.test(html), 'atributo activo');
        check(!/href="(?:javascript:|data:|https?:\/\/usuario:clave)/i.test(html), 'enlace inseguro');
    }
    const legitimate = Safe.formatMessageText('Fuente: https://es.wikipedia.org/wiki/1984_(novela)\nGracias & buen día');
    check(legitimate.includes('rel="noopener noreferrer"'), 'protección de enlaces externos');
    check(legitimate.includes('href="https://es.wikipedia.org/wiki/1984_(novela)"'), 'URL con paréntesis');
    check(legitimate.includes('<br>') && legitimate.includes('&amp; buen día'), 'saltos y escapes');
    check(Safe.formatMessageText('<think>texto literal</think>').includes('&lt;think&gt;'), 'texto literal');
    const markdown = Safe.formatMessageText('**Para empezar**\n- **Dune**, de Frank Herbert\n- Crónicas marcianas\n\n1. Lee el inicio\n2. Comenta sus ideas');
    check(markdown.includes('<strong>Para empezar</strong>') && markdown.includes('<strong>Dune</strong>'), 'negrita de Markdown seguro');
    check(markdown.includes('<ul class="lm-chat-list">') && markdown.includes('<ol class="lm-chat-list">'), 'listas estructuradas');
    check(!Safe.formatMessageText('**<img src=x onerror=alert(1)>**\n- <script>malicioso</script>').includes('<img'), 'Markdown no interpreta etiquetas');
    check(Safe.safeURL('javascript:alert(1)') === '', 'URL de script');
    check(Safe.safeURL('https://external.example/audio.mp3', { sameOrigin: true }) === '', 'audio externo');
    check(Safe.safeURL('/media/tts_cache/safe.mp3', { sameOrigin: true, base: 'https://litmate.example/chat/' }) === 'https://litmate.example/media/tts_cache/safe.mp3', 'audio del propio sitio');
    check(Safe.normalizeVolume('Infinity') === 1 && Safe.normalizeVolume('bad') === 1, 'preferencia de volumen corrupta');
    check(Safe.normalizeVolume('3') === 1 && Safe.normalizeVolume('-2') === 0, 'rango de volumen');

    for (const status of [429, 503]) {
        const response = { ok: false, status, headers: { get: () => 'application/json' }, json: async () => ({ response: status === 429 ? 'Espera un minuto.' : 'La IA está ocupada.' }) };
        await assert.rejects(() => Safe.readChatResponse(response), new RegExp(status === 429 ? 'Espera' : 'ocupada')); checks++;
    }
    check((await Safe.readChatProblem({ status: 403, headers: { get: () => 'text/html' } })).includes('Recarga'), 'CSRF/sesión');
    check((await Safe.readChatProblem({ status: 503, headers: { get: () => 'application/json' }, json: async () => { throw Error('JSON inválido'); } })).includes('no está disponible'), 'HTTP sin cuerpo legible');
    check((await Safe.readChatProblem({ status: 503, headers: { get: () => 'application/json' }, json: async () => ({ error: 'La voz externa está desactivada en este servidor.' }) })).includes('voz externa'), 'mensaje humano de voz');
    check(!(await Safe.readChatProblem({ status: 429, headers: { get: () => 'application/json' }, json: async () => ({ error: 'quota_exceeded' }) })).includes('quota_exceeded'), 'códigos internos no son mensajes de usuario');
    check(await Safe.readChatResponse({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({ response: 'Respuesta JSON' }) }) === 'Respuesta JSON', 'respaldo JSON');
    await assert.rejects(() => Safe.readChatResponse({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({ response: '' }) }), /no envió/); checks++;
    await assert.rejects(() => Safe.readChatResponse({ ok: true, headers: { get: () => 'text/html' } }), /inesperada/); checks++;

    const unicode = bytes('data:{"token":"Hola, lectura ñ 📚"}\r\n\r\ndata: [DONE]\r\n\r\n');
    const unicodeStream = streaming(Array.from(unicode, value => new Uint8Array([value])));
    const updates = [];
    check(await Safe.readChatResponse(unicodeStream.response, text => updates.push(text)) === 'Hola, lectura ñ 📚', 'SSE CRLF y UTF-8 dividido');
    check(updates.length === 1 && unicodeStream.state.cancelled && unicodeStream.state.released, 'cierre del stream');
    const noFinalBlank = streaming([bytes('data: {"token":"Final"}\n\ndata: [DONE]')]);
    check(await Safe.readChatResponse(noFinalBlank.response) === 'Final', 'procesamiento del buffer final');
    const terminal = streaming([bytes('data: {"token":"Texto"}\n\ndata: [DONE]\n\ndata: {"token":"No publicar"}\n\n'), bytes('data: {"token":"Más"}\n\n')]);
    check(await Safe.readChatResponse(terminal.response) === 'Texto' && terminal.state.reads === 1, 'DONE termina toda la lectura');
    for (const [data, expected] of [
        ['data: [DONE]\n\n', /no envió/],
        ['data: {"token":"Parcial"}\n\n', /interrumpió/],
        ['data: {roto}\n\n', /dañada/],
        ['data: null\n\n', /dañada/],
        ['data: {"error":"failed","response":"Servicio ocupado"}\n\n', /Servicio ocupado/]
    ]) {
        await assert.rejects(() => Safe.readChatResponse(streaming([bytes(data)]).response), expected); checks++;
    }
    const metadata = streaming([bytes(': ping\n\ndata: {"sources":[]}\n\ndata: {"token":"Sí"}\n\ndata: [DONE]\n\n')]);
    check(await Safe.readChatResponse(metadata.response) === 'Sí', 'comentarios/metadatos');
    const cardsMetadata = [];
    const cardsStream = streaming([bytes('data: {"token":"Dune"}\n\ndata: ' + JSON.stringify({ token: '', books: [CARD] }) + '\n\ndata: [DONE]\n\n')]);
    check(await Safe.readChatResponse(cardsStream.response, () => {}, event => cardsMetadata.push(event)) === 'Dune', 'metadatos no alteran texto SSE');
    check(cardsMetadata.length === 1 && cardsMetadata[0].books[0].links.length === 3, 'callback de libros en frame vacío');
    let jsonCards;
    await Safe.readChatResponse({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({ response: 'Dune', books: [CARD] }) }, () => {}, event => { jsonCards = event.books; });
    check(jsonCards.length === 1 && jsonCards[0].title === 'Dune', 'metadatos en respaldo JSON');
    check(Safe.normalizeBooks([CARD, { ...CARD, id: 'otra-edicion' }]).length === 1, 'tarjetas duplicadas por obra y autor');
    const dangerousCard = { ...CARD, title: '<img src=x onerror=alert(1)>', author: '<script>autor</script>',
        image_url: 'javascript:alert(1)', synopsis: '<b>Sinopsis</b>', links: [
            { label: 'Amazon', url: 'https://amazon.com.evil.example/' },
            { label: 'Buscalibre', url: 'javascript:alert(1)' },
            { label: 'Amazon', url: 'https://www.buscalibre.cl/' },
            { label: 'Google Books', url: 'http://books.google.com/books?id=x' }
        ] };
    const cleanedCard = Safe.normalizeBooks([dangerousCard])[0];
    check(cleanedCard.image_url === '' && cleanedCard.links.length === 0 && cleanedCard.synopsis === 'Sinopsis', 'URLs de tarjetas y texto de sinopsis validados');
    global.document = { createElement: tag => new MockNode(tag) };
    const host = new MockNode();
    Safe.renderBookCards(host, [dangerousCard, CARD]);
    const rendered = descendants(host);
    check(rendered.some(node => node.textContent === dangerousCard.title) && rendered.every(node => !node.innerHTML.includes('<img')), 'títulos y autores son textContent');
    const cover = rendered.find(node => node.tagName === 'IMG');
    cover.handlers.error();
    check(cover.hidden === true && rendered.some(node => node.className === 'lm-chat-book-cover-fallback' && node.hidden === false), 'portada fallida muestra alternativa');
    check(Safe.renderBookCards(new MockNode(), []) === null, 'sin libros no inventa tarjetas');
    check(Safe.normalizeBooks([{ ...CARD, image_url: 'https://127.0.0.1/private.jpg' }])[0].image_url === '', 'portada no solicita IP privada');
    check(Safe.normalizeBooks([{ ...CARD, image_url: 'https://unknown.example/cover.jpg' }])[0].image_url === '', 'portada sólo de proveedores permitidos');
    check(Safe.normalizeBooks([{ ...CARD, links: [{ label: 'Google Books', url: 'https://play.google.com/store/books/details?id=x' }] }])[0].links.length === 1, 'enlace Google Play Books');
    const noSynopsisHost = new MockNode();
    Safe.renderBookCards(noSynopsisHost, [{ ...CARD, synopsis: '' }]);
    check(!descendants(noSynopsisHost).some(node => node.className === 'lm-chat-book-synopsis'), 'no inventa copy de sinopsis ausente');
    delete global.document;

    const typeClock = clock(), textNode = new MockNode();
    let paints = 0;
    const writer = Safe.createTypewriter(textNode, { reducedMotion: false, environment: { document: { hidden: false } },
        schedule: typeClock.schedule, unschedule: typeClock.clear, now: typeClock.now, onPaint: () => { paints++; } });
    const gradualText = '**Dune** & <script>texto</script> ' + 'Lectura 📚 '.repeat(50);
    writer.push(gradualText);
    check(textNode.innerHTML === '', 'escritura gradual no publica todo de golpe');
    typeClock.next();
    check(textNode.innerHTML.length > 0 && !textNode.innerHTML.includes('<script>'), 'primer avance seguro');
    const typingDone = writer.finish();
    let frames = 0;
    while (typeClock.next()) { frames++; assert(frames < 100, 'animación acotada'); }
    await typingDone;
    check(textNode.innerHTML === Safe.formatMessageText(gradualText) && paints <= 65, 'fin exacto sin redibujar por cada carácter');
    const reducedNode = new MockNode();
    Safe.createTypewriter(reducedNode, { reducedMotion: true }).push('Respuesta sin animación');
    check(reducedNode.innerHTML === 'Respuesta sin animación', 'respeta movimiento reducido');
    const longNode = new MockNode();
    Safe.createTypewriter(longNode, { reducedMotion: false }).push('a'.repeat(10001));
    check(longNode.innerHTML.length === 10001, 'respuestas largas se completan sin espera artificial');
    const skipClock = clock(), skipNode = new MockNode();
    const skipWriter = Safe.createTypewriter(skipNode, { reducedMotion: false, schedule: skipClock.schedule, unschedule: skipClock.clear });
    skipWriter.push('Puedes saltar la animación.');
    skipNode.handlers.click();
    check(skipNode.innerHTML === 'Puedes saltar la animación.' && skipClock.pending === 0, 'clic completa la animación');

    const avatarNode = new MockNode('img'), avatarClock = clock();
    const avatar = Safe.createChatAvatar(avatarNode, { environment: { setTimeout: avatarClock.schedule, clearTimeout: avatarClock.clear } });
    avatar.emotion('Una novela de terror');
    check(avatarNode.src.includes('miedo.png'), 'avatar contextual: terror');
    avatar.emotion('Una tragedia literaria');
    check(avatarNode.src.includes('triste.png'), 'avatar contextual: tragedia');
    avatar.emotion('Gracias por la recomendación');
    check(avatarNode.src.includes('agradecida.png'), 'avatar contextual: agradecimiento');
    avatar.resetAfter(100);
    avatar.stage('search');
    check(!avatarClock.next() && avatarNode.src.includes('pensativa.png'), 'timer anterior no interrumpe búsqueda');
    avatar.emotion('Texto neutral', 'surprised');
    avatar.resetAfter(100);
    avatar.speaking(true);
    check(!avatarClock.next() && avatarNode.src.includes('sorprendida.png'), 'avatar conserva emoción mientras habla');
    avatar.show('../otra-imagen.jpg');
    check(avatarNode.src.includes('sorprendida.png'), 'avatar no acepta rutas de metadata');

    const unavailableVoice = voiceEnvironment('unavailable');
    const readerVoice = Safe.createChatVoice({ environment: unavailableVoice.env, useServer: true,
        onChange: state => unavailableVoice.changes.push(state) });
    await readerVoice.speak('**Dune** es una novela.');
    check(unavailableVoice.spoken.length === 1 && unavailableVoice.spoken[0].lang === 'es-CL', 'voz del navegador cuando servidor no está disponible');
    check(unavailableVoice.spoken[0].text === 'Dune es una novela.' && readerVoice.speaking, 'lectura sin marcas visuales');
    unavailableVoice.spoken[0].onboundary({ charIndex: 5 });
    readerVoice.setVolume('0.25');
    check(unavailableVoice.spoken.length === 2 && unavailableVoice.spoken[1].volume === .25 && unavailableVoice.spoken[1].text === 'es una novela.', 'volumen real reinicia desde límite de palabra');
    readerVoice.toggle();
    check(readerVoice.volume === 0 && !readerVoice.speaking && unavailableVoice.cancels > 0, 'silenciar cancela la voz del navegador');
    readerVoice.toggle();
    check(readerVoice.volume === .25, 'restaura el volumen anterior');
    const queuedVoice = voiceEnvironment();
    queuedVoice.env.speechSynthesis.speak = reading => queuedVoice.spoken.push(reading);
    const queuedReader = Safe.createChatVoice({ environment: queuedVoice.env, useServer: false });
    await queuedReader.speak('Voz todavía en cola.');
    queuedReader.setVolume(.2);
    check(queuedVoice.spoken[0].volume === .2, 'volumen actualizado antes de empezar a hablar');
    queuedReader.stop();
    const audioVoice = voiceEnvironment('audio');
    const serverReader = Safe.createChatVoice({ environment: audioVoice.env, useServer: true, volume: .5 });
    await serverReader.speak('Texto leído por el servidor.');
    check(audioVoice.players.length === 1 && audioVoice.spoken.length === 0 && audioVoice.players[0].volume === .5, 'audio servidor y navegador no hablan juntos');
    serverReader.setVolume(.75);
    check(audioVoice.players[0].volume === .75, 'volumen aplicado al audio activo');
    serverReader.stop();
    check(audioVoice.players[0].paused && audioVoice.players[0].src === '', 'detiene y libera audio activo');
    const brokenAudio = voiceEnvironment('audio-error');
    await Safe.createChatVoice({ environment: brokenAudio.env, useServer: true }).speak('Respaldo de audio.');
    check(brokenAudio.spoken.length === 1, 'fallo de audio y play rechazado generan un solo respaldo');
    const lateAudio = voiceEnvironment('audio');
    let answerVoiceRequest;
    lateAudio.env.fetch = () => new Promise(resolve => { answerVoiceRequest = resolve; });
    const lateReader = Safe.createChatVoice({ environment: lateAudio.env, useServer: true });
    const latePromise = lateReader.speak('Respuesta tardía de voz.');
    lateReader.setVolume(0);
    answerVoiceRequest({ ok: true, json: async () => ({ audio_url: '/media/late.mp3' }) });
    await latePromise;
    check(lateAudio.players.length === 0 && lateAudio.spoken.length === 0, 'silenciar invalida respuestas de voz tardías');

    const stages = [];
    const stageStream = streaming([bytes('data: {"token":"","stage":"search","message":"Buscando..."}\n\ndata: {"token":"Listo"}\n\ndata: [DONE]\n\n')]);
    check(await Safe.readChatResponse(stageStream.response, () => {}, value => stages.push(value)) === 'Listo' && stages[0].stage === 'search', 'estado de progreso separado del texto');

    let deadlineCallback, requestedTimeout, pendingFetch, requestSignal, latePaints = 0;
    const deadlineEnv = { AbortController,
        setTimeout(callback, delay) { deadlineCallback = callback; requestedTimeout = delay; return 123; },
        clearTimeout() {},
        fetch(url, options) { requestSignal = options.signal; return new Promise(resolve => { pendingFetch = resolve; }); }
    };
    const timedQuery = Safe.queryChat('Libros', () => { latePaints++; }, () => { latePaints++; }, { environment: deadlineEnv });
    check(requestedTimeout === 10000, 'petición completa limitada a diez segundos');
    deadlineCallback();
    await assert.rejects(timedQuery, /10 segundos/); checks++;
    check(requestSignal.aborted, 'se cancela transporte al vencer la espera');
    pendingFetch(streaming([bytes('data: {"token":"TARDE"}\n\ndata: [DONE]\n\n')]).response);
    await new Promise(resolve => setImmediate(resolve));
    check(latePaints === 0, 'respuesta tardía nunca reemplaza el error ni publica contenido');

    global.document = { cookie: 'sessionid=abc; csrftoken=token%20csrf' };
    check(Safe.getCookie('csrftoken') === 'token csrf', 'CSRF decodificado');
    global.document.cookie = 'csrftoken=%zz';
    check(Safe.getCookie('csrftoken') === '', 'cookie malformada');
    delete global.document;

    for (const file of ['chatbot.js', 'floating_chat.js']) {
        const source = fs.readFileSync(path.join(__dirname, 'static', 'js', file), 'utf8');
        new vm.Script(source, { filename: file });
        check(source.includes('LitMateSafe.queryChat(') && source.includes('LitMateSafe.renderMessage('), file + ': transporte acotado/formato compartido');
        check(!source.includes('function formatMessageText') && !source.includes('function readChatProblem'), file + ': sin copias de helpers');
        check(source.includes('LitMateSafe.queryChat('), file + ': usa POST compartido protegido con CSRF');
        await clientRequest(file);
        await clientRequest(file, 503);
        await clientRequest(file, 200, [CARD]);
    }
    const browser = { URL, TextDecoder, globalThis: null }; browser.globalThis = browser;
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, 'static/js/litmate_safe.js'), 'utf8'), browser);
    check(typeof browser.LitMateSafe.readChatResponse === 'function', 'exportación de navegador');
    const base = fs.readFileSync(path.join(__dirname, 'templates/base.html'), 'utf8');
    check(base.indexOf("js/litmate_safe.js") >= 0 && base.indexOf("js/litmate_safe.js") < base.indexOf("js/floating_chat.js"), 'helper cargado antes del widget');
    check(base.includes('css/chat-books.css') && base.includes('?v=chat-v6'), 'estilos y scripts IA con versión de caché');
    const css = fs.readFileSync(path.join(__dirname, 'static/css/chat-books.css'), 'utf8');
    check(css.includes('background: #c9a96e;') && css.includes('minmax(min(100%, 245px), 1fr)'), 'burbujas doradas y tarjetas adaptables');
    check(css.includes('#floating-chat-body .lm-chat-books-grid { grid-template-columns: minmax(0, 1fr); }'), 'widget muestra una columna sin desbordamiento');
    for (const name of ['chatbot.html', 'chatbotbase.html']) {
        const template = fs.readFileSync(path.join(__dirname, 'templates', name), 'utf8');
        check(!template.includes('Cuando tengamos una ficha') && template.includes('?v=chat-v6'), name + ': copy retirado y cliente actualizado');
    }
    for (const file of ['feliz.png', 'agradecida.png', 'triste.png', 'miedo.png', 'enojo.png', 'sorprendida.png', 'pensativa.png', 'sin conexion.png', 'cuerpo.jpg']) {
        check(fs.existsSync(path.join(__dirname, 'static/assets/img/avatar', file)), 'avatar existente: ' + file);
    }
    console.log(`${checks} comprobaciones de chat: seguridad, formato, SSE, HTTP, CSRF y voz correctas.`);
}
main().catch(error => { console.error(error); process.exitCode = 1; });
