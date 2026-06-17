# strutil 2.0.0

## Breaking changes

- `split_fields(text, delimiter=...)` renamed to `parse_fields(text, *, delim=...)`.
- The delimiter argument is keyword-only and renamed to `delim`.

## Migration

Replace imports of `split_fields` with `parse_fields` and pass `delim=` instead of `delimiter=`.
