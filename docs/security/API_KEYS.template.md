# API Keys Management Template

This template defines how to manage shared API keys for project automation jobs.

Do not put real tokens in this file.

## Required Keys

- `PPLX_API_KEY`: Perplexity API key
- `GEMINI_API_KEY`: Gemini API key

## Recommended Runtime Variables

- `NOTION_TOKEN`: Notion integration token
- `NOTION_DATABASE_ID`: Default database ID (optional if routing by DB map)

## Key Rotation Metadata

Fill metadata only (no real secret values):

| Key | Owner | Last Rotated | Rotation Interval | Notes |
|---|---|---|---|---|
| PPLX_API_KEY | <team/person> | YYYY-MM-DD | 90d | <scope> |
| GEMINI_API_KEY | <team/person> | YYYY-MM-DD | 90d | <scope> |

## Storage Policy

- Local development: store keys in `.env` (never commit).
- CI/CD (GitHub Actions): store keys in repository secrets.
- Docs: never paste real key values.

## Naming Policy

- `PPLX_API_KEY`
- `GEMINI_API_KEY`
- `NOTION_TOKEN`
- `NOTION_DATABASE_ID`

## Multi-DB Operation Policy

- Same key set can be reused across all jobs.
- Project-specific behavior is controlled by database IDs/config mapping, not by issuing separate API keys per DB.
- If strict separation is required later, create key groups by environment:
  - `PPLX_API_KEY_PROD`, `PPLX_API_KEY_DEV`
  - `GEMINI_API_KEY_PROD`, `GEMINI_API_KEY_DEV`

## Incident Response

1. Revoke compromised key immediately.
2. Rotate secret in provider console.
3. Update GitHub Actions secrets.
4. Verify workflow run with masked logs.
5. Record rotation date in metadata table.
