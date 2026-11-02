/* Sólo lo carga el perfil optativo de cuentas. El servidor decide las cuotas. */
(() => {
    'use strict';
    document.documentElement.classList.add('lm-reader-chat');
    const nativeFetch = window.fetch.bind(window);
    function showActions(message) {
        let actions = document.getElementById('reader-actions');
        if (!actions) {
            const body = document.getElementById('floating-chat-body');
            if (!body) return;
            actions = document.createElement('div');
            actions.id = 'reader-actions';
            for (const [label, href] of [['Iniciar sesión', '/login/'], ['Crear cuenta', '/registro/'], ['Ver planes', '/suscripciones/planes/']]) {
                const link = document.createElement('a');
                link.className = 'btn btn-outline-primary btn-sm m-1';
                link.textContent = label; link.href = href;
                actions.appendChild(link);
            }
            body.appendChild(actions);
        }
        actions.hidden = false;
        const quota = document.getElementById('reader-quota');
        if (quota) quota.textContent = message;
    }
    async function refreshQuota() {
        try {
            const response = await nativeFetch('/api/cuota-ia/');
            const data = await response.json();
            const quota = document.getElementById('reader-quota');
            if (!quota) return;
            if (data.cuota) {
                const q = data.cuota;
                quota.textContent = q.plan + ': ' + q.usadas + ' utilizadas' +
                    (q.es_ilimitado ? ' · Sin límite diario' : ' · ' + q.restantes + ' disponibles') +
                    (q.invitado ? ' en total como invitado.' : ' hoy (hora de Chile).');
            } else quota.textContent = data.response || '';
        } catch (_) { /* No impedir el chat por el indicador informativo. */ }
    }
    window.fetch = async (input, options) => {
        const url = new URL(typeof input === 'string' ? input : input.url, location.href);
        const query = url.origin === location.origin && url.pathname === '/chatbot_query/';
        if (query && options && typeof options.body === 'string') {
            const body = JSON.parse(options.body);
            body.request_id = body.request_id || crypto.randomUUID();
            options = {...options, body: JSON.stringify(body)};
        }
        const response = await nativeFetch(input, options);
        if (url.origin === location.origin && ['/chatbot_query/', '/chatbot_finalize/'].includes(url.pathname)) {
            if (!response.ok) {
                try {
                    const data = await response.clone().json();
                    if (['guest_limit', 'quota_exceeded', 'plan_required'].includes(data.error)) {
                        showActions(data.response);
                    }
                } catch (_) { /* El cliente existente gestiona los demás errores. */ }
            }
            void refreshQuota();
        }
        return response;
    };
    document.addEventListener('DOMContentLoaded', () => {
        void refreshQuota();
        const footer = document.getElementById('chat-footer-page');
        for (const id of ['reader-quota', 'reader-actions']) {
            const element = document.getElementById(id);
            if (footer && element) footer.insertBefore(element, document.getElementById('chat-form'));
        }
        const scroller = document.getElementById('chat-body-page');
        if (!scroller) return;
        // Son como máximo seis tarjetas por respuesta. Evitar que la carga
        // diferida del navegador deje vacías portadas dentro del scroll anidado.
        function loadCovers() {
            scroller.querySelectorAll('.lm-chat-book-cover img[loading="lazy"]').forEach(image => { image.loading = 'eager'; });
        }
        new MutationObserver(loadCovers).observe(scroller, {childList: true, subtree: true});
        loadCovers();
        // Mantener anclaje si el lector sube a mensajes anteriores. La posición
        // sólo se corrige después de una modificación, nunca al desplazar a mano.
        let readingEarlier = false, previousTop = 0, intent = 0, userUntil = 0, touchY = 0, restoring = false;
        // El cliente original escribe scrollTop inmediatamente al recibir SSE,
        // antes de que el navegador entregue el evento scroll del gesto previo.
        // Proteger sólo ESTA instancia evita perder la posición en esa carrera;
        // no altera Element.prototype ni los otros chats de la demostración.
        const nativeScroll = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
        if (nativeScroll?.get && nativeScroll?.set) {
            Object.defineProperty(scroller, 'scrollTop', {
                configurable: true,
                get() { return nativeScroll.get.call(this); },
                set(value) {
                    const upwardGesture = performance.now() < userUntil && intent < 0 &&
                        Number(value) <= nativeScroll.get.call(this);
                    if (!readingEarlier || restoring || upwardGesture) {
                        nativeScroll.set.call(this, value);
                        if (readingEarlier && upwardGesture) previousTop = nativeScroll.get.call(this);
                    }
                }
            });
        }
        function trace(event) {
            if (Array.isArray(window.__readerScrollAudit)) {
                window.__readerScrollAudit.push({event,top:scroller.scrollTop,saved:previousTop,readingEarlier,intent});
                window.__readerScrollAudit = window.__readerScrollAudit.slice(-100);
            }
        }
        scroller.addEventListener('wheel', event => {
            intent = Math.sign(event.deltaY); userUntil = performance.now() + 200;
            if (intent < 0) { readingEarlier = true; previousTop = scroller.scrollTop; }
            trace('wheel');
        }, {passive: true});
        scroller.addEventListener('touchstart', event => { touchY = event.touches[0]?.clientY || 0; }, {passive: true});
        scroller.addEventListener('touchmove', event => {
            const next = event.touches[0]?.clientY || touchY;
            intent = Math.sign(touchY - next); touchY = next; userUntil = performance.now() + 200;
            if (intent < 0 && !readingEarlier) { readingEarlier = true; previousTop = scroller.scrollTop; }
        }, {passive: true});
        scroller.addEventListener('scroll', () => {
            if (!readingEarlier || restoring) return;
            const top = scroller.scrollTop;
            const userMove = performance.now() < userUntil && (intent < 0 ? top <= previousTop : top >= previousTop);
            if (userMove) {
                previousTop = top;
                if (intent > 0 && scroller.scrollHeight - top - scroller.clientHeight < 35) readingEarlier = false;
            } else if (Math.abs(top - previousTop) > 1) {
                restoring = true; scroller.scrollTop = previousTop; restoring = false;
            }
            trace('scroll');
        }, {passive: true});
        document.getElementById('chat-form')?.addEventListener('submit', () => { readingEarlier = false; trace('submit'); });
        const viewport = window.visualViewport;
        function resize() {
            document.documentElement.style.setProperty('--lm-viewport-height', (viewport?.height || window.innerHeight) + 'px');
            if (window.innerWidth <= 767 && document.activeElement?.id === 'chat-input') {
                footer?.scrollIntoView({block: 'end'});
            }
            trace('resize');
        }
        viewport?.addEventListener('resize', resize);
        window.addEventListener('resize', resize);
        resize();
    });
})();
