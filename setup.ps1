# EasyDo HRMS MCP Setup Script for Windows
# Run: .\setup.ps1

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  EasyDo HRMS MCP Server Setup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get script directory
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SCRIPT_DIR

# Step 1: Check/Install Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow

$pythonCmd = $null
$pythonPaths = @("python", "python3", "py")

foreach ($cmd in $pythonPaths) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python 3\.([9]|[1-9][0-9])") {
            $pythonCmd = $cmd
            Write-Host "       Found: $version" -ForegroundColor Green
            break
        }
    } catch { }
}

if (-not $pythonCmd) {
    Write-Host "       Python 3.9+ not found. Installing..." -ForegroundColor Yellow

    # Try winget first
    $wingetAvailable = Get-Command winget -ErrorAction SilentlyContinue
    if ($wingetAvailable) {
        Write-Host "       Using winget to install Python..." -ForegroundColor Gray
        winget install Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $pythonCmd = "python"
    } else {
        # Download and install Python directly
        Write-Host "       Downloading Python installer..." -ForegroundColor Gray
        $installerUrl = "https://www.python.org/ftp/python/3.12.0/python-3.12.0-amd64.exe"
        $installerPath = "$env:TEMP\python-installer.exe"

        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
        Write-Host "       Running installer (this may take a minute)..." -ForegroundColor Gray
        Start-Process -FilePath $installerPath -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1" -Wait
        Remove-Item $installerPath -Force

        # Refresh PATH
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $pythonCmd = "python"
    }

    # Verify installation
    try {
        $version = & $pythonCmd --version 2>&1
        Write-Host "       Installed: $version" -ForegroundColor Green
    } catch {
        Write-Host "       ERROR: Python installation failed. Please install manually from python.org" -ForegroundColor Red
        exit 1
    }
}

# Step 2: Create virtual environment
Write-Host "[2/4] Setting up virtual environment..." -ForegroundColor Yellow

if (-not (Test-Path ".venv")) {
    & $pythonCmd -m venv .venv
}
Write-Host "       Virtual environment ready" -ForegroundColor Green

# Step 3: Install dependencies
Write-Host "[3/4] Installing dependencies..." -ForegroundColor Yellow

& .\.venv\Scripts\pip.exe install --upgrade pip --quiet
& .\.venv\Scripts\pip.exe install -r requirements.txt --quiet
& .\.venv\Scripts\pip.exe install -e . --quiet
Write-Host "       Dependencies installed" -ForegroundColor Green

# Step 4: Configure MCP
Write-Host "[4/4] Configuring Claude Code MCP..." -ForegroundColor Yellow

$venvPython = Join-Path $SCRIPT_DIR ".venv\Scripts\python.exe"
$mcpConfig = @{
    mcpServers = @{
        "easydo-hrms" = @{
            command = $venvPython
            args = @("-m", "mcp_server.server")
            cwd = $SCRIPT_DIR
        }
    }
}

$homeMcpPath = Join-Path $env:USERPROFILE ".mcp.json"

if (Test-Path $homeMcpPath) {
    $existingConfig = Get-Content $homeMcpPath -Raw | ConvertFrom-Json -AsHashtable
    if (-not $existingConfig.mcpServers) {
        $existingConfig["mcpServers"] = @{}
    }
    $existingConfig["mcpServers"]["easydo-hrms"] = @{
        command = $venvPython
        args = @("-m", "mcp_server.server")
        cwd = $SCRIPT_DIR
    }
    $existingConfig | ConvertTo-Json -Depth 4 | Set-Content $homeMcpPath
} else {
    $mcpConfig | ConvertTo-Json -Depth 4 | Set-Content $homeMcpPath
}
Write-Host "       Config saved to: $homeMcpPath" -ForegroundColor Green

# Done
Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Open/restart Claude Code" -ForegroundColor White
Write-Host "  2. Type: /mcp" -ForegroundColor White
Write-Host "  3. Say: login to prod with <your-phone>" -ForegroundColor White
Write-Host ""
Write-Host "Example: login to prod with 98XXXXXXXX" -ForegroundColor Gray
Write-Host ""
