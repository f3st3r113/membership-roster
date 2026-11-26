# Cicero VFD Membership Roster

Web replacement for the Access membership database. Flask + SQLite, packaged as one Docker container.
All data lives in a single `data/` folder, and member data is never part of this repository.

## Features

| Access | Web app |
|---|---|
| Contacts table | `members` table (import your Access export with `import-csv`; original IDs are kept) |
| Contact details form | **Members** list (search, filters, 10/25/50/100 members per page (your choice is remembered), columns fit their content) and the **Add/Update Member** form, with *Go to*, *Save and New*, *E-mail*, *Save as Contact (.vcf)* |
| Membership Roster report | **Save As PDF/Print**: active members grouped by membership status (each group on its own page), sorted by last/first name, banner on page 1, confidentiality footer and page numbers. Several job titles print on separate lines |
| Welcome form buttons | Buttons across the top of every page |
| Mobile Info export (MobileInfo.xlsx + PowerShell, mi.json) | **Export Mobile Info** (administrators only), see [Mobile Info](#mobile-info-mijson) |
| Logins | Administrator / Editor / Viewer roles, see [Users](#users) |
| Dark mode | Moon/sun switch top right; remembered per browser |
| "Believe 31" and other exports | Not built yet |

## Repository layout

| Path | What it is |
|---|---|
| `app.py` | The whole application (routes, database, CLI commands) |
| `templates/`, `static/` | Pages, stylesheets, scripts, logo |
| `Dockerfile`, `requirements.txt` | How the image is built |
| `docker-compose.yml` | For `docker compose up --build` from this folder |
| `docker-compose.dockhand.yml` | Image-only stack to paste into Dockhand |
| `update.sh` | On the NAS: pull the latest code and rebuild the image |

## Installing on a Synology NAS with Dockhand (full steps)

A stack pasted into Dockhand has no project folder, so it cannot build the image (you would get
`failed to read dockerfile`). So the image is built once on the NAS, and Dockhand only runs it.

### 1. Let the NAS read the (private) GitHub repo

Use a read-only **deploy key** that belongs to this one repository. Over SSH on the NAS:

```sh
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "nas-membership-roster" -f ~/.ssh/cfd_deploy -N ""
cat ~/.ssh/cfd_deploy.pub          # copy this line
```

On GitHub: the repo's **Settings → Deploy keys → Add deploy key**, paste the line, title it `NAS`, leave
**Allow write access** unchecked. (If the repo is public you can skip this and clone over `https://`.)

### 2. Get the code and build the image

Keep the code in its own folder, separate from the data folder:

```sh
GIT_SSH_COMMAND="ssh -i ~/.ssh/cfd_deploy -o IdentitiesOnly=yes" \
  git clone git@github.com:f3st3r113/membership-roster.git /volume1/docker/cfd-roster-src
cd /volume1/docker/cfd-roster-src
sudo docker build -t cfd-roster:latest .
```

If `git` is not installed on the NAS, download the ZIP from GitHub, copy it over with File Station, and
unzip it into `/volume1/docker/cfd-roster-src`. Check the image exists with `sudo docker images cfd-roster`.

### 3. Prepare the data folder

```sh
mkdir -p /volume1/docker/cfd-roster/data
id <your-nas-user>                  # note the numeric uid and gid, e.g. 1026 and 100
sudo chown -R <uid>:<gid> /volume1/docker/cfd-roster/data
```

The container runs as that uid/gid (`PUID`/`PGID`), so the folder must be writable by it. If you see
`attempt to write a readonly database`, this is the cause.

To start with your existing members, either copy an existing `cfd.db` into this folder, or leave it empty and
import the Access export after the first start (see [Importing from Access](#importing-from-access)).

### 4. Create the stack in Dockhand

**Stacks → Create** (a normal stack, not a Git one), name it `cfd-roster`, and paste the contents of
`docker-compose.dockhand.yml`. It must not contain a `build:` line. Add these **Environment variables**:

| Variable | Meaning |
|---|---|
| `PUID` / `PGID` | The numeric uid/gid from step 3 |
| `CFD_ADMIN_PASSWORD` | Password for the first `admin` login (only read when no users exist yet; remove it afterwards if you like) |
| `CFD_COOKIE_SECURE` | `0` over plain HTTP, `1` once served over HTTPS |

Deploy, then open `http://<nas-address>:8080` and sign in as `admin`. Change `8080` in the compose file's
`ports:` line if that port is taken.

### 5. Updating later

On the NAS, in the code folder:

```sh
cd /volume1/docker/cfd-roster-src
sh update.sh            # git pull, then rebuild the image
```

Then redeploy the stack in Dockhand (stop and start it if it keeps the old container). Your data is
not touched. Refresh the browser once so it picks up new stylesheets.

### Other ways to run it

* **Docker Compose directly:** `export CFD_ADMIN_PASSWORD='...'; docker compose up -d --build` in this folder,
  then open `http://<host>:8080`. Data goes in `./data`.
* **Synology Container Manager project:** copy this folder to the NAS, create a project pointing at it, use
  `docker-compose.yml`, and set `CFD_ADMIN_PASSWORD`, `PUID` and `PGID`.

## Users

Administrators manage logins in the app: **Users** (top right) to add people, change roles, reset
passwords or delete them. Everyone can change their own password by clicking their name at the top.

| Role | Can do |
|---|---|
| Administrator | Everything an editor can, plus manage users and export Mobile Info |
| Editor | Add, edit and delete members |
| Viewer | Search and view members, save/print the roster |

Passwords need at least 10 characters and are stored only as salted hashes (never in plain text).
Resetting a password signs that person out everywhere. There is always at least one administrator,
and you can't delete your own account. Existing databases are upgraded automatically: the first user
ever created becomes the administrator.

## Command line

Useful if you ever get locked out. On the NAS, run commands inside the container:

```sh
sudo docker exec -it cfd-roster flask --app app create-user alice            # can edit
sudo docker exec -it cfd-roster flask --app app create-user carol --admin    # administrator
sudo docker exec -it cfd-roster flask --app app create-user bob --viewer     # view-only
sudo docker exec -it cfd-roster flask --app app set-password admin
sudo docker exec -it cfd-roster flask --app app list-users
sudo docker exec -it cfd-roster flask --app app delete-user bob
```

(With `docker compose`, use `docker compose exec roster flask --app app ...` instead.)

## Mobile Info (mi.json)

`mi.json` is built straight from the database: every active member, sorted by name, with the fields
`name`, `id`, `phone`, `email`, `title`. No Excel, no renaming headers, no script. Only administrators see the
**Export Mobile Info** button.

* **Choose the folder each time:** click **Export Mobile Info**. In Chrome or Edge a Save dialog opens, so
  browse to the folder you want (a mapped drive or network share works) and confirm replacing `mi.json`.
  The browser only offers this dialog on `https://` pages or `localhost`. Over plain `http://<nas>:8080` the
  button falls back to a normal download (turn on "Ask where to save each file" in the browser to pick the folder).
  Serving the app over HTTPS (below) gets you the dialog.
* **Command line:** `sudo docker exec cfd-roster flask --app app export-mi /data/mi.json`

## Importing from Access

Export the Contacts table to CSV (for example with `mdb-export`) with these column headers:
`Unique_ID, Last Name, First Name, Emergency Contact, ID #, Address, City, State, ZIP/Postal Code,
Fire Station, Job Title, Home Phone, Mobile Phone, E-mail Address, Membership Status, Notes, Active`.
Put the file in the data folder (for example `/volume1/docker/cfd-roster/data/contacts.csv`), then:

```sh
sudo docker exec cfd-roster flask --app app import-csv /data/contacts.csv          # into an empty database
sudo docker exec cfd-roster flask --app app import-csv /data/contacts.csv --replace   # replace existing members
```

Cleanups applied during import:

* Phone numbers stored as 10 raw digits are formatted `(315) 555-0100` (new entries are formatted the same way).
* State "New York" becomes `NY`.
* Status values are matched to the standard names (for example "09-Line Of Duty Family" becomes "09-Line of Duty Family").

## HTTPS

Passwords and member data cross the network, so don't expose this to the internet over plain HTTP.
Keep it on the LAN, or put it behind a reverse proxy with a certificate (Synology: *Login Portal →
Advanced → Reverse Proxy*) and set `CFD_COOKIE_SECURE=1`.

## Backups

Everything is in `data/cfd.db` (plus `data/.secret_key`, which only keeps people signed in). The database
holds member data as readable text, so keep the folder's permissions tight and store backups somewhere safe.
Stop the container, or use `sqlite3 data/cfd.db ".backup backup.db"`, for a consistent copy.

## Privacy of the member list

The Members page only sends one page of members (10, 25, 50 or 100, chosen with the *Show ... per page* box at the bottom of the list; 25 by default) to the browser, and the *Go to* box on the member
form looks names up on demand (2+ characters, at most 10 results) instead of listing everyone. Nobody gets the
whole roster in a single page or request. Change the default with `CFD_PAGE_SIZE` (one of 10, 25, 50, 100). Anyone signed in can
still page or search through the members their role allows, so access is controlled by who has a login.

## Layout tweaks

* The roster is plain HTML/CSS in `templates/roster.html` and `static/roster.css` (column widths, fonts,
  colors, the page footer). The PDF is generated from it by WeasyPrint.
* The app's look (light and dark themes) is in `static/app.css`; the switch is `static/theme.js`.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `failed to read dockerfile ... no such file or directory` when deploying | The stack text still contains `build:`. Use the image-only `docker-compose.dockhand.yml`, and build the image on the NAS first (step 2). |
| `attempt to write a readonly database` | The data folder isn't writable by `PUID`/`PGID`. Run `chown -R <uid>:<gid>` on it and set the same values in the stack. |
| Image not found on deploy | `sudo docker images cfd-roster` shows nothing: re-run the build (step 2). |
| Can't sign in as `admin` | `CFD_ADMIN_PASSWORD` is only used when there are no users. Reset with `set-password admin` (see Command line). |
| `E: Unable to locate package` during the build | The base image's package names changed; the Dockerfile uses `fonts-crosextra-carlito` for the Calibri-compatible font. |
| Old look after an update | Refresh the browser once (Ctrl+F5). |
