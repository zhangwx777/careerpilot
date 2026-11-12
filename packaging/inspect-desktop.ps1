param([int]$DesktopId, [string]$OutputRoot)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$bounds = [Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = [Drawing.Bitmap]::new($bounds.Width, $bounds.Height)
$graphics = [Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($bounds.Location, [Drawing.Point]::Empty, $bounds.Size)
    $bitmap.Save((Join-Path $OutputRoot 'desktop-screen.png'))
} finally { $graphics.Dispose(); $bitmap.Dispose() }
Add-Type -AssemblyName UIAutomationClient
$condition = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ProcessIdProperty, $DesktopId)
$windows = [Windows.Automation.AutomationElement]::RootElement.FindAll([Windows.Automation.TreeScope]::Children, $condition)
$details = foreach ($window in $windows) {
    $window.Current.Name
    $elements = $window.FindAll([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.Condition]::TrueCondition)
    foreach ($element in $elements) { if ($element.Current.Name) { $element.Current.Name } }
}
$details | Out-File (Join-Path $OutputRoot 'desktop-accessibility.log')
