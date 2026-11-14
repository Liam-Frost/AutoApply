# Export one .docx to .pdf (same folder, same basename) in a fresh Word instance.
# Run each call inside Start-Job + Wait-Job -Timeout 60; kill orphan WINWORD (no window title) on timeout.
# Prints the page count - cover letters must be 1 page; shorten text if it reports 2.
param([Parameter(Mandatory)][string]$docx)
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.DisplayAlerts = 0
try {
  $d = $w.Documents.Open($docx, $false, $true)
  $pg = $d.ComputeStatistics(2)
  $d.SaveAs2([IO.Path]::ChangeExtension($docx, '.pdf'), 17)
  $d.Close($false)
  "$pg page(s): $docx"
} finally { $w.Quit() }
