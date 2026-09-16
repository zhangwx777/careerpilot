Option Explicit

Dim shell, fso, root, command, powershell
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
powershell = shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"
command = """" & powershell & """ -NoProfile -ExecutionPolicy Bypass -File """ & root & "\start.ps1"""
shell.Run command, 1, False
