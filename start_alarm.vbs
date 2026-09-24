Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
shell.Run "pythonw.exe " & Chr(34) & folder & "\alarm_reminder.py" & Chr(34), 1, False
