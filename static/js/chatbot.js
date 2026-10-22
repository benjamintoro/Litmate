/**
 * LitMate AI Chatbot - respuestas revisadas, streaming SSE, voz y control de volumen
 */

document.addEventListener('DOMContentLoaded', () => {

    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatBody = document.getElementById('chat-body-page');
    const sendBtn = document.getElementById('send-btn');
    const micBtn = document.getElementById('mic-btn');
    const ttsToggleBtn = document.getElementById('tts-toggle-btn');
    const ttsIcon = document.getElementById('tts-icon');
    const volumeSlider = document.getElementById('tts-volume-slider');
    const volumeLabel = document.getElementById('tts-volume-label');
    const avatar = document.querySelector("#chat-character-page img");

    if (!chatForm || !chatInput || !chatBody || !window.LitMateSafe) return;

    const avatarController = LitMateSafe.createChatAvatar(avatar);

    function scrollToBottom() {
        if (!chatBody) return;
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    // =====================================================================
    // 1. SÍNTESIS DE VOZ Y CONTROL DE VOLUMEN (HATSUNE MIKU)
    // =====================================================================
    function updateTTSUI(state) {
        if (volumeSlider) volumeSlider.value = state.volume;
        if (volumeLabel) volumeLabel.textContent = Math.round(state.volume * 100) + '%';
        if (!ttsToggleBtn || !ttsIcon) return;
        ttsIcon.className = state.enabled ? 'fa-solid fa-volume-high' : 'fa-solid fa-volume-xmark';
        ttsToggleBtn.title = state.error || (state.speaking ? 'Leyendo la respuesta (clic para silenciar)' : state.pending ? 'Preparando voz...' : state.enabled ? 'Voz activada (clic para silenciar)' : 'Voz silenciada (clic para activar)');
        ttsToggleBtn.setAttribute('aria-pressed', String(state.enabled));
        if (state.speaking) ttsToggleBtn.classList.add('speaking-pulse');
        else ttsToggleBtn.classList.remove('speaking-pulse');
    }

    const voice = LitMateSafe.createChatVoice({ useServer: true, onChange: updateTTSUI,
        onStart: () => avatarController.speaking(true),
        onStop: () => avatarController.speaking(false),
        onEnd: () => { avatarController.speaking(false); avatarController.resetAfter(5000); }
    });
    function stopSpeaking() { voice.stop(); }
    function speakText(text) { return voice.speak(text); }
    if (volumeSlider) volumeSlider.addEventListener('input', event => voice.setVolume(event.target.value));
    if (ttsToggleBtn) ttsToggleBtn.addEventListener('click', event => {
        event.preventDefault(); event.stopPropagation(); voice.toggle();
    });

    // Dictado de voz, independiente de la lectura de las respuestas.
    const SpeechRecognitionConstructor = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognition = null;
    let isListening = false;
    let baseText = '';
    let finalTranscript = '';

    function resetMicUI() {
        if (!micBtn) return;
        micBtn.classList.remove('listening', 'error');
        micBtn.title = 'Hablar con micrófono';
        micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
        if (chatInput && chatInput.placeholder.includes('Escuchando')) {
            chatInput.placeholder = 'Pregúntame sobre un libro...';
        }
    }

    function setMicListeningUI() {
        if (!micBtn) return;
        micBtn.classList.add('listening');
        micBtn.title = 'Detener grabación';
        micBtn.innerHTML = '<i class="fa-solid fa-stop"></i>';
        if (chatInput) chatInput.placeholder = 'Escuchando... habla ahora';
    }

    if (micBtn && SpeechRecognitionConstructor) {
        recognition = new SpeechRecognitionConstructor();
        recognition.lang = 'es-CL';
        recognition.interimResults = true;
        recognition.continuous = true;

        micBtn.addEventListener('click', (e) => {
            e.preventDefault();
            stopSpeaking();
            if (isListening) {
                try { recognition.stop(); } catch(err) {}
                return;
            }
            try {
                baseText = chatInput && chatInput.value.trim() ? chatInput.value.trim() + ' ' : '';
                finalTranscript = '';
                recognition.start();
            } catch (error) {}
        });

        recognition.onstart = () => {
            isListening = true;
            setMicListeningUI();
            setAvatar("pensativa.png");
        };

        recognition.onresult = (event) => {
            let interimTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) finalTranscript += event.results[i][0].transcript + ' ';
                else interimTranscript += event.results[i][0].transcript;
            }
            if (chatInput) {
                chatInput.value = baseText + finalTranscript + interimTranscript;
                chatInput.focus();
            }
        };

        recognition.onend = () => {
            isListening = false;
            resetMicUI();
        };

        recognition.onerror = () => {
            isListening = false;
            resetMicUI();
        };
    } else if (micBtn) {
        micBtn.disabled = true;
        micBtn.title = 'Este navegador no admite dictado de voz.';
    }

    // =====================================================================
    // 3. EXPRESIONES DEL AVATAR
    // =====================================================================
    function setAvatar(file) { avatarController.show(file); }
    function resetToDefault(delay = 12000) { avatarController.resetAfter(delay); }
    function beforeSend() { avatarController.stage('search'); }
    function onError() { avatarController.error(); avatarController.resetAfter(7000); }
    function applySmartEmotion(text, mood = '') { avatarController.emotion(text, mood); }

    // =====================================================================
    // 4. STREAMING SSE Y ENVÍO DE MENSAJES
    // =====================================================================
    async function sendMessage(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }

        const userMessage = chatInput ? chatInput.value.trim() : '';
        if (!userMessage || (sendBtn && sendBtn.disabled)) return false;

        stopSpeaking();

        appendMessage(userMessage, 'user');
        chatInput.value = '';
        if (sendBtn) sendBtn.disabled = true;

        beforeSend();

        const botMessageDiv = document.createElement('div');
        botMessageDiv.classList.add('chat-message', 'bot');
        const botParagraph = LitMateSafe.element('div', 'lm-chat-message-text');
        botParagraph.hidden = true;
        botMessageDiv.appendChild(botParagraph);
        const status = LitMateSafe.element('div', 'lm-chat-status');
        status.setAttribute('role', 'status');
        status.appendChild(LitMateSafe.element('span', 'lm-chat-status-dot'));
        const statusText = LitMateSafe.element('span', '', 'Buscando entre libros...');
        status.appendChild(statusText);
        botMessageDiv.appendChild(status);
        chatBody.appendChild(botMessageDiv);
        scrollToBottom();
        const writer = LitMateSafe.createTypewriter(botParagraph, { onPaint: scrollToBottom });

        let accumulatedText = "";
        let suggestedBooks = [];
        let answerMood = '', hasText = false;

        try {
            accumulatedText = await LitMateSafe.queryChat(userMessage, value => {
                if (!value.trim()) return;
                botParagraph.hidden = false;
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

            // La respuesta ya fue verificada completa. No sumar otros 2,5 s
            // de animación al presupuesto de espera del lector.
            writer.skip();
            status.hidden = true;
            LitMateSafe.renderBookCards(botMessageDiv, suggestedBooks);
            scrollToBottom();
            applySmartEmotion(userMessage + ' ' + accumulatedText, answerMood);
            resetToDefault(15000);
            speakText(accumulatedText);

        } catch (error) {
            console.error("Error en chatbot query:", error);
            writer.cancel();
            status.hidden = true;
            botParagraph.hidden = false;
            LitMateSafe.renderMessage(botParagraph, error.message || 'No se pudo conectar con el asistente. Vuelve a intentar.');
            onError();
        } finally {
            if (sendBtn) sendBtn.disabled = false;
            if (chatInput) chatInput.focus();
            scrollToBottom();
        }

        return false;
    }

    if (chatForm) chatForm.addEventListener('submit', sendMessage);

    const getCookie = LitMateSafe.getCookie;

    function appendMessage(message, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('chat-message', sender);
        const p = LitMateSafe.element('div', 'lm-chat-message-text');
        LitMateSafe.renderMessage(p, message);
        messageDiv.appendChild(p);
        chatBody.appendChild(messageDiv);
        scrollToBottom();
    }

    // =====================================================================
    // 5. PARALLAX 2.5D (SEGUIMIENTO DEL CURSOR)
    // =====================================================================
    const avatarWrapper = document.querySelector("#chat-character-page");
    if (avatarWrapper && avatar) {
        document.addEventListener('mousemove', (e) => {
            const { innerWidth, innerHeight } = window;
            const x = (e.clientX / innerWidth - 0.5) * 14;
            const y = (e.clientY / innerHeight - 0.5) * -14;

            avatar.style.transform = `perspective(600px) rotateY(${x}deg) rotateX(${y}deg)`;
        });

        document.addEventListener('mouseleave', () => {
            avatar.style.transform = 'perspective(600px) rotateY(0deg) rotateX(0deg)';
        });
    }
});
