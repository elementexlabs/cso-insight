# Security policy

cso-insight is an offline analysis package for public combined sewer overflow (CSO) reports. It runs no hosted service, holds no credentials and processes no personal information.

## Reporting a vulnerability

Please email info@elementexlabs.ca with "cso-insight security" in the subject line. Describe the issue, the affected file or command, and how to reproduce it. Please do not open a public issue for a security problem.

We aim to acknowledge a report within five business days and to tell you what we will do about it. A confirmed issue is fixed in the next release, and the fix is noted in CHANGELOG.md. We do not run a bug bounty.

## Supported versions

Only the latest commit on the main branch is supported.

## Scope

In scope: the code in src/ and scripts/, and the pinned dependency set in requirements-lock.txt. Please report a vulnerability in a third-party package to that package's maintainers as well.
