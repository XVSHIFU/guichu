/* Runs before app/CSS: one validated theme catalog for first paint and React. */
(function(){
 const rows=[
 ['pine','松绿','温暖、耐看',['#f5f6f2','#ffffff','#243831','#596b61','#e0e5de','#edf1eb','#22745e','#172e27'],['#19231f','#202d26','#dce5da','#acbeb2','#354239','#2a382f','#78bfa2','#111e18']],
 ['mist','雾蓝','清晰、安静',['#f3f5f8','#ffffff','#263449','#59697d','#dbe1e9','#e9eef5','#355f95','#192b43'],['#19212d','#222d3c','#e0e8f3','#b1bfd2','#38485d','#2c394c','#8cb4e6','#121c2a']],
 ['oat','燕麦陶红','温润、质朴',['#f7f3ec','#fffdf8','#45342b','#756051','#e6dcd0','#f0e7dc','#9a4938','#39271f'],['#29211e','#352b26','#f0e5d8','#cfbbae','#514239','#41352e','#e4a08b','#211914']],
 ['plum','暮紫','柔和、沉静',['#f5f2f7','#fffdfF','#3b3047','#706078','#e3dbe9','#eee7f2','#79538e','#2c2137'],['#241e2b','#302638','#ece1f2','#c4b3ce','#493b54','#3c3047','#c5a1dc','#1c1623']],
 ['sea','海盐青','清爽、明净',['#f0f6f5','#ffffff','#263c3c','#576f70','#d6e5e3','#e4efee','#236d73','#173438'],['#192728','#223335','#dcebec','#adc6c8','#354d50','#2c4144','#78bfc5','#122022']],
 ['graphite','石墨','克制、专注',['#f4f4f3','#ffffff','#303334','#646869','#dedfde','#eaeceb','#515c61','#252a2c'],['#202324','#2b2f31','#e5e8e8','#b9c1c3','#444b4e','#363d40','#aebec5','#171b1d']]
 ];
 const keys=['bg','surface','ink','muted','line','soft','accent','nav'];
 const themes=rows.map(([id,name,note,light,dark])=>({id,name,note,light:Object.fromEntries(keys.map((k,i)=>[k,light[i]])),dark:Object.fromEntries(keys.map((k,i)=>[k,dark[i]]))}));
 const modes=['light','dark','system'];const fallback={palette:'pine',mode:'light'};
 function validate(v){return {palette:themes.some(t=>t.id===v?.palette)?v.palette:'pine',mode:modes.includes(v?.mode)?v.mode:'light'}}
 function read(){try{const raw=localStorage.getItem('desk-appearance');if(raw){try{const parsed=JSON.parse(raw);if(parsed&&typeof parsed==='object'&&!Array.isArray(parsed))return validate(parsed)}catch{}}return validate({palette:'pine',mode:localStorage.getItem('desk-theme')})}catch{return {...fallback}}}
 function resolve(mode){return mode==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):mode}
 function tokens(palette,mode){const dark=mode==='dark',base=themes.find(t=>t.id===palette)?.[mode]||themes[0][mode];return {...base,hover:base.soft,focus:base.accent,'on-accent':dark?base.nav:'#ffffff','nav-ink':'#f2f5f3','nav-muted':'#becbc6','nav-active':base.accent,'nav-active-ink':dark?base.nav:'#ffffff',success:dark?'#a1d1af':'#286440',warning:dark?'#e8c789':'#805413',danger:dark?'#f0afa7':'#9d352e','warning-bg':dark?'#423726':'#fbf0dc','warning-line':dark?'#78613b':'#dec59b',overlay:dark?'rgba(0,0,0,.48)':'rgba(23,29,27,.34)',selection:base.accent,'selection-ink':dark?base.nav:'#ffffff'}}
 // The accent foreground uses the same dark navigation ink for all dark variants.
 const makeTokens=tokens;function paletteTokens(palette,mode){const t=makeTokens(palette,mode);t['on-accent']=mode==='dark'?t.nav:'#ffffff';return t}
 function apply(value,persist=false){const selected=validate(value),mode=resolve(selected.mode),t=paletteTokens(selected.palette,mode),root=document.documentElement;root.dataset.theme=mode;root.dataset.palette=selected.palette;root.dataset.appearanceMode=selected.mode;for(const [key,val]of Object.entries(t))root.style.setProperty('--'+key,val);root.style.colorScheme=mode;root.style.backgroundColor=t.bg;root.style.color=t.ink;document.querySelector('meta[name="theme-color"]')?.setAttribute('content',t.bg);let failed=false;if(persist)try{localStorage.setItem('desk-appearance',JSON.stringify(selected));localStorage.setItem('desk-theme',mode)}catch{failed=true}return {...selected,resolved:mode,failed}}
 window.DeskThemes={themes,read,validate,apply,tokens:paletteTokens};apply(read());
})();
