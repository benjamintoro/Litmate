/**
 * LitMate AI Chatbot - Streaming SSE, Memoria de Hilo, Tarjetas Interactivas, Voz Miku y Control de Volumen
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

    let resetTimer = null;

    function scrollToBottom() {
        if (!chatBody) return;
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    // =====================================================================
    // 1. SÍNTESIS DE VOZ Y CONTROL DE VOLUMEN (HATSUNE MIKU)
    // =====================================================================
    let ttsEnabled = true;
    let currentMikuAudio = null;
    let ttsAbortController = null;

    // Recuperar volumen previo del usuario o 100% por defecto
    let currentVolume = parseFloat(localStorage.getItem('litmate_miku_volume') ?? '1.0');
    let previousVolume = currentVolume > 0 ? currentVolume : 1.0;

    if (volumeSlider) {
        volumeSlider.value = currentVolume;
        if (volumeLabel) volumeLabel.textContent = `${Math.round(currentVolume * 100)}%`;
    }

    function updateTTSUI(speaking = false) {
        if (!ttsToggleBtn || !ttsIcon) return;

        if (!ttsEnabled || currentVolume === 0) {
            ttsIcon.className = 'fa-solid fa-volume-xmark';
            ttsToggleBtn.title = 'Voz silenciada (clic para activar)';
            ttsToggleBtn.style.backgroundColor = '#6c757d';
            ttsToggleBtn.classList.remove('speaking-pulse');
        } else if (speaking) {
            ttsIcon.className = 'fa-solid fa-volume-high';
            ttsToggleBtn.title = 'Hablando... (clic para silenciar)';
            ttsToggleBtn.style.backgroundColor = '#227D8E';
            ttsToggleBtn.classList.add('speaking-pulse');
        } else {
            ttsIcon.className = currentVolume < 0.5 ? 'fa-solid fa-volume-low' : 'fa-solid fa-volume-high';
            ttsToggleBtn.title = `Voz activada al ${Math.round(currentVolume * 100)}%`;
            ttsToggleBtn.style.backgroundColor = '#3b2818';
            ttsToggleBtn.classList.remove('speaking-pulse');
        }
    }

    function stopSpeaking() {
        if (ttsAbortController) {
            try { ttsAbortController.abort(); } catch (e) {}
            ttsAbortController = null;
        }

        if (currentMikuAudio) {
            try {
                currentMikuAudio.pause();
                currentMikuAudio.currentTime = 0;
                currentMikuAudio.src = "";
                currentMikuAudio.load();
            } catch (e) {}
            currentMikuAudio = null;
        }

        if ('speechSynthesis' in window) {
            try { window.speechSynthesis.cancel(); } catch (e) {}
        }

        updateTTSUI(false);
        resetToDefault(400);
    }

    function cleanTextForSpeech(text) {
        if (!text) return '';
        return text
            .replace(/<think>[\s\S]*?<\/think>/gi, '')
            .replace(/\[LIBRO:.*?\]?/gi, '')
            .replace(/https?:\/\/\S+/gi, '')
            .replace(/[*#_~`\[\]()<>]/g, '')
            .replace(/"/g, '')
            .replace(/\s+/g, ' ')
            .trim();
    }

    async function speakText(text) {
        if (!ttsEnabled || currentVolume === 0 || !text) return;
        stopSpeaking();

        const textoLimpio = cleanTextForSpeech(text);
        if (!textoLimpio) return;

        ttsAbortController = new AbortController();

        try {
            const res = await fetch('/api/miku-tts/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify({ text: textoLimpio }),
                signal: ttsAbortController.signal
            });

            if (!res.ok) throw new Error("Fallo al obtener audio Miku");
            const data = await res.json();

            if (!ttsEnabled || currentVolume === 0 || !data.audio_url) {
                stopSpeaking();
                return;
            }

            currentMikuAudio = new Audio(data.audio_url);
            currentMikuAudio.volume = currentVolume; // Aplica el volumen en vivo

            currentMikuAudio.onplay = () => {
                if (!ttsEnabled || currentVolume === 0) {
                    stopSpeaking();
                    return;
                }
                updateTTSUI(true);
                setAvatar("feliz.png");
            };

            currentMikuAudio.onended = () => {
                updateTTSUI(false);
                resetToDefault(3000);
                currentMikuAudio = null;
            };

            currentMikuAudio.onerror = () => {
                updateTTSUI(false);
                resetToDefault(1000);
                currentMikuAudio = null;
            };

            await currentMikuAudio.play().catch(e => {
                console.warn("Reproducción interrumpida o bloqueada:", e);
                updateTTSUI(false);
                currentMikuAudio = null;
            });

        } catch (err) {
            if (err.name !== 'AbortError') {
                console.warn("No se pudo reproducir la voz de Miku:", err);
            }
            updateTTSUI(false);
        }
    }

    // Control deslizante de volumen
    if (volumeSlider) {
        volumeSlider.addEventListener('input', (e) => {
            currentVolume = parseFloat(e.target.value);
            localStorage.setItem('litmate_miku_volume', currentVolume);

            if (volumeLabel) {
                volumeLabel.textContent = `${Math.round(currentVolume * 100)}%`;
            }

            // Aplicar inmediatamente al audio que esté sonando
            if (currentMikuAudio) {
                currentMikuAudio.volume = currentVolume;
            }

            if (currentVolume > 0) {
                ttsEnabled = true;
                previousVolume = currentVolume;
            } else {
                ttsEnabled = false;
                stopSpeaking();
            }

            updateTTSUI(currentMikuAudio && !currentMikuAudio.paused);
        });
    }

    // Botón de clic para silenciar o restaurar volumen
    if (ttsToggleBtn) {
        ttsToggleBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();

            if (ttsEnabled && currentVolume > 0) {
                // Silenciar
                previousVolume = currentVolume > 0 ? currentVolume : 1.0;
                currentVolume = 0;
                ttsEnabled = false;
                if (volumeSlider) volumeSlider.value = 0;
                if (volumeLabel) volumeLabel.textContent = '0%';
                stopSpeaking();
            } else {
                // Restaurar
                currentVolume = previousVolume > 0 ? previousVolume : 1.0;
                ttsEnabled = true;
                if (volumeSlider) volumeSlider.value = currentVolume;
                if (volumeLabel) volumeLabel.textContent = `${Math.round(currentVolume * 100)}%`;
                updateTTSUI(false);
            }

            localStorage.setItem('litmate_miku_volume', currentVolume);
        });
    }

    updateTTSUI(false);

    // =====================================================================
    // 2. MICRÓFONO (SPEECH RECOGNITION)
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
    }

    // =====================================================================
    // 3. EXPRESIONES DEL AVATAR
    // =====================================================================
    function setAvatar(file) {
        if (!avatar) return;
        avatar.src = `/static/assets/img/avatar/${file}?v=` + Date.now();
    }

    function resetToDefault(delay = 12000) {
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

    function applySmartEmotion(text, isSocial = false, genre = "none") {
        const msg = text.toLowerCase();
        if (isSocial || msg.includes("gracias")) setAvatar("agradecida.png");
        else if (genre === "terror" || msg.includes("miedo") || msg.includes("horror")) setAvatar("miedo.png");
        else if (genre === "accion" || msg.includes("guerra")) setAvatar("enojo.png");
        else if (genre === "drama" || msg.includes("triste")) setAvatar("triste.png");
        else if (genre === "fantasia" || msg.includes("increible")) setAvatar("sorprendida.png");
        else if (msg.includes("hola") || msg.includes("recomiendo")) setAvatar("feliz.png");
        else setAvatar("cuerpo.jpg");
        resetToDefault(12000);
    }

    // =====================================================================
    // 4. RESOLUTOR DE PORTADAS DE LIBROS
    // =====================================================================
    async function resolveBookCovers() {
        const containers = document.querySelectorAll('.chatbot-book-thumb-container:not([data-resolved])');

        for (const cont of containers) {
            cont.setAttribute('data-resolved', 'true');
            const img = cont.querySelector('.chatbot-book-thumb');
            const placeholder = cont.querySelector('.chatbot-book-placeholder');

            const title = decodeURIComponent(cont.getAttribute('data-title') || '').trim();
            const author = decodeURIComponent(cont.getAttribute('data-author') || '').trim();
            if (!title) continue;

            let coverLoaded = false;

            try {
                const q = encodeURIComponent(`intitle:${title} inauthor:${author}`);
                const res = await fetch(`https://www.googleapis.com/books/v1/volumes?q=${q}&maxResults=1`);
                if (res.ok) {
                    const data = await res.json();
                    const thumb = data?.items?.[0]?.volumeInfo?.imageLinks?.thumbnail ||
                                  data?.items?.[0]?.volumeInfo?.imageLinks?.smallThumbnail;
                    if (thumb) {
                        img.src = thumb.replace('http:', 'https:');
                        img.onload = () => {
                            img.style.display = 'block';
                            if (placeholder) placeholder.style.display = 'none';
                        };
                        coverLoaded = true;
                    }
                }
            } catch (e) {}

            if (!coverLoaded) {
                try {
                    const olRes = await fetch(`https://openlibrary.org/search.json?title=${encodeURIComponent(title)}&author=${encodeURIComponent(author)}&limit=1`);
                    if (olRes.ok) {
                        const olData = await olRes.json();
                        const coverId = olData?.docs?.[0]?.cover_i;
                        if (coverId) {
                            img.src = `https://covers.openlibrary.org/b/id/${coverId}-M.jpg`;
                            img.onload = () => {
                                img.style.display = 'block';
                                if (placeholder) placeholder.style.display = 'none';
                            };
                            coverLoaded = true;
                        }
                    }
                } catch (e) {}
            }

            if (!coverLoaded) {
                img.style.display = 'none';
                if (placeholder) placeholder.style.display = 'flex';
            }
        }
        scrollToBottom();
    }

    // =====================================================================
    // 5. PARSER DE MENSAJES Y TARJETAS
    // =====================================================================
    function formatMessageText(text) {
        if (!text) return '';

        let cleaned = text.replace(/<think>[\s\S]*?<\/think>/gi, '');
        cleaned = cleaned.replace(/Enlace de compra:\s*https?:\/\/\S+/gi, '');
        cleaned = cleaned.replace(/https?:\/\/(www\.)?buscalibre\.cl\/\S+/gi, '');

        let formatted = cleaned
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, '"$1"')
            .replace(/\*(.*?)\*/g, '$1')
            .replace(/^[ \t]*#+[ \t]*/gm, '')
            .replace(/[\*#]/g, '');

        formatted = formatted.replace(/\[LIBRO:\s*([^\]\n\r]+)\]?/gi, (match, content) => {
            const cleanContent = content.replace(/[\]]/g, '').trim();
            const parts = cleanContent.split('|').map(p => p.trim());

            const titulo = (parts[0] || 'Libro recomendado').replace(/["']/g, '');
            const autor = (parts[1] || 'Autor').replace(/["']/g, '');

            let rawPrecio = parts[2] || '$14.990 CLP';
            let precio = rawPrecio.replace(/[^\d.,$A-Za-z\s]/g, '').trim();
            if (!precio.includes('$')) precio = '$' + precio;

            const searchUrl = `https://www.buscalibre.cl/libros/search?q=${encodeURIComponent(titulo + ' ' + autor)}`;

            return `
                <div class="chatbot-book-card">
                    <div class="chatbot-book-thumb-container" data-title="${encodeURIComponent(titulo)}" data-author="${encodeURIComponent(autor)}">
                        <img src="" alt="${titulo}" class="chatbot-book-thumb" style="display:none;" onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
                        <div class="chatbot-book-placeholder">
                            <i class="fa-solid fa-book-bookmark book-spine-icon"></i>
                            <span class="book-spine-title">${titulo}</span>
                        </div>
                    </div>
                    <div class="chatbot-book-info">
                        <div class="chatbot-book-title" title="${titulo}">${titulo}</div>
                        <div class="chatbot-book-author">${autor}</div>
                        <div class="chatbot-book-price">${precio}</div>
                    </div>
                    <div class="chatbot-book-actions">
                        <a href="${searchUrl}" target="_blank" rel="noopener noreferrer" class="chatbot-book-btn">
                            Ver / Comprar
                        </a>
                    </div>
                </div>
            `;
        });

        return formatted.replace(/\n/g, '<br>');
    }

    // =====================================================================
    // 6. STREAMING SSE, CUOTAS Y ENVÍO DE MENSAJES
    // =====================================================================
    async function sendMessage(e) {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }

        const userMessage = chatInput ? chatInput.value.trim() : '';
        if (!userMessage) return false;

        stopSpeaking();

        appendMessage(userMessage, 'user');
        chatInput.value = '';
        if (sendBtn) sendBtn.disabled = true;

        beforeSend();

        const botMessageDiv = document.createElement('div');
        botMessageDiv.classList.add('chat-message', 'bot');
        const botParagraph = document.createElement('p');
        botParagraph.innerHTML = '<span class="spinner-border spinner-border-sm text-secondary"></span>';
        botMessageDiv.appendChild(botParagraph);
        chatBody.appendChild(botMessageDiv);
        scrollToBottom();

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

            if (response.status === 429) {
                let dataError = {};
                try {
                    dataError = await response.json();
                } catch (jsonErr) {
                    dataError = { response: 'Has alcanzado el límite diario de mensajes para tu plan.' };
                }

                const mensajeCuota = dataError.response || 'Has alcanzado el límite diario de consultas de tu plan.';
                const planNombre = (dataError.info_cuota && dataError.info_cuota.plan) ? dataError.info_cuota.plan : 'Plan Actual';

                botParagraph.innerHTML = `
                    <div class="quota-warning-box">
                        <i class="fa-solid fa-hourglass-end text-warning me-2"></i>
                        <strong>Límite diario alcanzado (${planNombre})</strong>
                        <p class="mt-2 mb-3 small text-muted">${mensajeCuota}</p>
                        <a href="/suscripciones/planes/" class="btn btn-sm btn-primary chatbot-upgrade-btn">
                            <i class="fa-solid fa-crown me-1"></i> Mejorar mi Membresía
                        </a>
                    </div>
                `;

                setAvatar("triste.png");
                resetToDefault(7000);
                scrollToBottom();
                return false;
            }

            if (!response.ok) {
                throw new Error(`HTTP Error ${response.status}`);
            }

            const contentType = response.headers.get("content-type") || "";

            if (contentType.includes("application/json")) {
                const json = await response.json();
                accumulatedText = json.response || json.error || "No se obtuvo respuesta.";
                botParagraph.innerHTML = formatMessageText(accumulatedText);
                scrollToBottom();
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
                                if (dataStr === "[DONE]") break;
                                try {
                                    const parsed = JSON.parse(dataStr);
                                    if (parsed.token) {
                                        if (isFirstToken) {
                                            botParagraph.innerHTML = "";
                                            isFirstToken = false;
                                        }
                                        accumulatedText += parsed.token;
                                        botParagraph.innerHTML = formatMessageText(accumulatedText);
                                        scrollToBottom();
                                    }
                                } catch (parseErr) {}
                            }
                        }
                    }
                }
            }

            resolveBookCovers();
            applySmartEmotion(accumulatedText);
            speakText(accumulatedText);

        } catch (error) {
            console.error("Error en chatbot query:", error);
            botParagraph.innerHTML = 'Lo siento, ocurrió un problema al conectar con el asistente.';
            onError();
        } finally {
            if (sendBtn) sendBtn.disabled = false;
            if (chatInput) chatInput.focus();
            scrollToBottom();
        }

        return false;
    }

    if (chatForm) chatForm.addEventListener('submit', sendMessage);

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
        scrollToBottom();
        resolveBookCovers();
    }

    // =====================================================================
    // 7. PARALLAX 2.5D (SEGUIMIENTO DEL CURSOR)[cite: 1]
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