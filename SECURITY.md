# Security Policy

## Supported versions

Security fixes target the latest public beta or the current `main` branch until a stable release process exists.

## Reporting a vulnerability

Do not open a public issue for sensitive reports.

Report privately through GitHub's private vulnerability reporting if it is enabled for this repository. If private reporting is not available, contact the repository owner through GitHub and request a private disclosure channel.

## Sensitive local data

This project can process local screenshots and stores runtime data in SQLite. Reports should avoid attaching:

- personal screenshots;
- local `data/forza.sqlite3` databases;
- logs containing filesystem paths or gamertags;
- generated model artifacts or raw model responses;
- private configuration files.

## Distribution policy

Beta packages must not bundle local user data, LM Studio model weights, private spreadsheets, screenshots, logs, SQLite databases, or development-only tools.
