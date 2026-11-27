---
name: free-asset-library
description: Where the series' free 3D models, skies, textures and sounds live on D:\assets\milo-saga, their licences and credits, which free sites to use for more (Kenney, Quaternius, Poly Pizza, Poly Haven, BlendKit, Sketchfab, Sonniss), and the tested download tricks from Iran (proxy, Kenney signed links, itch.io, Google Drive quota). Use before modelling anything new, when a shot needs a prop/vehicle/location, or when writing the video description credits.
---

# Free asset library (The Milo Saga)

Rule from the owner (2026-11-14): free only; free sign-ups are fine (owner enters the email); stylised
worlds are fine. Never re-model what a free kit has.

## What is already on disk (`D:\assets\milo-saga\`)

| Folder | Content | Licence |
|---|---|---|
| `x/quaternius-downtown/Exports/glTF (Godot)` | NYC-style city: streets, intersections, sidewalks, 3 ready buildings, modular facades, props | CC0 |
| `x/majadroid-ruins/.../fbx files` | 7 ruined skyscrapers, billboards, wreckage, fire stairs | CC0 |
| `x/kenney/<kit>` | city commercial/suburban/industrial/roads, car-kit (~50 cars), building-kit, modular-buildings, survival-kit (~530 GLB) | CC0 |
| `dl/kenney/particle-pack` (zip) | smoke, fire, spark, flare sprites | CC0 |
| `dl/polypizza/*.glb` | 6 helicopters, 10 planes/jets, zombies, broken/police cars, ambulances, fire trucks, buses, fences, barriers, sandbags, tents, street lights | CC0 / CC-BY (see `CREDITS.tsv`) |
| `dl/polyhaven-hdri`, `dl/polyhaven/hdri` | 9 skies: dusk, sunset, overcast, 5 night | CC0 |
| `dl/polyhaven/tex` | asphalt, concrete, rusty metal, mud, brick, corrugated iron (2K) | CC0 |
| `dl/sonniss-gdc2026` | 484 pro sound effects (5 zips, ~7 GB) | royalty-free, no credit, no AI training |
| `x/city-generator` | outerreaches building generator add-on (ruined cities, highway) | GPL-3 add-on, output is ours |
| `x/duik`, `tools/rhubarb`, `tools/flamenco`, `tools/blender-mcp` | AE rigging, lip sync, render farm, Blender MCP | GPL / MIT |

## Credits

CC-BY models need the author's name in the video description. Build the credits block from `CREDITS.tsv`
for the models that appear in the episode ("3D models: Helicopter by jeremy (Poly Pizza, CC-BY) ..."). CC0
and Sonniss need nothing, but listing Kenney/Quaternius/Poly Haven is a nice touch.

## Where to get more (free)

| Site | Account | Notes |
|---|---|---|
| Kenney (kenney.nl) | no | CC0. Signed link: from any kenney.nl page run `fetch('/download-link/' + hex('assets/<slug>'))` -> `{url}` (hex = ASCII hex of the string); then download through the proxy |
| Quaternius (quaternius.com, itch) | no | CC0; some packs on Google Drive (quota can run out for a day) |
| Poly Pizza (poly.pizza) | no | model page HTML contains `https://static.poly.pizza/<uuid>.glb`; licence and author on the page |
| Poly Haven | no | `https://api.polyhaven.com/files/<id>` gives direct URLs (strip `\r` on Windows) |
| BlendKit (blenderkit.com) | free account | Royalty Free / CC0, commercial OK; Chinook, cargo plane, wrecks, terminal. Public search API: `/api/v1/search/?query=X+asset_type:model+is_free:true` |
| Sketchfab | free account | filter "Downloadable" + CC0/CC-BY |
| Sonniss GDC bundles | no | gdc.sonniss.com (2026), sonniss.com/gameaudiogdc (2015-2024) |
| Mixamo | free Adobe account | animations if 3D crowds are ever needed |

## Network notes (from Iran, tested 2026-11-14)

- itch.io, kenney.nl pages, Google APIs: only through v2rayN `http://127.0.0.1:10808`. GitHub, Poly Haven,
  Poly Pizza CDN, Sonniss downloads, itch's R2 CDN: direct is faster.
- itch.io starts a Cloudflare challenge after many automated requests: stop, never try to bypass it; ask the
  owner to download by hand, or retry another day.
- Long downloads: run detached (`Start-Process` Git bash) with `curl -C - --retry`, log to a file.
- Downloads go into their own folder under `dl/`, unzip into `x/`; never run code from a download before
  reading it; open .blend files with scripts disabled; prefer glTF/FBX over .blend.
