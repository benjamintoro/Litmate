/**
 * LitMate AI Chatbot - Integración completa con Streaming SSE, Micrófono en Vivo y Text-to-Speech (TTS)
 */

document.addEventListener('DOMContentLoaded', () => {

    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatBody = document.getElementById('chat-body-page');
    const sendBtn = document.getElementById('send-btn');
    const micBtn = document.getElementById('mic-btn');
    const ttsToggleBtn = document.getElementById('tts-toggle-btn');
    const ttsIcon = document.getElementById('tts-icon');
    const avatar = document.querySelector("#chat-character-page img");

    let resetTimer = null;

// =====================================================================
    // 1. SÍNTESIS DE VOZ (Text-to-Speech con estados visuales dinámicos)
    // =====================================================================
    let ttsEnabled = true;
    let isSpeaking = false;

    function updateTTSUI(speaking = false) {
        if (!ttsToggleBtn || !ttsIcon) return;
        isSpeaking = speaking;

        if (!ttsEnabled) {
            // Estado: Silenciado / Muteado
            ttsIcon.className = 'fa-solid fa-volume-xmark';
            ttsToggleBtn.title = 'Voz silenciada (clic para activar)';
            ttsToggleBtn.style.backgroundColor = '#6c757d'; // Gris apagado
            ttsToggleBtn.classList.remove('speaking-pulse');
        } else if (speaking) {
            // Estado: La monita está hablando en este momento
            ttsIcon.className = 'fa-solid fa-volume-high';
            ttsToggleBtn.title = 'Hablando... (clic para silenciar)';
            ttsToggleBtn.style.backgroundColor = '#227D8E'; // Verde/azul acento activo
            ttsToggleBtn.classList.add('speaking-pulse');
        } else {
            // Estado: En espera / Listo para hablar
            ttsIcon.className = 'fa-solid fa-volume-low';
            ttsToggleBtn.title = 'Voz activada (en espera)';
            ttsToggleBtn.style.backgroundColor = '#3b2818'; // Café base
            ttsToggleBtn.classList.remove('speaking-pulse');
        }
    }

    function cleanTextForSpeech(text) {
        if (!text) return '';
        return text
            .replace(/https?:\/\/\S+/gi, '') // Omite enlaces
            .replace(/[*#_~`\[\]()<>]/g, '')
            .replace(/"/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function stopSpeaking() {
        if ('speechSynthesis' in window) {
            window.speechSynthesis.cancel();
        }
        updateTTSUI(false);
    }

    function speakText(text) {
        if (!ttsEnabled || !('speechSynthesis' in window)) return;

        stopSpeaking();

        const cleanText = cleanTextForSpeech(text);
        if (!cleanText) return;

        const utterance = new SpeechSynthesisUtterance(cleanText);
        utterance.lang = 'es-CL';
        utterance.pitch = 1.45; // Tono agudo/kawaii
        utterance.rate = 1.12;  // Fluido y alegre
        utterance.volume = 1.0;

        const voices = window.speechSynthesis.getVoices();
        const femaleVoiceNames = [
            'sabina', 'paulina', 'dalia', 'monica', 'helena', 
            'laura', 'sofia', 'paloma', 'jimena', 'francisca', 
            'google español', 'natural'
        ];

        let preferredVoice = voices.find(v => 
            v.lang.startsWith('es') && 
            femaleVoiceNames.some(name => v.name.toLowerCase().includes(name))
        );

        if (!preferredVoice) {
            preferredVoice = voices.find(v => v.lang === 'es-CL') ||
                             voices.find(v => v.lang === 'es-MX') ||
                             voices.find(v => v.lang.startsWith('es-419')) ||
                             voices.find(v => v.lang.startsWith('es'));
        }

        if (preferredVoice) {
            utterance.voice = preferredVoice;
        }

        // Mientras empieza a hablar
        utterance.onstart = () => {
            updateTTSUI(true);
            if (avatar && !avatar.src.includes('sin conexion')) {
                avatar.src = '/static/assets/img/avatar/feliz.png?v=' + Date.now();
            }
        };

        // Al terminar de hablar
        utterance.onend = () => {
            updateTTSUI(false);
            resetToDefault(4000);
        };

        // En caso de error o interrupción
        utterance.onerror = () => {
            updateTTSUI(false);
            resetToDefault(1000);
        };

        window.speechSynthesis.speak(utterance);
    }

    if ('speechSynthesis' in window) {
        window.speechSynthesis.onvoiceschanged = () => {
            window.speechSynthesis.getVoices();
        };
    }

    // Toggle al hacer clic manual sobre el botón
    if (ttsToggleBtn && ttsIcon) {
        ttsToggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            ttsEnabled = !ttsEnabled;
            if (!ttsEnabled) {
                stopSpeaking();
            } else {
                updateTTSUI(false);
            }
        });
    }
    // =====================================================================
    // 2. MICRÓFONO DE VOZ (Web Speech API)
    // =====================================================================
    const SpeechRecognitionConstructor = window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognition = null;
    let isListening = false;
    let baseText = '';
    let finalTranscript = '';

    function resetMicUI() {
        if (!micBtn) return;
        micBtn.classList.remove('listening', 'error');
        micBtn.title = 'Hablar con micrófono';
        micBtn.setAttribute('aria-label', 'Habla con tu voz');
        micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
        if (chatInput && chatInput.placeholder.includes('Escuchando')) {
            chatInput.placeholder = 'Pregúntame sobre un libro...';
        }
    }

    function setMicListeningUI() {
        if (!micBtn) return;
        micBtn.classList.add('listening');
        micBtn.classList.remove('error');
        micBtn.title = 'Detener grabación (Stop)';
        micBtn.setAttribute('aria-label', 'Detener grabación');
        micBtn.innerHTML = '<i class="fa-solid fa-stop"></i>';
        if (chatInput) {
            chatInput.placeholder = 'Escuchando... habla ahora (clic en ■ para parar)';
        }
    }

    function setMicErrorUI(message = 'No se pudo usar el micrófono') {
        if (!micBtn) return;
        micBtn.classList.add('error');
        micBtn.classList.remove('listening');
        micBtn.title = message;
        micBtn.setAttribute('aria-label', message);
        micBtn.innerHTML = '<i class="fa-solid fa-triangle-exclamation"></i>';
        if (chatInput) {
            chatInput.placeholder = 'Permiso de micrófono requerido';
        }
    }

    function stopListeningAndFinish() {
        if (!isListening || !recognition) return;
        try {
            recognition.stop();
        } catch (error) {
            // Ya finalizado
        }
    }

    if (micBtn && SpeechRecognitionConstructor) {
        recognition = new SpeechRecognitionConstructor();
        recognition.lang = 'es-CL';
        recognition.interimResults = true;
        recognition.continuous = true;

        micBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();

            stopSpeaking();

            if (isListening) {
                stopListeningAndFinish();
                return;
            }

            try {
                baseText = chatInput && chatInput.value.trim() ? chatInput.value.trim() + ' ' : '';
                finalTranscript = '';
                recognition.start();
            } catch (error) {
                setMicErrorUI('El micrófono ya está activo');
            }
        });

        recognition.onstart = () => {
            isListening = true;
            setMicListeningUI();
            if (avatar) {
                avatar.src = '/static/assets/img/avatar/pensativa.png?v=' + Date.now();
            }
        };

        recognition.onresult = (event) => {
            let interimTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; ++i) {
                if (event.results[i].isFinal) {
                    finalTranscript += event.results[i][0].transcript + ' ';
                } else {
                    interimTranscript += event.results[i][0].transcript;
                }
            }
            if (chatInput) {
                chatInput.value = baseText + finalTranscript + interimTranscript;
                chatInput.focus();
            }
        };

        recognition.onerror = (event) => {
            isListening = false;
            console.error('Error reconocimiento de voz:', event.error);
            setMicErrorUI(event.error);
            if (avatar) {
                avatar.src = '/static/assets/img/avatar/sin conexion.png?v=' + Date.now();
            }
        };

        recognition.onend = () => {
            isListening = false;
            resetMicUI();
            if (chatInput) {
                chatInput.focus();
            }
        };
    } else if (micBtn) {
        micBtn.disabled = true;
        micBtn.title = 'Reconocimiento de voz no disponible en este navegador';
        micBtn.innerHTML = '<i class="fa-solid fa-microphone-slash"></i>';
    }

    // =====================================================================
    // 3. AVATAR Y EXPRESIONES
    // =====================================================================
    function setAvatar(file) {
        if (!avatar) return;
        avatar.src = `/static/assets/img/avatar/${file}?v=${Date.now()}`;
    }

    function resetToDefault(delay = 15000) {
        if (resetTimer) clearTimeout(resetTimer);
        resetTimer = setTimeout(() => {
            setAvatar("cuerpo.jpg");
            resetTimer = null;
        }, delay);
    }

    function beforeSend() {
        setAvatar("pensativa.png");
    }

    function onError() {
        setAvatar("sin conexion.png");
        resetToDefault(7000);
    }

    function normalizeText(str) {
        return str
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .replace(/[^a-zA-Z0-9\s]/g, "")
            .replace(/\s+/g, " ")
            .trim()
            .toLowerCase();
    }

    const genreKeywords = {
        fantasia: ["fantasia", "magia", "dragon", "dragones", "elfo", "elfos", "orco", "hechizo", "mago", "medieval"],
        terror: ["terror", "horror", "miedo", "fantasma", "demonio", "pesadilla", "sangre"],
        accion: ["guerra", "militar", "batalla", "soldado", "armas", "combate", "accion"],
        romance: ["romance", "amor", "pareja", "enamorar", "relacion", "corazon", "beso"],
        drama: ["drama", "dramatico", "tragedia", "triste", "perdida", "llorar"],
        scifi: ["ciencia ficcion", "sci fi", "espacio", "nave", "robot", "futuro", "distopia", "apocalipsis"]
    };

    function detectGenreSmart(message) {
        const msg = normalizeText(message);
        for (const genre in genreKeywords) {
            for (const word of genreKeywords[genre]) {
                if (msg.includes(word)) return genre;
            }
        }
        return "none";
    }

    function applyGenreEmotion(genre) {
        switch (genre) {
            case "fantasia": setAvatar("sorprendida.png"); break;
            case "terror": setAvatar("miedo.png"); break;
            case "accion": setAvatar("enojo.png"); break;
            case "romance": setAvatar("feliz.png"); break;
            case "drama": setAvatar("triste.png"); break;
            case "scifi": setAvatar("sorprendida.png"); break;
            default: setAvatar("cuerpo.jpg");
        }
        resetToDefault(15000);
    }

    function applyBackendEmotion(text) {
        const msg = normalizeText(text);
        if (msg.includes("hola") || msg.includes("buenas")) {
            setAvatar("feliz.png");
            resetToDefault();
            return;
        }
        if (msg.includes("gracias") || msg.includes("placer")) {
            setAvatar("agradecida.png");
            resetToDefault();
            return;
        }
        if (msg.includes("no encontre") || msg.includes("error")) {
            setAvatar("triste.png");
            resetToDefault();
            return;
        }
        resetToDefault();
    }

    function isSocialMessage(text) {
        const msg = normalizeText(text);
        return (
            msg.includes("como estas") ||
            msg.includes("que tal") ||
            msg.includes("hola") ||
            msg.includes("gracias")
        );
    }

    // =====================================================================
    // 4. FORMATEO DE TEXTO
    // =====================================================================
    function formatMessageText(text) {
        if (!text) return '';
        return text
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, '"$1"')
            .replace(/\*(.*?)\*/g, '$1')
            .replace(/^[ \t]*#+[ \t]*/gm, '')
            .replace(/[\*#]/g, '')
            .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #0085a1; font-weight: 600; text-decoration: underline;">$1</a>')
            .replace(/\n/g, '<br>');
    }

    // =====================================================================
    // 5. ENVÍO CON STREAMING EN TIEMPO REAL (SSE)
    // =====================================================================
    async function sendMessage(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }

        const userMessage = chatInput ? chatInput.value.trim() : '';
        if (!userMessage) return false;

        stopSpeaking();

        const genreDetected = detectGenreSmart(userMessage);
        const socialDetected = isSocialMessage(userMessage);

        appendMessage(userMessage, 'user');
        chatInput.value = '';
        if (sendBtn) sendBtn.disabled = true;

        beforeSend();

        const botMessageDiv = document.createElement('div');
        botMessageDiv.classList.add('chat-message', 'bot');
        const botParagraph = document.createElement('p');
        botParagraph.innerHTML = '<span class="typing-indicator" style="display:inline-block; margin:0;"><span></span><span></span><span></span></span>';
        botMessageDiv.appendChild(botParagraph);
        chatBody.appendChild(botMessageDiv);
        chatBody.scrollTop = chatBody.scrollHeight;

        let accumulatedText = "";
        let isFirstToken = true;

        try {
            const response = await fetch("/chatbot_query/", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken'),
                },
                body: JSON.stringify({ message: userMessage }),
            });

            if (!response.ok) {
                throw new Error(`HTTP Error ${response.status}`);
            }

            const contentType = response.headers.get("content-type") || "";

            if (contentType.includes("application/json")) {
                const json = await response.json();
                accumulatedText = json.response || json.error || "No se obtuvo respuesta.";
                botParagraph.innerHTML = formatMessageText(accumulatedText);
                chatBody.scrollTop = chatBody.scrollHeight;
            } else {
                const reader = response.body.getReader();
                const decoder = new TextDecoder("utf-8");
                let buffer = "";

                while (true) {
                    const { value, done } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });
                    const events = buffer.split("\n\n");
                    buffer = events.pop();

                    for (const ev of events) {
                        const lines = ev.split("\n");
                        for (const line of lines) {
                            const trimmed = line.trim();
                            if (trimmed.startsWith("data: ")) {
                                const dataStr = trimmed.slice(6).trim();
                                if (dataStr === "[DONE]") {
                                    break;
                                }
                                try {
                                    const parsed = JSON.parse(dataStr);
                                    if (parsed.token) {
                                        if (isFirstToken) {
                                            botParagraph.innerHTML = "";
                                            isFirstToken = false;
                                        }
                                        accumulatedText += parsed.token;
                                        botParagraph.innerHTML = formatMessageText(accumulatedText);
                                        chatBody.scrollTop = chatBody.scrollHeight;
                                    }
                                } catch (parseErr) {
                                    // Chunk parcial ignorado
                                }
                            }
                        }
                    }
                }
            }

            // Expresión final del avatar
            if (socialDetected) {
                setAvatar("agradecida.png");
                resetToDefault();
            } else if (genreDetected !== "none") {
                applyGenreEmotion(genreDetected);
            } else {
                applyBackendEmotion(accumulatedText);
            }

            // Leer respuesta completa en voz alta
            speakText(accumulatedText);

        } catch (error) {
            console.error("Error en chat streaming:", error);
            botParagraph.innerHTML = 'Lo siento, ocurrió un problema al conectar con el asistente.';
            onError();
        } finally {
            if (sendBtn) sendBtn.disabled = false;
            if (chatInput) chatInput.focus();
        }

        return false;
    }

    if (chatForm) {
        chatForm.addEventListener('submit', sendMessage);
    }

    // =====================================================================
    // 6. UTILIDADES
    // =====================================================================
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                cookie = cookie.trim();
                if (cookie.startsWith(name + '=')) {
                    cookieValue = decodeURIComponent(cookie.slice(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    function appendMessage(message, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.classList.add('chat-message', sender);
        const p = document.createElement('p');
        p.innerHTML = formatMessageText(message);
        messageDiv.appendChild(p);
        chatBody.appendChild(messageDiv);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    if (chatBody) {
        chatBody.scrollTop = chatBody.scrollHeight;
    }
});