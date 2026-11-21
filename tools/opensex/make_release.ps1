<#
The animation repo's release artifacts: each pack's archive, AMM list and scene files, a zip per pack, dist\<pack>-<Version>.zip.

  powershell -File tools\opensex\make_release.ps1 -Version 0.2.0 [-Rigs all|test] [-Packs opensex,ostimng] [-Workers 4] [-NoBake]

-Rigs all (the default, a real release) bakes man_big, man_fat, woman_big and woman_fat too. -Rigs test stays on the
pack's man_base, woman_base and V. A rig's set is kept when it is newer than its NPC set, and a set that fails stops the
run before anything is packed. Nothing is uploaded: the last line is the gh command. docs/design/opensex-port.md §5.
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory)][string]$Version,
  [ValidateSet('all', 'test')][string]$Rigs = 'all',
  [string[]]$Packs = @('opensex', 'ostimng'),
  [int]$Workers = 4,
  [switch]$NoBake,   # zip what is built: no big/fat set baked, though -Rigs all still names them in clips.json
  [string]$Anims = ''   # build.json's packs
)
if (-not $Anims) { $Anims = python -c "import sys; sys.path.insert(0, r'$(Join-Path (Split-Path $PSScriptRoot) 'retarget')'); import build_config; print(build_config.load()['packs'])" }

$ErrorActionPreference = 'Stop'
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
$tools  = Split-Path $PSScriptRoot
$repo   = Split-Path $tools
$retarget = Join-Path $tools 'retarget'
$logs   = Join-Path $retarget 'work\run\release_logs'
$built  = Join-Path $retarget 'work\depot'
$dist   = Join-Path $repo 'dist'
$extra  = if ($Rigs -eq 'all' -and -not $NoBake) { @{ ma = @('man_big', 'man_fat'); wa = @('woman_big', 'woman_fat') } } else { @{} }
New-Item -ItemType Directory -Force $logs, $dist | Out-Null

function Step($what, [scriptblock]$body) {
  Write-Host "=== $what ($(Get-Date -Format HH:mm))" -ForegroundColor Cyan
  & $body
  if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

$queue = New-Object System.Collections.Queue
foreach ($pack in $Packs) {
  $depot = Join-Path $Anims "$pack\depot"
  foreach ($set in Get-ChildItem $depot -Recurse -Filter '*.anims' | Where-Object { $_.DirectoryName -match '\\npc$' }) {
    if ($set.Name -notmatch '_(ma|wa)\.anims$') { throw "not an NPC set: $($set.FullName)" }
    foreach ($rig in $extra[$Matches[1]]) {
      $rel = $set.FullName.Substring($depot.Length + 1) -replace '\\npc\\', "\$rig\"
      $rel = $rel -replace '\.anims$', "_$rig.anims"
      $dest = Join-Path $depot $rel
      if ((Test-Path $dest) -and (Get-Item $dest).LastWriteTime -ge $set.LastWriteTime) { continue }
      $queue.Enqueue([pscustomobject]@{ Set = $set.FullName; Rig = $rig; Rel = $rel; Dest = $dest; Name = "$pack-$rig-$($set.BaseName)" })
    }
  }
}

if ($queue.Count) {
  Write-Host "=== bake $($queue.Count) sets onto the big and fat rigs ($(Get-Date -Format HH:mm))" -ForegroundColor Cyan
  dotnet build (Join-Path $retarget 'wk_anims\WkAnims.csproj') -c Release -v q --nologo | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'build wk_anims failed' }
}
$running = @()
$failed = @()
while ($queue.Count -or $running) {
  while ($queue.Count -and $running.Count -lt $Workers) {
    $job = $queue.Dequeue()
    Write-Host "== $($job.Rel) ($($queue.Count) queued)"
    $log = Join-Path $logs "$($job.Name).log"
    $argv = @('-ExecutionPolicy', 'Bypass', '-File', "`"$(Join-Path $retarget 'retarget.ps1')`"", '-Anims', "`"$($job.Set)`"",
              '-Rig', $job.Rig, '-DepotPath', "`"$($job.Rel)`"", '-SkipBuild', '-RunName', $job.Name)
    $p = Start-Process powershell -ArgumentList $argv -PassThru -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    $null = $p.Handle   # ExitCode reads empty on a process whose handle was never taken
    $p.PriorityClass = 'BelowNormal'
    $running += [pscustomobject]@{ Process = $p; Job = $job }
  }
  Start-Sleep -Seconds 2
  $done = @(); $left = @()
  foreach ($r in $running) { if ($r.Process.HasExited) { $done += $r } else { $left += $r } }
  $running = $left
  foreach ($d in $done) {
    if ($d.Process.ExitCode -ne 0) {
      $failed += $d.Job.Rel
      Write-Host "FAILED $($d.Job.Rel), see $logs" -ForegroundColor Red
      continue
    }
    New-Item -ItemType Directory -Force (Split-Path $d.Job.Dest) | Out-Null
    Copy-Item (Join-Path $built $d.Job.Rel) $d.Job.Dest -Force
  }
}
if ($failed) { throw "$($failed.Count) sets failed: $($failed -join ', ')" }

$list = $Packs -join ','
$amm = Join-Path $PSScriptRoot 'make_amm_poses.py'
if ($Rigs -eq 'all') { Step 'name the rigs in clips.json' { python $amm --packs $list --add-rigs 'man_big,man_fat,woman_big,woman_fat' } }
Step 'scene workspots' { python (Join-Path $PSScriptRoot 'make_scene_workspots.py') --anims $Anims --packs $list }
Step 'AMM poses' { python $amm --packs $list --anims $Anims }

$pack_py = "import sys; sys.path.insert(0, r'$retarget'); import pack_transitions as p; [p.pack_archive(x) for x in sys.argv[1:]]"
Step 'pack archives' { python -c $pack_py @Packs }

# A zip per pack: GitHub refuses a release file over 2 GiB, and both packs together passed it in 0.2.2.
# Each keeps its licence and credits under licenses\<pack>, its licence differing per pack.
$names = @()
foreach ($pack in $Packs) {
  $stage = Join-Path $dist 'stage'
  if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
  $root = Join-Path $Anims $pack
  $license = if (Test-Path (Join-Path $root 'LICENSE')) { $root } else { $Anims }
  $held = Join-Path $stage "licenses\$pack"
  New-Item -ItemType Directory -Force $held | Out-Null
  Copy-Item (Join-Path $root 'CREDITS.md'), (Join-Path $license 'LICENSE') $held
  $name = Join-Path $dist "$pack-$Version.zip"
  if (Test-Path $name) { Remove-Item $name }
  # Windows' bsdtar by path: Git's tar, first on PATH from bash, reads C: as a remote host
  Step "zip $pack" { & "$env:SystemRoot\System32\tar.exe" -a -c -f $name -C $root archive bin -C $stage licenses }
  Remove-Item $stage -Recurse -Force
  if ((Get-Item $name).Length -ge 2GB) { throw "$name is over GitHub's 2 GiB per file" }
  $hash = (Get-FileHash $name -Algorithm SHA256).Hash
  Write-Host "$name  $([math]::Round((Get-Item $name).Length / 1MB)) MB  sha256 $hash"
  $names += "`"$name`""
}
Write-Host 'OK' -ForegroundColor Green
Write-Host "To publish: gh release create v$Version $($names -join ' ') --repo blackpotoftea/CyberpunkAnimations"
