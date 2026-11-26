# somepanic Kodi repository

One Kodi repository for SiloMod (SM4K), JellyMod (JM4K), Plex Uno, PlexMod for Kodi (PM4K) and CoreTube, at
https://somepanic.github.io/.

## Install in Kodi

1. Open **Settings → System → Add-ons** and turn on **Unknown sources**.
2. Open **Settings → File manager → Add source**, enter `https://somepanic.github.io/` and name it **somepanic**.
3. Open **Add-ons → Install from zip file → somepanic** and choose the repository zip.
4. Open **Add-ons → Install from repository → somepanic** and pick an add-on.

Kodi reads the list for its own version:

| Kodi | List | For |
| --- | --- | --- |
| 21 (Omega) | `omega/` | CoreELEC 21, 32-bit ARM |
| 22 (Piers), and its 21.90+ test builds | `piers/` | CoreELEC 22, 64-bit AArch64 |

SiloMod, JellyMod, Plex Uno and PlexMod are the same in both lists. CoreTube has one build for each.

## Where the add-ons come from

| Add-on | ID | Taken from |
| --- | --- | --- |
| SiloMod | `script.silomod` | the latest release of [somepanic/SM4K](https://github.com/somepanic/SM4K) |
| JellyMod | `script.jellymod` | the latest release of [somepanic/JM4K](https://github.com/somepanic/JM4K) |
| CoreTube | `browser.tizentube` | the latest release of [somepanic/CoreTube](https://github.com/somepanic/CoreTube): its `-arm` and `-aarch64` zips |
| PlexMod for Kodi | `script.plexmod` | pannal's [Don't Panic](https://github.com/pannal/dontpanickodi) repository, unchanged |
| Plex Uno | `script.plexmod-uno` | FilHarr's [Maybe Panic](https://github.com/FilHarr/maybepanic) repository, unchanged |

A release needs its zip (`<id>-<version>.zip`, or one per architecture) and a `SHA256SUMS` file listing it. A
project without a release yet is left out. Each list holds only the newest version of each add-on, as Kodi's and
CoreELEC's own repositories do. Kodi keeps the zips it downloaded before, so **Versions** can still go back one.

## How it updates

GitHub Actions ([publish.yml](.github/workflows/publish.yml)) runs every 6 hours, on each push to `main`, from
**Actions → Publish the Kodi repository → Run workflow**, and when a project sends an `addon-released` event. It runs
the tests, collects the newest zips and checks them ([collect_zips.py](tools/collect_zips.py)), builds the site
([build_site.py](tools/build_site.py)) and publishes it on GitHub Pages. No zips are stored in this repository.

GitHub pauses the 6-hourly run after 60 days without any activity in this repository. Push a change or run the
workflow by hand to wake it.

## Change it

- **Add an add-on:** add it to `SOURCES` in [collect_zips.py](tools/collect_zips.py).
- **Change the repository add-on** (its lists or its icon): edit [repository/addon.xml](repository/addon.xml) and raise
  its version, so Kodi updates it.
- **Try it on your computer:**

  ```
  python3 -m unittest discover -s tests -t . -b
  python3 tools/collect_zips.py staging
  python3 tools/build_site.py staging site
  ```

## License

BSD-3-Clause ([LICENSE](LICENSE)). The add-ons keep their own licenses.
