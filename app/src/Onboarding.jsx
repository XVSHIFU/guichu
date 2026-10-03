import React,{useEffect,useState} from 'react';
import {ArrowRight,Check,X} from 'lucide-react';
import './onboarding.css';
export default function Onboarding({data,scanning,offline,post,onScan,onSettings,onAsk}){
 const [hidden,setHidden]=useState(()=>{try{return localStorage.getItem('desk-onboarding')==='hidden'}catch{return false}});
 const [connected,setConnected]=useState(false),[failure,setFailure]=useState(''),[target,setTarget]=useState('');
 useEffect(()=>{let alive=true;if(!hidden&&!offline)post('model/settings').then(v=>{if(alive){setConnected(!!v.config?.endpoint&&!!v.config?.model&&v.key_configured);setFailure('')}}).catch(()=>{if(alive)setFailure('模型状态暂时无法读取，可前往设置检查。')});return()=>{alive=false}},[hidden,offline]);
 const objects=data?.objects||[],candidates=objects.filter(o=>['agent','mcp','software'].includes(o.kind)).slice(0,40);
 const selected=candidates.find(o=>o.id===target)||candidates[0];
 function dismiss(){setHidden(true);try{localStorage.setItem('desk-onboarding','hidden')}catch{}}
 if(hidden)return null;
 return <section className="getting-started" aria-label="开始使用归处"><div className="getting-started-heading"><div><h2>让归处认识这台电脑</h2><p>先看看发现了什么，再选一个工具交给助手了解。</p></div><button className="icon-button" onClick={dismiss} aria-label="暂时收起使用引导" title="暂时收起"><X size={18}/></button></div><ol><li><span className="setup-index">{data?.at?<Check size={16}/>:1}</span><div><strong>查看本机环境</strong><p>{scanning?'正在检查软件与配置…':data?.at?`已收录 ${objects.length} 个对象${data.issues?.length?'，部分来源需要重新检查':''}`:'读取软件与配置位置，建立第一份清单。'}</p></div><button className="button" onClick={onScan} disabled={offline||scanning}>{scanning?'检查中':'重新检查'}</button></li><li><span className="setup-index">{connected?<Check size={16}/>:2}</span><div><strong>连接你的模型</strong><p>{connected?'已配置模型；连通性可在设置中测试。':'填写兼容 OpenAI 的服务地址、模型和密钥。'}</p></div><button className="button" onClick={onSettings}>{connected?'检查连接':'配置模型'}</button></li><li><span className="setup-index">3</span><div><strong>从一个工具开始</strong><p>选择对象，进入助手后提出你的问题。</p><select aria-label="引导处理对象" value={selected?.id||''} onChange={e=>setTarget(e.target.value)}>{!candidates.length&&<option value="">暂无对象，请先检查</option>}{candidates.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></div><button className="button primary" disabled={offline||!selected} onClick={()=>onAsk(selected)}>询问助手<ArrowRight size={15}/></button></li></ol>{failure&&<p role="status">{failure}</p>}<button className="text-button" onClick={dismiss}>我先自己看看</button></section>
}
