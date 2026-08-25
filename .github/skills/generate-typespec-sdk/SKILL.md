---
name: generate-typespec-sdk
description: "Generate and safely integrate a vendored Python SDK from TypeSpec. Use when refreshing the Azure Device Registry management SDK, changing its API version, generating from azure-rest-api-specs-pr, or validating TypeSpec Python emitter output."
---

# Generate a TypeSpec Python SDK

Use this workflow to refresh the vendored Azure Device Registry management client in
`azext_edge/edge/vendor/clients/deviceregistrymgmt`. It is designed for SDK refreshes
that retain the extension's raw-dictionary provider contract.

## Required inputs

- An explicit source repository, branch, tag, or commit.
- The TypeSpec entrypoint and target API version.
- The desired generated Python package namespace.
- The API-version migration policy: replace the shared default, or add an opt-in version.

Do not infer these values from generated output. Do not hand-edit generated SDK files.

## 1. Preflight and provenance

1. Confirm the current repository is `azure-iot-ops-cli-extension` and inspect `git status`.
   Do not overwrite unrelated edits.
2. Confirm the source repository is available and the explicit source ref resolves. Record the
   resolved commit ID in the change description.
3. Export that commit into a temporary directory with `git archive`; do not switch or modify the
   source checkout.
4. Copy every TypeSpec import required by the entrypoint. For Device Registry Management, this
   includes both:
   - `specification/deviceregistry/DeviceRegistry.Management`
   - `specification/deviceregistry/common`
5. Read the source `tspconfig.yaml` and its `package.json` before selecting generator packages.
   Treat the TypeSpec compiler, TypeSpec libraries, Azure libraries, and language emitter as one
   coherent exact-version toolchain.
6. Use an isolated temporary npm prefix. Never install TypeSpec globally, never use `latest`,
   `--force`, or `--legacy-peer-deps` to resolve dependency conflicts.
7. Invoke an explicit Node executable that satisfies every package engine requirement. Do not
   assume the `npm` launcher uses the same Node executable; verify the compiler command itself.

## 2. Generate in temporary storage

1. Create separate temporary source and output directories outside this repository.
2. Point the exported source's `node_modules` resolution at the isolated toolchain only. A stale
   source `node_modules` link can silently load a different compiler or emitter.
3. Generate a synchronous, dictionary-compatible client. For the ADR preview generation validated
   on 2026-08-25, the baseline was:
   - TypeSpec compiler, HTTP, and OpenAPI packages: `1.15.0`
   - TypeSpec REST, Versioning, Events, SSE, Streams, and XML packages: `0.85.0`
   - Azure TypeSpec packages: `0.71.0`
   - `@azure-tools/typespec-client-generator-core`: `0.71.2`
   - `@azure-tools/typespec-python`: `0.63.5`
   - `@typespec/http-client-python`: `0.36.0`
   - Node: `22.23.1`
4. Use explicit emitter options equivalent to:

   ```shell
   node <toolchain>/node_modules/@typespec/compiler/cmd/tsp.js compile \
     <source>/specification/deviceregistry/DeviceRegistry.Management/main.tsp \
     --emit @azure-tools/typespec-python \
     --option "@azure-tools/typespec-python.models-mode=none" \
     --option "@azure-tools/typespec-python.no-async=true" \
     --option "@azure-tools/typespec-python.namespace=<target-namespace>" \
     --option "@azure-tools/typespec-python.emitter-output-dir=<temporary-output>"
   ```

5. Treat compiler errors as blockers. Investigate warnings and report them; do not suppress them
   without understanding whether they affect the emitted client.

## 3. Validate generated output

1. Verify the target version in generated metadata and generated operation defaults.
2. Confirm there is no async client when synchronous generation was requested.
3. Compile generated Python with `python3 -m compileall`.
4. Import the generated package with `PYTHONPATH` pointing to the temporary output from outside
   this repository. This avoids a checked-out `azext_edge` package shadowing the generated one.
5. Compare the public client constructor and every operation surface used by extension providers.
   At minimum for ADR namespace updates, validate `namespaces.get`, `namespaces.begin_update`,
   and `namespaces.begin_create_or_replace`.
6. Inspect request builders for provider inputs. Dictionary resources must be passed as JSON rather
   than requiring generated model objects.
7. Inspect all extension references to the current client version, its operation re-exports, and
   internal generated modules. Determine whether imports need updating.

`models-mode=none` in modern emitters can generate `types.py` TypedDict declarations and a
lightweight `models/` import shim. This is acceptable only when application code remains
dictionary-based and does not instantiate generated model classes. Record that compatibility
decision in the change summary.

## 4. Integrate deliberately

1. Replace only the generated package subtree and its generated package-level exports. Preserve
   unrelated vendored clients.
2. Update `azext_edge/edge/vendor/clients/deviceregistrymgmt/__init__.py` and `operations.py` to
   expose the selected client version.
3. Update `azext_edge/edge/util/az_client.py` and API-version tests according to the chosen shared
   default or opt-in policy.
4. When changing the shared default, inspect every ADR provider and version-selection logic,
   including clone or migration code that intentionally chooses historical API versions.
5. Do not alter provider code merely to satisfy generated type annotations. Preserve raw-dictionary
   behavior unless the API contract itself requires a change.

## 5. Verify integration

1. Run focused unit tests for `az_client` and each changed ADR provider.
2. Run regression tests for namespace GET, PATCH, PUT, and any feature that uses fields introduced
   by the new API version.
3. Run integration coverage when the feature or SDK update changes live ARM requests.
4. Run a final import check against the vendored package and `git diff --check`.
5. Report source commit, exact generator versions, target API version, warnings, compatibility
   findings, tests run, and any intentionally retained historical API-version paths.

## Guardrails

- Never modify a generated SDK by hand.
- Never regenerate directly into the repository.
- Never treat a successful TypeSpec compile as sufficient validation.
- Never switch all callers to a new default API version without regression coverage.
- Keep temporary toolchains and output outside the repository.