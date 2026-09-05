# TestRail API excerpts

Hand-maintained TestRail API v2 excerpts (Cloud, 2024+ pagination).
Coding agents read them via `tr docs TOPIC` or `tr docs search QUERY`.
Call the API only through `tr api METHOD[/id]`; never raw HTTP from agents.
Required reading: `tr docs quirks` (official JSON examples are often wrong).
Topics: auth, cases, sections, runs, tests, results, quirks.
Bulk GET: `{offset,limit,size,_links:{next,prev},<entity>:[]}`; limit max 250.
Writes dry-run unless `--commit` is set; never call HTTP except via `tr api`.
Auth never appears here; keys come from `TESTRAIL_API_KEY` or the keyring.
