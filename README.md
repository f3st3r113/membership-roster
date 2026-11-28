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
| `interview.py`, `templates/interview.html` | New Member Interview rules and the PDF form layout |
| `config.default.yaml`, `config.py` | Template and loader for the settings file (see [Settings](#settings-configyaml)) |
| `VERSION` | Current version (shown at the bottom of every page) |
| `docker-compose.ghcr.yml` | Stack that pulls the published image from ghcr.io (easiest; no clone or build) |
| `docker-compose.dockhand.yml` | Image-only stack for an image you built yourself on the NAS |
| `.github/workflows/docker.yml` | GitHub Action that builds and publishes the image |
| `update.sh` | On the NAS: pull the latest code and rebuild the image |

## Installing from the published image (no clone, no build)

Every change to `main` is built by GitHub Actions and published as
`ghcr.io/f3st3r113/membership-roster:latest` (amd64 and arm64). Each version also gets a pinned image such as `:26.11.26.1` (see *Versions and releases*). With that, a stack is all you need, like most self-hosted apps.

1. **One-time, on GitHub:** open the repo's **Actions** tab and confirm *Publish Docker image* ran green.
   Then open your profile's **Packages → membership-roster → Package settings**:
   * To let the NAS pull without logging in, set the package's visibility to **Public** (the image contains
     only the app code, never member data; package visibility is separate from the repo's).
   * Or keep it private and log the NAS in once (needs a personal access token with `read:packages`):
     `echo <TOKEN> | sudo docker login ghcr.io -u f3st3r113 --password-stdin`
2. **Prepare the data folder** (step 3 of the install above).
3. **Dockhand:** create a normal stack and paste `docker-compose.ghcr.yml`. Add `PUID`, `PGID`,
   `CFD_ADMIN_PASSWORD` and `CFD_COOKIE_SECURE`, plus `DATA_DIR` if your data folder isn't
   `/volume1/docker/cfd-roster/data`. Deploy.
4. **Update:** redeploy the stack. It always pulls the newest `:latest` (or change the tag to pin a version).

## Versions and releases

Versions are dated: `YY.MM.DD.N` (for example `26.11.26.1` is the first release of 26 Nov 2026). The current version is in the
`VERSION` file and is shown at the bottom of every page.

To publish a release, change `VERSION`, commit and push:

```sh
echo 26.12.03.1 > VERSION
git add VERSION && git commit -m "Release 26.12.03.1" && git push
```

GitHub Actions then builds the image, publishes it as `ghcr.io/f3st3r113/membership-roster:26.12.03.1` (and `:latest`),
and creates a GitHub Release `v26.12.03.1` with generated notes if that version has no release yet.
In a stack, use the version tag instead of `:latest` to pin a release. (Pushes that don't change `VERSION`
still refresh `:latest` and the current version's image.)

## Installing on a Synology NAS with Dockhand (build it yourself)

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

## New member folder and interview form

The member form has two extra fields, **Response Type** (Normal, Duty Hours) and **Membership Class**
(Interior, Exterior, Junior, EMS, Driver, Fire Police, Associate), and a **Create new member folder** check box next to
*Active*. Tick it and click **Save** or **Save and New**: after saving, the app creates this folder for **next month**
and puts a filled-in New Member Interview form (PDF) in it:

```
<NEW_MEMBER_DIR>/<year>/<MM-Month>/<ID #>_<Last>_<First>/New_Member_Interview_<Last>_<First>_<date>.pdf
e.g. run on 28 Nov 2026:  /nmd/2026/12-December/2103_Johnson_Roberto/New_Member_Interview_Johnson_Roberto_2026-11-28.pdf
```

If there is no ID # the folder starts with an underscore (`_Johnson_Roberto`). If the folder already exists the new form is
simply added to it (a form with the same name, i.e. the same member on the same day, is replaced). The box is unticked each time the page
loads, so a folder is only made when you ask for it. If the Membership Class (or Response Type) isn't filled in yet, the
folder is still created and a notice says the form needs them; fill them in and save again with the box ticked to add the form.

**Setup:** mount the host folder at `/nmd` and set `NEW_MEMBER_DIR` to `/nmd` in the stack (see the commented
lines in `docker-compose.ghcr.yml`). The folder must exist and be writable by `PUID:PGID`. Without `NEW_MEMBER_DIR`,
ticking the box shows a notice instead (unless SharePoint is set up, see below). Dates use the `timezone` setting in `config.yaml`.

### Saving to SharePoint instead of (or as well as) the local folder

`storage` in `config.yaml` chooses where the folders go: `auto` (every place that is set up; the default),
`local`, `sharepoint`, or `both`. SharePoint files land in
`<library>/<sharepoint_folder>/<year>/<MM-Month>/<ID>_<Last>_<First>/`. A form with the same name (same member, same day) is replaced; the date is part of the name, so another day keeps the earlier one.
The link to the PDF in SharePoint is added to the member's **Notes** as a line `New Member Interview form: <link>` (once; saving again doesn't repeat it), and any web links in Notes show as clickable "Open link" lines under the box.
If one place fails (for example SharePoint is unreachable) the other still gets its copy and a notice names the one that failed.

One-time setup, as a Microsoft 365 / Entra administrator:

1. **Register the app.** Entra admin center > App registrations > New registration (any name, e.g. *Roster Folders*,
   single tenant). Copy the **Directory (tenant) ID** and **Application (client) ID**.
2. **Create a secret.** Certificates & secrets > New client secret. Copy the **Value** now (it is shown once) and note the expiry date.
3. **Give it permission.** API permissions > Add > Microsoft Graph > **Application permissions** > `Sites.Selected` >
   Grant admin consent. (`Sites.Selected` means the app can reach *only* the sites you name; it can't see the rest of SharePoint.)
4. **Allow it on the one site.** In [Graph Explorer](https://developer.microsoft.com/graph/graph-explorer), signed in as an admin
   (consent to `Sites.FullControl.All` for Graph Explorer if asked):
   - `GET https://graph.microsoft.com/v1.0/sites/cicerofd.sharepoint.com:/sites/MembershipCommittee` and copy the `id`.
   - `POST https://graph.microsoft.com/v1.0/sites/<that id>/permissions` with body
     `{"roles": ["write"], "grantedToIdentities": [{"application": {"id": "<client id>", "displayName": "Roster Folders"}}]}`
5. **Add three settings to the stack** (Dockhand environment): `SP_TENANT_ID`, `SP_CLIENT_ID`, `SP_CLIENT_SECRET`, and pass them to the
   container (see the commented `SP_...` lines in the compose files).
6. **Check `config.yaml`:** `sharepoint_site_url`, `sharepoint_library` (the library's real name, usually `Documents`, which is
   the one shown as *Shared Documents* in web addresses) and `sharepoint_folder`. Use something like `General/TEST` while trying things out, then switch to the real folder.

The container needs outbound HTTPS to `login.microsoftonline.com` and `graph.microsoft.com`. Remember to replace the client
secret before it expires, or SharePoint saves will start failing with a "sign-in failed" notice.

What the form fills in:

| Form field | Filled from |
|---|---|
| Date | Today (MM/DD/YY) |
| Name, Email | First Last, E-mail |
| Address | Street, City, State Zip |
| Response Location | Fire Station, as `Station <number>` |
| Response Type, Class | Response Type, Membership Class |
| Drills / Meetings / Call % | From the class and response type (table below) |
| Present to Membership | First Thursday of next month |
| Present to Commissioners | Second Tuesday of next month |
| Physical | Last Wednesday of next month |
| Check boxes along the bottom | The `interviewers` list in `config.yaml`, plus one blank box |

| Class | Drills | Meetings | Normal | Duty Hours |
|---|---|---|---|---|
| Interior, Exterior, Junior | 16 | 6 | Call % 10% | Hours 288 |
| EMS, Driver, Fire Police | 8 | 6 | Call % 10% | Hours 288 |
| Associate | NA | 6 | Hours per Quarter 60 (either response type) | |

Membership Class is required for the button, and Response Type is required for every class except Associate.
The rules are in `interview.py`; the layout is `templates/interview.html`.

## Users

Administrators manage logins in the app: **Users** (top right) to add people, change roles, reset
passwords or delete them. Everyone can change their own password by clicking their name at the top.

| Role | Can do |
|---|---|
| Administrator | Everything an editor can, plus delete members, manage users and export Mobile Info |
| Editor | Add and edit members |
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

## Settings (config.yaml)

Branding and membership groups are set in `config.yaml`, which lives in the data folder next to `cfd.db`
(for example `/volume1/docker/cfd-roster/data/config.yaml`). It is created automatically on first start from
`config.default.yaml`, and edits apply within moments, no restart needed.

| Setting | What it does |
|---|---|
| `department_name` | Page banner, browser tab titles |
| `formal_name` | Printed/PDF roster and contact cards (.vcf). Optional, defaults to `department_name` |
| `logo_file` | Logo image (png, jpg, gif, svg, webp; max 2 MB). A plain file name is looked up in the data folder; if missing, the built-in logo is used |
| `theme_color` | Hex color for the banner, buttons and links (for example `"#1d9a45"`). Dark mode adjusts it automatically. White text is drawn on it, so pick a medium or dark color |
| `roster_banner_color` | Hex color of the banner strip on the printed roster |
| `timezone` | Time zone for "today" (for example `America/New_York`) |
| `response_types`, `membership_classes` | Choices on the member form |
| `interviewers` | Names with check boxes at the bottom of the interview form |
| `groups` | Membership groups in the order shown. The number prefix sorts them and is hidden on the printed roster; the first is the default for new members |

A bad value is ignored (the default is used) and a warning is written to the container log
(`sudo docker logs cfd-roster`). Members whose group is not in the list still appear everywhere; the list only
controls what is offered for new entries and which names the Access import recognises.
To change the logo, copy the image into the data folder and set `logo_file` to its name.

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
