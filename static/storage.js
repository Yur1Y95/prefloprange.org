// ============================================================================
// DEPRECATED — this file no longer ships.
//
// Previously contained `UserStorage` — a localStorage-backed range cache used
// by Editor/Visualizer/Drill. It caused the P-001 bug (edits saved here
// instead of the server's data/ folder, so changes never reached the
// Visualizer — and duplicates appeared in file lists with "★" suffix).
//
// Removed: 2026-05-28. The editor is the configurator of your own server-side
// JSON. All persistence goes through `POST /api/ranges/save` now.
// See docs/problems.md P-001 for the full backstory.
//
// File kept (rather than deleted) because the sandbox can't remove it.
// The <script> tag in index.html that loaded it is gone — this code never
// runs.
// ============================================================================
