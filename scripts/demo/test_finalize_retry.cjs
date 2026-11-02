// Regresión del 409 transitorio de dos lectores con una cuota/IP compartida.
const assert = require('node:assert/strict');
const Safe = require('../../static/js/litmate_safe.js');
const token = 'r'.repeat(43);
const ready = () => new Response('data: ' + JSON.stringify({ready: token}) + '\n\ndata: [DONE]\n\n',
    {headers: {'Content-Type': 'text/event-stream'}});
const busy = retry => new Response(JSON.stringify({response: 'Guardando otra respuesta.'}),
    {status: 409, headers: {'Content-Type': 'application/json', ...(retry ? {'Retry-After': '1'} : {})}});

async function run() {
    const calls = [];
    const env = {AbortController, clearTimeout,
        setTimeout(callback, delay) {return setTimeout(callback, delay <= 2000 ? 0 : delay);},
        async fetch(url, options) {
            calls.push({url, options});
            if (url === '/chatbot_query/') return ready();
            if (calls.length === 2) return busy(true);
            return Response.json({response: 'Respuesta ya verificada.', status: 'answered', books: []});
        }};
    assert.equal(await Safe.queryChat('Pregunta', () => {}, () => {}, {environment: env}), 'Respuesta ya verificada.');
    assert.equal(calls.filter(call => call.url === '/chatbot_query/').length, 1);
    assert.equal(calls.length, 3);
    assert.equal(calls[1].options.body, calls[2].options.body);
    assert.equal(calls[0].options.signal, calls[2].options.signal);

    for (const retry of [false, true]) {
        let attempts = 0;
        const failedEnv = {...env, async fetch(url) {
            if (url === '/chatbot_query/') return ready();
            attempts++;
            return busy(retry);
        }};
        await assert.rejects(() => Safe.queryChat('Pregunta', () => {}, () => {}, {environment: failedEnv}));
        assert.equal(attempts, retry ? 3 : 1);
    }
    let finalizations = 0;
    const deadlineEnv = {AbortController, setTimeout, clearTimeout, async fetch(url) {
        if (url === '/chatbot_query/') return ready();
        finalizations++;
        return busy(true);
    }};
    await assert.rejects(() => Safe.queryChat('Pregunta', () => {}, () => {},
        {environment: deadlineEnv, timeout: 5}), /límite/i);
    await new Promise(resolve => setTimeout(resolve, 1050));
    assert.equal(finalizations, 1);
    console.log('4 casos de finalización: reintento idempotente, conflicto definitivo, límite y deadline OK.');
}
run().catch(error => {console.error(error); process.exitCode = 1;});
