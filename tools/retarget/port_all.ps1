# Every source in build.json end to end, in its order: its inventory, then every stage into its own run folder and
# pack; each pack's clips.json gains the bodies it now carries. Every side of a scene of two or more is baked on both
# bodies. A stage stopping stops the run; a clip already baked is kept, so a rerun resumes.
param([string[]]$Only = @())
$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot

function Step([string]$what, [string[]]$cmd) {
    Write-Host "=== $what $(Get-Date -Format 'HH:mm:ss')"
    & python @cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

# build_config checks the paths (no two sources share a folder) before anything runs
Step 'build.json' @("$here\build_config.py")
$root  = Split-Path (Split-Path $here)
$build = Get-Content (Join-Path $root 'build.json') -Raw | ConvertFrom-Json
function Abs([string]$p) { if ([IO.Path]::IsPathRooted($p)) { $p } else { [IO.Path]::GetFullPath((Join-Path $root $p)) } }
foreach ($p in $build.sources.PSObject.Properties) {
    $name = $p.Name
    if ($Only.Count -and $name -notin $Only) { continue }
    switch ($p.Value.inventory) {
        'opensex' { }   # skyrim_port's own inventory stage, run by 'all'
        'ostimng' { Step "$name inventory" @("$here\skyrim_scenes_ostimng.py", (Abs $p.Value.run), '--ostimng', (Abs $p.Value.input)) }
        default   { throw "build.json: $name has no inventory '$($p.Value.inventory)'" }
    }
    Step $name @("$here\skyrim_port.py", 'all', '--source', $name)
}
Write-Host "=== done $(Get-Date -Format 'HH:mm:ss')"
