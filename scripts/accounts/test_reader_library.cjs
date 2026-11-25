// Sin navegador, red ni dependencias: carrera entre consulta inicial y escritura.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tagName=tag;this.dataset={};this.children=[];this.attrs={};this.events={};this.disabled=false;
    this.classList={toggle(){}}; }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.append(node); }
  setAttribute(key,value) { this.attrs[key]=value; }
  getAttribute(key) { return this.attrs[key]; }
  addEventListener(key,callback) { this.events[key]=callback; }
  querySelector() { return null; }
  click() {if(!this.disabled)this.events.click?.({preventDefault(){}});}
}
async function main() {
  const timers=[],calls=[];
  let releaseGet;
  const body = new Element('body');
  const context={document:{currentScript:{dataset:{authenticated:'true'}},cookie:'csrftoken=fixture',body,
    createElement: tag=>new Element(tag),getElementById:()=>null,addEventListener(){},querySelectorAll:()=>[]},
    window:{},location:{href:''},setTimeout:callback=>{timers.push(callback);return 1;},
    fetch:async(path,options)=>{
      calls.push({path,options});
      if(!options?.method)return await new Promise(resolve=>{releaseGet=()=>resolve({ok:true,json:async()=>({books:{fixture:{favorite_id:null}}})});});
      return {ok:true,json:async()=>({status:'ok',id:42})};
    }};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(require.resolve('../../static/js/reader-library.js'),'utf8'),context);
  const first=new Element('article'),second=new Element('article');
  const book={id:'fixture',title:'Libro de prueba',author:'Autora',image_url:''};
  context.window.LitmateLibrary.decorate(first,book);
  context.window.LitmateLibrary.decorate(second,book);
  const button=first.children[0].children[0],other=second.children[0].children[0];
  const pending=timers.shift()();
  button.click();other.click();
  await new Promise(setImmediate);
  assert.equal(calls.filter(c=>c.options?.method==='POST').length,1,'rapid duplicate controls issue only one mutation');
  assert.equal(button.getAttribute('aria-pressed'),'true');
  assert.equal(other.getAttribute('aria-pressed'),'true','same book controls synchronize');
  releaseGet();await pending;
  assert.equal(button.getAttribute('aria-pressed'),'true','late initial snapshot cannot undo confirmed mutation');
  button.click();await new Promise(setImmediate);
  assert.equal(calls.at(-1).path,'/favoritos/eliminar/42/');
  assert.equal(other.getAttribute('aria-pressed'),'false','confirmed removal synchronizes every control');
  console.log('4 controles de biblioteca aprobados: doble clic, sincronización, GET tardío y retirada.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
