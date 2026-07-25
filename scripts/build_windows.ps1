[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $ProjectRoot "build\pyinstaller"
$Executable = Join-Path $ProjectRoot "dist\sius-ingest.exe"
$ChecksumFile = Join-Path $ProjectRoot "dist\SHA256SUMS.txt"

Push-Location $ProjectRoot
try {
    New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null

    if (-not $SkipInstall) {
        & $PythonCommand -m pip install -e ".[build]"
        if ($LASTEXITCODE -ne 0) {
            throw "Installing the build dependencies failed."
        }
    }

    & $PythonCommand -m PyInstaller `
        --clean `
        --noconfirm `
        --onefile `
        --console `
        --noupx `
        --name "sius-ingest" `
        --paths "src" `
        --distpath "dist" `
        --workpath $BuildRoot `
        --specpath $BuildRoot `
        "src\sius_ingest\app.py"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }

    if (-not (Test-Path $Executable -PathType Leaf)) {
        throw "Expected executable was not created at $Executable."
    }

    $Hash = (Get-FileHash -Path $Executable -Algorithm SHA256).Hash.ToLowerInvariant()
    $ChecksumContents = "$Hash  sius-ingest.exe`n"
    [System.IO.File]::WriteAllText(
        $ChecksumFile,
        $ChecksumContents,
        [System.Text.Encoding]::ASCII
    )

    Write-Host "Built $Executable"
    Write-Host "SHA-256: $Hash"
}
finally {
    Pop-Location
}
