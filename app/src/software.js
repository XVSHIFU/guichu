import {pinyin} from 'pinyin-pro';
export const softwareCategories=['全部分类','办公与协作','游戏与平台','开发工具','开发环境','网络与远程','影音与创作','系统与驱动','其他软件'];
const rules=[
 ['游戏与平台',/崩坏|星穹|原神|米哈游|绝区|steam|epic games|battle\.net|wegame|riot|minecraft|育碧|ubisoft|游戏|hoyoplay/i],
 ['办公与协作',/语雀|yuque|office|wps|onenote|outlook|notion|obsidian|typora|飞书|feishu|钉钉|ding|腾讯会议|微信|wechat|teams|zoom|pdf|石墨/i],
 ['开发环境',/anaconda|miniconda|python|node\.js|nodejs|jdk|java\b|rust|golang|\bgo programming|\.net|asp\.net|visual c\+\+|redis|mysql|postgres|mongodb|docker|sdk|runtime|redistributable|开发工具包|运行库|targeting pack|host fx|host resolver/i],
 ['开发工具',/visual studio|vscode|intellij|pycharm|webstorm|jetbrains|git\b|svn|sublime|notepad|navicat|postman|android studio|cursor|codex|claude|cc.?switch|herdr|vcpkg|cmake|msbuild|windows app certification|windows software development/i],
 ['网络与远程',/chrome|edge|firefox|browser|浏览器|clash|v2ray|flclash|vpn|todesk|向日葵|远程|mobaxterm|finalshell|windterm|winscp|putty|xshell|xftp|tigervnc|netbird|tailscale|zerotier|百度网盘|baidu.*netdisk|夸克|quark/i],
 ['影音与创作',/photoshop|illustrator|adobe|blender|figma|obs studio|剪映|音乐|music|vlc|potplayer|视频|video|capture|录屏|snipaste|picgo|网易云|哔哩/i],
 ['系统与驱动',/driver|驱动|nvidia|intel|realtek|amd |microsoft update|windows.*(update|health)|vulkan|directx|physx|chipset|bandizip|7-zip|winrar|everything|treesize|geek|vmware|virtualbox|coodesker|mayenano|卸载|安全|组件/i]
];
export function softwareCategory(o){if(softwareCategories.slice(1).includes(o.manualCategory))return o.manualCategory;if(o.kind==='agent')return 'AI Agent';return rules.find(([,pattern])=>pattern.test(o.name))?.[0]||'其他软件'}
const collator=new Intl.Collator('en',{numeric:true,sensitivity:'base'});
export function compareSoftware(a,b){return collator.compare(pinyin(a.name,{toneType:'none',nonZh:'consecutive'}),pinyin(b.name,{toneType:'none',nonZh:'consecutive'}))||a.id.localeCompare(b.id)}
