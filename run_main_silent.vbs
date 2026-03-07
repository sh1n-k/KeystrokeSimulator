Set shell = CreateObject("WScript.Shell")
Set args = WScript.Arguments

scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "cmd.exe /c """ & scriptDir & "\run_main.cmd"""

If args.Count > 0 Then
    For i = 0 To args.Count - 1
        command = command & " """ & Replace(args.Item(i), """", """""") & """"
    Next
End If

shell.CurrentDirectory = scriptDir
shell.Run command, 0, False
