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
$shell=New-Object -ComObject WScript.Shell
foreach($item in $items){
    $large=[IntPtr]::Zero;$small=[IntPtr]::Zero;$bitmap=$null;$source=$null;$icon=$null
    try{
        if(-not (Test-Path -LiteralPath $item.path -PathType Leaf)){continue}
        $resourcePath=$item.path;$resourceIndex=[int]$item.index
        if([IO.Path]::GetExtension($resourcePath) -eq '.lnk'){
            $shortcut=$shell.CreateShortcut($resourcePath)
            $location=[Environment]::ExpandEnvironmentVariables($shortcut.IconLocation)
            if($location -match '^"?(.+\.(?:exe|dll|ico))"?(?:,\s*(-?\d+))?$'){
                $resourcePath=$Matches[1];$resourceIndex=0
                if($Matches[2]){$resourceIndex=[int]$Matches[2]}
            }else{$resourcePath=$shortcut.TargetPath;$resourceIndex=0}
            if($resourcePath -notmatch '^[A-Za-z]:\\' -or -not (Test-Path -LiteralPath $resourcePath -PathType Leaf)){continue}
        }
        if([IO.Path]::GetExtension($resourcePath) -match '^\.(png|jpg|jpeg)$'){
            $source=[System.Drawing.Image]::FromFile($resourcePath)
            if($source.Width -gt 4096 -or $source.Height -gt 4096){continue}
            $bitmap=New-Object System.Drawing.Bitmap 64,64
            $graphics=[System.Drawing.Graphics]::FromImage($bitmap)
            try{
                $graphics.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
                $ratio=[Math]::Min(64.0/$source.Width,64.0/$source.Height)
                $w=[int]($source.Width*$ratio);$h=[int]($source.Height*$ratio)
                $graphics.DrawImage($source,[int]((64-$w)/2),[int]((64-$h)/2),$w,$h)
            }finally{$graphics.Dispose()}
        }else{
            [void][DeskIcons]::ExtractIconEx($resourcePath,$resourceIndex,[ref]$large,[ref]$small,1)
            $handle=if($large -ne [IntPtr]::Zero){$large}else{$small}
            if($handle -eq [IntPtr]::Zero){continue}
            $icon=[System.Drawing.Icon]::FromHandle($handle)
            $bitmap=$icon.ToBitmap()
        }
        $bitmap.Save((Join-Path $Destination ($item.key+'.png')),[System.Drawing.Imaging.ImageFormat]::Png)
    }catch{continue}finally{
        if($bitmap){$bitmap.Dispose()}
        if($source){$source.Dispose()}
        if($icon){$icon.Dispose()}
        if($large -ne [IntPtr]::Zero){[void][DeskIcons]::DestroyIcon($large)}
        if($small -ne [IntPtr]::Zero){[void][DeskIcons]::DestroyIcon($small)}
    }
}
[void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
