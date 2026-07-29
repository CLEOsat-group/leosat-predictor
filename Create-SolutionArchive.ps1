param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$OutputZip,

    [Parameter(Mandatory = $false)]
    [string]$SourcePath = ".",

    [switch]$Force,

    [switch]$Verify,

    [switch]$ListOnly
)

$ErrorActionPreference = "Stop"

# Resolve source folder
$SourceRoot = (Resolve-Path -LiteralPath $SourcePath).Path.TrimEnd('\', '/')

if (-not (Test-Path -LiteralPath $SourceRoot -PathType Container)) {
    throw "Source path is not a folder: $SourceRoot"
}

# If only a filename is given, place the ZIP next to the source folder.
# This prevents the archive from being included inside itself.
$outputDir = [System.IO.Path]::GetDirectoryName($OutputZip)

if ([string]::IsNullOrWhiteSpace($outputDir)) {
    $parentDir = Split-Path -Parent $SourceRoot
    $OutputZip = Join-Path $parentDir $OutputZip
}
else {
    $OutputZip = [System.IO.Path]::GetFullPath($OutputZip)
}

if ([System.IO.Path]::GetExtension($OutputZip) -ne ".zip") {
    $OutputZip = "$OutputZip.zip"
}

$OutputZip = [System.IO.Path]::GetFullPath($OutputZip)

# Exclusion rules
$ExcludedDirectoryNames = @(
    ".git",
    ".vs",
    ".idea",
    ".venv",
    "venv",
    "env",
    "bin",
    "obj",
    "packages",
    "TestResults",
    "node_modules",
    "__pycache__",
    # Predictor-specific:
    "raw_results"    # Exclude raw analysis outputs, keep TLE cache (data/tle/)
)

# Generated output is excluded only at the repository root. Source-controlled
# tooling under tools/build must remain part of solution archives.
$ExcludedRootDirectoryNames = @(
    "build",
    "dist"
)

$ExcludedExtensions = @(
    ".user",
    ".suo",
    ".pdb",
    ".cache",
    ".ilk",
    ".log",
    ".pyc",           # Python compiled bytecode
    ".db"             # SQLite databases (predictors can regenerate)
)

function Get-RelativeArchivePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )

    $relative = $FullPath.Substring($SourceRoot.Length).TrimStart('\', '/')
    return $relative.Replace('\', '/')
}

function Test-IsExcludedFile {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.FileInfo]$File
    )

    $fullPath = [System.IO.Path]::GetFullPath($File.FullName)

    # Never include the output ZIP itself.
    if ($fullPath -eq $OutputZip) {
        return $true
    }

    $relativePath = Get-RelativeArchivePath -FullPath $fullPath
    $parts = $relativePath -split "[\\/]"

    if ($parts.Count -gt 0 -and $ExcludedRootDirectoryNames -contains $parts[0]) {
        return $true
    }

    foreach ($part in $parts) {
        if ($ExcludedDirectoryNames -contains $part) {
            return $true
        }
    }

    $extension = [System.IO.Path]::GetExtension($File.Name)

    if ($ExcludedExtensions -contains $extension) {
        return $true
    }

    return $false
}

Write-Host "Scanning source folder..."
Write-Host "Source : $SourceRoot"
Write-Host "Output : $OutputZip"
Write-Host ""

$FilesToArchive = Get-ChildItem -LiteralPath $SourceRoot -Recurse -File -Force |
    Where-Object { -not (Test-IsExcludedFile -File $_) }

$FileCount = @($FilesToArchive).Count

Write-Host "Files selected for archive: $FileCount"

if ($FileCount -eq 0) {
    throw "No files were selected for the archive. Check SourcePath and exclusion rules."
}

if ($ListOnly) {
    Write-Host ""
    Write-Host "First selected files:"
    $FilesToArchive |
        Select-Object -First 100 |
        ForEach-Object { Write-Host "  $(Get-RelativeArchivePath -FullPath $_.FullName)" }

    Write-Host ""
    Write-Host "ListOnly mode enabled. No ZIP was created."
    exit 0
}

if (Test-Path -LiteralPath $OutputZip) {
    if ($Force) {
        Remove-Item -LiteralPath $OutputZip -Force
    }
    else {
        throw "Output file already exists: $OutputZip. Use -Force to overwrite it."
    }
}

$outputFolder = Split-Path -Parent $OutputZip

if (-not (Test-Path -LiteralPath $outputFolder)) {
    New-Item -ItemType Directory -Path $outputFolder -Force | Out-Null
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$zipStream = [System.IO.File]::Open($OutputZip, [System.IO.FileMode]::CreateNew)
$zipArchive = New-Object System.IO.Compression.ZipArchive($zipStream, [System.IO.Compression.ZipArchiveMode]::Create)

try {
    foreach ($file in $FilesToArchive) {
        $entryName = Get-RelativeArchivePath -FullPath $file.FullName

        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zipArchive,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $zipArchive.Dispose()
    $zipStream.Dispose()
}

$zipInfo = Get-Item -LiteralPath $OutputZip

Write-Host ""
Write-Host "Archive created successfully."
Write-Host "Files  : $FileCount"
Write-Host "Size   : $([math]::Round($zipInfo.Length / 1MB, 2)) MB"
Write-Host "Output : $OutputZip"

if ($Verify) {
    Write-Host ""
    Write-Host "Verifying ZIP contents..."

    $readZip = [System.IO.Compression.ZipFile]::OpenRead($OutputZip)

    try {
        $entryCount = $readZip.Entries.Count
        Write-Host "ZIP entries: $entryCount"

        if ($entryCount -eq 0) {
            throw "Verification failed: ZIP contains no entries."
        }

        $ArchiveEntryNames = @($readZip.Entries | ForEach-Object { $_.FullName })
        $RequiredBuildToolPaths = @(
            "tools/build/build_gui_windows.ps1",
            "tools/build/verify_gui_windows_artifact.ps1"
        )
        foreach ($RequiredPath in $RequiredBuildToolPaths) {
            $RequiredSourcePath = Join-Path $SourceRoot $RequiredPath
            if ((Test-Path -LiteralPath $RequiredSourcePath -PathType Leaf) -and
                ($ArchiveEntryNames -notcontains $RequiredPath)) {
                throw "Verification failed: required source tool is missing from ZIP: $RequiredPath"
            }
        }

        $badEntries = $readZip.Entries |
             Where-Object {
                 $_.FullName -match '^(build|dist)(/|$)' -or
                 $_.FullName -match '(^|/)(\.git|\.vs|\.idea|\.venv|venv|env|bin|obj|packages|TestResults|node_modules|__pycache__|raw_results)(/|$)' -or
                 $_.FullName -match '\.(user|suo|pdb|cache|ilk|log|pyc|db)$'
             }

        if ($badEntries) {
            Write-Warning "Some excluded-looking entries were found:"
            $badEntries |
                Select-Object -First 30 |
                ForEach-Object { Write-Warning "  $($_.FullName)" }
        }
        else {
            Write-Host "Verification passed. No excluded entries found."
        }
    }
    finally {
        $readZip.Dispose()
    }
}