Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "C:\Users\steve\OneDrive\Documents\Investing"
shell.Run """C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\pythonw.exe"" ""C:\Users\steve\OneDrive\Documents\Investing\run.py""", 0, False
