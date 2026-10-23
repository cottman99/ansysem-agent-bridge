# Copy a node or canvas selection into an Agent conversation

Linux AEDT 2026 R1, HFSS 3D Layout, synthetic `ContextDemoLinux` project.

| User action | Observed result |
| --- | --- |
| Right-click the design and copy | One Agent menu item; plaintext context identifies `ContextDemo` and the exact live session. |
| Right-click a setup and choose from its branch | The picker lists `ContextSetup_A` and `ContextSetup_B`; selecting B copies its full Analysis hierarchy. |
| Select `Patch_B`, then click Automation / Copy Agent Context | Plaintext context contains `Patch_B`, `Layout`, and the canvas selection hierarchy. |
| Hand each context to a fresh Runtime MCP client | Native readback confirms the project, design, selected object or selected setup. |

Installation uses whitespace-free toolkit directories with readable button
labels. The previous paths containing spaces caused Linux AEDT to omit the
buttons and ignore Toolkit-menu launches. Changing only the script paths in a
controlled comparison restored all three buttons; the corrected installer was
then exercised in the live application.

Project-tree menus copy nodes only. The documented custom XML right-click
interface covers the project tree; a supported canvas right-click registration
was not established. Canvas copying uses the Automation tab.

Local checks: 176 Ansys tests, Ruff lint/format, clean wheel installation and CLI
startup. Installer tests cover repair, profile routing, copied-file integrity,
button retargeting, preservation, and uninstall registration. Runtime and ADS
are tested in their independent repositories. Release CI checks supported
Python/platform combinations separately.

This acceptance verifies context handoff and native identity readback. No solver
or new engineering-result claim is made. Windows AEDT was excluded from this
acceptance at the owner's request. Screenshot instructions are prepared after
the accepted actions and are not engineering-task timing.

References: [Ansys menu customization](https://ansyshelp.ansys.com/public/Views/Secured/Electronics/v252/en/Subsystems/EMIT/Content/GettingStarted/CustomizeAEDTMenus.htm)
and [official PyAEDT extensions](https://aedt.docs.pyansys.com/version/stable/User_guide/extensions.html).
