# collect.ps1 - read-only Windows health snapshot for the pc-checkup skill. Changes NOTHING on the machine.
# Windows PowerShell 5.1 compatible; works without admin rights and says what it could not read.
# Usage: powershell -NoProfile -File collect.ps1 [-Days 30] [-OutDir <folder>]
# Matches events by provider + ID only, never by message text.
param([int]$Days = 30, [string]$OutDir = (Join-Path $env:USERPROFILE 'pc-checkup'))
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $OutDir | Out-Null
$report = Join-Path $OutDir ("report-{0:yyyyMMdd-HHmm}.txt" -f (Get-Date))
$since = (Get-Date).AddDays(-$Days)
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("pc-checkup report {0:yyyy-MM-dd HH:mm} | window: last $Days days | Admin: $admin" -f (Get-Date))

function Section($name, [scriptblock]$body) {
  Write-Host "  $name..."
  $lines.Add("`n## $name")
  try {
    $r = (& $body | Out-String -Width 250).TrimEnd()
    $lines.Add($(if ($r) { $r } else { '(none found)' }))
  } catch { $lines.Add("(could not read: $($_.Exception.Message))") }
}

Section 'System' {
  $cs = Get-CimInstance Win32_ComputerSystem; $os = Get-CimInstance Win32_OperatingSystem
  $bios = Get-CimInstance Win32_BIOS; $cv = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
  [pscustomobject]@{
    Model     = "$($cs.Manufacturer) $($cs.Model)"
    BIOS      = "$($bios.SMBIOSBIOSVersion) dated $($bios.ReleaseDate)"
    Windows   = "$($os.Caption) $($cv.DisplayVersion) build $($cv.CurrentBuild).$($cv.UBR)"
    LastBoot  = $os.LastBootUpTime
    CPU       = (Get-CimInstance Win32_Processor).Name -join '; '
    RAM_GB    = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    GPU       = (Get-CimInstance Win32_VideoController | ForEach-Object { "$($_.Name) driver $($_.DriverVersion) ($($_.DriverDate))" }) -join '; '
  } | Format-List
}

Section 'Pending reboot' {
  $k = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion'
  [pscustomobject]@{
    ComponentServicing = Test-Path "$k\Component Based Servicing\RebootPending"
    WindowsUpdate      = Test-Path "$k\WindowsUpdate\Auto Update\RebootRequired"
    FileRenames        = [bool](Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
  } | Format-List
}

Section 'Reliability index (1-10, Windows own score, newest)' {
  Get-CimInstance Win32_ReliabilityStabilityMetrics | Sort-Object TimeGenerated -Descending |
    Select-Object -First 1 TimeGenerated, SystemStabilityIndex | Format-List
}

# Crash/error events. K = how to group: p0 = by first event field (app or service name), wer = by report type + app.
$checks = @(
  @{L='System'; P='Microsoft-Windows-WER-SystemErrorReporting'; I=1001; W='BLUE SCREEN (BSOD) - message holds the stop code'}
  @{L='System'; P='Microsoft-Windows-Kernel-Power'; I=41; W='Hard reset / power loss without clean shutdown'}
  @{L='System'; P='EventLog'; I=6008; W='Unexpected shutdown'}
  @{L='System'; P='Microsoft-Windows-WHEA-Logger'; I=1,17,18,19,46,47; W='HARDWARE error (CPU / RAM / PCIe)'}
  @{L='System'; P='Display'; I=4101; W='Graphics driver stopped responding and recovered'}
  @{L='System'; P='nvlddmkm'; I=13,14,153; W='NVIDIA driver error'}
  @{L='System'; P='amdkmdag','amdkmdap'; I=4101,62464; W='AMD graphics driver error'}
  @{L='System'; P='disk'; I=7,11,51,153; W='DISK I/O error (bad block / retry / paging)'}
  @{L='System'; P='stornvme','storahci','iaStorVD','iaStorAC','iaStorA'; I=129; W='Storage controller reset'}
  @{L='System'; P='Ntfs','Microsoft-Windows-Ntfs'; I=55; W='File system corruption'}
  @{L='System'; P='Microsoft-Windows-Resource-Exhaustion-Detector'; I=2004; W='Ran low on memory'}
  @{L='System'; P='Microsoft-Windows-Kernel-Processor-Power'; I=37; W='CPU slowed by firmware (heat or power limit)'}
  @{L='System'; P='Microsoft-Windows-WindowsUpdateClient'; I=20; W='Windows Update install failed'}
  @{L='System'; P='Microsoft-Windows-Kernel-PnP'; I=219; W='Driver failed to load'}
  @{L='System'; P='Service Control Manager'; I=7031,7034; W='Service crashed'; K='p0'}
  @{L='System'; P='Service Control Manager'; I=7000,7009,7023; W='Service failed to start'; K='p0'}
  @{L='Application'; P='Application Error'; I=1000; W='App crashed'; K='p0'}
  @{L='Application'; P='Application Hang'; I=1002; W='App froze'; K='p0'}
  @{L='Application'; P='Windows Error Reporting'; I=1001; W='Kernel error reports (LiveKernelEvent 141/117 = GPU hang; BlueScreen)'; K='wer'}
)
Section "Crashes and errors (last $Days days; nothing listed = clean)" {
  foreach ($c in $checks) {
    # a provider not installed on this machine (e.g. another GPU vendor's driver) throws "parameter is incorrect" = nothing to report
    try { $ev = @(Get-WinEvent -FilterHashtable @{LogName=$c.L; ProviderName=$c.P; Id=$c.I; StartTime=$since} -ErrorAction SilentlyContinue) }
    catch { continue }
    if ($c.K -eq 'wer') { $ev = @($ev | Where-Object { "$($_.Properties[2].Value)" -match '^(LiveKernelEvent|BlueScreen)$' }) }
    if (-not $ev) { continue }
    "### $($c.W): $($ev.Count)x, newest $($ev[0].TimeCreated)"
    $ev | Group-Object {
      if ($c.K -eq 'p0') { "$($_.Properties[0].Value)" }
      elseif ($c.K -eq 'wer') { "$($_.Properties[2].Value) $($_.Properties[5].Value)" }
      else { "$($_.ProviderName)/$($_.Id)" }
    } | Sort-Object Count -Descending | Select-Object -First 8 | ForEach-Object {
      $e = $_.Group[0]
      "  {0}x {1} | newest {2:yyyy-MM-dd HH:mm} | {3}" -f $_.Count, $_.Name, $e.TimeCreated,
        ((("$($e.Message)" -replace '\s+', ' ')[0..279]) -join '')
    }
  }
}

Section 'Drives and free space' {
  Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter, FileSystemLabel, FileSystem, HealthStatus,
    @{n='SizeGB';e={[math]::Round($_.Size / 1GB)}}, @{n='FreeGB';e={[math]::Round($_.SizeRemaining / 1GB, 1)}},
    @{n='FreePct';e={ if ($_.Size) { [math]::Round(100 * $_.SizeRemaining / $_.Size) } }} | Format-Table -AutoSize
  Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, HealthStatus, OperationalStatus,
    @{n='SizeGB';e={[math]::Round($_.Size / 1GB)}} | Format-Table -AutoSize
}

Section 'Disk wear and errors (needs admin)' {
  Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object DeviceId, Wear, Temperature, TemperatureMax,
    ReadErrorsUncorrected, WriteErrorsUncorrected, PowerOnHours | Format-Table -AutoSize
}

Section 'Memory and busiest processes' {
  $os = Get-CimInstance Win32_OperatingSystem
  "RAM free {0:N1} of {1:N1} GB | commit free {2:N1} of {3:N1} GB" -f ($os.FreePhysicalMemory / 1MB),
    ($os.TotalVisibleMemorySize / 1MB), ($os.FreeVirtualMemory / 1MB), ($os.TotalVirtualMemorySize / 1MB)
  Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 Name, Id,
    @{n='RAM_MB';e={[math]::Round($_.WorkingSet64 / 1MB)}}, @{n='CPU_sec';e={[math]::Round($_.CPU)}} | Format-Table -AutoSize
}

Section 'Battery' {
  $x = Join-Path $env:TEMP 'pc-checkup-battery.xml'
  powercfg /batteryreport /xml /output $x | Out-Null
  $b = New-Object xml; $b.Load($x); Remove-Item $x -ErrorAction SilentlyContinue
  foreach ($bt in $b.BatteryReport.Batteries.Battery) {
    [pscustomobject]@{ DesignmWh = $bt.DesignCapacity; FullChargemWh = $bt.FullChargeCapacity
      HealthPct = [math]::Round(100 * [double]$bt.FullChargeCapacity / [math]::Max(1, [double]$bt.DesignCapacity)); Cycles = $bt.CycleCount }
  }
}

Section 'Power plan' {
  powercfg /getactivescheme
}

Section 'Devices with problems (error code; 22 = disabled on purpose, 28 = no driver)' {
  Get-CimInstance Win32_PnPEntity | Where-Object { $_.ConfigManagerErrorCode -ne 0 } |
    Select-Object Name, PNPClass, ConfigManagerErrorCode | Format-Table -AutoSize -Wrap
}

Section 'Startup programs (current user and machine)' {
  Get-CimInstance Win32_StartupCommand | Select-Object Name, Command, Location | Format-Table -AutoSize -Wrap
}

Section 'Network adapters' {
  Get-NetAdapter | Where-Object Status -eq 'Up' | Select-Object Name, InterfaceDescription, LinkSpeed | Format-Table -AutoSize
}

Set-Content -Path $report -Value $lines -Encoding UTF8
Write-Host "`nReport: $report"
