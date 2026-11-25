(() => {
    const social = document.querySelector('.lm-social');
    if (!social) return;

    for (const form of social.querySelectorAll('[data-like-form]')) {
        form.addEventListener('submit', async event => {
            event.preventDefault();
            const button = form.querySelector('button');
            if (button.disabled) return;
            button.disabled = true;
            let feedback = form.querySelector('[role=status]');
            if (!feedback) {
                feedback = document.createElement('span');
                feedback.setAttribute('role', 'status');
                form.appendChild(feedback);
            }
            feedback.textContent = '';
            try {
                const data = new URLSearchParams(new FormData(form));
                data.set('action', button.value);
                const response = await fetch(form.getAttribute('action'), { method: 'POST', body: data,
                    headers: { Accept: 'application/json' } });
                if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) {
                    throw Error('No pudimos actualizar el corazón. Comprueba tu sesión e inténtalo otra vez.');
                }
                const result = await response.json();
                button.value = result.liked ? 'remove' : 'add';
                button.setAttribute('aria-pressed', String(result.liked));
                button.setAttribute('aria-label', result.liked ? 'Quitar Me gusta' : 'Me gusta');
                button.querySelector('[data-heart]').textContent = result.liked ? '♥' : '♡';
                button.querySelector('[data-like-count]').textContent = result.count;
                if (!result.liked && data.get('action') === 'add') {
                    feedback.textContent = 'Habilita tu perfil público en Configuración para participar.';
                }
            } catch (error) { feedback.textContent = error.message; }
            finally { button.disabled = false; }
        });
    }
    for (const link of social.querySelectorAll('[data-reply-to]')) {
        link.addEventListener('click', () => {
            const input = social.querySelector('#comment-form textarea[name=body]');
            if (input) {
                input.value = '@' + link.dataset.replyTo + ' ';
                input.focus();
            }
        });
    }

    for (const image of social.querySelectorAll('[data-cover-image]')) {
        const hideBroken = () => { image.hidden = true; };
        image.addEventListener('error', hideBroken);
        if (image.complete && image.naturalWidth <= 1) hideBroken();
        image.addEventListener('load', () => { if (image.naturalWidth <= 1) hideBroken(); });
    }
    for (const button of social.querySelectorAll('[data-share]')) {
        button.hidden = false;
        button.addEventListener('click', async () => {
            const url = new URL(button.dataset.share, location.origin).href;
            const feedback = social.querySelector('[data-share-status]');
            try {
                await navigator.clipboard.writeText(url);
                feedback.textContent = 'Enlace copiado.';
            } catch {
                feedback.textContent = url;
            }
        });
    }
    for (const link of social.querySelectorAll('[data-choose-book]')) {
        link.addEventListener('click', event => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            const input = social.querySelector('[name=catalogue_id]');
            input.value = link.dataset.chooseBook;
            social.querySelector('[data-book-selected]').textContent = input.value
                ? 'Libro vinculado · ' + link.dataset.bookLabel : 'Sin libro vinculado';
        });
    }
    for (const form of social.querySelectorAll('[data-submit-once]')) {
        form.addEventListener('submit', event => {
            if (form.dataset.submitting) event.preventDefault();
            form.dataset.submitting = 'true';
            form.querySelector('button[type=submit], button:not([type])')?.setAttribute('aria-disabled', 'true');
        });
        window.addEventListener('pageshow', () => {
            delete form.dataset.submitting;
            form.querySelector('[aria-disabled=true]')?.removeAttribute('aria-disabled');
        });
    }
    const profile = social.querySelector('[data-profile-form]');
    if (!profile) return;
    const inputs = [...profile.querySelectorAll('input[type=file]')];
    const status = profile.querySelector('[data-upload-status]');
    const focus = profile.querySelector('[name=cover_focus]');
    const position = { center: '50% 50%', top: '50% 0%', bottom: '50% 100%', left: '0% 50%', right: '100% 50%' };
    focus?.addEventListener('change', () => {
        profile.querySelector('[data-preview=cover]').style.objectPosition = position[focus.value] || position.center;
    });
    const validateSize = () => {
        const total = inputs.reduce((sum, input) => sum + (input.files[0]?.size || 0), 0);
        const message = total > 2 * 1024 * 1024 ? 'Las imágenes juntas no pueden superar 2 MiB.' : '';
        for (const input of inputs) input.setCustomValidity(message);
        status.textContent = message;
    };
    for (const input of inputs) {
        const preview = profile.querySelector('[data-preview=' + input.name + ']');
        const original = preview.getAttribute('src');
        let blob = null;
        input.addEventListener('change', () => {
            validateSize();
            if (blob) URL.revokeObjectURL(blob);
            blob = input.files[0] ? URL.createObjectURL(input.files[0]) : null;
            const source = blob || original;
            preview.hidden = !source;
            if (source) preview.src = source;
            else preview.removeAttribute('src');
        });
    }
})();
