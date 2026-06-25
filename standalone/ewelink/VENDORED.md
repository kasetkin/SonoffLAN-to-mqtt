# Vendored transport core

The files in this directory are a **verbatim copy** of the Home-Assistant-free
transport core from the SonoffLAN integration:

    custom_components/sonoff/core/ewelink/{__init__,base,cloud,local}.py

They are vendored here so the `standalone` package is self-contained (installable
as a wheel without the rest of the repo). `custom_components/` remains the source
of truth and is never modified for this.

## Kept identical

These files are byte-identical to their source. `camera.py` is intentionally
**excluded** — it is not imported by the collector. The lazy
`from ..devices import …` calls inside `__init__.py` stay dormant because
`standalone/registry.py` overrides `setup_devices` and `local_update`.

## Re-sync after pulling upstream changes

```bash
cp custom_components/sonoff/core/ewelink/{__init__,base,cloud,local}.py standalone/ewelink/
diff -rq standalone/ewelink custom_components/sonoff/core/ewelink   # expect: only camera.py differs
```
