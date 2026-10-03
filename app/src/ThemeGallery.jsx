import React,{useEffect,useState} from 'react';
import {Check} from 'lucide-react';
import {themes} from './themes';
import './theme-gallery.css';
const groups=[['自然','pine','bamboo','moss','matcha','sea','glacier'],['纸与火','oat','desert','ink','parchment','coffee','amber'],['花与金属','plum','rose','sakura','lavender','copper','burgundy'],['城市与夜','mist','graphite','porcelain','cobalt','midnight','aurora']];
const family=id=>groups.find(g=>g.includes(id))?.[0]||'自然';
export default function ThemeGallery({value,onChange}){
 const [group,setGroup]=useState(()=>family(value.palette));
 useEffect(()=>setGroup(family(value.palette)),[value.palette]);
 const mode=value.resolved||'light',ids=groups.find(g=>g[0]===group).slice(1);
 return <section className="theme-library" aria-label="主题配色集"><div className="theme-library-heading"><h3>配色集</h3><span>24 套配色 · 深浅相伴</span></div><div className="theme-families" role="group" aria-label="配色风格">{groups.map(([name])=><button type="button" key={name} aria-pressed={group===name} onClick={()=>setGroup(name)}>{name}</button>)}</div><div className="theme-gallery">{ids.map(id=>{const t=themes.find(t=>t.id===id),c=t[mode],selected=value.palette===id;return <button type="button" className="theme-sample" key={id} aria-label={'选择'+t.name+'主题'} aria-pressed={selected} onClick={e=>{const r=e.currentTarget.getBoundingClientRect();onChange({palette:id},{x:r.left+r.width/2,y:r.top+r.height/2})}}><span className="theme-miniature" aria-hidden="true" style={{'--sample-bg':c.bg,'--sample-surface':c.surface,'--sample-nav':c.nav,'--sample-accent':c.accent,'--sample-line':c.line,'--sample-ink':c.ink}}><span className="mini-nav"><i/><i/><i/></span><span className="mini-page"><b/><span className="mini-toolbar"/><span className="mini-rows"><i/><i/><i/></span></span><span className="mini-detail"><i/><i/></span></span><span className="theme-sample-caption"><span><strong>{t.name}</strong><small>{t.note}</small></span>{selected?<Check size={17}/>:<span className="theme-pigment" style={{background:c.accent}}/>}</span></button>})}</div></section>
}
