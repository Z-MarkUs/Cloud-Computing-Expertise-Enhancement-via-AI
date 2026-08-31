# Security policy

## Supported version

Security fixes are applied to the latest commit on `main`.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not open a public
issue containing credentials, exploit details, private data, or a working proof of concept.

Include the affected endpoint or component, reproduction steps, impact, and any suggested
mitigation. You should receive an acknowledgement within five business days.

## Deployment boundary

The default `demo` mode uses bundled public educational content and makes no paid cloud calls.
An Azure deployment is an operator-controlled configuration and must add authentication,
network restrictions, managed identity, budget alerts, and rate limits appropriate to its users.
The included infrastructure is a secure starting point, not a compliance certification.

Never commit `.env` files, Azure keys, connection strings, tokens, or exported private corpora.
Rotate a credential immediately if it appears in a log, screenshot, issue, or commit.
