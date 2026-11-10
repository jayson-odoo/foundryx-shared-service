# Issue tracker: GitHub

Engineering issues for this repository live in GitHub Issues at `jayson-odoo/foundryx-shared-service`.

Use `/opt/homebrew/bin/gh-axi` for issue, pull-request, label, and other GitHub operations. Run commands from this clone so the repository is inferred from `origin`.

## Conventions

- Create an issue with `gh-axi issue create`.
- Read an issue and its comments with `gh-axi issue view <number> --comments`.
- List issues with `gh-axi issue list` and the required state or label filters.
- Apply the mapped AFK-ready label before handing a fully specified ticket to an agent.
- UAC and plan files in `documentation/plans/` remain the source of truth. Issues are the execution queue and must link those files.
