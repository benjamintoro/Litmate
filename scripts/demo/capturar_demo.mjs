// CDP nativo de Edge; no instala paquetes, no altera la aplicación ni fabrica respuestas.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
input = '';
if (!Number.isInteger(config.port ?? 8002) || (config.port ?? 8002) < 1024 || (config.port ?? 8002) > 65535) {
  throw new Error('Puerto local inválido.');
}
const origin = 'http://127.0.0.1:' + (config.port ?? 8002);
const root = process.cwd();
const folder = path.resolve(config.folder);
if (!folder.startsWith(path.join(root, 'reports') + path.sep) || fs.existsSync(folder)) {
  throw new Error('Carpeta de capturas no válida o existente.');
}
fs.mkdirSync(folder, {recursive: true});
const profile = path.join(root, '.testtmp', 'edge-demo-' + Date.now());
fs.mkdirSync(profile, {recursive: true});
const browser = spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ['--headless=new', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0',
   '--remote-debugging-address=127.0.0.1', '--user-data-dir=' + profile, '--window-size=1280,800', 'about:blank'],
  {stdio: 'ignore', windowsHide: true});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
let counter = 0;
const pending = new Map();
const frames = [], conversation = [], errors = [], http = [];
const navigation = [];
let sessionPreservedAcrossNavigation = null;
const started = performance.now();
const elapsed = () => (performance.now() - started) / 1000;
let capturing = false;
async function command(method, params = {}) {
  const id = ++counter;
  return await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('CDP timeout: ' + method)); }, 15000);
    pending.set(id, {resolve: value => {clearTimeout(timer); resolve(value);},
                     reject: value => {clearTimeout(timer); reject(value);}});
    socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const result = await command('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw new Error('No se pudo ejecutar la comprobación del navegador.');
  return result.result.value;
}
async function capture() {
  if (capturing || frames.length >= 90) return;
  capturing = true;
  try {
    const result = await command('Page.captureScreenshot', {format: 'png'});
    const file = 'frame-' + String(frames.length).padStart(3, '0') + '.png';
    fs.writeFileSync(path.join(folder, file), Buffer.from(result.data, 'base64'));
    frames.push({file, seconds: elapsed()});
  } finally {capturing = false;}
}
async function navigate(route) {
  const clicked = await evaluate(`(() => {
    const link = Array.from(document.querySelectorAll('a[href]')).find(a =>
      a.getAttribute('href') === ${JSON.stringify(route)} && a.getClientRects().length > 0);
    if (!link) return false;
    link.click(); return true;
  })()`);
  if (!clicked) await command('Page.navigate', {url: origin + route});
  let ready = false;
  for (let tries = 0; tries < 100; tries++) {
    ready = await evaluate(`location.pathname === ${JSON.stringify(route)} && document.readyState === 'complete' && Boolean(document.querySelector('.navbar-brand'))`);
    if (ready) break;
    await sleep(200);
  }
  const status = await evaluate(`({path: location.pathname, ready: ${Boolean(ready)},
    localBrokenImages: Array.from(document.images).filter(img => img.getAttribute('src') && img.src.startsWith(${JSON.stringify(origin)}) && img.complete && img.naturalWidth === 0).map(img => new URL(img.src).pathname),
    externalBrokenImages: Array.from(document.images).filter(img => img.getAttribute('src') && !img.src.startsWith(${JSON.stringify(origin)}) && img.complete && img.naturalWidth === 0).map(img => img.src),
    loadedImages: Array.from(document.images).filter(img => img.complete && img.naturalWidth > 0).length,
    previewNotice: Boolean(document.querySelector('.alert-info[role="status"]'))})`);
  status.navigationMethod = clicked ? 'existing-link-click' : 'direct-url';
  navigation.push(status);
  if (!ready) throw new Error('La navegación no terminó: ' + route);
}
let timer;
try {
  const active = path.join(profile, 'DevToolsActivePort');
  for (let tries = 0; tries < 100 && !fs.existsSync(active); tries++) await sleep(200);
  const port = Number(fs.readFileSync(active, 'utf8').split('\n')[0]);
  const targets = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
  socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  socket.onmessage = async event => {
    const message = JSON.parse(event.data);
    if (message.id) {
      const item = pending.get(message.id);
      if (item) {pending.delete(message.id); message.error ? item.reject(new Error(message.error.message)) : item.resolve(message.result);}
    } else if (message.method === 'Fetch.requestPaused') {
      await command('Fetch.continueRequest', {requestId: message.params.requestId});
    } else if (message.method === 'Fetch.authRequired') {
      // Nunca envía la contraseña a Google Fonts, portadas u otros dominios.
      const local = message.params.authChallenge.origin === origin;
      await command('Fetch.continueWithAuth', {requestId: message.params.requestId,
        authChallengeResponse: local ? {response: 'ProvideCredentials', username: 'demo', password: config.password}
                                    : {response: 'CancelAuth'}});
    } else if (message.method === 'Runtime.exceptionThrown') {
      errors.push('Excepción JavaScript en la página de demo.');
    } else if (message.method === 'Network.responseReceived') {
      const response = message.params.response;
      if (response.url.startsWith(origin + '/')) {
        http.push({path: new URL(response.url).pathname, status: response.status,
                   mimeType: response.mimeType, seconds: elapsed()});
      }
    }
  };
  await command('Page.enable');
  await command('Runtime.enable');
  await command('Network.enable');
  await command('Fetch.enable', {handleAuthRequests: true, patterns: [{urlPattern: origin + '/*'}]});
  if (config.navigation) {
    for (const route of ['/', '/about/', '/post/', '/libros/', '/suscripciones/planes/', '/contact/',
                         '/login/', '/registro/', '/password-reset/', '/terminos-y-condiciones/',
                         '/politica-de-privacidad/', '/politica-de-cookies/']) {
      await navigate(route);
      if (route === '/' || route === '/libros/') await capture();
    }
  }
  await command('Page.navigate', {url: origin + '/chat/'});
  let ready = false;
  for (let tries = 0; tries < 100; tries++) {
    ready = await evaluate("Boolean(document.getElementById('chat-input') && window.LitMateSafe)");
    if (ready) break;
    await sleep(200);
  }
  if (!ready) throw new Error('La interfaz no terminó de cargar.');
  // Controles reales de la interfaz; no modifica estilos ni respuestas.
  await evaluate("document.getElementById('btnRejectCookies')?.click();if(!document.documentElement.classList.contains('dark-mode'))document.getElementById('themeToggleBtn')?.click();true");
  await sleep(700);
  await evaluate("document.getElementById('chat-container')?.scrollIntoView({block:'center'});true");
  await capture();
  timer = setInterval(() => {capture().catch(() => {});}, 2000);
  const questions = config.navigation ? [
    'Recomiéndame dos novelas de fantasía en español', 'Cuéntame más del segundo'
  ] : [
    'Recuerdo un libro donde un niño vive en un planeta pequeño y cuida una rosa',
    '¿Qué pistas te hicieron pensar en ese libro?',
    '¿Qué relación hay entre el principito y el zorro?',
    'Recomiéndame dos novelas de fantasía en español',
    'Ya leí el primero y no me interesa el segundo',
    'Dame otros dos libros de fantasía en español',
    'Cuéntame más del segundo',
    '¿Dónde puedo encontrarlo?'
  ];
  for (const question of questions) {
    if (config.navigation && conversation.length === 1) {
      const beforeCookies = await command('Network.getCookies', {urls: [origin + '/chat/']});
      const previousSession = beforeCookies.cookies.find(cookie => cookie.name === 'litmate_demo_sessionid')?.value;
      await navigate('/about/');
      await navigate('/libros/');
      await navigate('/chat/');
      const afterCookies = await command('Network.getCookies', {urls: [origin + '/chat/']});
      sessionPreservedAcrossNavigation = Boolean(previousSession) && previousSession ===
        afterCookies.cookies.find(cookie => cookie.name === 'litmate_demo_sessionid')?.value;
    }
    const before = await evaluate("document.querySelectorAll('.chat-message.bot').length");
    const stamp = elapsed();
    await evaluate("document.getElementById('chat-input').value=" + JSON.stringify(question) + ";document.getElementById('chat-form').requestSubmit();true");
    let done = false;
    for (let tries = 0; tries < 100; tries++) {
      await sleep(500);
      done = await evaluate("!document.getElementById('send-btn').disabled && document.querySelectorAll('.chat-message.bot').length>" + before);
      if (done) break;
    }
    const answer = await evaluate("Array.from(document.querySelectorAll('.chat-message.bot')).at(-1).innerText");
    await evaluate("document.getElementById('chat-container')?.scrollIntoView({block:'center'});true");
    conversation.push({question, answer, completed: done, seconds: elapsed() - stamp});
    await capture();
    if (!done) break;
    // Ritmo humano para conservar intactos los límites de solicitudes.
    await sleep(11000);
  }
  clearInterval(timer);
  await sleep(500);
  await capture();
  console.log(JSON.stringify({capturedFrames: frames.length, completedTurns: conversation.filter(turn => turn.completed).length}));
} finally {
  clearInterval(timer);
  fs.writeFileSync(path.join(folder, 'captura.json'), JSON.stringify({
    authenticBrowserCapture: true, externalNetworkTested: false, origin,
    frames, conversation, navigation, sessionPreservedAcrossNavigation, errors, http
  }, null, 2), 'utf8');
  try {if (socket?.readyState === 1) await command('Browser.close');} catch {}
  socket?.close();
  if (browser.exitCode === null) browser.kill();
}
