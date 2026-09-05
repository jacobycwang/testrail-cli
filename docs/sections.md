# Sections

Sections group cases inside a suite. Nested via `parent_id`.
Call only via `tr api`. See `tr docs quirks`.

## GET get_sections/{project_id}

Required: `project_id` (int). `suite_id` required in multi-suite mode.
Query: `suite_id` int, `limit` int (max 250), `offset` int.
Paginated `{offset,limit,size,_links,sections}`.

```json
{
  "offset": 0,
  "limit": 250,
  "size": 3,
  "_links": { "next": null, "prev": null },
  "sections": [
    {
      "id": 2,
      "name": "Auth",
      "parent_id": null,
      "depth": 0,
      "suite_id": 1,
      "display_order": 1
    },
    {
      "id": 12,
      "name": "Token",
      "parent_id": 2,
      "depth": 1,
      "suite_id": 1,
      "display_order": 2
    }
  ]
}
```

    tr api get_sections/1 --query suite_id=1,limit=250 --paginate

## GET get_section/{section_id}

Required: `section_id` (int). One section object (same fields as above).

    tr api get_section/12

## POST add_section/{project_id}

Required: `project_id` (int). Body `name` required.
`suite_id` required in multi-suite mode. `parent_id` optional.
`description` optional string.

```json
{
  "suite_id": 1,
  "name": "Token",
  "parent_id": 2,
  "description": "Token expiry cases"
}
```

Response: same shape as `get_section`.

    tr api add_section/1 --data body.json --commit

## parent_id / depth and paths

`parent_id` is null and `depth` is 0 for root sections.
A child points `parent_id` at its parent and has `depth >= 1`.

To build a path like `Parent/Child` (cache `section` front matter):

1. Start at the case's `section_id`.
2. Collect `name`, then follow `parent_id` until null.
3. Reverse the names and join with `/`.

Example: Auth (`id=2`, `parent_id=null`) + Token (`id=12`,
`parent_id=2`) yields `Auth/Token`.
