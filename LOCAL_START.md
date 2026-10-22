# Open SupplyOps on this computer

1. Open `C:\Users\shiva\Projects\Supplier-Confirmation-Agent` in File Explorer.
2. Double-click **Start SupplyOps.cmd**.
3. Open http://127.0.0.1:8501 if the browser does not open automatically.

Keep the command window open while using SupplyOps. Closing it stops the local website. To stop deliberately, press **Ctrl+C** in that window. Restart the launcher whenever you want to use the app again, including after restarting Windows.

If the address reports a connection error, check that the command window is still running. If it says port 8501 is already in use, another server is already running: try the address first. To reload changed Python code cleanly, stop the old server with Ctrl+C and launch again.

## Independent Python setup (optional, one time)

The launcher currently uses the existing Python runtime and packages on this computer when there is no project virtual environment. For a setup independent of those Codex files, install Python 3.12, open PowerShell, and run:

```powershell
cd C:\Users\shiva\Projects\Supplier-Confirmation-Agent
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The launcher will then use `.venv` automatically. You can also start manually:

```powershell
cd C:\Users\shiva\Projects\Supplier-Confirmation-Agent
.\.venv\Scripts\python.exe -m streamlit run app.py
```

This optional setup has not been installed by the launcher. No AI key is needed for the available-records review. Starting the app does not change its storage settings: without local persistence enabled, each new browser session starts with illustrative records.
