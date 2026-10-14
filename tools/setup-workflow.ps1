$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $repoRoot '.runtime\qwen21-nsfw-pose-skill'
$upstream = 'https://github.com/Arekejoker/qwen21-nsfw-pose-skill.git'
$commit = '4ca900d'

if (-not (Test-Path -LiteralPath (Join-Path $runtimeRoot 'scripts\qwen_pose_test.py'))) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeRoot) -Force | Out-Null
    git clone $upstream $runtimeRoot
    if ($LASTEXITCODE -ne 0) { throw 'Unable to clone the workflow dependency.' }
}

if (Test-Path -LiteralPath (Join-Path $runtimeRoot '.git')) {
    git -C $runtimeRoot fetch --depth 1 origin $commit
    if ($LASTEXITCODE -ne 0) { throw 'Unable to fetch the pinned workflow commit.' }
    git -C $runtimeRoot checkout --detach $commit
    if ($LASTEXITCODE -ne 0) { throw 'Unable to check out the pinned workflow commit.' }
}

$lockFile = Join-Path $runtimeRoot 'scripts\media_lock.py'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'media_lock_windows.py') -Destination $lockFile -Force

$runnerFile = Join-Path $runtimeRoot 'scripts\qwen_pose_test.py'
$runner = Get-Content -LiteralPath $runnerFile -Raw
$runner = $runner.Replace('wf[save_id]["inputs"]["filename_prefix"] = f"poselab/{cfg[''name'']}"', 'safe_name = Path(str(cfg["name"])).name.replace("/", "_").replace("\\", "_")' + [Environment]::NewLine + '    wf[save_id]["inputs"]["filename_prefix"] = f"qianmi_pose_{safe_name}"')
$runner = [regex]::Replace(
    $runner,
    'return 0\r?\n\r?\nif __name__ == "__main__":',
    'return 0 if res["ok"] else 1' + [Environment]::NewLine + [Environment]::NewLine + 'if __name__ == "__main__":'
)
Set-Content -LiteralPath $runnerFile -Value $runner -Encoding utf8
if ($runner -notmatch 'qianmi_pose_\{safe_name\}' -or $runner -notmatch 'return 0 if res\["ok"\] else 1') {
    throw 'Workflow compatibility patch verification failed.'
}

$installDir = Join-Path $runtimeRoot 'install'
New-Item -ItemType Directory -Path $installDir -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $repoRoot 'config\windows_extra_model_paths.yaml') -Destination (Join-Path $installDir 'windows_extra_model_paths.yaml') -Force

Write-Host "Workflow ready: $runtimeRoot"
