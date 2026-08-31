/**
 * LitMate AI Chatbot - Lógica Original del Asistente Literario
 */

document.addEventListener('DOMContentLoaded', () => {

    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatBody = document.getElementById('chat-body-page');
    const sendBtn = document.getElementById('send-btn');
    const avatar = document.querySelector("#chat-character-page img");

    let resetTimer = null;

    // --- 1. AVATAR Y EMOCIONES ---
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
            .replace(/([a-zA-Z])\1{2,}/g, "$1")
            .trim()
            .toLowerCase();
    }

    const genreKeywords = {
        fantasia: ["fantasia","magia","magico","dragon","dragones","elfo","elfos","orcos","hechizo","hechicero","mago","criatura","espada","medieval","mitologia"],
        terror: ["terror","horror","miedo","espanto","fantasma","demonio","espiritu","bruja","sombras","pesadilla","sangre","sangriento"],
        accion: ["guerra","militar","batalla","conflicto","soldado","ejercito","armas","combate","accion","belico","explosion","tiroteo"],
        romance: ["romance","amor","pareja","enamorar","relacion","romantico","corazon","beso"],
        drama: ["drama","dramatico","tragedia","triste","perdida","dolor","llorar","sentimental","realista"],
        scifi: ["ciencia ficcion","sci fi","espacio","nave","robot","androide","futuro","distopia","apocalipsis","tecnologia","inteligencia artificial"]
    };

    function detectGenreSmart(message) {
        const msg = normalizeText(message);
        for (const genre in genreKeywords) {
            for (const word of genreKeywords[genre]) {
                const normalizedWord = normalizeText(word);
                if (msg.includes(normalizedWord) || fuzzyMatch(msg, normalizedWord)) {
                    return genre;
                }
            }
        }
        return "none";
    }

    function fuzzyMatch(msg, keyword) {
        const distance = levenshteinDistance(msg, keyword);
        return distance <= 2 && msg.length >= keyword.length - 2;
    }

    function levenshteinDistance(a, b) {
        const matrix = [];
        for (let i = 0; i <= b.length; i++) matrix[i] = [i];
        for (let j = 0; j <= a.length; j++) matrix[0][j] = j;

        for (let i = 1; i <= b.length; i++) {
            for (let j = 1; j <= a.length; j++) {
                matrix[i][j] = b.charAt(i - 1) === a.charAt(j - 1)
                    ? matrix[i - 1][j - 1]
                    : Math.min(
                        matrix[i - 1][j - 1] + 1,
                        matrix[i][j - 1] + 1,
                        matrix[i - 1][j] + 1
                    );
            }
        }
        return matrix[b.length][a.length];
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

        if (msg.includes("hola") || msg.includes("buenas") || msg.includes("buen dia") || msg.includes("buenas tardes") || msg.includes("buenas noches")) {
            setAvatar("feliz.png");
            resetToDefault();
            return;
        }

        if (msg.includes("como estas") || msg.includes("que tal") || msg.includes("todo bien") || msg.includes("gracias") || msg.includes("muchas gracias")) {
            setAvatar("agradecida.png");
            resetToDefault();
            return;
        }

        if (msg.includes("adios") || msg.includes("chao") || msg.includes("hasta luego") || msg.includes("nos vemos")) {
            setAvatar("agradecida.png");
            resetToDefault(8000);
            return;
        }

        if (msg.includes("no encontre") || msg.includes("error") || msg.includes("no puedo")) {
            setAvatar("triste.png");
            resetToDefault();
            return;
        }

        if (msg.includes("como") || msg.includes("que") || msg.includes("?")) {
            setAvatar("pensativa.png");
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
            msg.includes("todo bien") ||
            msg.includes("hola") ||
            msg.includes("buenas")
        );
    }

    // --- 2. FORMATO DE TEXTO ESTRUCTURADO (SIN * NI #) ---
    function formatMessageText(text) {
        if (!text) return '';
        let formatted = text
            // Escapar HTML peligroso
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            // Convertir cualquier **texto** en "texto" y limpiar asteriscos / hashtags
            .replace(/\*\*(.*?)\*\*/g, '"$1"')
            .replace(/\*(.*?)\*/g, '$1')
            .replace(/^[ \t]*#+[ \t]*/gm, '')
            .replace(/[\*#]/g, '')
            // Enlaces a librerías
            .replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer" style="color: #0085a1; font-weight: 600; text-decoration: underline;">$1</a>')
            // Saltos de línea
            .replace(/\n/g, '<br>');

        return formatted;
    }

    // --- 3. ENVIAR MENSAJE ---
    async function sendMessage(e) {
        e.preventDefault();
        const userMessage = chatInput.value.trim();
        if (!userMessage) return;

        const genreDetected = detectGenreSmart(userMessage);
        const socialDetected = isSocialMessage(userMessage);

        appendMessage(userMessage, 'user');
        chatInput.value = '';
        sendBtn.disabled = true;

        beforeSend();
        showTypingIndicator();

        try {
            const response = await fetch("/chatbot_query/", {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken'),
                },
                body: JSON.stringify({ message: userMessage }),
            });

            const data = await response.json();
            hideTypingIndicator();
            appendMessage(data.response, 'bot');

            if (socialDetected) {
                setAvatar("agradecida.png");
                resetToDefault();
            } else if (genreDetected !== "none") {
                applyGenreEmotion(genreDetected);
            } else {
                applyBackendEmotion(data.response);
            }

        } catch (error) {
            hideTypingIndicator();
            appendMessage('Lo siento, ocurrió un error de conexión.', 'bot');
            onError();
        } finally {
            sendBtn.disabled = false;
            chatInput.focus();
        }
    }

    if (chatForm) {
        chatForm.addEventListener('submit', sendMessage);
    }

    // --- 4. HELPERS ---
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let cookie of cookies) {
                cookie = cookie.trim();
                if (cookie.startsWith(name + '=')) {
                    cookieValue = decodeURIComponent(cookie.slice(name.length + 1));
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

    function showTypingIndicator() {
        const div = document.createElement('div');
        div.id = 'typing-indicator';
        div.classList.add('chat-message', 'bot', 'typing-indicator');
        div.innerHTML = `<span></span><span></span><span></span>`;
        chatBody.appendChild(div);
        chatBody.scrollTop = chatBody.scrollHeight;
    }

    function hideTypingIndicator() {
        const ind = document.getElementById('typing-indicator');
        if (ind) ind.remove();
    }

    // Scroll inicial
    if (chatBody) {
        chatBody.scrollTop = chatBody.scrollHeight;
    }

});
