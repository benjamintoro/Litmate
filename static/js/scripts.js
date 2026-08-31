/*!
* Start Bootstrap - Clean Blog v6.0.9 (https://startbootstrap.com/theme/clean-blog)
* Copyright 2013-2023 Start Bootstrap
* Licensed under MIT (https://github.com/StartBootstrap/startbootstrap-clean-blog/blob/master/LICENSE)
*/
window.addEventListener('DOMContentLoaded', () => {
    let scrollPos = 0;
    const mainNav = document.getElementById('mainNav');
    if (!mainNav) return;
    
    const headerHeight = mainNav.clientHeight || 50;

    window.addEventListener('scroll', function() {
        const currentTop = document.body.getBoundingClientRect().top * -1;
        if (currentTop < scrollPos) {
            // Scrolling Up
            if (currentTop > 0 && mainNav.classList.contains('is-fixed')) {
                mainNav.classList.add('is-visible');
            } else {
                mainNav.classList.remove('is-visible', 'is-fixed');
            }
        } else {
            // Scrolling Down
            mainNav.classList.remove('is-visible');
            if (currentTop > headerHeight && !mainNav.classList.contains('is-fixed')) {
                mainNav.classList.add('is-fixed');
            }
        }
        scrollPos = currentTop;
    });
});

// ScrollReveal seguro (solo si la librería está cargada)
if (typeof ScrollReveal !== 'undefined') {
    try {
        window.sr = ScrollReveal();
        sr.reveal('h3, h4, h5, h6, p, section, .card', {
            duration: 700,
            origin: 'bottom',
            distance: '30px',
            interval: 100,   
            reset: false     
        });
    } catch (e) {
        console.warn("ScrollReveal warning:", e);
    }
}