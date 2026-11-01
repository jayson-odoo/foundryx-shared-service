# AutoCount SQL Server connectivity (VPN + host relay)

How the production backend reaches an AutoCount Microsoft SQL Server on a private LAN. Host names, addresses, network ids and the host-side unit are kept in private ops notes.

## Topology

```
backend / celery container
   -> host.docker.internal:<sql-port>   (the pinned compose-network gateway)
   -> relay service on the host
   -> VPN network <vpn-network-id>
   -> <sql-host>:<sql-port>             (SQL Server, named instance <instance>)
```

- Named instances use dynamic ports: always configure host and explicit port.
- Never use `host\instance` in the integration: SQL Browser does not traverse the tunnel, and the driver URL path mangles `host\instance:port`.
- The Windows side is not ours. VPN members are authorized by the network admin.
- Containers hand the connection to the host, which reaches the SQL Server over the VPN.

## What is pinned in this repo

`docker-compose.yml`:
- `foundryx_ss_network` has a fixed `ipam` subnet and gateway, so a `docker compose down` recreates the network with the same gateway.
- `x-backend-base` adds `extra_hosts: host.docker.internal:host-gateway`, so the integration's Host field is a name, never a Docker-assigned IP.

## Host-side unit

A systemd unit on the server runs the relay, bound to the gateway only, and restarts on its own. Its definition is in private ops notes.

## Integration config

| Where | Host | Port |
|---|---|---|
| production | `host.docker.internal` | `<sql-port>` |
| local dev on the VPN | `<sql-host>` | `<sql-port>` |

Provider `sql_database` (type `erp`), read-only login.

## Runbook

- After a host reboot: the VPN and relay units come back alone. Run Test connection once.
- After `docker compose down` + `up`: the network is recreated with the same gateway and the relay reconnects by itself. Nothing to edit.
- Health: check the relay unit's status and the VPN client's network list.
- Container-side probe: `docker exec <backend-container> python -c "import socket;socket.create_connection(('host.docker.internal',<sql-port>),5);print('ok')"`
