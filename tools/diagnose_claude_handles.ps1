$ErrorActionPreference = 'Stop'
$tool = Join-Path $env:TEMP 'codex-claude-handle\handle64.exe'
$output = Join-Path $env:TEMP 'codex-claude-handles-admin.txt'
if (-not (Test-Path -LiteralPath $tool)) { throw 'Microsoft Handle is missing from the temporary directory.' }
$signature = Get-AuthenticodeSignature -LiteralPath $tool
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
    throw 'Microsoft Handle signature could not be verified.'
}
$results = & $tool -accepteula -nobanner 'Claude_2.2553.13.0' 2>&1 | Out-String
@(
    "Checked at: $(Get-Date -Format o)"
    "User: $(whoami)"
    "Tool: $tool"
    $results
) | Set-Content -LiteralPath $output -Encoding UTF8
Write-Output "Saved: $output"
