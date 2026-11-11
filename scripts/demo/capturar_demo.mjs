// CDP nativo de Edge; no instala paquetes, no altera la aplicación ni fabrica respuestas.
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {randomBytes} from 'node:crypto';
let input = '';
for await (const chunk of process.stdin) input += chunk;
const config = JSON.parse(input);
input = '';
if (!Number.isInteger(config.port ?? 8002) || (config.port ?? 8002) < 1024 || (config.port ?? 8002) > 65535) {
  throw new Error('Puerto local inválido.');
}
const origin = config.productionOpen ? config.origin : 'http://127.0.0.1:' + (config.port ?? 8002);
if(config.productionOpen && (new URL(origin).hostname!=='litmate.example.test' || new URL(origin).protocol!=='https:' || config.port===8003))throw new Error('El navegador de producción sólo admite el dominio ficticio del ensayo.');
const root = process.cwd();
const folder = path.resolve(config.folder);
if (!folder.startsWith(path.join(root, 'reports') + path.sep) || fs.existsSync(folder)) {
  throw new Error('Carpeta de capturas no válida o existente.');
}
fs.mkdirSync(folder, {recursive: true});
const profile = path.join(root, '.testtmp', 'edge-demo-' + Date.now());
fs.mkdirSync(profile, {recursive: true});
const browser = spawn('C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--remote-debugging-port=0',
   ...(config.productionOpen ? ['--host-resolver-rules=MAP litmate.example.test 127.0.0.1','--ignore-certificate-errors','--no-proxy-server'] : []),
   '--remote-debugging-address=127.0.0.1', '--user-data-dir=' + profile, '--window-size=1280,800', 'about:blank'],
  {stdio: 'ignore', windowsHide: true});
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
let counter = 0;
const pending = new Map();
const frames = [], conversation = [], errors = [], http = [];
const navigation = [];
const mobileChecks = [];
let scrollAudit = [];
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
    ready = await evaluate(`location.pathname === ${JSON.stringify(route.split('?')[0])} && document.readyState === 'complete' && Boolean(document.querySelector('.navbar-brand'))`);
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
async function sendReaderMessage(question, readEarlier = false) {
  const before = await evaluate("document.querySelectorAll('#chat-body-page .chat-message.bot').length");
  await evaluate(`document.getElementById('chat-input').value=${JSON.stringify(question)};document.getElementById('chat-form').requestSubmit();true`);
  if (readEarlier) await evaluate("(()=>{const b=document.getElementById('chat-body-page');b.dispatchEvent(new WheelEvent('wheel',{deltaY:-300}));b.scrollTop=0;return true})()");
  for (let i=0;i<100;i++) {
    if (await evaluate(`!document.getElementById('send-btn').disabled && document.querySelectorAll('#chat-body-page .chat-message.bot').length>${before}`)) break;
    await sleep(500);
  }
  const answer = await evaluate("Array.from(document.querySelectorAll('#chat-body-page .chat-message.bot')).at(-1).innerText");
  conversation.push({question,answer});
}
async function readerMobile() {
  await command('Emulation.setDeviceMetricsOverride', {width:390,height:844,deviceScaleFactor:1,mobile:true});
  await navigate('/chat/');
  await evaluate("document.getElementById('btnRejectCookies')?.click();true");
  await sleep(500);
  if (!config.readerLibrary) {
  await sendReaderMessage('Hola');
  await sendReaderMessage('Recomiéndame un libro');
  mobileChecks.push({case:'guest_actions',passed:await evaluate("!document.getElementById('reader-actions').hidden && document.getElementById('reader-actions').querySelectorAll('a').length===3")});
  }
  const user = 'movil_' + randomBytes(5).toString('hex');
  const password = randomBytes(24).toString('base64url');
  await navigate('/registro/');
  const registered = await evaluate(`(async()=>{const csrf=document.cookie.split('; ').find(v=>v.startsWith('csrftoken=')).split('=')[1];const r=await fetch('/registro/',{method:'POST',headers:{'X-CSRFToken':csrf},body:new URLSearchParams(${JSON.stringify({username:user,email:user+'@example.invalid',password,password_confirm:password})})});return r.ok && new URL(r.url).pathname==='/suscripciones/planes/'})()`);
  mobileChecks.push({case:'registration',passed:registered});
  await navigate('/suscripciones/planes/');
  await evaluate("document.querySelector('form[action=\"/cuenta/activar-gratis/\"]').requestSubmit();true");
  for(let i=0;i<100;i++){if(await evaluate("location.pathname==='/chat/' && Boolean(window.LitMateSafe) && Boolean(document.getElementById('chat-input'))"))break;await sleep(200);}
  await sleep(500);
  if (!config.readerLibrary) {
  await sendReaderMessage('Recomiéndame dos novelas de fantasía en español');
  await evaluate("Promise.race([Promise.allSettled(Array.from(document.querySelectorAll('.lm-chat-book-cover img')).map(img=>img.decode())),new Promise(r=>setTimeout(r,5000))])");
  mobileChecks.push(await evaluate("(()=>{const imgs=Array.from(document.querySelectorAll('.lm-chat-book-cover img'));return {case:'cover_elements',total:imgs.length,loaded:imgs.filter(i=>i.naturalWidth>0).length,pending:imgs.filter(i=>!i.complete).length,failed:imgs.filter(i=>i.complete&&!i.naturalWidth).length,passed:imgs.length===2}})()"));
  for (const [width,height] of [[320,568],[360,640],[375,667],[390,844],[414,896],[430,932],[768,1024],[844,390],[1280,800]]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:width<768});
    await sleep(350);
    const data = await evaluate(`(()=>{const r=document.getElementById('chat-input').getBoundingClientRect();const f=document.getElementById('chat-form').getBoundingClientRect();return {width:${width},height:${height},horizontalOverflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1,inputWidth:r.width,formLeft:f.left,formRight:f.right,viewportWidth:document.documentElement.clientWidth,cards:document.querySelectorAll('.lm-chat-book-card').length}})()`);
    data.passed = !data.horizontalOverflow && data.inputWidth>=50 && data.formLeft>=-1 && data.formRight<=data.viewportWidth+1 && data.cards===2;
    if(data.horizontalOverflow) data.overflowElements=await evaluate("Array.from(document.querySelectorAll('body *')).map(e=>({e,r:e.getBoundingClientRect()})).filter(({e,r})=>r.width>0 && (r.right>document.documentElement.clientWidth+1 || r.left< -1) && getComputedStyle(e).visibility!=='hidden').slice(0,12).map(({e,r})=>({tag:e.tagName,id:e.id,css:e.className,left:r.left,right:r.right}))");
    mobileChecks.push(data);
    if([320,390,768,1280].includes(width))await capture();
  }
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await sleep(500);
  await sendReaderMessage('Cuéntame más del segundo',true);
  await sleep(200);
  await capture();
  mobileChecks.push(await evaluate("(()=>{const b=document.getElementById('chat-body-page');return {case:'reading_earlier_not_interrupted',top:b.scrollTop,scrollHeight:b.scrollHeight,clientHeight:b.clientHeight,passed:b.scrollTop<5}})()"));
  scrollAudit = await evaluate('window.__readerScrollAudit || []');
  await evaluate("document.getElementById('chat-input').focus();true");
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:360,deviceScaleFactor:1,mobile:true});
  await sleep(500);
  await capture();
  const keyboard = await evaluate("(()=>{const r=document.getElementById('chat-input').getBoundingClientRect();return {case:'reduced_viewport_keyboard_simulation',top:r.top,bottom:r.bottom,viewport:visualViewport.height,passed:r.top>=0 && r.bottom<=visualViewport.height+1}})()");
  mobileChecks.push(keyboard);
  await capture();
  }
  // Flujo visible de biblioteca: botones existentes del catálogo, no sólo APIs.
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await navigate('/libros/');
  const selected = await evaluate("(()=>{const b=document.querySelector('.btn-fav');if(!b)return null;const book={id:b.dataset.googleId,title:b.dataset.titulo};b.click();return book})()");
  await sleep(800);
  await navigate('/cuenta/biblioteca/');
  mobileChecks.push({case:'catalogue_favorite_button_and_library',passed:Boolean(selected) && await evaluate(`document.querySelector('main').textContent.includes(${JSON.stringify(selected?.title ?? '__missing__')})`)});
  await evaluate("document.querySelector('input[name=nombre]').value='Lista móvil';document.querySelector('form[action=\"/api/listas/crear/\"]').requestSubmit();true");
  await sleep(1000);
  mobileChecks.push({case:'list_created_by_visible_form',passed:await evaluate("document.querySelector('main').textContent.includes('Lista móvil')")});
  for (const width of [320,360,390,430,768]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width<768});
    await sleep(200);
    const layout = await evaluate("(()=>{const width=document.documentElement.clientWidth;return {passed:document.documentElement.scrollWidth<=width+1,offenders:Array.from(document.querySelectorAll('main *')).filter(e=>e.getBoundingClientRect().right>width+1).slice(0,8).map(e=>({tag:e.tagName,width:e.getBoundingClientRect().width}))}})()");
    mobileChecks.push({case:'library_width_'+width,...layout});
  }
  await capture();
  await navigate('/libros/');
  await evaluate("document.querySelector('.btn-ver-demo').click();true");
  await sleep(500);
  await evaluate("document.querySelector('[onclick=\"abrirModalAgregarListaDirecto()\"]').click();true");
  await sleep(600);
  mobileChecks.push({case:'catalogue_list_selector_visible',passed:await evaluate("Boolean(document.querySelector('#userListsModalList .select-list-row'))")});
  await evaluate("document.querySelector('#userListsModalList .select-list-row')?.click();true");
  await sleep(700);
  await navigate('/cuenta/biblioteca/');
  mobileChecks.push({case:'catalogue_list_button_persists_book',passed:await evaluate("Array.from(document.querySelectorAll('main section li')).some(e=>!e.textContent.includes('Lista sin libros'))")});
  await navigate('/perfil/editar/');
  await evaluate("(async()=>{const canvas=document.createElement('canvas');canvas.width=80;canvas.height=80;const ctx=canvas.getContext('2d');ctx.fillStyle='#227d8e';ctx.fillRect(0,0,80,80);const blob=await new Promise(r=>canvas.toBlob(r,'image/png'));const files=new DataTransfer();files.items.add(new File([blob],'synthetic-avatar.png',{type:'image/png'}));document.querySelector('input[name=photo]').files=files.files;return true})()");
  await evaluate("document.querySelector('input[name=nombre]').value='Lectora móvil';document.querySelector('main form[method=post]').requestSubmit();true");
  await sleep(1000);
  mobileChecks.push({case:'profile_updated_by_visible_form',passed:await evaluate("location.pathname==='/perfil/' && document.querySelector('main').textContent.includes('Lectora móvil')")});
  mobileChecks.push({case:'private_avatar_uploaded_and_loaded',passed:await evaluate("Array.from(document.querySelectorAll('img[src=\"/cuenta/avatar/\"]')).some(i=>i.complete && i.naturalWidth>0)")});
  await capture();
}
async function platformLibrary() {
  const check = async (name, expression) => mobileChecks.push({case:name, passed:await evaluate(expression)});
  async function waitFor(expression) {
    for (let n=0;n<70;n++) {if (await evaluate(expression))return;await sleep(100);}
    throw new Error('No se completó un control de la biblioteca.');
  }
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await navigate('/login/');
  if(config.productionOpen) {
    await navigate('/registro/');
    await evaluate(`document.querySelector('input[name=username]').value=${JSON.stringify(config.platformUser)};document.querySelector('input[name=email]').value=${JSON.stringify(config.platformUser+'@example.invalid')};document.querySelector('input[name=password]').value=${JSON.stringify(config.platformPassword)};document.querySelector('input[name=password_confirm]').value=${JSON.stringify(config.platformPassword)};document.getElementById('registerForm').requestSubmit();true`);
    await waitFor("location.pathname==='/suscripciones/planes/'");
    await evaluate("document.querySelector('form[action=\"/cuenta/activar-gratis/\"]').requestSubmit();true");
    await waitFor("location.pathname==='/chat/'");
    await evaluate("(async()=>{const csrf=document.cookie.split('; ').find(v=>v.startsWith('csrftoken=')).split('=')[1];const post=async(url,data)=>await (await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':csrf},body:JSON.stringify(data)})).json();const b={google_id:'platform-a',titulo:'La isla de prueba',autores:'Autora sintética'};await post('/favoritos/agregar/',b);const l=await post('/api/listas/crear/',{nombre:'Mis lecturas'});await post('/api/listas/agregar-libro/',{...b,lista_id:l.id});return true})()");
  } else {
    await evaluate(`(async()=>{const csrf=document.cookie.split('; ').find(v=>v.startsWith('csrftoken=')).split('=')[1];await fetch('/login/',{method:'POST',headers:{'X-CSRFToken':csrf},body:new URLSearchParams(${JSON.stringify({username_or_email:config.platformUser,password:config.platformPassword})})});return true})()`);
  }
  await navigate('/chat/');
  await waitFor('Boolean(window.LitMateSafe && window.LitmateLibrary)');
  const cards = [
    {id:'platform-a',title:'La isla de prueba',author:'Autora sintética',image_url:'',synopsis:'',links:[]},
    {id:'platform-b',title:'El bosque de prueba',author:'Autor sintético',image_url:'',synopsis:'',links:[]}
  ];
  const render = `(()=>{let c=document.createElement('div');c.id='platform-cards';document.getElementById('chat-body-page').appendChild(c);LitMateSafe.renderBookCards(c,${JSON.stringify(cards)});LitMateSafe.renderBookCards(c,[${JSON.stringify(cards[1])}]);return true})()`;
  await evaluate(render);
  await waitFor("document.querySelector('#platform-cards button[data-library-ready]')?.getAttribute('aria-pressed')==='true'");
  await check('existing_favorite_restored_on_card',"document.querySelector('#platform-cards button[data-library-ready]').getAttribute('aria-pressed')==='true'");
  await evaluate("(()=>{const b=document.querySelectorAll('#platform-cards button[data-library-ready]');b[1].click();b[2].click();return true})()");
  await waitFor("Array.from(document.querySelectorAll('#platform-cards button[data-library-ready]')).slice(1).every(b=>b.getAttribute('aria-pressed')==='true'&&!b.disabled)");
  await check('duplicate_card_buttons_stay_synchronized',"Array.from(document.querySelectorAll('#platform-cards button[data-library-ready]')).every(b=>b.getAttribute('aria-pressed')==='true')");
  await capture();
  await navigate('/cuenta/biblioteca/');
  await check('favorite_survives_navigation',"document.querySelector('main').textContent.includes('El bosque de prueba')");
  await navigate('/cuenta/libro/?id=platform-a');
  await waitFor("document.querySelector('.btn-fav[data-library-ready]')?.getAttribute('aria-pressed')==='true'");
  await check('favorite_state_on_private_detail',"document.querySelector('.btn-fav').getAttribute('aria-pressed')==='true'");
  await evaluate("document.querySelector('textarea[name=nota_personal]').value='Nota privada desde el navegador';document.querySelector('textarea[name=nota_personal]').form.requestSubmit();true");
  await sleep(600);
  await check('note_saved_by_visible_form',"document.querySelector('textarea[name=nota_personal]').value==='Nota privada desde el navegador'");
  await evaluate("document.querySelector('select[name=estado]').value='leyendo';document.querySelector('select[name=estado]').form.requestSubmit();true");
  await waitFor("location.pathname==='/cuenta/biblioteca/'");
  await check('reading_state_saved',"document.querySelector('main').textContent.includes('Mi organizador de lectura') && document.querySelector('select[name=estado]').value==='leyendo'");
  for(const width of [320,390,768]) {
    await command('Emulation.setDeviceMetricsOverride',{width,height:844,deviceScaleFactor:1,mobile:width<768});
    await sleep(200);
    await check('organizer_width_'+width,'document.documentElement.scrollWidth<=document.documentElement.clientWidth+1');
    await capture();
  }
  await command('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await navigate('/chat/');
  await waitFor('Boolean(window.LitMateSafe && window.LitmateLibrary)');
  await evaluate(render);
  await waitFor("document.querySelectorAll('#platform-cards button[data-library-ready]')[1]?.getAttribute('aria-pressed')==='true'");
  await evaluate("document.querySelectorAll('#platform-cards button[data-library-ready]')[1].click();true");
  await waitFor("Array.from(document.querySelectorAll('#platform-cards button[data-library-ready]')).slice(1).every(b=>b.getAttribute('aria-pressed')==='false'&&!b.disabled)");
  await check('favorite_removed_and_duplicate_controls_updated',"Array.from(document.querySelectorAll('#platform-cards button[data-library-ready]')).slice(1).every(b=>b.getAttribute('aria-pressed')==='false')");
  const personalStarted = elapsed();
  await sendReaderMessage('Muéstrame mis favoritos');
  conversation.at(-1).seconds = elapsed()-personalStarted;
  await check('personal_sse_answer_uses_saved_library',"Array.from(document.querySelectorAll('#chat-body-page .chat-message.bot')).at(-1).textContent.includes('La isla de prueba')");
  await capture();
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
      const detail = message.params.exceptionDetails;
      errors.push({text: detail.text, description: detail.exception?.description?.split('\n').slice(0,6),
                   path: detail.url ? new URL(detail.url).pathname : '', line: detail.lineNumber});
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
  if(config.platform) {
    await platformLibrary();
    console.log(JSON.stringify({mobileChecks,errors}));
  } else if(config.readerMobile) {
    await command('Page.addScriptToEvaluateOnNewDocument',{source:'window.__readerScrollAudit=[];'});
    await readerMobile();
    console.log(JSON.stringify({mobileChecks,errors}));
  } else {
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
  }
} finally {
  clearInterval(timer);
  fs.writeFileSync(path.join(folder, 'captura.json'), JSON.stringify({
    authenticBrowserCapture: true, externalNetworkTested: false, origin,
    frames, conversation, navigation, mobileChecks, scrollAudit, sessionPreservedAcrossNavigation, errors, http
  }, null, 2), 'utf8');
  try {if (socket?.readyState === 1) await command('Browser.close');} catch {}
  socket?.close();
  if (browser.exitCode === null) browser.kill();
}
