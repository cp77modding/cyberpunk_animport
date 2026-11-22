<#
Generates a transition between two clips with MotionBricks and cooks it to an ordinary .anims, end to end.

  two source .anims
    -> WolvenKit export            glbs on the NPC rig
    -> mb_transition.py            A's last frames + B's first frames -> the model -> a clip on the same rig
    -> anims_json.py prep          container: A's set, emptied
    -> wk_anims (ImportAnims)      cooked by the WolvenKit nightly's SIMD encoder
    -> export + verify_retarget.py the cooked clip re-read and compared, per bone

  powershell -File tools\retarget\mb_transition.ps1 -FromAnims <a.anims> -FromClip <clip> -ToAnims <b.anims> -ToClip <clip> `
      -Name tr-kneel-to-sit -DepotPath ncn\anims\npc\tr_kneel_to_sit_ma.anims [-Rig woman_base] [-Tokens 11] [-Preview]

Both sets must be on -Rig. -Preview renders the body through the join: <run>\<Name>.gif. The model and its venv
are the MotionBricks clone (-MotionBricks or NCN_MOTIONBRICKS, else beside this repo). Output lands at
work\depot\<DepotPath>. docs/design/generated-motion.md §7.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$FromAnims,
  [Parameter(Mandatory)][string]$FromClip,
  [Parameter(Mandatory)][string]$ToAnims,
  [Parameter(Mandatory)][string]$ToClip,
  [Parameter(Mandatory)][string]$Name,
  [Parameter(Mandatory)][string]$DepotPath,
  [string]$Rig = 'man_base',
  [string]$Tokens = '8,9,10,11,12,13,14',
  [switch]$Preview,
  [string]$MotionBricks = $env:NCN_MOTIONBRICKS,
  [string]$GamePath  = '',   # build.local.json's tools.game
  [string]$WolvenKit = '',   # build.local.json's tools.wolvenkit
  [string]$WolvenKitCook = '',
  [string]$Blender = '',     # build.local.json's tools.blender
  [double]$MaxDeg = 0.1,
  [double]$MaxCm = 0.1
)
$cfg = Join-Path $PSScriptRoot 'build_config.py'
if (-not $GamePath)  { $GamePath  = & python $cfg --get tools.game }
if (-not $WolvenKit) { $WolvenKit = & python $cfg --get tools.wolvenkit }
if (-not $Blender)   { $Blender   = & python $cfg --get tools.blender }

$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'build_config.py') --motionbricks; if ($LASTEXITCODE -ne 0) { exit 1 }   # off in build.json
$root = $PSScriptRoot
$work = Join-Path $root 'work'
# Windows PowerShell leaves $PSScriptRoot empty in a param default.
if (-not $WolvenKitCook) { $WolvenKitCook = Join-Path $work 'wk_nightly' }
if (-not $MotionBricks) { $MotionBricks = Join-Path (Split-Path (Split-Path (Split-Path $root))) 'MotionBricks' }
$mbPython = Join-Path $MotionBricks '.venv\Scripts\python.exe'
$rigPath  = "base\characters\base_entities\$Rig\$Rig.rig"
$rigJson  = Join-Path $work "npcrig\cr2w\$rigPath.json"
$run      = Join-Path $work ('run\' + [IO.Path]::GetFileNameWithoutExtension($DepotPath))
$out      = Join-Path $work "depot\$DepotPath"

foreach ($p in @($WolvenKit, $rigJson, $FromAnims, $ToAnims, $mbPython)) {
  if (-not (Test-Path $p)) { throw "not found: $p (rig: guide section 3; venv: guide section 5)" }
}
if ($Preview -and -not (Test-Path $Blender)) { throw "not found: $Blender" }
if (-not (Test-Path (Join-Path $WolvenKitCook 'WolvenKit.Modkit.dll'))) {
  throw "no SIMD-capable WolvenKit at $WolvenKitCook -- build it (README, Toolchain)"
}
$FromAnims = (Resolve-Path $FromAnims).Path
$ToAnims   = (Resolve-Path $ToAnims).Path
if (Test-Path $run) { Remove-Item $run -Recurse -Force }
New-Item -ItemType Directory -Force $run, (Split-Path $out) | Out-Null

function Step($what, [scriptblock]$body) {
  Write-Host "-- $what" -ForegroundColor Cyan
  & $body
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

function Export-Set($label, $anims) {
  $dir = Join-Path $run $label
  New-Item -ItemType Directory -Force $dir | Out-Null
  $file = Join-Path $dir ([IO.Path]::GetFileName($anims))
  Copy-Item $anims $file
  Step "export $label" { & $WolvenKit export $file -o $dir -gp $GamePath -v Minimal }
  Step "serialize $label" { & $WolvenKit convert serialize $file -v Minimal }
  return $file
}

$fromFile = Export-Set 'from' $FromAnims | Select-Object -Last 1
$toFile   = Export-Set 'to' $ToAnims | Select-Object -Last 1
$made     = Join-Path $run "$Name.glb"

Push-Location $MotionBricks
try {
  Step 'generate' { & $mbPython (Join-Path $root 'mb_transition.py') "$fromFile.glb" $FromClip "$toFile.glb" $ToClip `
      $rigJson $Name $run --tokens $Tokens }
} finally { Pop-Location }

$stem = [IO.Path]::GetFileName($out)
$container = Join-Path $run "container\$stem.json"
New-Item -ItemType Directory -Force (Split-Path $container) | Out-Null
Step 'prep container' { python (Join-Path $root 'anims_json.py') prep "$fromFile.json" $rigPath $container }
Step 'deserialize container' { & $WolvenKit convert deserialize $container -o (Split-Path $out) -v Minimal }

$bridge = Join-Path $root 'wk_anims\bin\Release\net10.0\WkAnims.exe'
Step 'build wk_anims' { dotnet build (Join-Path $root 'wk_anims\WkAnims.csproj') -c Release -v q --nologo | Out-Null }
Step 'cook' { & $bridge $made $out $GamePath $WolvenKitCook }

$check = Join-Path $run 'check'
New-Item -ItemType Directory -Force $check | Out-Null
Step 'export cooked' { & (Join-Path $WolvenKitCook 'WolvenKit.CLI.exe') export $out -o $check -gp $GamePath -v Minimal }
Step 'verify' { python (Join-Path $root 'verify_retarget.py') $made (Join-Path $check "$stem.glb") --max-deg $MaxDeg --max-cm $MaxCm }

# A compressed buffer re-exports the same pose and still plays wrong, so verify cannot see it.
Copy-Item $out (Join-Path $check $stem)
Step 'serialize cooked' { & (Join-Path $WolvenKitCook 'WolvenKit.CLI.exe') convert serialize (Join-Path $check $stem) -v Minimal }
$kinds = Select-String -Path (Join-Path $check "$stem.json") -Pattern '"animAnimationBuffer(\w+)"' -AllMatches |
  ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value }
$notSimd = @($kinds | Where-Object { $_ -ne 'Simd' })
if (-not $kinds -or $notSimd) {
  throw "cooked buffers are not all SIMD: $(($kinds | Group-Object | ForEach-Object { "$($_.Count) $($_.Name)" }) -join ', ')"
}
Step 'check fallback' { python (Join-Path $root 'anims_json.py') check (Join-Path $check "$stem.json") }

if ($Preview) {
  Step 'join clips' { python (Join-Path $root 'mb_preview.py') whole $run $Name }
  $env:RIG = $Rig
  $env:RUN = $run
  Step 'render body' { & $Blender -b -t 4 --python (Join-Path $root 'blender_transition.py') }
  Step 'make gif' { python (Join-Path $root 'mb_preview.py') gif $run $Name }
}

Write-Host "OK  $out" -ForegroundColor Green
