// Keep the existing action path intact; label each observed location by role.
const parent=path=>path?.replace(/[\\/][^\\/]+[\\/]?$/,'')||'';
export function objectLocations(obj){
 if(obj.locations?.length)return obj.locations.map(location=>({label:({install:'安装目录',entry:'程序入口',icon:'图标资源文件',config:'配置目录',environment:'包环境目录',metadata:'安装元数据目录'}[location.role]||'位置')+(location.confidence==='candidate'?'（候选）':''),path:location.path,basis:location.basis,primary:location.path===obj.path}));
 if(obj.kind==='agent')return [
  {label:'入口所在目录',path:parent(obj.executable)},
  {label:'程序入口',path:obj.executable},
  {label:'配置目录',path:obj.path,primary:true},
 ];
 if(obj.kind==='software'){
  if(obj.distribution)return [
   {label:'包环境目录',path:obj.installPath},
   {label:obj.distribution==='pip'?'安装元数据目录':'包安装目录',path:obj.path,primary:true},
  ];
  if(obj.portable)return [
   {label:'安装目录',path:parent(obj.path)},
   {label:obj.entryRole==='auxiliary'?'软件附属程序':'程序入口',path:obj.path,primary:true},
  ];
  return [{label:'安装目录',path:obj.path,primary:true}];
 }
 return [{label:obj.kind==='directory'?'目录':obj.kind==='skill'?'技能文件':['mcp','plugin'].includes(obj.kind)?'配置文件':'位置',path:obj.path,primary:true}];
}
export const objectTypeLabel=(obj,isAgent)=>['agent','software'].includes(obj.kind)?(isAgent(obj)?'软件 · Agent':'软件'):null;
