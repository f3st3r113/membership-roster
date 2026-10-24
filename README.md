# Cicero VFD Membership Roster

Web replacement for the Access membership database: member list with search, add/edit form,
the **Membership Roster** (PDF / print), vCard export, and logins.
Flask + SQLite, packaged as one Docker container. All data lives in the `data/` folder.

## What's included

| Access | Web app |
|---|---|
| Contacts table | `members` table (import your Access export with `import-csv`; original IDs are kept) |
| Contact details form | **Members** list + edit form, with *Go to*, *Save and New*, *E-mail*, *Save as Contact (.vcf)* |
| Membership Roster report | **Save As PDF/Print** (opens the PDF in a new tab; save or print it from the viewer) (active members, grouped by membership status with each group on its own page, sorted by last/first name; banner on page 1, confidentiality footer and page numbers) |
| Welcome form buttons | Buttons across the top of every page |
| Mobile Info export (MobileInfo.xlsx + PowerShell → mi.json) | **Export Mobile Info** button (administrators only; you choose where to save, see *Mobile Info*) |
| "Believe 31" and other exports | Not built yet (to do later) |

## Run it

```sh
cd cfd-roster
export CFD_ADMIN_PASSWORD='choose-a-strong-password'   # first start only: creates user "admin"
docker compose up -d --build
```

Open `http://<host>:8080`, sign in as `admin`.

**Synology (Container Manager):** copy this folder to the NAS (e.g. `/volume1/docker/cfd-roster`),
then *Container Manager → Project → Create*, point it at that folder and use the existing
`docker-compose.yml`. Add environment values `CFD_ADMIN_PASSWORD`, `PUID` and `PGID`
(PUID/PGID = the numeric user/group that owns the `data` folder; run `id <your-user>` over SSH
to see them). The `data` folder must be writable by that user.

## Dockhand (or any UI where you paste the compose text)

A stack pasted into Dockhand has no project folder, so `build: .` fails with
"failed to read dockerfile". Build the image once on the NAS, then deploy it from the pasted file.

1. Copy this whole folder to the NAS, e.g. `/volume1/docker/cfd-roster` (it must contain
   `Dockerfile`, `app.py`, `templates/` and `static/`). Create an empty `data/` folder next to them; the database is created on first start (member data is never part of this repository).
2. Over SSH, build the image (needs internet to pull the Python base image):
   ```sh
   cd /volume1/docker/cfd-roster
   sudo docker build -t cfd-roster:latest .
   ```
3. In Dockhand: pick the environment (the NAS), then **Stacks → Create**, name it `cfd-roster`,
   and paste the contents of `docker-compose.dockhand.yml`.
4. Add **Environment variables** to the stack: `CFD_ADMIN_PASSWORD`, `PUID`, `PGID`.
5. **Deploy**, then open `http://<nas-address>:8080` and sign in as `admin`.
6. Make sure `/volume1/docker/cfd-roster/data` is writable by the PUID/PGID user.

To update after changing code: rebuild with the same `docker build` command, then redeploy the stack.

## Mobile Info (mi.json)

`mi.json` is built straight from the database: every active member, sorted by name, with the fields
`name`, `id`, `phone`, `email`, `title` (same format the PowerShell script produced). No Excel, no renaming
headers, no script. Only administrators see the **Export Mobile Info** button.

* **Choose the folder each time:** click **Export Mobile Info**. In Chrome or Edge a Save dialog opens, so
  browse to the Reports folder (a mapped drive or `\\NASStation\...` path works) and confirm replacing `mi.json`.
  The browser only offers this dialog on `https://` pages or `localhost`. Over plain `http://<nas>:8080` the button
  falls back to a normal download (turn on "Ask where to save each file" in the browser to pick the folder).
  Serving the app over HTTPS (see below) gets you the dialog.
* **Command line:** `docker exec cfd-roster flask --app app export-mi /path/mi.json`

## Users

Administrators manage logins in the app: **Users** (top right) to add people, change roles, reset
passwords or delete them. Everyone can change their own password by clicking their name at the top.

| Role | Can do |
|---|---|
| Administrator | Everything an editor can, plus manage users |
| Editor | Add, edit and delete members |
| Viewer | Search and view members, print/save the roster |

Passwords need at least 10 characters. Resetting a password signs that person out everywhere.
There is always at least one administrator, and you can't delete your own account.
Existing databases are upgraded automatically: the first user ever created becomes the administrator.

The command line also works (useful if you ever get locked out):

```sh
docker compose exec roster flask --app app create-user alice            # can edit
docker compose exec roster flask --app app create-user carol --admin    # administrator
docker compose exec roster flask --app app create-user bob --viewer     # view-only
docker compose exec roster flask --app app set-password admin
docker compose exec roster flask --app app list-users
docker compose exec roster flask --app app delete-user bob
```

## HTTPS

Passwords and member data cross the network, so don't expose this to the internet over plain HTTP.
Keep it on the LAN, or put it behind a reverse proxy with a certificate (Synology: *Login Portal →
Advanced → Reverse Proxy*) and set `CFD_COOKIE_SECURE=1`.

## Backups

Everything is in `data/cfd.db` (plus `data/.secret_key`, which only keeps people signed in).
Stop the container or use `sqlite3 data/cfd.db ".backup backup.db"` for a consistent copy.

## Re-importing from Access

Export the Contacts table to CSV (the file here was made with `mdb-export`) and run:

```sh
docker compose exec roster flask --app app import-csv /data/contacts.csv --replace
```

## Cleanups applied during import

* Phone numbers stored as 10 raw digits are formatted `(315) 555-0100` (new entries are formatted the same way).
* State "New York" → `NY`.
* Status "09-Line Of Duty Family" merged into "09-Line of Duty Family".
* The empty `Company` column was dropped.

## Layout tweaks

The roster is plain HTML/CSS in `templates/roster.html` and `static/roster.css`
(column widths, fonts, colors, the page footer). It uses the same file for screen, print and PDF.
