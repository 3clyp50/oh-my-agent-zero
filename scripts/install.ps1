$ErrorActionPreference = 'Stop'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Install Git for Windows, open a new PowerShell, and run this installer again.'
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $Installer = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName() + '.ps1')
    try {
        Invoke-WebRequest https://astral.sh/uv/install.ps1 -OutFile $Installer
        & $Installer
        $env:PATH = "$HOME\.local\bin;$env:PATH"
    } finally {
        Remove-Item $Installer -ErrorAction SilentlyContinue
    }
}
uv tool install --python 3.12 git+https://github.com/3clyp50/oh-my-agent-zero.git
if ($LASTEXITCODE -ne 0) { throw 'Launcher installation failed.' }
$ToolsBin = uv tool dir --bin
& (Join-Path $ToolsBin 'a0-native.exe') install
if ($LASTEXITCODE -ne 0) { throw 'Agent Zero installation failed.' }
Write-Host "Start Agent Zero with: & '$ToolsBin\a0-native.exe' start"
