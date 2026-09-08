# FIT Editor

A small local web app to view and edit Garmin FIT activity files. No third-party
Python packages are required (Python 3.9+, standard library only); the map uses
Leaflet with OpenStreetMap/Esri tiles from a CDN, so an internet connection is
needed for the map background.

## Run

```powershell
.\run.cmd
```

on Linux/macOS:

```bash
./run.sh
```

or, on any platform:

```powershell
py -3 -m fitedit --dir . --port 8731
```

The browser opens at <http://127.0.0.1:8731/>. The server only listens on
localhost and only reads/writes `.fit` files inside the directory passed via
`--dir`.

## Optional: downloading from Garmin Connect

The *Garmin…* button is an optional extra. Without it installed, everything else
works unchanged; the button then just explains how to enable it:

```powershell
py -3 -m pip install -r requirements-garmin.txt
```

This pulls in the community `garminconnect` library (Garmin has no public
consumer API). Sign in from the dialog, pick a period (last 7 days by default),
select activities and download them as FIT files into the working directory.

- The password is posted to the local server only, is never written to disk and
  is never logged; only the OAuth session tokens produced by Garmin are cached,
  by the library, in `~/.garminconnect`.
- Multi-factor codes are prompted for in the dialog.
- Behind a TLS-inspecting proxy (Zscaler and similar), the Windows certificate
  store is merged with `certifi` into a temporary CA bundle automatically, so
  the sign-in works without disabling certificate verification. Set
  `SSL_CERT_FILE` yourself to override this.
- Start the app with `--no-garmin` to switch the integration off completely.

## Configuration

Settings live in `~/.fitedit/config.json` (on Windows
`C:\Users\<you>\.fitedit\config.json`), created on demand:

```json
{
 "garmin": { "email": "you@example.com", "remember": true, "password": "dpapi:..." },
 "names": { "22872829433_ACTIVITY.fit": "El Boiler" },
 "ui": {}
}
```

- The Garmin password is only written when *remember on this computer* is
  ticked in the sign-in dialog.
- On Windows it is encrypted with DPAPI, so only your Windows user account can
  read it; on other platforms it is base64 only and the dialog says so.
- The file is created with owner-only permissions and is never served to the
  browser in clear text — the UI only learns whether a password is stored.
- Delete the file, or untick the box and sign in again, to remove it.
- The `ui` section is reserved for future settings.

## What it does

- **Map** – the GPS track is drawn on a street, satellite or topographic
  background (selector in the toolbar). The selected (kept) part is blue,
  trimmed parts are grey, with green/red markers for the new start and end.
  Dive files have no track, so the session start/end fix is shown instead.
- **Diving** – depth, ppO₂, CNS/N₂ load, NDL, ascent rate, air time remaining,
  SAC/RMV and the air-integration tank pressure (from `tank_update`) are
  plottable, and the *Activity* panel adds max/avg depth, bottom time, dive
  number, surface interval, tank start/end pressure and gas mix.
- **File list** – entries are shown as
  `2026-05-14 00:59 - Single-Gas - El Boiler - 22872829433_ACTIVITY.fit`, i.e.
  activity start time, type (sport profile name, or the sport), activity name
  (when known) and file name.
- **Units** – switch between metric (km/h, km) and nautical (kn, nm); plots,
  tooltips and the summary follow. The choice is remembered.
- **Hover** – moving the mouse over a plot or over the map shows a tooltip with
  every available data field at that sample, the wall-clock timestamp and the
  elapsed time counter. The same values stay visible in the *At cursor* panel.
- **Cursor slider** – scrub through the activity (or press play) to move the
  cursor along the track and the plots.
- **Plots** – any numeric record field (speed, altitude, heart rate, power,
  temperature, unknown and developer fields …) can be plotted against time.
  Wheel = zoom, drag = pan, double click = reset, and the x-axis can be switched
  between elapsed time and clock time.
- **Field visibility** – the *fields* button in the *At cursor* and *Activity*
  panels selects which rows are shown; the choice is remembered.
- **Layout** – the map and every left-hand panel can be collapsed with the
  chevron in its title and resized by dragging its bottom-right grip; heights
  and collapsed states are remembered.
- **Markers** – place markers by clicking on the map (*place on map*) or at the
  current cursor position, drag them around, rename them, pick a symbol
  (red/green/yellow/orange/blue buoy, flag, pin, anchor) or type exact
  latitude/longitude values. Markers are stored automatically in
  `<activity>.markers.json` next to the FIT file, and *load…* / *save to…*
  read and write arbitrary marker JSON files.
- **Activity name** – FIT files contain no activity name; the name you see in
  Garmin Connect ("El Boiler") is server-side metadata. It is captured when you
  download an activity, stored in `~/.fitedit/config.json`, shown in the file
  list and freely editable in the *Activity* panel. The sport profile name that
  *is* in the file ("Single-Gas") is shown separately as *Type* and left
  untouched.
- **Cropping** – drag the green/red bars in any plot, or use *Set at cursor*, to
  choose the range to keep. *Save cropped…* writes a new FIT file.

## Marker file format

```json
{ "markers": [ { "name": "Windward mark", "symbol": "buoy-yellow", "lat": 52.4, "lon": 13.166 } ] }
```

A bare JSON array of the same objects is accepted when loading.

## How cropping works

The original file is rewritten byte for byte, except that:

- record messages (and other sampled message types) outside the selected window
  are removed,
- `session`, `lap` and `activity` summaries are patched in place with recomputed
  start/end times, elapsed and timer time, distance, ascent/descent and
  average/maximum values,
- laps fully outside the window are dropped and the remaining ones renumbered,
- header size, header CRC and file CRC are recomputed.

Unknown message types and developer fields are preserved unchanged. The source
file is never modified; the result is always written to a new file.

## Layout

| Path | Purpose |
| --- | --- |
| `fitedit/fitfile.py` | FIT binary reader (header, definition/data messages, CRC) |
| `fitedit/profile.py` | Subset of the FIT global profile (message and field names, scales) |
| `fitedit/activity.py` | Converts a parsed file into JSON for the UI |
| `fitedit/crop.py` | Time-window crop and summary recalculation |
| `fitedit/config.py` | Local config file, DPAPI-protected secrets, activity names |
| `fitedit/sportname.py` | Reads the sport profile name stored in a file |
| `fitedit/garmin.py` | Optional Garmin Connect download support |
| `fitedit/server.py` | Local HTTP server and JSON API |
| `web/` | UI: `index.html`, `app.js`, `chart.js`, `garmin.js`, `style.css` |

## License

This project is licensed under the [GNU Lesser General Public License v3.0](LICENSE) or any later version.
