# AnsysEM Agent Bridge

AnsysEM Agent Bridge is an unofficial, local-first documentation and
automation bridge for Ansys Electronics Desktop (AEDT). It gives a
general-purpose Agent a stable CLI for exact target identity, capability
discovery, project-bundle checks, bounded live HFSS 3D Layout readback, local
documentation retrieval, and evidence-bearing artifacts.

> Alpha software. It is not affiliated with or endorsed by Ansys, Inc. Ansys,
> AEDT, HFSS, Maxwell, Q3D, and related names are trademarks of their respective
> owners.

![Abstract visualization of an Agent connected through a bounded local bridge to an electromagnetic design environment](docs/assets/ansysem-agent-bridge-hero.png)

## Why a Bridge

EDA automation fails when an Agent must guess the active project, API version,
object-ID domain, execution lane, or whether a visible result reached the
solver. The Bridge turns those implicit assumptions into machine-readable
contracts:

```text
User goal
   ↓
Agent + two public Skills
   ↓
target identity + capability state + bounded operation
   ↓
PyAEDT / PyEDB / native AEDT adapter
   ↓
readback + artifact hash + explicit evidence boundary
```

The Bridge owns runtime facts and bounded tool access. A future Harness may
compose it with workflows, authorization, engineering memory, and promotion
policy without duplicating the Bridge transport or AEDT adapters.

## Current alpha surface

- explicit AEDT installation configuration and discovery;
- `.aedt` plus `.aedb/edb.def` project-bundle verification;
- revision-aware compact runtime snapshots;
- capability descriptors separating declared, compatible, available, healthy,
  and authorized state;
- bounded live HFSS 3D Layout identity readback through PyAEDT;
- native `ZoomToFit` plus `ExportImage` behind a checked image-export command;
- private local documentation query/get commands;
- two mutually routing public Skills;
- conflict-safe Skill install, status, and uninstall.

See the [capability matrix](docs/CAPABILITY_MATRIX.md) for exact claims and stop
rules.

## Install

```console
pipx install git+https://github.com/cottman99/ansysem-agent-bridge.git
ansysem-agent --pretty doctor
```

Configure one explicit installation. Documentation is optional and remains on
the AEDT host:

```console
ansysem-agent --pretty setup \
  --aedt-root /path/to/AnsysEM/v261 \
  --version 2026.1 \
  --docs-root /path/to/private/local/docs
```

`setup` installs two small Skills by default:

- `ansysem-agent-bridge` for setup, exact target identity, runtime state,
  bounded operation, artifacts, and safe lifecycle;
- `ansysem-kb-docs` for version-matched local documentation without launching
  or mutating AEDT.

## Inspect before live work

```console
ansysem-agent --pretty instances list
ansysem-agent --pretty project inspect --project /path/to/model.aedt
ansysem-agent --pretty capabilities --project /path/to/model.aedt
ansysem-agent --pretty runtime-snapshot \
  --project /path/to/model.aedt --version 2026.1 --display :4.0
```

Suppress unchanged bounded state with the returned revision:

```console
ansysem-agent runtime-snapshot \
  --project /path/to/model.aedt \
  --since-revision <sha256>
```

## Live HFSS 3D Layout gate

Run the CLI on the AEDT host. A new session is closed only when the command
created it:

```console
ansysem-agent --pretty runtime-snapshot \
  --live --project /path/to/model.aedt --version 2026.1 --display :4.0
```

Export a bounded visual artifact through the native editor API:

```console
ansysem-agent --pretty layout export-image \
  --project /path/to/model.aedt \
  --version 2026.1 \
  --output /path/to/new-layout-view.png
```

The image proves only that AEDT exported the named live editor state. It does
not prove electrical correctness, solver input, mesh, convergence, or results.

## Documentation

```console
ansysem-agent --pretty docs status
ansysem-agent --pretty docs query "AddRefPortUsingEdges" \
  --module hfss_3d_layout --limit 6
ansysem-agent --pretty docs get <source-ref> \
  --focus "AddRefPortUsingEdges" --max-chars 4000
```

The package does not contain or redistribute Ansys documentation. Queries use
a corpus configured on the user's machine.

## Remote topology

Run `ansysem-agent` on the AEDT machine through SSH. Keep AEDT automation,
projects, documentation, and artifacts on that host unless the user explicitly
exports a sanitized result. A public remote Bridge protocol and multi-client
session lease service are not claimed.

## Safety boundary

- no implicit newest-version selection;
- no foreground-window guessing;
- no `.aedt`-only claim for HFSS 3D Layout bundles;
- no arbitrary Python execution in the default public interface;
- no blind GUI coordinates or screenshot-only success;
- no force-kill or silent discard of modified work;
- no claim that documentation, a visible object, or an exported image proves a
  successful solve.

See [the execution context contract](docs/EXECUTION_CONTEXT_CONTRACT.md),
[architecture](docs/ARCHITECTURE.md), [release contract](docs/RELEASE_CONTRACT.md),
[sanitized AEDT 2026 R1 Linux acceptance](docs/VALIDATION_AEDT_2026R1_LINUX.md),
and [security policy](SECURITY.md).

## Development

```console
python -m pip install -e ".[test]"
python -m pytest
```

The public repository contains synthetic tests only. Customer projects and
vendor documentation are intentionally excluded.
