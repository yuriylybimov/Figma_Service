(/*SCRIPTER*/async function __scripter_script_main(){
const S="__SENTINEL__",C="__CLOSING__",CAP=__CAP__,T0=Date.now();
const E=(o)=>{
  o.elapsed_ms=Date.now()-T0;
  let p;
  try{p=JSON.stringify(o)}catch(e){p=JSON.stringify({status:"error",version:1,kind:"serialize_failed",message:String(e&&e.message||e),elapsed_ms:Date.now()-T0})}
  if(p.length>CAP&&o.status==="ok")p=JSON.stringify({status:"error",version:1,kind:"payload_too_large",message:`result ${p.length}B exceeds cap ${CAP}B`,elapsed_ms:Date.now()-T0});
  figma.notify(S+p+C)
};
try{
  const R=await(async()=>{
/*__USER_JS__*/
  })();
  E({status:"ok",version:1,result:R===undefined?null:R})
}catch(e){
  E({status:"error",version:1,kind:"user_exception",message:String(e&&e.message||e),detail:e&&e.stack?String(e.stack).slice(0,2000):null})
}
})()/*SCRIPTER*/
