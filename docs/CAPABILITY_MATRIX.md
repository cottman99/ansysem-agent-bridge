# Capability, mechanism, and evidence matrix

| User task | Bridge mechanism | Alpha status | Boundary |
| --- | --- | --- | --- |
| Discover configured AEDT installations | Environment and explicit local configuration | Implemented | Never silently chooses among multiple installations |
| Verify an HFSS 3D Layout project bundle | `.aedt` hash plus `.aedb/edb.def` presence | Implemented | Does not prove design or solver correctness |
| Inspect current capability state | Versioned capability descriptors | Implemented | Static declaration and dynamic availability remain separate |
| Capture a compact host/project snapshot | Revision-aware runtime snapshot | Implemented | Host snapshot is not live AEDT proof |
| Read live HFSS 3D Layout identity | Bounded PyAEDT live probe | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 on Linux | Opens only an explicit complete project bundle and closes only its own new session |
| Export an HFSS 3D Layout image | Native editor `ZoomToFit` and `ExportImage` behind a bounded adapter | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 on Linux | Image is presentation evidence only |
| Query local version-matched documentation | Configured private corpus and bounded source references | Implemented | Documentation is not redistributed or treated as runtime proof |
| Create or repair arbitrary ports, stackups, geometry, setups, or solves | Not claimed in the first alpha | Not claimed | Promote only after a typed semantic operation and solver-side validation exist |
| General GUI automation | Not claimed | Not claimed | No blind coordinate or screenshot-only success path |

Unit tests protect public contracts and failure behavior. Real AEDT validation
is reported separately and does not broaden untested product claims.

`ValidateDesign` raised a PyAEDT gRPC API error in the Linux acceptance. The
Bridge preserves prior live readback and reports `attention_required`; it does
not claim that validation passed. See the
[sanitized acceptance record](VALIDATION_AEDT_2026R1_LINUX.md).
