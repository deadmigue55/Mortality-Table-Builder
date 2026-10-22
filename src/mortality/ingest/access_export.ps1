# Export one table of a Microsoft Access database (.mdb / .accdb) to a UTF-8 CSV file.
#
# Used to read the CNSF individual life statistics for 2018 to 2020, which are published as
# Access databases. It goes through the Windows ODBC driver, so it needs no Python package
# (compiled packages can be blocked by Windows Smart App Control). Read-only.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File access_export.ps1 -Path db.mdb -Table EMISION -Out emision.csv
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Table,
    [Parameter(Mandatory = $true)][string]$Out
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Data
$invariant = [System.Globalization.CultureInfo]::InvariantCulture

function Format-Cell($value) {
    if ($null -eq $value -or $value -is [System.DBNull]) { return "" }
    if ($value -is [System.IFormattable]) { $text = $value.ToString($null, $invariant) } else { $text = [string]$value }
    if ($text -match '[",\r\n]') { return '"' + $text.Replace('"', '""') + '"' }
    return $text
}

$connection = New-Object System.Data.Odbc.OdbcConnection(
    "Driver={Microsoft Access Driver (*.mdb, *.accdb)};Dbq=$Path;ReadOnly=1;")
$connection.Open()
try {
    $command = $connection.CreateCommand()
    $command.CommandTimeout = 0
    $command.CommandText = "SELECT * FROM [$Table]"
    $reader = $command.ExecuteReader()
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $writer = New-Object System.IO.StreamWriter($Out, $false, $encoding)
    try {
        $names = for ($i = 0; $i -lt $reader.FieldCount; $i++) { Format-Cell $reader.GetName($i) }
        $writer.WriteLine($names -join ",")
        while ($reader.Read()) {
            $cells = for ($i = 0; $i -lt $reader.FieldCount; $i++) { Format-Cell $reader.GetValue($i) }
            $writer.WriteLine($cells -join ",")
        }
    } finally {
        $writer.Close()
        $reader.Close()
    }
} finally {
    $connection.Close()
}
