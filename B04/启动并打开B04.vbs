' GreenMate B04 launcher: start server if not running, wait until ready, then open browser.
' Use this when double-clicking .bat files does nothing (broken .bat file association).
Option Explicit
Dim shell, root, i, ok, cmd
Set shell = CreateObject("WScript.Shell")
root = "E:\GreenMate\greenmate-final"
shell.CurrentDirectory = root

Function ServerUp()
  Dim h
  Set h = CreateObject("MSXML2.XMLHTTP")
  On Error Resume Next
  h.Open "GET", "http://127.0.0.1:8000/", False
  h.setTimeouts 2000, 2000, 2000, 2000
  h.Send
  ServerUp = (Err.Number = 0 And h.Status = 200)
  On Error GoTo 0
End Function

If Not ServerUp() Then
  cmd = "cmd /k ""cd /d " & root & " && .venv\Scripts\python.exe B06\run.py > greenmate_start.log 2>&1"""
  shell.Run cmd, 1, False
  ok = False
  For i = 1 To 25
    WScript.Sleep 2000
    If ServerUp() Then
      ok = True
      Exit For
    End If
  Next
  If Not ok Then
    MsgBox "Server not ready after 50 seconds. Please open greenmate_start.log in " & root & " and send its content to Claude.", 48, "GreenMate Start Failed"
    WScript.Quit 1
  End If
End If

shell.Run "http://127.0.0.1:8000/B04/"
