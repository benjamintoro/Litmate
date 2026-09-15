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

    if (!triggerBtn || !windowEl) return;

    let ttsEnabled = true;
    let isListening = false;
    let recognition = null;
    let resetTimer = null;

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

    // Control de avatar
    function setWidgetAvatar(file) {
        if (!headerAvatar) return;
        headerAvatar.src = `/static/assets/img/avatar/${file}?v=${Date.now()}`;
    }

    function resetWidgetAvatar(delay = 12000) {
        if (resetTimer) clearTimeout(resetTimer);
        resetTimer = setTimeout(() => {
            setWidgetAvatar("cuerpo.jpg");
            resetTimer = null;
        }, delay);
    }

    // TTS
    function stopSpeaking() {
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }
        if (ttsBtn && ttsEnabled) {
            ttsIcon.className = 'fa-solid fa-volume-low';
            ttsBtn.style.backgroundColor = '#3b2818';
        }
    }

    function speakText(text) {
        if (!ttsEnabled || !('speechSynthesis' in window)) return;
        stopSpeaking();

        const clean = text.replace(/https?:\/\/\S+/gi, '').replace(/[*#_~`\[\]()<>"]/g, '').trim();
        if (!clean) return;

        const utterance = new SpeechSynthesisUtterance(clean);
        utterance.lang = 'es-CL';
        utterance.pitch = 1.45;
        utterance.rate = 1.12;

        const voices = window.speechSynthesis.getVoices();
        const preferredVoice = voices.find(v => v.lang === 'es-CL') ||
                               voices.find(v => v.lang.startsWith('es-419')) ||
                               voices.find(v => v.lang.startsWith('es'));
        if (preferredVoice) utterance.voice = preferredVoice;

        utterance.onstart = () => {
            if (ttsBtn) {
                ttsIcon.className = 'fa-solid fa-volume-high';
                ttsBtn.style.backgroundColor = '#227D8E';
            }
            setWidgetAvatar("feliz.png");
        };

        utterance.onend = () => {
            stopSpeaking();
            resetWidgetAvatar(3000);
        };

        window.speechSynthesis.speak(utterance);
    }

    if (ttsBtn) {
        ttsBtn.addEventListener('click', (e) => {
            e.preventDefault();
            ttsEnabled = !ttsEnabled;
            if (!ttsEnabled) {
                stopSpeaking();
                ttsIcon.className = 'fa-solid fa-volume-xmark';
                ttsBtn.style.backgroundColor = '#6c757d';
            } else {
                ttsIcon.className = 'fa-solid fa-volume-low';
                ttsBtn.style.backgroundColor = '#3b2818';
            }
        });
    }

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
            setWidgetAvatar("pensativa.png");
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
    }

    // Formateo y CSRF
    function formatMessageText(text) {
        return text
            .replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, '"$1"').replace(/\*(.*?)\*/g, '$1')
            .replace(/^[ \t]*#+[ \t]*/gm, '').replace(/[\*#]/g, '')
            .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #227D8E; font-weight: 600; text-decoration: underline;">$1</a>')
            .replace(/\n/g, '<br>');
    }

    function getCsrfToken() {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                cookie = cookie.trim();
                if (cookie.startsWith('csrftoken=')) {
                    cookieValue = decodeURIComponent(cookie.slice(10));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // Enviar mensaje con streaming SSE
    if (form) {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!text) return;

            stopSpeaking();

            const userDiv = document.createElement('div');
            userDiv.className = 'chat-message user';
            userDiv.innerHTML = `<p style="background: #227D8E; color: #fff; padding: 8px 12px; border-radius: 14px; margin: 0; align-self: flex-end; max-width: 85%;">${formatMessageText(text)}</p>`;
            body.appendChild(userDiv);

            input.value = '';
            sendBtn.disabled = true;
            setWidgetAvatar("pensativa.png");

            const botDiv = document.createElement('div');
            botDiv.className = 'chat-message bot';
            const botP = document.createElement('p');
            botP.style.cssText = "background: #fff; border: 1px solid #e2e8f0; color: #1e293b; padding: 8px 12px; border-radius: 14px; margin: 0; align-self: flex-start; max-width: 85%;";
            botP.innerHTML = '<span class="spinner-border spinner-border-sm text-secondary"></span>';
            botDiv.appendChild(botP);
            body.appendChild(botDiv);
            body.scrollTop = body.scrollHeight;

            let accumulated = '';
            let firstToken = true;

            try {
                const res = await fetch('/chatbot_query/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    },
                    body: JSON.stringify({ message: text })
                });

                if (!res.ok) throw new Error('Error de conexión');

                const reader = res.body.getReader();
                const decoder = new TextDecoder('utf-8');
                let buffer = '';

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const events = buffer.split('\n\n');
                    buffer = events.pop();

                    for (const ev of events) {
                        for (const line of ev.split('\n')) {
                            const trimmed = line.trim();
                            if (trimmed.startsWith('data: ')) {
                                const dataStr = trimmed.slice(6).trim();
                                if (dataStr === '[DONE]') break;

                                try {
                                    const parsed = JSON.parse(dataStr);
                                    if (parsed.token) {
                                        if (firstToken) {
                                            botP.innerHTML = '';
                                            firstToken = false;
                                        }
                                        accumulated += parsed.token;
                                        botP.innerHTML = formatMessageText(accumulated);
                                        body.scrollTop = body.scrollHeight;
                                    }
                                } catch (errParse) {}
                            }
                        }
                    }
                }

                setWidgetAvatar("feliz.png");
                resetWidgetAvatar(5000);
                speakText(accumulated);

            } catch (err) {
                botP.innerHTML = 'Lo siento, ocurrió un error.';
                setWidgetAvatar("sin conexion.png");
                resetWidgetAvatar(6000);
            } finally {
                sendBtn.disabled = false;
                input.focus();
            }
        });
    }
});