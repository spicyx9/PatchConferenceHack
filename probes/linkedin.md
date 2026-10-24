# Probe: LinkedIn enrichment (Bright Data dataset gd_l1viktl72bvl7bjuj0)

- run at: 2026-10-24T19:16:37.391326+00:00 (122.0 s)
- graph: conferge_linkedin_probe (demo data, fixture sources); goal: goal-seed-investors
- targets: 10 (10 speakers; hosts of fixtures/people.json with a linkedin_url: 0)

## Existing snapshots

- sd_mvmpuno1cydgpjvik: kept data/probes/linkedin_sd_mvmpuno1cydgpjvik.json (already downloaded)
- sd_mvmpunm2ess6r1ual: kept data/probes/linkedin_sd_mvmpunm2ess6r1ual.json (already downloaded)

## Profiles

- from saved files (cached): 0/10
- missing before collection: 10 (new collection only when > 3)
- new collection: POST /datasets/v3/scrape, 10 inputs, 12 HTTP responses, last HTTP 202, status failed, snapshot sd_mvms2ssrh1bjodbs9, 0 records -> data/probes/linkedin_20261024T191436Z.json
- cost returned by the API: none (no cost header in the responses)
- collection errors: ['/datasets/v3/scrape (10 inputs): snapshot sd_mvms2ssrh1bjodbs9 not ready after 120s']
- matched (name confirmed): 0; name mismatch: 0; still missing: 10
- identity_confidence 1.0: 0, 0.7: 0

## FalkorDB writes (GraphStore MERGE)

- Person nodes written: 0; nodes with provider brightdata:linkedin: 0
- WORKS_AT edges: 0; Company nodes created: 0
- no ATTENDS edge, no presence_confidence change (identity only)

## people_for_goal top 5

Before:
1. Leonardo Esteban Villa (person:rainfocus:1783696982691001Zpoc_1768417809universe26) score 0.36
2. Kaush Ganguly (person:rainfocus:1683707625375001TUbD_1768417809universe26) score 0.225
3. Pamela Fox (person:rainfocus:1683842376812001m7gi_1768417809universe26) score 0.225
4. Christopher Harrison (person:rainfocus:1684527155555001kvYJ_1768417809universe26) score 0.225
5. Dylan McCarthy (person:rainfocus:1685316289726001Jven_1768417809universe26) score 0.225

After:
1. Leonardo Esteban Villa (person:rainfocus:1783696982691001Zpoc_1768417809universe26) score 0.36
2. Kaush Ganguly (person:rainfocus:1683707625375001TUbD_1768417809universe26) score 0.225
3. Pamela Fox (person:rainfocus:1683842376812001m7gi_1768417809universe26) score 0.225
4. Christopher Harrison (person:rainfocus:1684527155555001kvYJ_1768417809universe26) score 0.225
5. Dylan McCarthy (person:rainfocus:1685316289726001Jven_1768417809universe26) score 0.225
