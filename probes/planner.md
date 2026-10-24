# Probe: planner (window 09)

collected_at: 2026-10-24T07:36:52+00:00

The planner and networking agents call no external provider: they rank the records they are given. No OpenAI key is used; goal parsing is rule based. Every record below is **fixture** (fictional personas, `.invalid` URLs); nothing here is a live claim.

## Goal parser

- `Fondateur d'un outil dev IA, je vais à GitHub Universe pour rencontrer des investisseurs seed, des fondateurs d'agents IA et des PM Copilot.` -> goal-seed-investors w=0.45 roles=['investor'] topics=['developer tools'] tags=['parsed:planner-rules']; goal-founder w=0.35 roles=['founder'] topics=['ai agents'] tags=['parsed:planner-rules']; goal-pm w=0.2 roles=['pm'] topics=['copilot'] tags=['parsed:planner-rules']
- `(empty)` -> goal-seed-investors w=0.45 roles=['investor'] topics=['developer tools', 'ai agents'] tags=['default:no-goal-recognised']; goal-agent-founders w=0.35 roles=['founder'] topics=['ai agents', 'mcp'] tags=['default:no-goal-recognised']; goal-copilot-pms w=0.2 roles=['pm'] topics=['copilot', 'mcp'] tags=['default:no-goal-recognised']

Graph: FalkorDB answered on 127.0.0.1:6380.

## fixtures/planner.json (w09 fixture)

- agent: `planner-w09`, status **ok**, source_mode **fixture** (context declared `fixture`)
- input: 8 people, 8 events, 0 goals in context
- output: 7 people opportunities, 4 planned items, 4 rejected; runtime 2 ms
- errors: none

| rank | person | score | presence | where | source |
|---|---|---|---|---|---|
| 1 | Bo Fixturely (fictional), Partner | 76.6 | confirmed | Fixture panel: seed rounds for devtools (2026-10-28T11:00:00-07:00, Fort Mason Center (fixture), Room B (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 2 | Di Sampleton (fictional), Principal | 61.2 | confirmed | Fixture side event: devtools VC dinner (2026-10-28T19:00:00-07:00, Mission Table (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 3 | Ana Mockwell (fictional), Founder | 60.2 | confirmed | Fixture talk: agent infrastructure (2026-10-28T10:00:00-07:00, Fort Mason Center (fixture), Room A (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 4 | Cy Stubbs (fictional), Co-founder | 56.2 | confirmed | Fixture side event: agents night (2026-10-28T18:30:00-07:00, Pier Loft (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 5 | Eve Dummond (fictional), Product Manager, Copilot | 51.4 | confirmed | Fixture talk: Copilot extensions roadmap (2026-10-29T14:00:00-07:00, Fort Mason Center (fixture), Room C (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 6 | Gil Placeholder (fictional), Associate | 40.1 | probable | Fixture side event: agents night (2026-10-28T18:30:00-07:00, Pier Loft (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 7 | Ira Titled (fictional), General Partner | 27.8 | unknown | unknown | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |

Top explanation:

> score 76.6 = 100 x U/0.85; U=0.651 = +0.35xG(0.56) [role investor] +0.25xP(1.00) [presence confirmed] +0.15xS(0.80) +0.10xN(1.00) -0.07xT(0.19) -0.04xC(0.00) [price unknown] -0.04xR(0.00). Facts: role investor serves goal 'Meet seed investors (developer tools)' (weight 0.45) (planner-fixture/fixture https://fixture.conferge.invalid/people/fx-p-inv-bo @ 2026-10-24T09:00:00+00:00) | presence confirmed: listed as speaker of 'Fixture panel: seed rounds for devtools' (planner-fixture/fixture https://fixture.conferge.invalid/events/fx-s-seed-panel @ 2026-10-24T09:00:00+00:00) | where: Fixture panel: seed rounds for devtools (2026-10-28T11:00:00-07:00, Fort Mason Center (fixture), Room B (fixture)) (planner-fixture/fixture https://fixture.conferge.invalid/events/fx-s-seed-panel @ 2026-10-24T09:00:00+00:00)

Plan:

- 2026-10-28: 10:00 Fixture talk: agent infrastructure (45.3), 11:00 Fixture panel: seed rounds for devtools (51.2), 18:30 Fixture side event: agents night (64.2)
- 2026-10-29: 14:00 Fixture talk: Copilot extensions roadmap (36.5)
- rejected `fx-side-cancelled`: status cancelled
- rejected `fx-side-untimed`: start or end time unknown; not scheduled
- rejected `fx-side-vc-dinner`: overlaps 'Fixture side event: agents night' (score 64.2)
- rejected `fx-side-weak`: candidate side event with relation_score 0.2 < 0.5
- warning: 3 planned item(s) have unknown price; not counted in budget

Explanations: no goals in context: parsed goals used (goal-seed-investors, goal-founder, goal-pm); graph not connected: ranking from AgentContext facts only; plan: 4 item(s) over 2 day(s), 4 rejected with reasons; source mode fixture: fixture-backed records are not live claims; Bo Fixturely (fictional), Partner: 76.6 (confirmed) Fixture panel: seed rounds for devtools (2026-10-28T11:00:00-07:00, Fort Mason Center (fixture), Room B (fixture)); Di Sampleton (fictional), Principal: 61.2 (confirmed) Fixture side event: devtools VC dinner (2026-10-28T19:00:00-07:00, Mission Table (fixture)); Ana Mockwell (fictional), Founder: 60.2 (confirmed) Fixture talk: agent infrastructure (2026-10-28T10:00:00-07:00, Fort Mason Center (fixture), Room A (fixture)); goals: goal-seed-investors=0.45, goal-founder=0.35, goal-pm=0.2

## fixtures/demo.json (w13 fixture, read only)

- agent: `planner-w09`, status **ok**, source_mode **fixture** (context declared `fixture`)
- input: 14 people, 10 events, 3 goals in context
- output: 10 people opportunities, 8 planned items, 2 rejected; runtime 2 ms
- errors: none

| rank | person | score | presence | where | source |
|---|---|---|---|---|---|
| 1 | Ada Lanternwood, Partner | 71.0 | confirmed | Funding Developer Tools in 2027 (2026-10-29T15:00:00-07:00, Fort Mason Center, Pavilion C (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 2 | Elin Orbitson, Founder and CEO | 69.6 | confirmed | Agents in Production (2026-10-28T10:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 3 | Gwen Kitesong, Founder | 69.6 | confirmed | MCP Tooling for Agent Builders (2026-10-29T11:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 4 | Bram Quillfeather, General Partner | 67.8 | confirmed | Agents After Hours (2026-10-28T18:30:00-07:00, Harbor Hall (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 5 | Faro Patchley, Co-founder | 64.5 | confirmed | Pre-Universe Builders Meetup (2026-10-27T18:30:00-07:00, Builders Loft (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 6 | Ines Copperfield, Product Manager, Copilot integrations | 56.3 | confirmed | Building Copilot Extensions with MCP (2026-10-28T14:00:00-07:00, Fort Mason Center, Pavilion B (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 7 | Cleo Marrowind, Principal | 55.4 | confirmed | Devtools Founders Dinner (2026-10-28T19:00:00-07:00, Union Table (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 8 | Dov Embersley, Associate | 53.5 | confirmed | Seed Office Hours (2026-10-29T18:00:00-07:00, Lanternseed Studio (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 9 | Hale Driftmoor, Co-founder and CTO | 50.8 | confirmed | Agents After Hours (2026-10-28T18:30:00-07:00, Harbor Hall (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 10 | Kael Windmere, Product Manager, Copilot integrations | 45.3 | confirmed | Devtools Founders Dinner (2026-10-28T19:00:00-07:00, Union Table (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |

Top explanation:

> score 71.0 = 100 x U/0.85; U=0.603 = +0.35xG(0.50) [role investor] +0.25xP(1.00) [presence confirmed] +0.15xS(0.62) +0.10xN(1.00) -0.07xT(0.19) -0.04xC(0.00) [price unknown] -0.04xR(0.08). Facts: role investor serves goal 'Meet seed investors active in developer tools' (weight 0.45) (conferge-demo-seed/fixture https://demo.conferge.invalid/people/p-inv-ada @ 2026-10-23T12:00:00+00:00) | presence confirmed: listed as speaker of 'Funding Developer Tools in 2027' (conferge-demo-seed/fixture https://demo.conferge.invalid/events/evt-s-funding-devtools @ 2026-10-23T12:00:00+00:00) | where: Funding Developer Tools in 2027 (2026-10-29T15:00:00-07:00, Fort Mason Center, Pavilion C (synthetic room)) (conferge-demo-seed/fixture https://demo.conferge.invalid/events/evt-s-funding-devtools @ 2026-10-23T12:00:00+00:00)

Plan:

- 2026-10-27: 18:30 Pre-Universe Builders Meetup (50.3)
- 2026-10-28: 10:00 Agents in Production (47.0), 14:00 Building Copilot Extensions with MCP (42.9), 18:30 Agents After Hours (64.9)
- 2026-10-29: 08:00 Copilot Extensions Breakfast (29.6), 11:00 MCP Tooling for Agent Builders (57.5), 15:00 Funding Developer Tools in 2027 (42.3), 18:00 Seed Office Hours (41.8)
- rejected `evt-side-devtools-dinner`: overlaps 'Agents After Hours' (score 64.9)
- rejected `evt-side-infra-mixer`: candidate side event with relation_score 0.3 < 0.5
- warning: 8 planned item(s) have unknown price; not counted in budget

Explanations: graph not connected: ranking from AgentContext facts only; plan: 8 item(s) over 3 day(s), 2 rejected with reasons; source mode fixture: fixture-backed records are not live claims; Ada Lanternwood, Partner: 71.0 (confirmed) Funding Developer Tools in 2027 (2026-10-29T15:00:00-07:00, Fort Mason Center, Pavilion C (synthetic room)); Elin Orbitson, Founder and CEO: 69.6 (confirmed) Agents in Production (2026-10-28T10:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)); Gwen Kitesong, Founder: 69.6 (confirmed) MCP Tooling for Agent Builders (2026-10-29T11:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)); goals: goal-seed-investors=0.45, goal-agent-founders=0.35, goal-copilot-pms=0.2

## fixtures/planner.json with FalkorDB reads

- agent: `planner-w09`, status **ok**, source_mode **fixture** (context declared `fixture`)
- input: 8 people, 8 events, 0 goals in context
- output: 7 people opportunities, 4 planned items, 4 rejected; runtime 8 ms
- errors: none

| rank | person | score | presence | where | source |
|---|---|---|---|---|---|
| 1 | Bo Fixturely (fictional), Partner | 76.6 | confirmed | Fixture panel: seed rounds for devtools (2026-10-28T11:00:00-07:00, Fort Mason Center (fixture), Room B (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 2 | Di Sampleton (fictional), Principal | 61.2 | confirmed | Fixture side event: devtools VC dinner (2026-10-28T19:00:00-07:00, Mission Table (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 3 | Ana Mockwell (fictional), Founder | 60.2 | confirmed | Fixture talk: agent infrastructure (2026-10-28T10:00:00-07:00, Fort Mason Center (fixture), Room A (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 4 | Cy Stubbs (fictional), Co-founder | 56.2 | confirmed | Fixture side event: agents night (2026-10-28T18:30:00-07:00, Pier Loft (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 5 | Eve Dummond (fictional), Product Manager, Copilot | 51.4 | confirmed | Fixture talk: Copilot extensions roadmap (2026-10-29T14:00:00-07:00, Fort Mason Center (fixture), Room C (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 6 | Gil Placeholder (fictional), Associate | 40.1 | probable | Fixture side event: agents night (2026-10-28T18:30:00-07:00, Pier Loft (fixture)) | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |
| 7 | Ira Titled (fictional), General Partner | 27.8 | unknown | unknown | planner-fixture/fixture @ 2026-10-24T09:00:00+00:00 |

Top explanation:

> score 76.6 = 100 x U/0.85; U=0.651 = +0.35xG(0.56) [role investor] +0.25xP(1.00) [presence confirmed] +0.15xS(0.80) +0.10xN(1.00) -0.07xT(0.19) -0.04xC(0.00) [price unknown] -0.04xR(0.00). Facts: role investor serves goal 'Meet seed investors (developer tools)' (weight 0.45) (planner-fixture/fixture https://fixture.conferge.invalid/people/fx-p-inv-bo @ 2026-10-24T09:00:00+00:00) | presence confirmed: listed as speaker of 'Fixture panel: seed rounds for devtools' (planner-fixture/fixture https://fixture.conferge.invalid/events/fx-s-seed-panel @ 2026-10-24T09:00:00+00:00) | where: Fixture panel: seed rounds for devtools (2026-10-28T11:00:00-07:00, Fort Mason Center (fixture), Room B (fixture)) (planner-fixture/fixture https://fixture.conferge.invalid/events/fx-s-seed-panel @ 2026-10-24T09:00:00+00:00)

Plan:

- 2026-10-28: 10:00 Fixture talk: agent infrastructure (45.3), 11:00 Fixture panel: seed rounds for devtools (51.2), 18:30 Fixture side event: agents night (64.2)
- 2026-10-29: 14:00 Fixture talk: Copilot extensions roadmap (36.5)
- rejected `fx-side-cancelled`: status cancelled
- rejected `fx-side-untimed`: start or end time unknown; not scheduled
- rejected `fx-side-vc-dinner`: overlaps 'Fixture side event: agents night' (score 64.2)
- rejected `fx-side-weak`: candidate side event with relation_score 0.2 < 0.5
- warning: 3 planned item(s) have unknown price; not counted in budget

Explanations: no goals in context: parsed goals used (goal-seed-investors, goal-founder, goal-pm); graph connected: 0 people have a goal path; plan: 4 item(s) over 2 day(s), 4 rejected with reasons; source mode fixture: fixture-backed records are not live claims; Bo Fixturely (fictional), Partner: 76.6 (confirmed) Fixture panel: seed rounds for devtools (2026-10-28T11:00:00-07:00, Fort Mason Center (fixture), Room B (fixture)); Di Sampleton (fictional), Principal: 61.2 (confirmed) Fixture side event: devtools VC dinner (2026-10-28T19:00:00-07:00, Mission Table (fixture)); Ana Mockwell (fictional), Founder: 60.2 (confirmed) Fixture talk: agent infrastructure (2026-10-28T10:00:00-07:00, Fort Mason Center (fixture), Room A (fixture)); goals: goal-seed-investors=0.45, goal-founder=0.35, goal-pm=0.2

## fixtures/demo.json with FalkorDB reads (read only)

- agent: `planner-w09`, status **ok**, source_mode **fixture** (context declared `fixture`)
- input: 14 people, 10 events, 3 goals in context
- output: 10 people opportunities, 8 planned items, 2 rejected; runtime 6 ms
- errors: none

| rank | person | score | presence | where | source |
|---|---|---|---|---|---|
| 1 | Ada Lanternwood, Partner | 71.0 | confirmed | Funding Developer Tools in 2027 (2026-10-29T15:00:00-07:00, Fort Mason Center, Pavilion C (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 2 | Elin Orbitson, Founder and CEO | 69.6 | confirmed | Agents in Production (2026-10-28T10:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 3 | Gwen Kitesong, Founder | 69.6 | confirmed | MCP Tooling for Agent Builders (2026-10-29T11:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 4 | Bram Quillfeather, General Partner | 67.8 | confirmed | Agents After Hours (2026-10-28T18:30:00-07:00, Harbor Hall (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 5 | Faro Patchley, Co-founder | 64.5 | confirmed | Pre-Universe Builders Meetup (2026-10-27T18:30:00-07:00, Builders Loft (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 6 | Ines Copperfield, Product Manager, Copilot integrations | 56.3 | confirmed | Building Copilot Extensions with MCP (2026-10-28T14:00:00-07:00, Fort Mason Center, Pavilion B (synthetic room)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 7 | Cleo Marrowind, Principal | 55.4 | confirmed | Devtools Founders Dinner (2026-10-28T19:00:00-07:00, Union Table (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 8 | Dov Embersley, Associate | 53.5 | confirmed | Seed Office Hours (2026-10-29T18:00:00-07:00, Lanternseed Studio (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 9 | Hale Driftmoor, Co-founder and CTO | 50.8 | confirmed | Agents After Hours (2026-10-28T18:30:00-07:00, Harbor Hall (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |
| 10 | Kael Windmere, Product Manager, Copilot integrations | 45.3 | confirmed | Devtools Founders Dinner (2026-10-28T19:00:00-07:00, Union Table (synthetic venue)) | conferge-demo-seed/fixture @ 2026-10-23T12:00:00+00:00 |

Top explanation:

> score 71.0 = 100 x U/0.85; U=0.603 = +0.35xG(0.50) [role investor] +0.25xP(1.00) [presence confirmed] +0.15xS(0.62) +0.10xN(1.00) -0.07xT(0.19) -0.04xC(0.00) [price unknown] -0.04xR(0.08). Facts: role investor serves goal 'Meet seed investors active in developer tools' (weight 0.45) (conferge-demo-seed/fixture https://demo.conferge.invalid/people/p-inv-ada @ 2026-10-23T12:00:00+00:00) | presence confirmed: listed as speaker of 'Funding Developer Tools in 2027' (conferge-demo-seed/fixture https://demo.conferge.invalid/events/evt-s-funding-devtools @ 2026-10-23T12:00:00+00:00) | where: Funding Developer Tools in 2027 (2026-10-29T15:00:00-07:00, Fort Mason Center, Pavilion C (synthetic room)) (conferge-demo-seed/fixture https://demo.conferge.invalid/events/evt-s-funding-devtools @ 2026-10-23T12:00:00+00:00)

Plan:

- 2026-10-27: 18:30 Pre-Universe Builders Meetup (50.3)
- 2026-10-28: 10:00 Agents in Production (47.0), 14:00 Building Copilot Extensions with MCP (42.9), 18:30 Agents After Hours (64.9)
- 2026-10-29: 08:00 Copilot Extensions Breakfast (29.6), 11:00 MCP Tooling for Agent Builders (57.5), 15:00 Funding Developer Tools in 2027 (42.3), 18:00 Seed Office Hours (41.8)
- rejected `evt-side-devtools-dinner`: overlaps 'Agents After Hours' (score 64.9)
- rejected `evt-side-infra-mixer`: candidate side event with relation_score 0.3 < 0.5
- warning: 8 planned item(s) have unknown price; not counted in budget

Explanations: graph connected: 0 people have a goal path; plan: 8 item(s) over 3 day(s), 2 rejected with reasons; source mode fixture: fixture-backed records are not live claims; Ada Lanternwood, Partner: 71.0 (confirmed) Funding Developer Tools in 2027 (2026-10-29T15:00:00-07:00, Fort Mason Center, Pavilion C (synthetic room)); Elin Orbitson, Founder and CEO: 69.6 (confirmed) Agents in Production (2026-10-28T10:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)); Gwen Kitesong, Founder: 69.6 (confirmed) MCP Tooling for Agent Builders (2026-10-29T11:00:00-07:00, Fort Mason Center, Pavilion A (synthetic room)); goals: goal-seed-investors=0.45, goal-agent-founders=0.35, goal-copilot-pms=0.2

