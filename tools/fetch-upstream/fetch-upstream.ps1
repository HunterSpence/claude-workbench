# fetch-upstream.ps1 - opt-in, pinned download of third-party skills (see README.md).
# Dry run by default. Windows PowerShell 5.1 and 7. Never call this from a hook.
#   .\fetch-upstream.ps1                         # show the plan
#   .\fetch-upstream.ps1 -Apply                  # download, verify SHA-256, install
#   .\fetch-upstream.ps1 -Apply -Only humanizer,impeccable [-Force] [-SkillsDir <path>]
#   .\fetch-upstream.ps1 -Optional [-Apply]      # also the optional design set (read THIRD-PARTY.md first)
#   .\fetch-upstream.ps1 -Pm [-Apply]            # the product-management pack instead of the default set
# If script execution is blocked on your machine, run the Python file directly instead (see README.md);
# never change or bypass the execution policy.
param([switch]$Apply, [string[]]$Only, [switch]$Force, [string]$SkillsDir, [string]$Lock, [switch]$Optional, [switch]$Pm)
$ErrorActionPreference = 'Stop'
$py = if (Get-Command py -ErrorAction SilentlyContinue) { @('py', '-3') }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { @('python') }
      else { throw 'Python 3.10+ is required (py -3 or python on PATH).' }
$a = @((Join-Path $PSScriptRoot 'fetch_upstream.py'))
if ($Apply) { $a += '--apply' }
if ($Force) { $a += '--force' }
if ($Optional) { $a += '--optional' }
if ($Pm) { $a += '--pm' }
if ($Only) { $a += @('--only', ($Only -join ',')) }
if ($SkillsDir) { $a += @('--skills-dir', $SkillsDir) }
if ($Lock) { $a += @('--lock', $Lock) }
$exe = $py[0]; $pre = @($py | Select-Object -Skip 1)
& $exe @pre @a
exit $LASTEXITCODE
