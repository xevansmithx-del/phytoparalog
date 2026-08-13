# Security policy

## Supported versions

Security fixes are applied to the latest released minor version. Before the first stable release,
only the latest alpha release is supported.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, leaked credential, private biological
record, or path disclosure. Use GitHub's private vulnerability reporting feature on this
repository. Include the affected version, a minimal reproduction, expected impact, and any safe
mitigation you have identified.

The maintainers aim to acknowledge a report within seven days and provide a remediation plan or
status update within fourteen days. Timelines may change with severity and reproducibility.

## Data and execution model

PhytoParalog runs locally. It does not upload studies, sequences, receipts, or capsules. The core
has no network dependency. The optional ToolUniverse integration also performs local compilation;
it does not turn local evidence into a remote service.

Treat input studies and output capsules as potentially sensitive. Review them before sharing,
avoid embedding credentials in receipts, and run `python scripts/privacy_scan.py .` before a
public release. The scanner rejects symbolic links and binary content rather than following or
silently exempting them.

PhytoParalog validates structure and provenance commitments; it does not make a dataset safe to
publish, establish rights to share it, or remove controlled metadata.
