# gfm-addon: the GFM look, layouts, components and charts

A Slidev add-on (listed in `slidev/package.json`, after `addons/gfm-studio`). Slidev registers what is in these
folders by itself; Studio's palette and layout picker read the `<studio>` block of each file.

| Folder | What |
|---|---|
| `styles/index.css` | The shared look: colours (`--gfm-*`, light and dark), type sizes for a call, cards, motion. Every GFM layout and component uses it. |
| `layouts/gfm-*.vue` | The layouts: `gfm-cover`, `gfm-section`, `gfm-hero`, `gfm-full-chart`, `gfm-chart-insight`, `gfm-two-chart`, `gfm-kpi-grid`, `gfm-three-column`, `gfm-comparison`, `gfm-image-message`, `gfm-freeform`. |
| `components/Gfm*.vue` | Content and data parts: `GfmBigNumber`, `GfmCallout`, `GfmComparison`, `GfmInsight`, `GfmKpi`, `GfmKpiGrid`, `GfmProgress`, `GfmQuote`. |
| `components/Mission*.vue`, `lib/` | The charts (`MissionChart`, `MissionKpiChart`), drawn with the vendored ECharts. How to write them: `slidev/README.md`. |

## Rules for a layout or component

- A component or layout **owns** spacing, type, alignment and colour; a slide only chooses content. The default must look
  right with no styling (written for a 980 px slide read on a video call: nothing under 15 px, body 20 px).
- One root element (Studio cannot select a component with several roots). A `<studio>` block with a description, and for
  a component a `category` (`GFM content` or `GFM data`), a `snippet` and a `preview`.
- **Slidev keeps some frontmatter words back from a layout** (`title`, `level`, `src`, `lang`, `hide`, `layout`,
  `transition`, `clicks` ...). A layout's heading is therefore the prop `heading`, and it also reads `frontmatter.title`,
  which Slidev always passes, so a slide written with `title:` works too.
- **Numbers on a published deck are only answered for charts written in the deck's slides** (`chart-access.mjs`). A
  component that builds a chart query from its props would be refused. `GfmKpi` and `GfmKpiGrid` therefore draw
  `MissionKpiChart` (key numbers), and `chart-access.mjs` counts them like one. A new data component needs the same
  thought: either draw an existing chart tag, or teach `chart-spec.mjs` `pinnedKeys` to read its attributes.
- Anything loaded only when used (a panel, the formula editor, Monaco) is a dynamic `import()` / `defineAsyncComponent`.

## Looking at them

`slidev/tests/studio-perf/gfm-demo.md` is a deck with every layout and component (the test container publishes it as
`gfm-demo`; `slidev/tests/studio-perf/README.md`). `slidev/tests/gfm-components.test.mjs` checks the rules above.
