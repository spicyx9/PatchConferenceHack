# Conferge interface system

## Product and primary reference

Conferge helps a conference traveller move from an explicit networking goal to useful
people, events and a suggested program. Discovery is the entry point; this is an
interactive application, rather than a marketing landing page.

Primary references inspected on 2026-10-24:

- [Luma San Francisco discovery](https://luma.com/sf): city cover, dated event feed,
  restrained cards, artwork and a contextual secondary column.
- [Luma event page](https://luma.com/x7lmea3h): artwork and readable event information,
  explicit date/place, contained primary action, secondary source context.
- [Partiful event](https://partiful.com/e/h6YYc5rG42JsJ9zHCjMX): atmospheric
  artwork background, prominent title, compact event facts and a single clear action.
- [Native controls and accessibility patterns](https://www.radix-ui.com/primitives/docs/overview/accessibility):
  semantic buttons, accessible names, focus handling and keyboard interaction.
- [Progressive disclosure](https://www.nngroup.com/articles/progressive-disclosure/):
  source details and uncommon planning controls appear on request.
- [WCAG target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html):
  keep important controls comfortably usable and distinct.

The public HTML, inline CSS, external CSS and computed styles of both Luma pages
were inspected. Their raw bundles are research inputs; they are not shipped here.
The application uses its existing vanilla HTML/CSS/JavaScript architecture.

## Visual rules

- System sans-serif stack; no external font dependency. Default 16 px body,
  20 px event titles, 24 px section headings and 36–52 px prominent titles.
- Neutral background `#f7f7f7`, white surfaces, primary text `#151515`, muted text
  `#686868`, subtle `#e7e7e7` boundaries. Color communicates provenance and status.
- Black primary actions, pale gray secondary actions. Hero action is white on
  imagery. Ordinary actions have a 44 px target; compact secondary controls are
  spaced apart and remain keyboard accessible.
- Main content max width 1088 px including horizontal padding. Discovery uses a
  flexible feed plus 272 px context column with a 50 px gap on large screens.
- 12 px cards and 18 px cover radius. Avoid decorative shadows and dashboard tile grids.
- Event artwork belongs to the corresponding exact source record. Missing artwork
  uses an explicitly decorative typographic composition, never an unrelated event poster.
- The city cover is an AI-generated atmospheric illustration. Its generated nature
  is documented in `images/ASSETS.md`; it is not evidence about a venue or an event.

## Information architecture

1. **Discover:** destination, events around the trip, goal context, people, daily
   program preview, map, tradeoffs and replanning.
2. **Program:** days, participation/skip actions, conflicts, searchable event feed.
3. **People:** identity, rationale, presence qualification, evidence, conversation
   preparation, meeting note and explanation path.
4. **Travel:** observed offers, unknown prices, indicative budget, saved proposals,
   source links, locations and coordinate precision.
5. **Connections:** visual and textual graph, paths, relationship evidence and
   secondary agent coordination details.

Small screens have a compact, horizontally scrollable top navigation. The goal
appears before discovery; longer context details collapse through layout, without
removing access to sources, data mode or engine status.

## Behavior and honesty

- Source mode and engine availability are separate. Provider usage metadata must
  not turn a fixture session into a live or mixed-data claim.
- Scores are relevance scores, not probabilities or promises of a meeting.
- An announced speaker is not a confirmed attendee of every surrounding event.
- A suggested program is not presented as an optimized driving itinerary.
- Map lines indicate visit order, not computed ground routes.
- Participation, meeting memory and saving a travel proposal are distinct from
  booking or registering with an external service.
- Every mutation refreshes program, people, graph, map, metrics and overview.
- Dialogs have labels, visible cancel/close actions, native focus containment and
  Escape behavior. Errors remain within the active dialog when appropriate.
- Loading, empty results, partial failure and retry are explicit. Text paths and
  place lists remain usable when external visualization libraries fail.
- Motion is short and functional, and reduced-motion preferences are respected.

## Interface language and controls

The interface uses English, including empty states, errors, dates, accessible labels
and dialogs. Actions use concise text without decorative arrows. Source provenance
is available in Sources rather than repeated on every card. Event detail opens in
a native accessible dialog, using the matching event artwork and source link.
The header and trip context share the main content alignment.
