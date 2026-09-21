Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:DockerInstallDocs = "https://docs.docker.com/desktop/setup/install/windows-install/"
$script:DockerLicenseUrl = "https://www.docker.com/legal/docker-subscription-service-agreement/"

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
}

function Add-DockerCliToCurrentPath {
    Refresh-ProcessPath
    if (Get-Command docker -ErrorAction SilentlyContinue) { return }

    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\resources\bin\docker.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
    )
    $dockerCli = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($dockerCli) {
        $env:Path = "$(Split-Path -Parent $dockerCli);$env:Path"
    }
}

function Get-DockerDesktopExecutable {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Docker\Docker\Docker Desktop.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    )
    return $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

function Test-DockerEngine {
    Add-DockerCliToCurrentPath
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return $false }
    & docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Wait-DockerEngine {
    param([int]$TimeoutSeconds = 300)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-DockerEngine) { return $true }
        Start-Sleep -Seconds 3
    } while ((Get-Date) -lt $deadline)
    return $false
}

function Show-DockerConsentDialog {
    $form = New-Object Windows.Forms.Form
    $form.Text = "LeadHive Setup - Docker Desktop"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = New-Object Drawing.Size(610, 390)

    $title = New-Object Windows.Forms.Label
    $title.Text = "Docker Desktop is required"
    $title.Font = New-Object Drawing.Font("Segoe UI", 16, [Drawing.FontStyle]::Bold)
    $title.Location = New-Object Drawing.Point(24, 20)
    $title.AutoSize = $true
    $form.Controls.Add($title)

    $description = New-Object Windows.Forms.Label
    $description.Text = @"
LeadHive runs locally in Docker Desktop. The official Docker installer will be
downloaded and installed for the current Windows user.

Docker Desktop is free for personal use, education, non-commercial open source,
and qualifying small businesses. Other commercial or government use may require
a paid Docker subscription. Review the official terms before continuing.

WSL 2 is also required. Enabling WSL may show a Windows administrator prompt and
may require one restart. Run Install-LeadHive.cmd again after restarting.
"@
    $description.Font = New-Object Drawing.Font("Segoe UI", 10)
    $description.Location = New-Object Drawing.Point(28, 67)
    $description.Size = New-Object Drawing.Size(555, 190)
    $form.Controls.Add($description)

    $docsLink = New-Object Windows.Forms.LinkLabel
    $docsLink.Text = "Official installation requirements"
    $docsLink.Location = New-Object Drawing.Point(28, 260)
    $docsLink.AutoSize = $true
    $docsLink.Add_LinkClicked({ Start-Process $script:DockerInstallDocs })
    $form.Controls.Add($docsLink)

    $licenseLink = New-Object Windows.Forms.LinkLabel
    $licenseLink.Text = "Docker Subscription Service Agreement"
    $licenseLink.Location = New-Object Drawing.Point(285, 260)
    $licenseLink.AutoSize = $true
    $licenseLink.Add_LinkClicked({ Start-Process $script:DockerLicenseUrl })
    $form.Controls.Add($licenseLink)

    $accept = New-Object Windows.Forms.CheckBox
    $accept.Text = "I reviewed and accept the Docker Subscription Service Agreement."
    $accept.Location = New-Object Drawing.Point(28, 295)
    $accept.Size = New-Object Drawing.Size(550, 25)
    $form.Controls.Add($accept)

    $install = New-Object Windows.Forms.Button
    $install.Text = "Install Docker Desktop"
    $install.Location = New-Object Drawing.Point(350, 338)
    $install.Size = New-Object Drawing.Size(145, 32)
    $install.Enabled = $false
    $install.DialogResult = [Windows.Forms.DialogResult]::OK
    $form.Controls.Add($install)

    $cancel = New-Object Windows.Forms.Button
    $cancel.Text = "Cancel"
    $cancel.Location = New-Object Drawing.Point(505, 338)
    $cancel.Size = New-Object Drawing.Size(78, 32)
    $cancel.DialogResult = [Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancel)

    $accept.Add_CheckedChanged({ $install.Enabled = $accept.Checked })
    $form.AcceptButton = $install
    $form.CancelButton = $cancel
    return $form.ShowDialog() -eq [Windows.Forms.DialogResult]::OK
}

function Assert-DockerSystemRequirements {
    $os = Get-CimInstance Win32_OperatingSystem
    if ($os.Caption -match "Server") {
        throw "Docker Desktop is not supported on Windows Server."
    }
    $build = [int]$os.BuildNumber
    $minimumBuild = if ($os.Caption -match "Windows 11") { 22631 } else { 19045 }
    if ($build -lt $minimumBuild) {
        throw "Windows is too old for the current Docker Desktop. Run Windows Update first."
    }
    if (($os.TotalVisibleMemorySize / 1MB) -lt 7.5) {
        throw "Docker Desktop requires at least 8 GB of RAM."
    }
}

function Ensure-WslForDocker {
    & wsl.exe --version *> $null
    if ($LASTEXITCODE -ne 0) {
        [Windows.Forms.MessageBox]::Show(
            "WSL 2 will now be enabled. Approve the Windows administrator prompt. A restart may be required.",
            "LeadHive Setup",
            [Windows.Forms.MessageBoxButtons]::OK,
            [Windows.Forms.MessageBoxIcon]::Information
        ) | Out-Null
        $wslInstall = Start-Process -FilePath "wsl.exe" -ArgumentList "--install", "--no-distribution" -Verb RunAs -Wait -PassThru
        if ($wslInstall.ExitCode -notin @(0, 3010)) {
            throw "WSL installation failed with exit code $($wslInstall.ExitCode)."
        }
        & wsl.exe --version *> $null
        if ($LASTEXITCODE -ne 0 -or $wslInstall.ExitCode -eq 3010) {
            [Windows.Forms.MessageBox]::Show(
                "Restart Windows, then double-click Install-LeadHive.cmd again.",
                "Restart required",
                [Windows.Forms.MessageBoxButtons]::OK,
                [Windows.Forms.MessageBoxIcon]::Information
            ) | Out-Null
            throw "Windows restart is required before Docker Desktop can be installed."
        }
    }

    $wslUpdate = Start-Process -FilePath "wsl.exe" -ArgumentList "--update" -Wait -PassThru
    if ($wslUpdate.ExitCode -ne 0) {
        throw "WSL update failed. Run 'wsl --update' as administrator and try again."
    }
}

function Install-DockerDesktop {
    Assert-DockerSystemRequirements
    if (-not (Show-DockerConsentDialog)) {
        throw "Docker Desktop installation was cancelled."
    }
    Ensure-WslForDocker

    $architecture = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
    if ($architecture -eq "Arm64") {
        $downloadUrl = "https://desktop.docker.com/win/main/arm64/Docker%20Desktop%20Installer.exe"
    } elseif ($architecture -eq "X64") {
        $downloadUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"
    } else {
        throw "Docker Desktop requires 64-bit Windows (x64 or Arm64)."
    }

    $installerPath = Join-Path $env:TEMP "LeadHive-Docker-Desktop-Installer.exe"
    try {
        Write-Step "Downloading the official Docker Desktop installer"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath -UseBasicParsing
        $signature = Get-AuthenticodeSignature -FilePath $installerPath
        if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Docker") {
            throw "The Docker Desktop installer signature could not be verified."
        }

        Write-Step "Installing Docker Desktop"
        $dockerInstall = Start-Process -FilePath $installerPath -ArgumentList @(
            "install",
            "--user",
            "--backend=wsl-2",
            "--no-windows-containers",
            "--accept-license"
        ) -Wait -PassThru
        if ($dockerInstall.ExitCode -notin @(0, 3010)) {
            throw "Docker Desktop installation failed with exit code $($dockerInstall.ExitCode)."
        }
        if ($dockerInstall.ExitCode -eq 3010) {
            throw "Restart Windows, then run Install-LeadHive.cmd again."
        }
    } finally {
        if (Test-Path $installerPath) { Remove-Item -LiteralPath $installerPath -Force }
    }

    Add-DockerCliToCurrentPath
    $dockerDesktop = Get-DockerDesktopExecutable
    if (-not $dockerDesktop) {
        throw "Docker Desktop was installed, but its executable was not found."
    }
    Start-Process -FilePath $dockerDesktop
}

function Ensure-DockerDesktop {
    Add-DockerCliToCurrentPath
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Install-DockerDesktop
    } elseif (-not (Test-DockerEngine)) {
        $dockerDesktop = Get-DockerDesktopExecutable
        if (-not $dockerDesktop) {
            throw "Docker CLI is installed, but Docker Desktop was not found."
        }
        Write-Step "Starting Docker Desktop"
        Start-Process -FilePath $dockerDesktop
    }

    Write-Step "Waiting for Docker Desktop"
    if (-not (Wait-DockerEngine)) {
        throw "Docker Desktop did not start within 5 minutes. Open Docker Desktop and check its status."
    }
    & docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is unavailable. Update Docker Desktop."
    }
}
