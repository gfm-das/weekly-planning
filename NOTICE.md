# Third-party software and content

Weekly Planning is released under the MIT licence (`LICENSE`). It uses and includes the following. Each keeps its own licence.

## Included in this repository (vendored files)
| What | Where | Licence |
|---|---|---|
| Apache ECharts | `portal/echarts.min.js` (its licence header is in the file) | Apache-2.0 |
| SortableJS 1.15.6 | `portal/Sortable.min.js` | MIT |
| Excalidraw, React and their dependencies (the Whiteboard) | `portal/whiteboard/vendor/` (the full list with licence texts: `portal/whiteboard/vendor/THIRD_PARTY_LICENSES.txt`) | MIT and others, as listed there |
| Presentations V2 editor and player: GrapesJS, Reveal.js, ECharts, Vue and others | `slidev/presentations-v2/dist/` (built from `slidev/presentations-v2/`) | BSD-3-Clause, MIT, Apache-2.0 |
| Studio addon for Slidev | `slidev/manager/addons/gfm-studio/` (its own `LICENSE`) | as stated there |

## Installed from the internet when the system is set up (not part of this repository)
- Slidev and its packages (npm): MIT and others.
- Supabase (PostgreSQL, GoTrue, PostgREST, Kong, Studio and more), as container images: Apache-2.0, PostgreSQL licence and others.
- DataEase Community Edition (Dashboards), as a container image from its own registry: GPL-3.0. It runs as a separate program next to this
  software and is not changed or included here. Check its licence before you offer it to other people as a service.
- nginx, Node.js, Python, PostgreSQL client tools, cloudflared (Cloudflare): their own licences.

## Content
- The scripture and Preach My Gospel references point to churchofjesuschrist.org. The names "The Church of Jesus Christ of Latter-day
  Saints", its logos and its texts belong to their owners and are not licensed by this repository.
- The interface texts in 14 languages (`portal/i18n/`) are part of this software (MIT). All but English still need review by a native speaker.
