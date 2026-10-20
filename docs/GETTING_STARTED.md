# Guided use and recovery

Run `python3 start.py` from the repository. The menu works without installing research packages. `stock-pilot` with no command also opens it after package installation.

## First session

1. Open Setup check. Missing items are shown with the relevant installation commands.
2. Try the offline demo. It cannot change your paper balance or positions.
3. Review the portfolio. A fresh guided account has demonstration cash and paused entries.
4. Talk to Manager for portfolio/pause/resume questions. Local AI explanations are enabled only when the configured model is detected; otherwise explicit requests still work.

Type `back` in chat to return. Ctrl+C or EOF closes the console without claiming to stop any separately running processes. Most action errors return you to the menu instead of displaying a traceback.

## Guided research

Choose Advanced workflows, then Research a stock. Bare symbols are treated as NSE symbols and receive `.NS`; use `.BO` explicitly for BSE. Enter an analysis date or accept today's India date. Reports are stored in the guided profile's reports folder and become available to Manager's `why SYMBOL` request.

A report is an upstream model opinion, not an execution instruction or independently verified research. A reviewed source manifest, cost schedule, policy and proposal are still needed to pass the existing agency/assessment gate. Neither this menu nor the agency coordinator submits a purchase.

## Profile settings

The default guided profile is `data/paper/settings.json`. Its mode must stay `paper`. `limits` has the same schema as the existing limits JSON. The initial values are explicitly demonstration settings. `personal_policy_reviewed` controls the menu label; it does not independently verify policy or enable trading.

Optional `costs_file` and `instruments_file` refer to reviewed JSON files, resolved relative to the profile directory unless absolute paths are supplied. No API keys are copied into the profile. Model settings live in the profile's `research-config.json` after the first guided research request. Do not run multiple Qwen jobs in parallel on the 8 GB target until resource use has been measured.

A recovered or legacy database can be selected with `python3 start.py --db PATH`. The guided profile supplies its limits/configuration; a database backup alone does not preserve that configuration. Reconcile the recovered account and restore its matching reviewed configuration before clearing its entry block.

## Separate monitoring and watchdog

The menu shows the exact paths for your selected account. For the default guided account, run these in separate terminals from the repository:

```bash
python -m stock_pilot.cli --db data/paper/paper.db watch --source yahoo --interval 30
python -m stock_pilot.cli --db data/paper/paper.db watchdog --alerts data/paper/alerts.jsonl
```

The quote collector must be installed. A file feed can be used instead; see the command reference. Freshness limits remain enforced, including while the market is closed or public quotes are delayed. Invalid or unavailable data is not converted into a fictitious sell fill.

The monitor writes a heartbeat before/after quote work. The watchdog opens the existing database without creating a missing one, checks heartbeat age and health for held positions, and pauses new paper entries on critical conditions when possible. It logs state changes locally. If there are no open positions, health is IDLE. Fresh in-progress collection is BUSY, not a confirmed healthy quote feed. If the process stops, its heartbeat expires. The watchdog must itself be running separately; neither component can send an alert after a whole-host power/network failure from that host.

A one-cycle diagnostic is available with `watchdog --cycles 1`. After a finite `watch --cycles` run ends, the monitor heartbeat says stopped; the system does not pretend a background monitor remains active.

## Entry controls

Use Safety and backups in the menu, or select the correct existing database explicitly:

```bash
python -m stock_pilot.cli --db data/paper/paper.db emergency-stop --reason "Review monitoring outage"
python -m stock_pilot.cli --db data/paper/paper.db unlock-entries --reason "Portfolio and monitoring reviewed"
python -m stock_pilot.cli --db data/paper/paper.db resume
```

Unlocking leaves the account paused. A watchdog/feed issue can pause it again. A pause or emergency block never cancels an existing stop or turns off exit checks. Protection still depends on receiving usable prices and on the monitor running; broker-native protective orders remain unimplemented pending broker selection.

## Verified backup and restore

The menu generates a unique backup name. Advanced commands require explicit destinations:

```bash
python -m stock_pilot.cli --db data/paper/paper.db backup --output data/paper/backups/session.db
python -m stock_pilot.cli restore data/paper/backups/session.db --output data/paper/recoveries/recovered.db
```

Keep the `.db` and its `.db.json` manifest together. Restore validates the checksum, database and journal. Existing output files are refused. The recovered copy starts paused with an entry lock, and the original database remains unchanged. Use a new destination for every recovery attempt.

These are local consistency-checked snapshots, not independently authenticated or encrypted backups. They include database checkpoints, account state and journal, but not external source snapshots, reports, settings or model files. Keep those alongside your own protected recovery archive. Test restoration before relying on it.

## Current boundaries

Paper-only operation is enforced in the console/CLI; there is no live-order function to enable. Reliable market-data access, actual Qwen quality and target-server performance still need validation. Broker selection, authenticated broker connectivity, personal capital/loss limits, broker-hosted protection and corporate-action handling remain future live-readiness work. This update does not claim those are implemented.
