param(
    [string]$InputFile = (Join-Path $PSScriptRoot 'lan-sample.yaml'),
    [string]$OutputFile = '',
    [switch]$Watch
)
$ErrorActionPreference = 'Stop'
$bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (Test-Path -LiteralPath $bundledPython) {
    $pythonExe = $bundledPython
} else {
    $pythonExe = (Get-Command python -ErrorAction Stop).Source
}
$previousPythonPath = $env:PYTHONPATH
try {
    $localDeps = Join-Path $PSScriptRoot '.deps'
    if (Test-Path -LiteralPath $localDeps) {
        $env:PYTHONPATH = $localDeps + [IO.Path]::PathSeparator + $previousPythonPath
    }
    $arguments = @((Join-Path $PSScriptRoot 'generate_diagram.py'), $InputFile)
    if ($OutputFile) { $arguments += @('-o', $OutputFile) }
    if ($Watch) { $arguments += '--watch' }
    & $pythonExe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Diagram generation failed (exit $LASTEXITCODE)" }
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
