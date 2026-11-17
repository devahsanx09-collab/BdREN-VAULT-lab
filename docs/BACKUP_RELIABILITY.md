# Backup reliability: patient SSH, second pass and retry queue

Design spec for how VAULT takes a backup when devices are slow, busy or offline.
Goal: **every reachable device ends up with a complete backup**. Speed is secondary.

## The problem

Seen on a real run of 82 devices: 3–6 failed ("read timed out", "login failed") and the same devices
succeeded when started again a little later. Causes:

1. **One fixed timer.** A device had to deliver its whole configuration within 300 s, however it behaved.
   A slow but working device was cut off; a dead session held its worker for the full 300 s.
2. **Login bursts.** Up to 50 SSH logins started in the same second. Busy devices, full VTY lines and the
   AAA / RADIUS server behind the devices then answer late or reject the login.
3. **No automatic second try.** Only ping-offline devices of *scheduled* runs were retried; manual runs and
   temporary SSH failures waited for a person to press Retry.

## The design

### 1. Patient SSH session (apps/backups/engine.py)
- **Activity timer instead of a stopwatch.** While the device keeps sending data, VAULT keeps waiting.
  It gives up only when the device has been **silent** for `DBMS_COMMAND_IDLE_SECONDS` (default 180 s).
- **Safety ceiling** per device: `DBMS_COMMAND_TIMEOUT` (default 3600 s = 1 hour; was 300 s).
- **Patient login.** The SSH connect / login timeout is `DBMS_SSH_TIMEOUT` (30 s); a login that timed out is
  tried once more with **double** the time (a slow AAA login gets 60 s).
- **Paced logins.** New SSH logins start at most every `DBMS_LOGIN_SPACING` seconds (default 0.5 s), so 82
  devices do not knock on their AAA server at the same moment. When the parallel-session limit is the
  bottleneck (large inventories) this costs nothing.
- Nothing about saving changes: a backup is still written only when complete (all-or-nothing).

### 2. Every failure gets a kind
| Kind | Examples | What happens |
|---|---|---|
| `offline` | no ping reply | retry queue: checked by ping every minute; SSH backup as soon as it answers |
| `transient` | connect / read timeout, device silent, session closed, SSH banner error | second pass, then retry queue with back-off |
| `auth` | login rejected | second pass only once more (an overloaded AAA can reject); then retry queue **once** — never more, so no account lock-out |
| `permanent` | host key changed, command rejected, no privilege, wrong address, old SSH algorithms | no automatic retry: needs a person; shown in Backup Jobs |

### 3. Second pass inside the same job (apps/backups/jobs.py)
After the run, devices whose failure was `transient` or `auth` are tried **again in the same job**:
after a cool-down of `DBMS_RETRY_COOLDOWN` seconds (default 60), with at most `DBMS_RETRY_PASS_WORKERS`
(default 3) parallel sessions and 3 s between logins. A device that succeeds replaces its failed row
("succeeded on the automatic second try"). The job chip shows "Retrying N devices". Stop backup works
during the cool-down and the second pass. `DBMS_RETRY_PASS=0` turns the pass off.

### 4. Background retry queue (apps/scheduling/services.py)
Every job, manual or automatic, ends by updating the queue (`pending_backup_device_ids` + `retry_info`):
- success → leaves the queue; permanent failure → leaves the queue (a person must act);
- `offline` → waits; pinged every `DBMS_RECONNECT_RETRY_SECONDS` (60 s); backed up when it answers;
  dropped after `DBMS_RETRY_MAX_DAYS` (7) days;
- `transient` → retried after 10 min, 30 min and 2 h, then dropped;
- `auth` → retried once after 15 min, then dropped;
- devices a crashed job never reached → retried like `offline`.
The scheduler (every 30 s) pings only the devices that are due and starts one "retry-after-reconnect" job
for those that answer. New devices' first backups no longer wait behind this queue.

### 5. Visible to the operator
Backup Jobs shows **Waiting to retry** (device, why, since when, attempts, next check), failure messages say
what VAULT will do next, and the job chip shows the second pass.

## Settings (`/opt/dbms/.env`, then `sudo systemctl restart dbms`)
| Variable | Default | Meaning |
|---|---|---|
| `DBMS_COMMAND_IDLE_SECONDS` | 180 | give up when the device sends nothing for this long |
| `DBMS_COMMAND_TIMEOUT` | 3600 | longest time for one device's configuration (ceiling) |
| `DBMS_SSH_TIMEOUT` | 30 | SSH connect / login timeout (second try: double) |
| `DBMS_LOGIN_SPACING` | 0.5 | seconds between two new SSH logins (0 = off) |
| `DBMS_RETRY_PASS` | 1 | second pass inside the job (0 = off) |
| `DBMS_RETRY_COOLDOWN` | 60 | seconds before the second pass |
| `DBMS_RETRY_PASS_WORKERS` | 3 | parallel sessions in the second pass |
| `DBMS_RECONNECT_RETRY_SECONDS` | 60 | how often offline devices are pinged |
| `DBMS_RETRY_MAX_DAYS` | 7 | how long an offline device is waited for |

## Verification
A simulated SSH device (paramiko server in the test suite) proves: a device that sends its configuration
slowly for longer than the old 300 s-style limit is saved; a device that goes silent fails after the idle
time with a clear message; a fast device is unaffected; the second pass and the queue rules work.
