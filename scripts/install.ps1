$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Install Git for Windows, open a new PowerShell, and run this installer again.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Invoke-Expression (Invoke-RestMethod https://astral.sh/uv/install.ps1)
    $env:PATH = "$HOME\.local\bin;$env:PATH"
}
$PackageSpec = if ($env:OMA0_PACKAGE_SPEC) { $env:OMA0_PACKAGE_SPEC } else { 'git+https://github.com/3clyp50/oh-my-agent-zero.git' }
uv tool install --python 3.12 $PackageSpec
if ($LASTEXITCODE -ne 0) { throw 'Launcher installation failed.' }
$ToolsBin = uv tool dir --bin
if ($LASTEXITCODE -ne 0) { throw 'Could not locate installed tools.' }
$env:PATH = "$ToolsBin;$env:PATH"
& (Join-Path $ToolsBin 'a0-native.exe') install
if ($LASTEXITCODE -ne 0) { throw 'Agent Zero installation failed.' }
& ([scriptblock]::Create((Invoke-RestMethod https://raw.githubusercontent.com/agent0ai/a0-connector/main/install.ps1)))
& (Join-Path $ToolsBin 'a0.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'a0-connector installation verification failed.' }
Write-Host 'Both Agent Zero and a0-connector are installed.'
Write-Host "Start Agent Zero with: & '$ToolsBin\a0-native.exe' start"
Write-Host "In another terminal, open chat: & '$ToolsBin\a0.exe' --host http://127.0.0.1:50001 --connect --no-docker-discovery"
