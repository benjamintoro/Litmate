/**
 * LitMate AI - Widget Flotante Global con Streaming SSE y Voz
 */
document.addEventListener('DOMContentLoaded', () => {
    const triggerBtn = document.getElementById('floating-chat-trigger');
    const windowEl = document.getElementById('floating-chat-window');
    const closeBtn = document.getElementById('floating-chat-close');
    const form = document.getElementById('floating-chat-form');
    const input = document.getElementById('floating-chat-input');
    const body = document.getElementById('floating-chat-body');
    const sendBtn = document.getElementById('floating-send-btn');
    const micBtn = document.getElementById('floating-mic-btn');
    const ttsBtn = document.getElementById('floating-tts-btn');
    const ttsIcon = document.getElementById('floating-tts-icon');
    const headerAvatar = document.getElementById('floating-header-avatar');

    if (!triggerBtn || !windowEl || !form || !input || !body || !sendBtn || !window.LitMateSafe) return;

    let isListening = false;
    let recognition = null;
    const avatarController = LitMateSafe.createChatAvatar(headerAvatar);

    // Apertura y Cierre directo del Widget
    function toggleChatWindow(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }
        const isHidden = window.getComputedStyle(windowEl).display === 'none';
        if (isHidden) {
            windowEl.style.setProperty('display', 'flex', 'important');
            if (input) {
                setTimeout(() => input.focus(), 150);
            }
        } else {
            windowEl.style.setProperty('display', 'none', 'important');
            stopSpeaking();
        }
    }

    triggerBtn.addEventListener('click', toggleChatWindow);

    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            windowEl.style.setProperty('display', 'none', 'important');
            stopSpeaking();
        });
    }

    function setWidgetAvatar(file) { avatarController.show(file); }
    function resetWidgetAvatar(delay = 12000) { avatarController.resetAfter(delay); }
    const voice = LitMateSafe.createChatVoice({ useServer: false,
        onChange: state => {
            if (!ttsBtn || !ttsIcon) return;
            ttsIcon.className = state.enabled ? 'fa-solid fa-volume-high' : 'fa-solid fa-volume-xmark';
            ttsBtn.title = state.error || (state.speaking ? 'Leyendo (clic para silenciar)' : state.enabled ? 'Voz activada (clic para silenciar)' : 'Voz silenciada (clic para activar)');
            ttsBtn.setAttribute('aria-pressed', String(state.enabled));
        },
        onStart: () => avatarController.speaking(true),
        onStop: () => avatarController.speaking(false),
        onEnd: () => { avatarController.speaking(false); avatarController.resetAfter(5000); }
    });
    function stopSpeaking() { voice.stop(); }
    function speakText(text) { return voice.speak(text); }
    if (ttsBtn) ttsBtn.addEventListener('click', event => { event.preventDefault(); voice.toggle(); });

    // Micrófono
    const SpeechConstructor = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (micBtn && SpeechConstructor) {
        recognition = new SpeechConstructor();
        recognition.lang = 'es-CL';
        recognition.interimResults = true;
        recognition.continuous = true;

        micBtn.addEventListener('click', (e) => {
            e.preventDefault();
            stopSpeaking();
            if (isListening) {
                recognition.stop();
                return;
            }
            try {
                recognition.start();
            } catch (err) {
                console.warn(err);
            }
        });

        recognition.onstart = () => {
            isListening = true;
            micBtn.classList.add('listening');
            micBtn.innerHTML = '<i class="fa-solid fa-stop"></i>';
            avatarController.stage('search');
        };

        recognition.onresult = (e) => {
            let res = '';
            for (let i = e.resultIndex; i < e.results.length; i++) {
                res += e.results[i][0].transcript;
            }
            if (input) input.value = res;
        };

        recognition.onend = () => {
            isListening = false;
            micBtn.classList.remove('listening');
            micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
        };
        recognition.onerror = () => recognition.onend();
    } else if (micBtn) {
        micBtn.disabled = true;
        micBtn.title = 'Este navegador no admite dictado de voz.';
    }

    // Formateo y CSRF


    const getCsrfToken = () => LitMateSafe.getCookie('csrftoken');

    // Enviar mensaje con streaming SSE
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!text || sendBtn.disabled) return;

            stopSpeaking();

            const userDiv = document.createElement('div');
            userDiv.className = 'chat-message user';
            const userP = LitMateSafe.element('p');
            userP.className = 'lm-chat-message-text';
            LitMateSafe.renderMessage(userP, text);
            userDiv.appendChild(userP);
            body.appendChild(userDiv);

            input.value = '';
            sendBtn.disabled = true;
            setWidgetAvatar("pensativa.png");

            const botDiv = document.createElement('div');
            botDiv.className = 'chat-message bot';
            const botP = LitMateSafe.element('div', 'lm-chat-message-text');
            botP.hidden = true;
            botDiv.appendChild(botP);
            const status = LitMateSafe.element('div', 'lm-chat-status');
            status.setAttribute('role', 'status');
            status.appendChild(LitMateSafe.element('span', 'lm-chat-status-dot'));
            const statusText = LitMateSafe.element('span', '', 'Buscando entre libros...');
            status.appendChild(statusText);
            botDiv.appendChild(status);
            body.appendChild(botDiv);
            body.scrollTop = body.scrollHeight;
            const writer = LitMateSafe.createTypewriter(botP, { onPaint: () => { body.scrollTop = body.scrollHeight; } });

            let accumulated = '';
            let suggestedBooks = [];
            let answerMood = '', hasText = false;

            try {
                const res = await fetch('/chatbot_query/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({ message: text })
                });

                accumulated = await LitMateSafe.readChatResponse(res, value => {
                    if (!value.trim()) return;
                    botP.hidden = false;
                    if (!hasText) { hasText = true; avatarController.stage('writing'); statusText.textContent = 'Escribiendo...'; }
                    writer.push(value);
                }, metadata => {
                    if (Array.isArray(metadata.books)) suggestedBooks = metadata.books;
                    if (metadata.mood) answerMood = metadata.mood;
                    if (metadata.stage) {
                        statusText.textContent = metadata.message || ({ search: 'Buscando entre libros...', review: 'Revisando mi respuesta...', writing: 'Escribiendo...' })[metadata.stage];
                        avatarController.stage(metadata.stage);
                    }
                });

                await writer.finish();
                status.hidden = true;
                LitMateSafe.renderBookCards(botDiv, suggestedBooks);
                body.scrollTop = body.scrollHeight;
                avatarController.emotion(text + ' ' + accumulated, answerMood);
                resetWidgetAvatar(15000);
                speakText(accumulated);

            } catch (err) {
                writer.cancel();
                status.hidden = true;
                botP.hidden = false;
                LitMateSafe.renderMessage(botP, err.message || 'No se pudo conectar con el asistente. Vuelve a intentar.');
                setWidgetAvatar("sin conexion.png");
                resetWidgetAvatar(6000);
            } finally {
                sendBtn.disabled = false;
                input.focus();
            }
        });
    }
});
