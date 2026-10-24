# Probe w08 graph (FalkorDB)

- collected_at: 2026-10-24T06:34:40.635090+00:00
- endpoint: 127.0.0.1:6380 graph `conferge`
- source: FalkorDB round-trip is **live**; graph data is **fixture** (`fixtures/graph.json`, fictional people/events labelled `Fixture`/`[FIXTURE]`; conference anchor from docs/knowledge/03-demo-scenario.md)
- status: **ok** (termination: exhausted)
- seed: 29 node merges, 54 edge merges in 35 ms
- node counts: {'Company': 3, 'Venue': 3, 'Event': 5, 'Conference': 1, 'Person': 7, 'Goal': 3, 'Opportunity': 1, 'Topic': 6}
- edge counts: {'SERVES_GOAL': 1, 'LOCATED_AT': 5, 'HOSTS': 2, 'SPEAKS_AT': 2, 'EXHIBITS_AT': 1, 'WORKS_AT': 6, 'ABOUT': 28, 'ATTENDS_CONFIRMED': 1, 'PART_OF': 5, 'INVOLVES': 3}
- UI subgraph: {'node_count': 28, 'edge_count': 53, 'truncated': False}

## Ingest warnings (edges refused, not invented)

- ATTENDS_CONFIRMED p-fx-gina->e-fx-agents-night: no evidence URL

## people_for_goal(demo-user, g-agent-founders)

5 people reachable with a 2 to 4 hop path (acceptance: >= 5).

| person | score | reasons | paths | shortest hops |
|---|---|---|---|---|
| Fixture Speaker Alice | 1.365 | host_company, role:founder, speaker, topic | 5 | 2 |
| Fixture Founder Frank | 0.35 | role:founder, topic | 2 | 2 |
| Fixture Organizer Erin | 0.28 | role:founder, topic | 1 | 2 |
| Fixture Investor Carol | 0.252 | attendance | 1 | 3 |
| Fixture Engineer Bob | 0.231 | host_company, topic | 2 | 2 |

Example explanations (first path per person):

- [fixture] Your goal 'Meet AI agents founders' targets AI agents; '[FIXTURE] Building agents with MCP' is about AI agents; Fixture Speaker Alice speaks at '[FIXTURE] Building agents with MCP' on Oct 28 14:00 PDT. Sources: user/fixture, fixture:w08-graph/fixture.
- [fixture] Your goal 'Meet AI agents founders' targets AI agents; Fixture Founder Frank works on AI agents. Sources: user/fixture, fixture:w08-graph/fixture.
- [fixture] Your goal 'Meet AI agents founders' targets AI agents; Fixture Organizer Erin works on AI agents (inferred from text). Sources: user/fixture, fixture:w08-graph/fixture.
- [fixture] Your goal 'Meet AI agents founders' targets AI agents; '[FIXTURE] Agents Night (fictional side event)' is about AI agents; Fixture Investor Carol is publicly listed as attending '[FIXTURE] Agents Night (fictional side event)'. Sources: user/fixture, fixture:w08-graph/fixture.
- [fixture] Your goal 'Meet AI agents founders' targets AI agents; '[FIXTURE] Agents Night (fictional side event)' is about AI agents; Fixture AgentLabs (fictional) hosts '[FIXTURE] Agents Night (fictional side event)' on Oct 28 19:00 PDT; Fixture Engineer Bob works at Fixture AgentLabs (fictional) as Staff Engineer. Sources: user/fixture, fixture:w08-graph/fixture.

## events_for_goal(demo-user, g-agent-founders)

- [FIXTURE] Building agents with MCP (2026-10-28T14:00:00-07:00): 1 target people, basis {'SPEAKS_AT': ['p-fx-alice']}
- [FIXTURE] Agents Night (fictional side event) (2026-10-28T19:00:00-07:00): 1 target people, basis {'ATTENDS_CONFIRMED': ['p-fx-carol']}

## conflicts(github-universe-2026)

- overlap: [FIXTURE] Agents Night (fictional side event) x [FIXTURE] DevTools Mixer (fictional), distance 563 m
- unverifiable: [FIXTURE] Open source breakfast (time not published) (missing start or end time)

## path_user_to_person(demo-user, p-fx-alice)

- g-agent-founders (2 hops): [fixture] Your goal 'Meet AI agents founders' targets AI agents; Fixture Speaker Alice works on AI agents. Sources: user/fixture, fixture:w08-graph/fixture.
- g-seed-investors (2 hops): [fixture] Your goal 'Meet seed investors' targets AI agents; Fixture Speaker Alice works on AI agents. Sources: user/fixture, fixture:w08-graph/fixture.
- g-copilot-pms (4 hops): [fixture] Your goal 'Meet Copilot PMs' targets Copilot; 'GitHub Universe 2026' is about Copilot; 'GitHub Universe 2026' is about AI agents; Fixture Speaker Alice works on AI agents. Sources: user/fixture, fixture:w08-graph/fixture.

## Cross-session memory (scratch graph, deleted after)

- ranking before: ['p-fx-alice', 'p-fx-frank', 'p-fx-erin', 'p-fx-carol', 'p-fx-bob']
- recorded MET with: p-fx-alice
- ranking after: ['p-fx-frank', 'p-fx-erin', 'p-fx-carol', 'p-fx-bob']
