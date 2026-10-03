param([string]$Manifest,[string]$Destination)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class DeskIcons {
 [DllImport("shell32.dll", CharSet=CharSet.Unicode)] public static extern uint ExtractIconEx(string file,int index,out IntPtr large,out IntPtr small,uint count);
 [DllImport("user32.dll")] public static extern bool DestroyIcon(IntPtr icon);
}
'@
$items=Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
foreach($item in $items){
    $large=[IntPtr]::Zero;$small=[IntPtr]::Zero;$bitmap=$null
    try{
        if(-not (Test-Path -LiteralPath $item.path -PathType Leaf)){continue}
        [void][DeskIcons]::ExtractIconEx($item.path,[int]$item.index,[ref]$large,[ref]$small,1)
        if($large -eq [IntPtr]::Zero){continue}
        $icon=[System.Drawing.Icon]::FromHandle($large)
        $bitmap=$icon.ToBitmap()
        $bitmap.Save((Join-Path $Destination ($item.key+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
    }catch{continue}finally{
        if($bitmap){$bitmap.Dispose()}
        if($large -ne [IntPtr]::Zero){[void][DeskIcons]::DestroyIcon($large)}
        if($small -ne [IntPtr]::Zero){[void][DeskIcons]::DestroyIcon($small)}
    }
}
