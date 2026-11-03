# Archive import

## Provenance and scope

Source: `cineticfinal.zip`, provided by the project author. SHA-256:

```text
1a5c7fb45e66a744ce81d5ea4e62ca115e391225d498d25d7c4ac99b149a68fe
```

The ZIP contains 18,965 entries, including installed Python and JavaScript dependencies. It contains no original Git history. The existing repository's initial README commit is retained, and new commits group related parts of the snapshot using current commit dates.

The import preserves the contents of `src/`, `frontend/` source/configuration/lockfile, and `templates/` byte for byte. Original `courses.json` and `recordings/` data is relocated to `examples/`, also byte for byte. Root `config.json` is preserved but unused by the current application.

Excluded from Git:

- `.venv/` and `venv/`: machine-specific Python environments, including ARM binaries.
- `frontend/node_modules/`: installed dependencies, including platform-specific binaries.
- `static/` and `static-backups/`: compiled frontend assets and older build snapshots.
- Python bytecode and caches.
- Local course data and recordings, except the preserved example.
- The original ZIP, which remains available locally.

New repository material consists of this documentation, the README, ignore/attribute rules, recovered Python version pins, software tests, a local check script, and a GitHub Actions workflow. No dependency modernization or application refactor is part of the import.

## Commit boundaries

1. Repository hygiene and recovered Python dependencies.
2. Robot configuration, shared state, and JSON persistence.
3. UDP command encoding and telemetry reception.
4. Physical controller input, servo routing, and lighting fanout.
5. Flask application, browser shell, robot assignment, and live state stream.
6. Course metadata management, loading, and editor initialization.
7. Recording segments, deleting moves, and saving courses.
8. Individual-move and complete-course playback with status and stop operations.
9. Frontend build setup, design system, shared hooks, and application shell.
10. Live controller display and its browser route.
11. Course dashboard and its browser route.
12. Choreography timeline editor and its browser route.
13. Original course and telemetry recording as examples.
14. Hardware-free tests and the local check script.
15. GitHub Actions calling the shared check script.
16. Project overview, architecture, production credits, sources, and import record.

Dependencies precede their callers. Device-specific drive, servo, and lighting behavior stays together in the controller loop because it shares one input/sending lifecycle. The Python state and persistence modules precede networking and HTTP handlers; frontend shared modules precede the screens that use them. Tests and their local runner arrive before the hosted workflow.

The large Flask file is introduced incrementally by complete route functions. Each HTTP feature commit adds its related handlers together; the frontend shell adds routes with their screens. Intermediate revisions intentionally expose only the features introduced so far. The final application source and manifests match the archive byte for byte.

These boundaries explain the final system. They are not a reconstructed day-by-day development history. Some intermediate imports are libraries or partial application shells, rather than a complete robot control system. The complete application is assembled by the example-data commit.

## Local verification

Verified on 3 November 2026 with Python 3.12.3:

- The complete `bash scripts/check.sh` run passed with installed dependencies: seven backend tests, Python compilation, and the Vite 5.4.19 production build.
- Python dependency consistency passed `.venv/bin/python -m pip check`; Flask 3.1.1 was loaded from the local Python 3.12 virtual environment.
- Python compilation passed for `src/` and `tests/`.
- Imported application/frontend/template files and example data match their archived bytes.
- The revised 16-commit sequence was checked at intermediate revisions: Python source parses, each of the four Flask handler stages instantiates its app factory, and local frontend imports resolve after each screen is introduced. These structural checks are not a substitute for a frontend build.
- A targeted credential-pattern scan of the extracted project files found no matches for private keys, GitHub tokens, AWS access keys, or obvious assigned credentials. This is a limited scan, not a guarantee that every kind of secret is absent.

Initial backend checks used dependencies recovered from the ZIP via a scratch `PYTHONPATH`, because package downloads were blocked by the session network restrictions. After the owner installed dependencies, the full check script was rerun normally using the local virtual environment and frontend dependencies, and passed. The owner reported running the installation commands; their terminal output was not independently observed. Archived ARM dependency binaries were not used for the successful frontend build.

**Not verified here:** installation from an empty environment, browser rendering, TypeScript types, GitHub-hosted workflow execution, or physical robot/light operation. The GitHub workflow is configured to install dependencies and call the same `scripts/check.sh` entry point available locally. A passing backend check does not establish that the frontend or hardware works.

The archive has no tests or CI configuration of its own. The checks in this repository were added during import; no claim is made that they ran during the original production.
