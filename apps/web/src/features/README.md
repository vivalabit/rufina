# Feature import boundaries

`shared` is the lowest layer: it may not import `app` or any feature.

Ordinary features (`jobs`, `job-search`, `applications`, `calendar`, `profile`,
`settings`, and `activity`) may import their own files and `shared`. The sole
related-feature dependency is `applications` -> `jobs`.

`app-shell` and `dashboard` are aggregation features and may read other
features. All features may be composed by `app` but must not import `app`.

During the migration, imports from the existing `src/components` and `src/lib`
directories remain allowed. Do not add cross-feature imports as a replacement
for those legacy paths.
