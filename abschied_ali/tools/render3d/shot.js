const {chromium}=require('playwright');
(async()=>{
  const b=await chromium.launch({args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const p=await b.newPage({viewport:{width:1600,height:1200}});
  p.on('console',m=>console.log('console:',m.text())); p.on('pageerror',e=>console.log('err:',e.message));
  for(const [q,f] of [['view=hero','hero'],['view=detail','detail'],['view=hero&paint=0','hero_roh']]){
    await p.goto('http://127.0.0.1:8765/index.html?'+q);
    await p.waitForFunction(()=>window.__done===true,null,{timeout:120000});
    await p.screenshot({path:`render_${f}.png`});
    console.log('ok',f);
  }
  await b.close();
})();
