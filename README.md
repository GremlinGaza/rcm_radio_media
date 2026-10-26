# RCM Media

## Start the site

Open PowerShell in this folder and run:

```powershell
.\run.ps1
```

The launcher creates a project-local `.venv` and installs packages listed in
`requirements.txt` on its first run. VS Code is configured to use the same
interpreter; reopen the workspace or select `.venv\Scripts\python.exe` if
Pylance has not refreshed yet.

If PowerShell blocks scripts, run the equivalent commands directly:

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe --requirements requirements.txt
& .\.venv\Scripts\python.exe app.py
```

If Windows blocks the virtual-environment executable, `run.ps1` falls back to
the base Python interpreter recorded in `.venv\pyvenv.cfg`. For the direct
commands above, use that interpreter with the environment's installed packages:

```powershell
$venv = Join-Path $PWD ".venv"
$homeSetting = Get-Content (Join-Path $venv "pyvenv.cfg") |
    Where-Object { $_ -match '^home\s*=\s*(.+)$' } |
    Select-Object -First 1
$pythonHome = $homeSetting -replace '^home\s*=\s*', ''
$env:PYTHONPATH = Join-Path $venv "Lib\site-packages"
& (Join-Path $pythonHome "python.exe") app.py
```

The workspace recommends the VS Code Python, Pylance, Python Debugger, and
Python Environments extensions. They are already installed in the current VS
Code environment.

Open http://127.0.0.1:5000. On the first run, visit
http://127.0.0.1:5000/setup and create the initial editor account. The
single-use setup page closes after this account is created.

## SQLite database and role-based accounts

Sign in at `/journalist/login`. The newsroom stores accounts in
`instance/rcm_radio.sqlite3`. The database contains accounts, news articles,
and the program catalog, with SQLite constraints and indexes. On first startup,
existing `instance/accounts.json` and `instance/news.json` data is imported
automatically; those original files are left untouched. Legacy article program
links are cleared during import because they pointed to the old sample shows.
Passwords remain salted PBKDF2-SHA256 hashes, not plaintext.

Back up the entire `instance` directory securely. It contains the database and
Flask session signing key, and should not be shared publicly or committed.

- **Journalist:** can submit reports for editorial review.
- **Editor:** can approve and publish reports or reject them with a recorded
  reason. Editors can open **Manage Accounts** to create journalist/editor
  accounts, change usernames and roles, reset passwords, or deactivate
  accounts. **Activity History** is editor-only and shows the latest 250
  successful/failed sign-ins, sign-outs, report submissions and review
  decisions, and account changes.

Only editors can manage accounts. Accounts cannot be created from public
registration. At least one active editor must remain. Deactivating or changing
the role of an account immediately removes its access on the next request.

Use unique usernames and strong passwords of at least 12 characters. If the
database is lost, account access must be bootstrapped again; published reports,
drafts, accounts, and programs are stored there.
Rejected reports remain in the editorial desk with their rejection reason;
they are not published or permanently deleted. Activity history does not record
passwords or IP addresses.

## News and video workflow

- Recent videos are fetched from the official RCM Media YouTube channel feed.
  Upload dates are shown, and titles containing a program name are labeled with
  that program.
- The RCM Radio program page lists the weekday schedule (RCM Breakfast,
  Gumzo 254, Vibes Mtaani, RCM Drive, and Around the World) and weekend shows
  (Random Sato and Weekend Wrap Up on Saturday; Taarab Taratibu on Sunday).
  Available posters are shown on the matching program cards; other cards keep
  their icon artwork until matching posters are provided. Follow the Facebook
  page for broadcast updates.
- The Partners & Promotions page features the supplied RCM partner posters and
  the website or phone contact links printed on them.
- Journalists can submit dated reports, add an optional source link, and
  associate reports with shows or programs.
- Submitted reports remain pending until an editor approves them for the News
  page or rejects them with feedback.
