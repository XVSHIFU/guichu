/* Runs before app/CSS: one validated theme catalog for first paint and React. */
(function(){
 const rows=[
 ['pine','松绿','温暖、耐看',['#f5f6f2','#ffffff','#243831','#596b61','#e0e5de','#edf1eb','#22745e','#172e27'],['#19231f','#202d26','#dce5da','#acbeb2','#354239','#2a382f','#78bfa2','#111e18']],
 ['mist','雾蓝','清晰、安静',['#f3f5f8','#ffffff','#263449','#59697d','#dbe1e9','#e9eef5','#355f95','#192b43'],['#19212d','#222d3c','#e0e8f3','#b1bfd2','#38485d','#2c394c','#8cb4e6','#121c2a']],
 ['oat','燕麦陶红','温润、质朴',['#f7f3ec','#fffdf8','#45342b','#756051','#e6dcd0','#f0e7dc','#9a4938','#39271f'],['#29211e','#352b26','#f0e5d8','#cfbbae','#514239','#41352e','#e4a08b','#211914']],
 ['plum','暮紫','柔和、沉静',['#f5f2f7','#fffdfF','#3b3047','#706078','#e3dbe9','#eee7f2','#79538e','#2c2137'],['#241e2b','#302638','#ece1f2','#c4b3ce','#493b54','#3c3047','#c5a1dc','#1c1623']],
 ['sea','海盐青','清爽、明净',['#f0f6f5','#ffffff','#263c3c','#576f70','#d6e5e3','#e4efee','#236d73','#173438'],['#192728','#223335','#dcebec','#adc6c8','#354d50','#2c4144','#78bfc5','#122022']],
 ['graphite','石墨','克制、专注',['#f4f4f3','#ffffff','#303334','#646869','#dedfde','#eaeceb','#515c61','#252a2c'],['#202324','#2b2f31','#e5e8e8','#b9c1c3','#444b4e','#363d40','#aebec5','#171b1d']],
 ["bamboo", "竹影", "竹叶与米纸", ["#f2f5e9", "#fcfff5", "#293526", "#59654f", "#dce3cc", "#e8efdc", "#4f681f", "#24331e"], ["#1e251a", "#283120", "#e8edda", "#b8c4a1", "#424d32", "#333e29", "#b2c877", "#151e12"]],
 ["moss", "苔石", "潮湿森林的静谧", ["#eff3eb", "#fcfdf8", "#303a2d", "#606b57", "#dbe1d3", "#e5eadf", "#516943", "#2c3525"], ["#20261e", "#2a3227", "#e4eada", "#b8c5aa", "#414d39", "#35412e", "#b2c994", "#172015"]],
 ["matcha", "抹茶", "奶油纸面与茶绿", ["#faf6e9", "#fffdf3", "#3b3d2c", "#696953", "#e6e1c9", "#f0ebd8", "#626b2c", "#333821"], ["#26281c", "#323525", "#eeeeda", "#c4c5a6", "#4b5037", "#3c412b", "#c0c77d", "#1e2115"]],
 ["glacier", "冰川", "冰蓝与冷白", ["#edf7fa", "#faffff", "#213b47", "#506b78", "#d3e5ed", "#e1eff4", "#246c87", "#163443"], ["#12262f", "#1d333e", "#deeff5", "#a5c5d2", "#31515f", "#25434f", "#7bcbe4", "#0b1c25"]],
 ["desert", "沙丘", "砂岩与烧橙", ["#faf3e5", "#fffaf0", "#473426", "#78604b", "#e9dac4", "#f2e6d2", "#955320", "#402d1c"], ["#2b2319", "#392f21", "#f3e4cd", "#d1b995", "#54432e", "#453822", "#e2b273", "#21190f"]],
 ["rose", "蔷薇", "柔粉底色与深莓红", ["#faf1f3", "#fffbfc", "#4a2c38", "#795965", "#ead7df", "#f3e4e9", "#984564", "#402331"], ["#2d1d26", "#3b2733", "#f5e0e9", "#d2afbf", "#58394a", "#492e3c", "#e6a0bd", "#22141c"]],
 ["sakura", "樱雪", "樱花与淡墨", ["#fff5f4", "#fffdfb", "#4b3535", "#795f5f", "#efdedb", "#f7e9e6", "#a14b56", "#422a31"], ["#2b2023", "#392b2f", "#f5e4e5", "#cdb4b8", "#543f45", "#45323a", "#e4a4ad", "#21171b"]],
 ["lavender", "薰衣草", "淡紫纸面与草本紫", ["#f4f2fb", "#fdfbff", "#373149", "#6a617e", "#e0dcef", "#ece8f6", "#6b549e", "#29223e"], ["#221e30", "#2e2840", "#e9e2f7", "#bdb1d6", "#463b5c", "#392f4d", "#bfa8e9", "#191525"]],
 ["ink", "水墨", "宣纸、墨线与朱砂", ["#f3f1e9", "#fffef6", "#302f2a", "#68655b", "#dfddd1", "#eae7dc", "#8e3c31", "#242a29"], ["#202421", "#2b302b", "#e9e8dd", "#bfbeae", "#424940", "#353c33", "#dfa498", "#161c18"]],
 ["parchment", "羊皮卷", "书页里的旧金色", ["#f6edda", "#fff9e9", "#423723", "#716046", "#e5d5b5", "#eedfc1", "#79591d", "#362d1e"], ["#272318", "#342f21", "#efe6ca", "#c9bb93", "#4d4530", "#403926", "#d8bd72", "#1d1a11"]],
 ["coffee", "浓咖", "奶白与烘焙棕", ["#f5efea", "#fffaf5", "#3e2d27", "#745e54", "#e4d7cf", "#ede2d9", "#7d4e37", "#32241f"], ["#241c19", "#322620", "#eeded2", "#c7af9c", "#4b392e", "#3e2e25", "#d4a17b", "#1a1310"]],
 ["porcelain", "青花", "瓷白上的靛蓝", ["#f4f6fc", "#ffffff", "#252f4b", "#5d6883", "#dce1ed", "#e9edf6", "#3155a0", "#1b2850"], ["#171f36", "#202c48", "#e1e8ff", "#b0bde1", "#35466c", "#29395a", "#9bb8ff", "#10182c"]],
 ["amber", "琥珀", "暖白与树脂金", ["#faf4e9", "#fffdf6", "#413522", "#766249", "#e9dcc4", "#f3e7d1", "#875916", "#3d2c15"], ["#292217", "#382f1d", "#f5e8cb", "#d0bd96", "#52442b", "#443721", "#e4bc65", "#211a0f"]],
 ["copper", "赤铜", "氧化铜与金属暖意", ["#f8f0ec", "#fffaf7", "#47332c", "#785f55", "#e8d8cf", "#f2e5dd", "#9c482a", "#3c2c28"], ["#2c211d", "#3a2c26", "#f4dfd3", "#cfb09d", "#574035", "#47342b", "#e3a47f", "#221812"]],
 ["cobalt", "钴蓝", "高对比的工作节奏", ["#f1f4fc", "#ffffff", "#202d4b", "#576580", "#d9e0f0", "#e5ebf8", "#264ec0", "#142449"], ["#141e35", "#1d2b47", "#e0e9ff", "#a9bce4", "#30466e", "#253859", "#8cb4ff", "#0c1529"]],
 ["burgundy", "酒红", "天鹅绒般的深红", ["#f7f0f1", "#fffbfa", "#482c32", "#78585f", "#e7d6da", "#efe2e5", "#8b354b", "#3c1e2a"], ["#29191f", "#38232c", "#f4dfe6", "#d0aab9", "#523440", "#422a34", "#e5a0b6", "#1f1118"]],
 ["midnight", "午夜", "深海蓝与月光", ["#eff3f9", "#fcfdff", "#23324d", "#566780", "#d7e0ed", "#e3eaf5", "#3e5792", "#101e39"], ["#0e1729", "#17233a", "#e0e9fa", "#a6badb", "#2c3e5c", "#20304a", "#a1baff", "#080f1e"]],
 ["aurora", "极光", "靛夜里的薄荷绿", ["#edf7f4", "#f8fffc", "#243b38", "#506d65", "#d2e6df", "#dff0e9", "#166c59", "#22213e"], ["#181a2e", "#22273c", "#e0f1e9", "#a9c6be", "#38485b", "#2b364c", "#83dcc0", "#101226"]]
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
