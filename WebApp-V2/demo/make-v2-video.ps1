$ErrorActionPreference = "Stop"

$screenshots = Join-Path $PSScriptRoot "screenshots"
$frames = Join-Path $PSScriptRoot "frames"
$output = Join-Path $PSScriptRoot "qwen-sci-v2-demo.mp4"
$concat = Join-Path $PSScriptRoot "concat-v2.txt"

New-Item -ItemType Directory -Force -Path $frames | Out-Null
Remove-Item -LiteralPath (Join-Path $frames "*.png") -ErrorAction SilentlyContinue

$files = Get-ChildItem -LiteralPath $screenshots -Filter "*.png" | Sort-Object Name
if ($files.Count -eq 0) {
  throw "No screenshots found in $screenshots"
}

$i = 1
foreach ($file in $files) {
  $frame = Join-Path $frames ("frame-{0:D3}.png" -f $i)
  ffmpeg -y -i $file.FullName -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=#eef6ff,setsar=1" -frames:v 1 -update 1 $frame | Out-Null
  $i += 1
}

$lines = @()
Get-ChildItem -LiteralPath $frames -Filter "*.png" | Sort-Object Name | ForEach-Object {
  $safe = $_.FullName.Replace("\", "/").Replace("'", "'\''")
  $lines += "file '$safe'"
  $lines += "duration 3.5"
}
$last = (Get-ChildItem -LiteralPath $frames -Filter "*.png" | Sort-Object Name | Select-Object -Last 1).FullName.Replace("\", "/").Replace("'", "'\''")
$lines += "file '$last'"
Set-Content -LiteralPath $concat -Value $lines -Encoding ASCII

ffmpeg -y -f concat -safe 0 -i $concat -vf "fps=30,format=yuv420p" -c:v libx264 -movflags +faststart $output
Write-Output $output
