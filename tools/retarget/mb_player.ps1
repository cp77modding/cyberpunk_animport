<#
Bakes the batch's gen_*_ma / _wa sets onto V's skeletons with retarget.ps1, then fills "player" in gen_results.jsonl.

  powershell -File tools\retarget\mb_player.ps1 [-Workers 4] [-Only <regex>] [-DepotPath ncn\anims\player]

Output: work\depot\<DepotPath>\gen_<set>_pma / _pwa.anims. A set that fails is named at the end and the rest go on; its
sides stay null. A set already baked and newer than its NPC set is kept. Each worker is one low-priority retarget.ps1
with its own run folder and log. -Only or another -DepotPath is a trial: the results file is left alone.
#>
param(
  [int]$Workers = 4,
  [string]$Only = '',
  [string]$DepotPath = 'ncn\anims\player'
)
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'build_config.py') --motionbricks; if ($LASTEXITCODE -ne 0) { exit 1 }   # off in build.json
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
$root   = $PSScriptRoot
$work   = Join-Path $root 'work'
$npc    = Join-Path $work 'depot\ncn\anims\npc'
$player = Join-Path $work "depot\$DepotPath"
$logs   = Join-Path $work 'run\mb_player_logs'
New-Item -ItemType Directory -Force $logs | Out-Null

$queue = New-Object System.Collections.Queue
foreach ($set in Get-ChildItem $npc -Filter 'gen_*.anims') {
  if ($Only -and $set.Name -notmatch $Only) { continue }
  if ($set.Name -notmatch '_(m|w)a\.anims$') { throw "not an NPC set: $($set.Name)" }
  $body = if ($Matches[1] -eq 'm') { 'man' } else { 'woman' }
  $name = $set.Name -replace '_([mw])a\.anims$', '_p$1a.anims'
  $out  = Join-Path $player $name
  # retarget.ps1 writes $out before its checks, so a run killed mid-set leaves a file that looks baked; the mark says not
  $mark = Join-Path $logs "$name.baking"
  if ((Test-Path $out) -and -not (Test-Path $mark) -and (Get-Item $out).LastWriteTime -ge $set.LastWriteTime) { continue }
  $queue.Enqueue([pscustomobject]@{ Set = $set.FullName; Body = $body; Name = $name; Out = $out; Mark = $mark })
}

# retarget.ps1 builds this too: one build first, or the workers fight over its output
dotnet build (Join-Path $root 'wk_anims\WkAnims.csproj') -c Release -v q --nologo | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'build wk_anims failed' }

$running = @()
$failed = @()
while ($queue.Count -or $running) {
  while ($queue.Count -and $running.Count -lt $Workers) {
    $job = $queue.Dequeue()
    Write-Host "== $($job.Name) ($($queue.Count) queued)" -ForegroundColor Cyan
    $log = Join-Path $logs "$($job.Name).log"
    New-Item -ItemType File -Force $job.Mark | Out-Null
    $argv = @('-ExecutionPolicy', 'Bypass', '-File', "`"$(Join-Path $root 'retarget.ps1')`"", '-Anims', "`"$($job.Set)`"",
              '-Body', $job.Body, '-DepotPath', "`"$DepotPath\$($job.Name)`"", '-SkipBuild')
    $p = Start-Process powershell -ArgumentList $argv -PassThru -NoNewWindow -RedirectStandardOutput $log -RedirectStandardError "$log.err"
    $null = $p.Handle   # ExitCode reads empty on a process whose handle was never taken
    $p.PriorityClass = 'BelowNormal'
    $running += [pscustomobject]@{ Process = $p; Job = $job }
  }
  Start-Sleep -Seconds 2
  # one read of HasExited per worker: two can lose one that exits between them
  $done = @(); $left = @()
  foreach ($r in $running) { if ($r.Process.HasExited) { $done += $r } else { $left += $r } }
  $running = $left
  foreach ($d in $done) {
    if ($d.Process.ExitCode -ne 0) {
      $failed += $d.Job.Name
      Write-Host "FAILED $($d.Job.Name), see $logs" -ForegroundColor Red
      if (Test-Path $d.Job.Out) { Remove-Item $d.Job.Out }
    }
    Remove-Item $d.Job.Mark
  }
}
if (-not $Only -and $DepotPath -eq 'ncn\anims\player') {
  python (Join-Path $root 'mb_batch.py') player $player (Join-Path $work 'run\gen_results.jsonl')
  if ($LASTEXITCODE -ne 0) { throw 'filling the results failed' }
}
if ($failed) { throw "failed: $($failed -join ', ')" }
Write-Host 'OK' -ForegroundColor Green
