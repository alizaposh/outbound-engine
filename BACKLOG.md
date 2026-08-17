# Backlog

Deferred work, with the trigger that unblocks each item. Nothing here is in v1 scope
until its trigger is met.

## Google Sheets review surface
**Trigger:** after copy testing is validated.

Set up a GCP service account and enable the Sheets API, put the key path in
`GOOGLE_SERVICE_ACCOUNT_JSON`, share the target sheet with the service-account email,
then build an "export review dataset to Google Sheet" step. The sheet is the artifact:
share its link in Slack for review, which fits the planned Slack review/approval flow.

**Until then:** generation writes to a local CSV.
