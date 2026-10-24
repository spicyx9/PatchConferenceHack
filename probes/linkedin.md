# Probe: LinkedIn enrichment (Bright Data dataset gd_l1viktl72bvl7bjuj0)

- run at: 2026-10-24T19:26:11.048081+00:00 (1.8 s)
- graph: conferge_linkedin_probe (demo data, fixture sources); goal: goal-seed-investors
- targets: 10 (10 speakers; hosts of fixtures/people.json with a linkedin_url: 0)

## Existing snapshots

- sd_mvmpuno1cydgpjvik: kept data/probes/linkedin_sd_mvmpuno1cydgpjvik.json (already downloaded)
- sd_mvmpunm2ess6r1ual: kept data/probes/linkedin_sd_mvmpunm2ess6r1ual.json (already downloaded)
- sd_mvms2ssrh1bjodbs9: kept data/probes/linkedin_sd_mvms2ssrh1bjodbs9.json (already downloaded)

## Profiles

- from saved files (cached): 10/10
- missing before collection: 0 (new collection only when > 3)
- new collection: none
- matched (name confirmed): 9; name mismatch: 1; still missing: 0
- identity_confidence 1.0: 6, 0.7: 3

## FalkorDB writes (GraphStore MERGE)

- Person nodes written: 9; nodes with provider brightdata:linkedin: 9
- WORKS_AT edges: 8; Company nodes created: 2
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
