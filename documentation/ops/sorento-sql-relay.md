# Sorento AutoCount SQL Server - prod connectivity (ZeroTier + host relay)

Set up 2026-09-04. How the prod backend on `srv933531` (Hostinger, Docker) reaches the
Sorento AutoCount Microsoft SQL Server that lives on a private LAN.

## Topology

```
backend / celery container
   -> host.docker.internal:59773      (= 172.21.0.1, the pinned compose-network gateway)
   -> socat relay on the host          (sorento-sql-relay.service)
   -> ZeroTier network 565799d8f64453bc ("Sorento_Foundryx_VPN", host member 192.168.196.248)
   -> 192.168.196.185:59773            (SQL Server, named instance E2016)
```

- The SQL Server host runs two instances: `A2006` on TCP 50102 and `E2016` on TCP **59773**.
  Nothing listens on 1433. Named instances use dynamic ports - always configure host + explicit port.
- Never use `host\instance` in the integration: SQL Browser (UDP 1434) does not traverse the tunnel,
  and the pymssql URL path mangles `host\instance:port`.
- The Windows side is NOT ours. ZeroTier members are authorized by the network admin.
- The relay exists because containers could not route to the ZeroTier subnet even with the
  forward chain open, and the host's INPUT firewall drops bridge -> host traffic by default.
  The host itself reaches the SQL Server fine, so containers hand the connection to the host.

## What is pinned in this repo

`docker-compose.yml`:
- `foundryx_ss_network` has a fixed `ipam` subnet `172.21.0.0/16`, gateway `172.21.0.1`.
  A `docker compose down` therefore recreates the network with the SAME gateway.
- `x-backend-base` adds `extra_hosts: host.docker.internal:host-gateway`, so the integration's
  Host field is a NAME (`host.docker.internal`), never a Docker-assigned IP.

## Host-side unit (not in the repo - lives on the server)

`/etc/systemd/system/sorento-sql-relay.service`:

```ini
[Unit]
Description=Relay Docker bridge -> Sorento SQL Server over ZeroTier
After=network-online.target zerotier-one.service docker.service
Wants=network-online.target

[Service]
# Firewall rule keyed on the PINNED subnet + gateway, not the bridge interface name
# (br-<id> changes on network recreate; the subnet does not). Idempotent.
ExecStartPre=/bin/sh -c 'iptables -C INPUT -s 172.21.0.0/16 -d 172.21.0.1 -p tcp --dport 59773 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -s 172.21.0.0/16 -d 172.21.0.1 -p tcp --dport 59773 -j ACCEPT'
ExecStart=/usr/bin/socat TCP-LISTEN:59773,bind=172.21.0.1,fork,reuseaddr TCP:192.168.196.185:59773
# bind fails while the compose network is absent (mid-recreate) - keep retrying.
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Bound to the gateway only - nothing is exposed on the public interface.

## Integration config

| Where | Host | Port |
|---|---|---|
| prod (`chat.foundryx.my`) | `host.docker.internal` | `59773` |
| local dev (Mac on the ZeroTier network) | `192.168.196.185` | `59773` |

Provider `sql_database` (type `erp`), database `AED_SORENTO`, read-only login.

## Runbook

- After a host reboot: ZeroTier + relay are enabled units, come back alone. Run Test connection once.
- After `docker compose down` + `up`: network recreated with the same gateway; relay reconnects
  by itself (Restart=always). Nothing to edit.
- Relay health: `systemctl status sorento-sql-relay`; ZeroTier: `sudo zerotier-cli listnetworks`
  (status must be `OK` with `192.168.196.248/24`).
- Container-side probe:
  `docker exec foundryx_ss_backend_blue python -c "import socket;socket.create_connection(('host.docker.internal',59773),5);print('ok')"`
