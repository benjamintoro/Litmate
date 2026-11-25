(() => {
    const target = document.getElementById('litmate-online-count');
    if (!target) return;
    let busy = false;
    async function heartbeat() {
        if (document.hidden || busy) return;
        busy = true;
        try {
            const csrf = document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.slice(10);
            const response = await fetch('/api/presencia/', { method: 'POST',
                headers: { 'X-CSRFToken': csrf || '' }, cache: 'no-store' });
            if (!response.ok) throw Error('presence');
            const { online } = await response.json();
            target.textContent = online === 1 ? '1 lector conectado' : online + ' lectores conectados';
        } catch {
            target.textContent = 'Conectados · temporalmente no disponible';
        } finally { busy = false; }
    }
    void heartbeat();
    setInterval(heartbeat, 30000);
    document.addEventListener('visibilitychange', heartbeat);
    window.addEventListener('pageshow', heartbeat);
})();
