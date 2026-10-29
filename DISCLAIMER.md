# Disclaimer and legal notice

**Status:** personal research record, last reviewed 2026-10-29.
**Applies to:** this repository and every file in it, including earlier revisions.

This is not legal advice. It is a plain statement of what this repository is, what it is
not, and the terms on which it is published. If you need legal advice, consult a lawyer
in your jurisdiction.

---

## 1. Purpose

This repository is a personal engineering notebook. It records reverse-engineering
analysis of hardware I own, performed to understand how the platform boots and how its
software is put together, and to document that work in a form other researchers can
check. The intended audience is people studying console platform security, firmware
formats and browser-engine hardening.

## 2. This repository is not a jailbreak

It does not contain, and will not contain:

- Sony firmware, update packages (PUP), decrypted images, or extracted SELF/ELF components;
- decryption keys, key-derivation material, or signing material of any kind;
- a bootable image, a flashed loader, or anything that modifies a console;
- a kernel exploit, privilege-escalation chain, or post-exploitation payload;
- a loader payload, game save file, or other artefact that grants code execution on a retail console;
- step-by-step instructions whose purpose is to obtain unauthorised access to a console,
  a PSN account, or paid content.

What it does contain is analysis: notes, parsers, probe pages, harnesses, and measurement
data. Where a finding is only a hypothesis, it is labelled as one. Several documents
describe vulnerability *classes* and the reasoning used to rule candidates in or out;
that is security research writing, not a working exploit.

Nothing here has been tested against, or is intended for, a device I do not own.

## 3. Hardware, accounts and authorisation

- All console work is performed on hardware I own, with my own PSN account, on my own network.
- The console is kept off Sony's update and telemetry estate by local DNS policy. No attempt
  is made to reach PSN services in a modified state, to obtain paid content without payment,
  or to interfere with another person's device, account or network.
- No content here is intended for use against a device you are not authorised to test.
  Running any of it against someone else's console is outside the scope of this project and
  is not authorised by anything written here.

## 4. No circumvention service, no trafficking

Nothing in this repository is offered, marketed, or provided as a service for circumventing
a technological protection measure, and nothing here is sold, licensed, or distributed as a
circumvention product. The repository exists to publish research results and to let others
reproduce the analysis, not to enable circumvention.

## 5. Third-party material

Some files quote or derive from openly published third-party sources — chiefly WebKit
source, including the WebKit source Sony publishes under its own open-source obligations.
Those components remain under their original licences, listed in [NOTICE.md](NOTICE.md).
Third-party code that could not be redistributed under a compatible licence has been
removed from the published tree and is referenced by link only.

No Sony proprietary code, binary, key, or firmware image is redistributed here. Quotations
from Sony's published open-source drops are limited to what those licences permit.

## 6. Personal data

The repository contains no console serial numbers, PSN IDs, account names, MAC addresses,
public IP addresses or other identifiers of people or devices. Local network addresses in
notes and scripts are placeholders (`<console-ip>`, `<host-ip>`, and so on). Captured logs
that contained hardware addresses from third parties were removed rather than republished.

## 7. Legal framework — informational only

Different jurisdictions treat circumvention differently, and nothing below is a conclusion
about this repository's status in any of them.

**United States.** 17 U.S.C. §1201(a)(1)(A) prohibits circumventing a technological measure
that controls access to a protected work; §1201(a)(2) and §1201(b)(1) prohibit trafficking in
technology primarily designed or marketed for circumvention. The security-testing exemption in
§1201(j) applies only to §1201(a)(1)(A) — it is not a defence to the trafficking provisions.
That asymmetry is the reason this repository publishes analysis and measurements rather than
working tooling: a public repository that shipped functional circumvention code would be
relying on an exemption that does not cover distribution.

**Canada.** Copyright Act s.41.1(1) prohibits circumventing a technological protection measure,
offering circumvention services to the public, and manufacturing, importing, distributing or
offering circumvention technology. Narrow, condition-bound exceptions exist — for example
s.41.12 (interoperability) and s.41.13 (encryption research) — and each requires specific
conditions to be met. They are not relied on here, because nothing circumvention-capable is
distributed.

**Elsewhere.** Other jurisdictions have their own rules, some stricter. No representation is
made that any particular use of this material is lawful where you are.

## 8. No warranty, no support, no legal advice

Everything here is provided "as is", without warranty of any kind, express or implied,
including fitness for any particular purpose. Firmware analysis is provisional by nature:
findings are tied to a specific build and can be wrong, incomplete, or stale. Nothing here
is legal advice, and nothing here is a statement of any employer's position — the views are
my own and do not represent any current or former employer.

## 9. Corrections and takedown

If you are a rights holder and believe something here infringes your rights, open an issue on
this repository or contact the owner through GitHub and identify the file and the concern. I
will review it and remove or amend the material promptly. Corrections of technical claims are
equally welcome; findings are dated and superseded rather than silently rewritten.
