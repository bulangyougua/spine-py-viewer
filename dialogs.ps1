param(
    [Parameter(Mandatory = $true)][ValidateSet('pick', 'error')][string]$Mode,
    [string]$Initial = '',
    [string]$Message = '',
    [string]$Title = 'Spine 动画查看器'
)

# Replaces tkinter: builds always ship without Tcl/Tk on some Python builds,
# and Windows can show native dialogs through WinForms instead.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

if ($Mode -eq 'error') {
    [System.Windows.Forms.MessageBox]::Show($Message, $Title, 'OK', 'Error') | Out-Null
    exit 0
}

# invisible top-most owner so the dialog cannot open behind the browser window
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.StartPosition = 'CenterScreen'
$owner.Size = New-Object System.Drawing.Size(1, 1)
$owner.Show()

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择包含 Spine 动画的文件夹'
$dialog.ShowNewFolderButton = $false
$dialog.UseDescriptionForTitle = $true
if ($Initial -and (Test-Path -LiteralPath $Initial)) {
    $dialog.SelectedPath = $Initial
}

$result = $dialog.ShowDialog($owner)
$owner.Close()

if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.WriteLine($dialog.SelectedPath)
}
