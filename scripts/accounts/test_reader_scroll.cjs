// Carrera reproducida sin red: gesto hacia arriba y escritura SSE antes de scroll.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {};
class Element {
    constructor() { this.top = 500; this.clientHeight = 200; this.scrollHeight = 1000; this.events = {}; }
    get scrollTop() { return this.top; }
    set scrollTop(value) { this.top = Math.max(0, Math.min(Number(value), 800)); }
    addEventListener(name, callback) { this.events[name] = callback; }
    querySelectorAll() { return []; }
}
const body = new Element();
const form = new Element();
let clock = 0;
const document = {
    documentElement: {classList: {add() {}}, style: {setProperty() {}}},
    addEventListener(name, callback) { listeners[name] = callback; },
    getElementById(id) { return {'chat-body-page': body, 'chat-form': form}[id] || null; }
};
const context = {
    document, Element, performance: {now: () => clock}, URL,
    location: {href: 'http://127.0.0.1/chat/', origin: 'http://127.0.0.1'},
    MutationObserver: class { observe() {} },
    window: {innerWidth: 390, innerHeight: 844, addEventListener() {},
        fetch: async () => ({json: async () => ({})})}
};
vm.runInNewContext(fs.readFileSync('static/js/reader-transport.js', 'utf8'), context);
listeners.DOMContentLoaded();
body.events.wheel({deltaY: -300});
body.scrollTop = 0;
// Todavía no se ha entregado scroll; el cliente anterior intenta bajar al final.
body.scrollTop = body.scrollHeight;
assert.equal(body.scrollTop, 0);
clock = 300;
body.scrollTop = body.scrollHeight;
assert.equal(body.scrollTop, 0);
// Un gesto nativo no utiliza el setter de la instancia: simular desplazamiento.
body.events.wheel({deltaY: 300});
Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop').set.call(body, 800);
body.events.scroll();
body.scrollTop = 650;
assert.equal(body.scrollTop, 650);
body.events.wheel({deltaY: -300});
body.scrollTop = 100;
form.events.submit();
body.scrollTop = body.scrollHeight;
assert.equal(body.scrollTop, 800);
assert.equal(Object.hasOwn(Element.prototype, 'top'), false);
console.log('4 casos de scroll: carrera SSE, espera, gesto al final y nuevo envio OK.');
