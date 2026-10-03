import React,{Children,useRef,useState} from 'react';
import {Plug,FolderSearch,Palette,Database,Bot} from 'lucide-react';
import './settings-layout.css';

const sections=[['模型连接','接口与调用预算',Plug],['检查来源','便携软件与项目',FolderSearch],['外观','主题与显示',Palette],['本地数据','保存与离线方式',Database],['助手','使用方式与入口',Bot]];
export default function SettingsLayout({children}){
 const [active,setActive]=useState(0),buttons=useRef([]);
 function keyboard(event,index){let next;if(['ArrowDown','ArrowRight'].includes(event.key))next=(index+1)%sections.length;else if(['ArrowUp','ArrowLeft'].includes(event.key))next=(index+sections.length-1)%sections.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=sections.length-1;else return;event.preventDefault();setActive(next);buttons.current[next]?.focus()}
 return <div className="settings-workspace"><div className="settings-nav" role="tablist" aria-label="设置分类">{sections.map(([name,hint,Icon],index)=><button key={name} ref={node=>buttons.current[index]=node} type="button" role="tab" id={'settings-tab-'+index} aria-controls={'settings-panel-'+index} aria-selected={active===index} tabIndex={active===index?0:-1} onClick={()=>setActive(index)} onKeyDown={event=>keyboard(event,index)}><Icon size={17}/><span><strong>{name}</strong><small>{hint}</small></span></button>)}</div><div className="settings-panels">{Children.toArray(children).map((child,index)=><div key={index} role="tabpanel" id={'settings-panel-'+index} aria-labelledby={'settings-tab-'+index} hidden={active!==index} tabIndex={0}>{child}</div>)}</div></div>
}
