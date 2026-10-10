$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$outputDirectory = Join-Path $repositoryRoot "dist"
$commit = (& git -C $repositoryRoot rev-parse HEAD).Trim()
if (-not $commit) { throw "Git commit could not be determined." }
if (@(& git -C $repositoryRoot status --porcelain --untracked-files=normal).Count -gt 0) {
    throw "Distribution requires a clean committed release. Commit or review changes before packaging."
}

$packageName = "LeadHive-Windows-Local-$($commit.Substring(0, 12))"
$stageRoot = Join-Path $outputDirectory $packageName
$zipPath = Join-Path $outputDirectory "$packageName.zip"
$checksumPath = "$zipPath.sha256"

function Assert-InOutputDirectory([string]$Path) {
    $resolvedOutput = [IO.Path]::GetFullPath($outputDirectory).TrimEnd('\') + '\'
    $resolvedPath = [IO.Path]::GetFullPath($Path)
    if (-not $resolvedPath.StartsWith($resolvedOutput, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the distribution directory: $resolvedPath"
    }
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
Assert-InOutputDirectory $stageRoot
Assert-InOutputDirectory $zipPath
Assert-InOutputDirectory $checksumPath

if (Test-Path $stageRoot) { Remove-Item -LiteralPath $stageRoot -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
if (Test-Path $checksumPath) { Remove-Item -LiteralPath $checksumPath -Force }
New-Item -ItemType Directory -Path $stageRoot -Force | Out-Null
$snapshotRoot = Join-Path $outputDirectory "$packageName-source"
$snapshotZip = Join-Path $outputDirectory "$packageName-source.zip"
Assert-InOutputDirectory $snapshotRoot
Assert-InOutputDirectory $snapshotZip
if (Test-Path $snapshotRoot) { Remove-Item -LiteralPath $snapshotRoot -Recurse -Force }
if (Test-Path $snapshotZip) { Remove-Item -LiteralPath $snapshotZip -Force }
& git -C $repositoryRoot archive --format=zip --output=$snapshotZip $commit
if ($LASTEXITCODE -ne 0) { throw "Cannot export the committed release." }
Expand-Archive -LiteralPath $snapshotZip -DestinationPath $snapshotRoot

$rootFiles = @(
    "Adopt-LeadHive.cmd",
    "Import-LeadHiveBackup.cmd",
    "Repair-LeadHiveInstance.cmd",
    "Resume-LeadHive.cmd",
    "Stop-LeadHiveOutbound.cmd",
    ".dockerignore",
    "Backup-LeadHive.cmd",
    "Diagnose-LeadHive.cmd",
    "Install-LeadHive.cmd",
    "Open-Manual.cmd",
    "Open-QuickStart.cmd",
    "Open-DeploymentGuide.cmd",
    "README.md",
    "Restore-LeadHive.cmd",
    "Start-LeadHive.cmd",
    "Stop-LeadHive.cmd",
    "Update-LeadHive.cmd",
    "compose.local.yaml"
)
$fixedFiles = @(
    "backend/.dockerignore",
    "backend/Dockerfile",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/requirements.lock",
    "deploy/nginx.conf",
    "deploy/README-FIRST.txt",
    "docs/73_WINDOWS_LOCAL_INSTALLER.md",
    "docs/DEPLOYMENT_OPTIONS.md",
    "docs/G14_BEGINNER_QUICKSTART.md",
    "docs/acceptance/LEADHIVE_ACCEPTANCE_SAMPLE.csv",
    "docs/82_LEADHIVE_USER_MANUAL.md",
    "frontend/.dockerignore",
    "frontend/Dockerfile",
    "frontend/index.html",
    "frontend/package-lock.json",
    "frontend/package.json",
    "frontend/tsconfig.json",
    "frontend/vite.config.ts"
)
$directoryPrefixes = @(
    ".agents/skills/leadhive-form-submit/",
    "backend/app/",
    "backend/migrations/",
    "frontend/src/",
    "scripts/windows/"
)

$trackedFiles = & git -C $repositoryRoot ls-files
$selectedFiles = $trackedFiles | Where-Object {
    $relativePath = $_
    $rootFiles -contains $relativePath -or
    $fixedFiles -contains $relativePath -or
    ($directoryPrefixes | Where-Object { $relativePath.StartsWith($_) }).Count -gt 0
} | Sort-Object -Unique

foreach ($relativePath in $selectedFiles) {
    $sourcePath = Join-Path $snapshotRoot $relativePath
    if (-not (Test-Path $sourcePath -PathType Leaf)) {
        throw "Tracked package file was not found: $relativePath"
    }
    $destinationPath = Join-Path $stageRoot $relativePath
    $destinationParent = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath
}
Remove-Item -LiteralPath $snapshotRoot -Recurse -Force
Remove-Item -LiteralPath $snapshotZip -Force

$readmeSource = Join-Path $stageRoot "deploy\README-FIRST.txt"
Move-Item -LiteralPath $readmeSource -Destination (Join-Path $stageRoot "README-FIRST.txt")
Remove-Item -LiteralPath (Join-Path $stageRoot "deploy\README-FIRST.txt") -ErrorAction SilentlyContinue

$versionText = @(
    "LeadHive Windows Local",
    "Commit: $commit",
    "BuiltAtUtc: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
) -join "`r`n"
$utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $stageRoot "VERSION.txt"), $versionText, $utf8WithoutBom)

$forbiddenFiles = Get-ChildItem $stageRoot -Recurse -Force | Where-Object {
    $_.Name -like ".env*" -or $_.Name -like "*.dump*" -or
    $_.Name -in @("secrets.json", "credentials.json") -or
    $_.FullName -match "([\\/])node_modules([\\/]|$)" -or
    $_.FullName -match "([\\/])\.venv([\\/]|$)"
}
if ($forbiddenFiles) {
    throw "The package contains a secret or development-only file."
}

$manifestLines = Get-ChildItem $stageRoot -Recurse -File | Sort-Object FullName | ForEach-Object {
    $relativePath = $_.FullName.Substring($stageRoot.Length + 1).Replace('\', '/')
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash.ToLowerInvariant()
    "$hash  $relativePath"
}
[IO.File]::WriteAllText(
    (Join-Path $stageRoot "MANIFEST-SHA256.txt"),
    ($manifestLines -join "`r`n"),
    $utf8WithoutBom
)

Compress-Archive -LiteralPath $stageRoot -DestinationPath $zipPath -CompressionLevel Optimal

$zipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
[IO.File]::WriteAllText($checksumPath, "$zipHash  $([IO.Path]::GetFileName($zipPath))`r`n", $utf8WithoutBom)

$checksumRecord = (Get-Content -LiteralPath $checksumPath -Raw).Trim()
if ($checksumRecord -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
    throw "The package checksum record is invalid."
}
$recordedZipHash = $Matches[1].ToLowerInvariant()
$recordedZipName = $Matches[2]
$verifiedZipHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $zipPath).Hash.ToLowerInvariant()
if ($recordedZipName -ne [IO.Path]::GetFileName($zipPath) -or $recordedZipHash -ne $verifiedZipHash) {
    throw "The package checksum verification failed."
}

$verificationRoot = Join-Path $outputDirectory "$packageName-verification"
Assert-InOutputDirectory $verificationRoot
if (Test-Path $verificationRoot) { Remove-Item -LiteralPath $verificationRoot -Recurse -Force }
New-Item -ItemType Directory -Path $verificationRoot -Force | Out-Null
try {
    Expand-Archive -LiteralPath $zipPath -DestinationPath $verificationRoot
    $extractedRoot = Join-Path $verificationRoot $packageName
    foreach ($requiredFile in @(
        "Adopt-LeadHive.cmd",
        "Import-LeadHiveBackup.cmd",
        "Repair-LeadHiveInstance.cmd",
        "Resume-LeadHive.cmd",
        "Install-LeadHive.cmd",
        "Open-Manual.cmd",
        "Open-DeploymentGuide.cmd",
        "docs\DEPLOYMENT_OPTIONS.md",
        "Diagnose-LeadHive.cmd",
        "Restore-LeadHive.cmd",
        "compose.local.yaml",
        "backend\Dockerfile",
        "frontend\Dockerfile",
        "scripts\windows\DockerSetup.ps1",
        "scripts\windows\InstanceIdentity.ps1",
        "scripts\windows\Adopt-LeadHive.ps1",
        ".agents\skills\leadhive-form-submit\SKILL.md",
        "README-FIRST.txt",
        "docs\82_LEADHIVE_USER_MANUAL.md",
        "MANIFEST-SHA256.txt"
    )) {
        if (-not (Test-Path (Join-Path $extractedRoot $requiredFile) -PathType Leaf)) {
            throw "Package verification failed. Missing: $requiredFile"
        }
    }

    $manifestPath = Join-Path $extractedRoot "MANIFEST-SHA256.txt"
    $manifestEntries = @{}
    foreach ($manifestLine in Get-Content -LiteralPath $manifestPath) {
        if ($manifestLine -notmatch '^([0-9a-fA-F]{64})  (.+)$') {
            throw "Package manifest contains an invalid record: $manifestLine"
        }

        $expectedHash = $Matches[1].ToLowerInvariant()
        $relativePath = $Matches[2].Replace('\', '/')
        if ($manifestEntries.ContainsKey($relativePath)) {
            throw "Package manifest contains a duplicate path: $relativePath"
        }

        $manifestEntries[$relativePath] = $expectedHash
        $packagedPath = Join-Path $extractedRoot $relativePath.Replace('/', '\')
        if (-not (Test-Path -LiteralPath $packagedPath -PathType Leaf)) {
            throw "Package manifest references a missing file: $relativePath"
        }

        $actualHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $packagedPath).Hash.ToLowerInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "Package manifest hash verification failed: $relativePath"
        }
    }

    $packagedFiles = Get-ChildItem $extractedRoot -Recurse -File | ForEach-Object {
        $_.FullName.Substring($extractedRoot.Length + 1).Replace('\', '/')
    } | Where-Object { $_ -ne "MANIFEST-SHA256.txt" }
    foreach ($packagedFile in $packagedFiles) {
        if (-not $manifestEntries.ContainsKey($packagedFile)) {
            throw "Package contains a file that is absent from the manifest: $packagedFile"
        }
    }
    if ($manifestEntries.Count -ne @($packagedFiles).Count) {
        throw "Package manifest file count does not match the archive contents."
    }

    $parseErrors = @()
    Get-ChildItem (Join-Path $extractedRoot "scripts\windows") -Filter "*.ps1" | ForEach-Object {
        $tokens = $null
        $fileErrors = $null
        [Management.Automation.Language.Parser]::ParseFile(
            $_.FullName,
            [ref]$tokens,
            [ref]$fileErrors
        ) | Out-Null
        if ($fileErrors) { $parseErrors += $fileErrors }
    }
    if ($parseErrors) { throw "A packaged PowerShell script has a syntax error." }

    if (Get-Command docker -ErrorAction SilentlyContinue) {
        $verificationEnv = Join-Path $extractedRoot ".env.local"
        $verificationSettings = @(
            "POSTGRES_PASSWORD=package-verification-only",
            "SETTINGS_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
            "LEADHIVE_DATA_VOLUME=leadhive-package-validation-data",
            "LEADHIVE_PORT=18787",
            "CORS_ORIGINS=http://localhost:18787,http://127.0.0.1:18787",
            "PUBLIC_APP_URL=http://localhost:18787"
        ) -join "`r`n"
        [IO.File]::WriteAllText($verificationEnv, $verificationSettings, $utf8WithoutBom)
        & docker compose --env-file $verificationEnv -f (Join-Path $extractedRoot "compose.local.yaml") config --quiet
        if ($LASTEXITCODE -ne 0) { throw "The packaged Compose configuration is invalid." }
        Remove-Item -LiteralPath $verificationEnv -Force
    }
} finally {
    if (Test-Path $verificationRoot) {
        Assert-InOutputDirectory $verificationRoot
        Remove-Item -LiteralPath $verificationRoot -Recurse -Force
    }
    if (Test-Path $stageRoot) {
        Assert-InOutputDirectory $stageRoot
        Remove-Item -LiteralPath $stageRoot -Recurse -Force
    }
}

Write-Host "Package: $zipPath"
Write-Host "SHA256: $zipHash"
