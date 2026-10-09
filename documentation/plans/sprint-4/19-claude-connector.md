# 19 - Claude connector module (SS-CONNECTOR)

Status: **Plan stage - behaviour card under owner review (crew-ask on the PR). No code yet.**

Scope (owner decisions 9 Oct): a `connector` module in `service_backend/modules/` that owns the
claude.ai remote-MCP connector for every product (OAuth authorization server + MCP endpoint per
product, grants, audit, response caps). Each product only exposes a signed read-only tool/data API.

The behaviour card, UAC and plan land in this file + `19-claude-connector-acceptance-criteria.md`
once the card is agreed.
