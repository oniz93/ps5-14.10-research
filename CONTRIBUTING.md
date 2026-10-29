# Contributing

Contributions that improve the accuracy of the analysis are welcome. This repository is a
research record, not a distribution channel, and the rules below exist to keep it that way.

## What is welcome

- Corrections to technical claims, with the evidence and the exact build it was measured on.
- Negative results. "This did not reproduce, here is the run" is as valuable as a positive.
- Source-level analysis of code that ships on the console, with the file and the line cited.
- Tooling that is read-only: parsers, harnesses, measurement scripts, format validators.
- Better labelling of what is verified, inferred, or unverified.

## What will be rejected

- Sony firmware, update packages, decrypted images, or extracted binaries.
- Keys, key-derivation material, or anything that decrypts a Sony container.
- Working exploits, payloads, loaders, save files, or anything that grants code execution on
  a retail console.
- Instructions whose purpose is to obtain unauthorised access to a device, account, or paid
  content, or to interfere with someone else's console or network.
- Console serial numbers, PSN IDs, MAC addresses, public IPs, hostnames, or personal data.
- Third-party code without a clear licence that permits redistribution. Link to it instead.
- Unlabelled speculation presented as a finding.

## Evidence standard

Each claim should carry: the target build, the method, what was expected, what was observed,
how many times it was run, and what remains unknown. A pattern match is not a vulnerability.
A crash is not an exploit. A hypothesis is not a result. If a conclusion depends on a tool's
output, say which tool and which version.

## Licensing of contributions

By contributing you agree that your contribution is your own work, that you have the right to
submit it, and that it may be published under the terms in [LICENSE](LICENSE). Third-party
material must be identified with its licence in [NOTICE.md](NOTICE.md).

## Reporting a rights issue

See section 9 of [DISCLAIMER.md](DISCLAIMER.md). Rights-holder requests are actioned first.
