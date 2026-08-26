# Contributing

Keep changes small, testable, and within the public product boundary. Do not
commit customer data, vendor documentation, private indexes, credentials,
private infrastructure paths, or generated AEDT projects.

Before opening a pull request, run:

```text
python -m pytest
python -m build
```

New runtime claims require a version-specific capability probe, a bounded
semantic operation, independent readback, and an update to the capability
matrix. A failed exploratory script is not evidence that an AEDT capability is
absent.
