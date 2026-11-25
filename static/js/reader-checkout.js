(() => {
    for (const form of document.querySelectorAll('.lm-checkout [data-submit-once]')) {
        form.addEventListener('submit', event => {
            if (form.dataset.submitting) event.preventDefault();
            form.dataset.submitting = 'true';
        });
        window.addEventListener('pageshow', () => { delete form.dataset.submitting; });
    }
    for (const button of document.querySelectorAll('[data-print]')) {
        button.hidden = false;
        button.addEventListener('click', () => window.print());
    }
})();
