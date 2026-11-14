# Generate cover-letter .docx files from a JSON spec by cloning the user's Word template.
# Usage (run inside Start-Job with a timeout - Word COM can hang on dialogs):
#   & gen_cover_letters.ps1 -Letters <letters.json> -OutBase <folder> [-Date 'October 3, 2026']
# Then export each .docx to PDF with docx_to_pdf.ps1 in a FRESH Word instance
# (exporting in the same session that edited the doc hangs).
# letters.json: [{id, folder, file, recipient ("line1\u000bline2"), re, salutation, p1, p2, p3, p4,
#                 bold: [names to set in bold on first mention], links: [{text, url}], replace: [{find, with}]}]
param(
  [Parameter(Mandatory)][string]$Letters,
  [Parameter(Mandatory)][string]$OutBase,
  [string]$Date = (Get-Date).ToString('MMMM d, yyyy', [Globalization.CultureInfo]::InvariantCulture),
  [Parameter(Mandatory)][string]$Template
)
$ErrorActionPreference = 'Stop'
$log = Join-Path $OutBase 'gen.log'
New-Item -ItemType Directory -Force $OutBase | Out-Null
function Log($m) { Add-Content -Path $log -Value $m }
$spec = Get-Content -Raw -Encoding UTF8 $Letters | ConvertFrom-Json

# Template paragraph map: 1 name, 2 title, 3 contact, 4 date, 6 recipient, 8 Re:, 10 salutation,
# 12/14/16/18 body paragraphs, 20 "Sincerely,", 21 name.
function Set-Para($doc, $n, $text) {
  $r = $doc.Paragraphs.Item($n).Range
  $r.MoveEnd(1, -1) | Out-Null
  $r.Text = $text
  return $r
}

$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try {
  foreach ($L in $spec) {
    $dir = Join-Path $OutBase $L.folder
    New-Item -ItemType Directory -Force $dir | Out-Null
    $docx = Join-Path $dir ($L.file + '.docx')
    if (Test-Path $docx) { throw "exists: $docx" }
    Copy-Item $Template $docx
    Log "$($L.id) open"
    $d = $w.Documents.Open($docx)
    # Replacing text inherits the wrong run formatting on the date line - reset it.
    $r = Set-Para $d 4 $Date; $r.Font.Size = 10.5; $r.Font.Bold = 0
    Set-Para $d 6 $L.recipient | Out-Null
    Set-Para $d 8 $L.re | Out-Null
    Set-Para $d 10 $L.salutation | Out-Null
    foreach ($pair in @(@(12, $L.p1), @(14, $L.p2), @(16, $L.p3), @(18, $L.p4))) {
      $r = Set-Para $d $pair[0] $pair[1]; $r.Font.Bold = 0
    }
    # Names the applicant wants in bold on first mention in each body paragraph (a convention of their template).
    foreach ($n in 12, 14, 16) {
      foreach ($name in @($L.bold)) {
        if (-not $name) { continue }
        $r = $d.Paragraphs.Item($n).Range
        $f = $r.Find; $f.ClearFormatting()
        if ($f.Execute($name, $true, $true)) { $r.Font.Bold = -1 }
      }
    }
    # Links that were in the template's closing paragraph are lost when its text is replaced: put them back.
    foreach ($lk in @($L.links)) {
      if (-not $lk -or -not $lk.text) { continue }
      $r = $d.Paragraphs.Item(18).Range
      if ($r.Find.Execute($lk.text)) { $d.Hyperlinks.Add($r, $lk.url) | Out-Null }
    }
    # Fixed text of the template that should read differently (a typo in the header, an old address).
    foreach ($rp in @($L.replace)) {
      if (-not $rp -or -not $rp.find) { continue }
      $r = $d.Content
      $r.Find.Execute($rp.find, $true, $false, $false, $false, $false, $true, 0, $false, $rp.with, 2) | Out-Null
    }
    $d.Save()
    $d.Close($false)
    Log "$($L.id) saved $docx"
  }
} finally { $w.Quit() }
