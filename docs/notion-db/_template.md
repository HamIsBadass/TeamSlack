# <DB Name> Guide

Replace this template with DB-specific rules.

## DB Purpose

Describe what this database stores and what automation should do.

## Required Properties

| Property | Type | Rule |
|---|---|---|
| source_url | URL | Required for processing |
| title | Title | Fill from extraction |
| keywords | Multi-select | Only allowed keyword set |
| apply_start_date | Date | Extract application/entry start date; leave empty if unknown |
| event_start_date | Date | Extract event start date; leave empty if unknown |
| memo | Text | Standardized blocks (date/time duplication not allowed) |
| autofilled | Checkbox | Success flag |
| last_autofill_at | Date | Set on success |
| error | Text | Failure reason |

## Allowed Keywords

- <keyword-1>
- <keyword-2>
- <keyword-3>

Policy:

- Keep only allowed options.
- Drop unknown values.

## Field Rules

### source_url

- Rule:

### title

- Rule:

### memo

- Rule:

### apply_start_date

- Rule:

### event_start_date

- Rule:

## Processing Target (Suggested)

- `source_url` is not empty
- `autofilled` is not checked
- `error` is empty or retryable

## Error Message Convention

- `network_error`
- `source_unreachable`
- `json_parse_error`
- `notion_validation_error`
- `rate_limited`

## Quality Check After Autofill

1. Keyword values are allowed.
2. Application/event dates (if any) follow `YYYY-MM-DD`.
3. Memo uses a fixed section order and avoids duplicate date/time facts.
4. Unknown values remain empty.
5. On successful autofill: `autofilled=true` and `last_autofill_at` are automatically set by automation.
6. Failure indicators (`error` flag) match actual processing errors.
