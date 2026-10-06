import React,{useEffect,useRef} from 'react';
export default function SelectionCheckbox({checked,mixed=false,onChange,label,disabled=false}){
 const ref=useRef(null);
 useEffect(()=>{if(ref.current)ref.current.indeterminate=mixed},[mixed]);
 return <label className="selection-checkbox" title={label}><input ref={ref} type="checkbox" checked={checked} aria-label={label} aria-checked={mixed?'mixed':checked} disabled={disabled} onChange={onChange}/><span aria-hidden="true"/></label>;
}
