# GoodWe SEMS Plus — Reverse-Engineered API Notes

Source: decompiled `com.goodwe.sems.plus` Android app (React Native / Hermes bytecode).
Goal: extend a Home Assistant custom integration with alarms + on/off-grid status
(and, as a bonus, live PV/battery/grid/load power flow).

## How this was produced (for reproducing / digging further)

- APK unpacked with `jadx` → `decompiled/` (Java bridge modules, manifest, resources).
  Not very useful for API logic — this is a React Native app, so the real logic is JS.
- The RN bundle `decompiled/resources/assets/index.android.bundle` is **Hermes bytecode**
  (not plain JS), version 96.
- Used [`hermes-dec`](https://github.com/P1sec/hermes-dec) (pure Python, no deps) to:
  - dump the string table → `hermes_out/strings.txt` (450k strings, useful for grepping
    URLs/endpoint paths/config keys)
  - fully decompile all ~80,000 functions to pseudocode → `hermes_out/decompiled.js`
    (200MB, ~3.9M lines). This is register-based pseudocode (`r0`, `r1`, ...), not clean
    JS, but original function/variable names are preserved as comments
    (`// Original name: xxx`), which made it possible to grep for things like
    `getGridStatusInfo`, `useAlarmListData`, `mergeApiEnergyFlowWithSecond`, etc.
- All line numbers below refer to `/home/hayden/Desktop/SEMS/hermes_out/decompiled.js`.
  If that file isn't present in the new environment, re-run:
  ```
  python3 hbc-decompiler index.android.bundle decompiled.js
  ```
  (hermes-dec repo: `/home/hayden/tools/hermes-dec-main`, jadx: `/home/hayden/tools/jadx-1.5.6`)

Community SEMS API clients (pysems, etc.) already have auth nailed, so auth is included
here only for context/cross-reference — the new work is alarms, grid status, and energy flow.

---

## Base URLs (regional gateways)

```
https://us-gateway.semsportal.com/web/
https://eu-gateway.semsportal.com/web/
https://au-gateway.semsportal.com/web/
https://hk-gateway.semsportal.com/web/
https://hz-gateway.sems.com.cn/web/     (China)
```

Full endpoint URL = `<gateway>/web/` + `<service-prefix>` + `<path>`, e.g.:
```
https://us-gateway.semsportal.com/web/sems-alarm/api/v2/alarm/page
```

Endpoints are declared throughout the bundle as small route-config objects:
```js
{'prefix': '/sems-alarm/api', 'post': '/v2/alarm/page'}
```
(region around `decompiled.js:526300-531000` has ~250 of these across
`/sems-user`, `/sems-plant`, `/sems-remote`, `/sems-alarm`, `/sems-report` services —
worth a full read if you need more endpoints later. Quick list of raw paths also
in `hermes_out/api_paths.txt`.)

---

## Auth (for reference — already solved by community clients)

- Login: `POST /sems-user/api/v1/auth/cross-login` (REST-style, current) or legacy
  `POST /api/v2/Common/CrossLogin` / `/api/v3/Common/CrossLogin`.
- Every request carries a `Token` header = `JSON.stringify(tokenInfo)`.
- Pre-login bootstrap `tokenInfo` (`decompiled.js:869493`):
  ```json
  {
    "client": "semsplus_android",   // or semsplus_ios
    "code": "<build number>",
    "language": "en",
    "projectname": "pvmaster",
    "timestamp": 0,
    "token": "a5b3t89bf7",           // static bootstrap token, literal in the bundle
    "uid": "",
    "version": "<app version>"
  }
  ```
- Post-login, `{uid, token, timestamp}` from the login response replace the
  placeholder values (`decompiled.js:777018`) and get merged into the same envelope.
- Response envelope: `{code, msg, data}`. Success = `0` / `"0"` / `"00000"`
  depending on endpoint generation. Auth-invalid codes: `100001`
  (`SEMS_AUTH_ERROR_NO_ACCESS`), `100002` (`SEMS_AUTH_ERROR`), plus legacy string
  codes `C0602`/`Z0100`/`C0607` (`decompiled.js:736412`, `770372`).

---

## Alarms

Route config, prefix `/sems-alarm/api` (`decompiled.js:527001-527020`):

| purpose | method | path |
|---|---|---|
| list (paginated) | POST | `/v2/alarm/page` |
| detail | POST | `/v2/alarm/detail` |
| counts | POST | `/alarm/statistics` |
| acknowledge | POST | `/alarm/confirm` |
| delete | POST | `/alarm/delete` |
| star/favorite | POST | `/alarm/star` |
| filter templates | POST | `/filter/template/list` |
| gdpr export | GET | `/alarm/gdpr/{pwId}` |
| notify config (get) | GET | `/api/v2/alert-notify-config/user` |
| notify config (update) | POST | `/api/v2/alert-notify-config/update` |

### `alarm/statistics` response
Simple counts, good for a single "active alarms" sensor
(`decompiled.js:1268693`):
```json
{ "total": 0, "happened": 0, "recovery": 0 }
```

### `alarm/page` request/response
Request needs at least `pageIndex`, `pageSize` (defaults to page size 20 if
omitted — `decompiled.js:1269188`); likely also accepts a `stationId` filter
(list is per-station in the UI) though the exact full param set wasn't traced
to a literal object — it's built up from component state. Worth checking with
a packet capture if you need date-range/level filters.

Response envelope (`decompiled.js:1269091-1269181`):
```json
{
  "code": 0,
  "data": {
    "dataList": [ /* alarm items, see below */ ],
    "current": 1,
    "total": 42,
    "size": 20
  }
}
```

### Alarm item shape
Collected from the `AlarmCard` component (`decompiled.js:1260428-1262740`):
```json
{
  "id": "...", "warningid": "...",
  "stationId": "...",
  "stationname": "...", "warningStationName": "...",
  "deviceName": "...", "devicesn": "...",
  "warningname": "...",
  "alarmLevel": 2,
  "status": 0,
  "happentimes": "2026-09-01 12:00:00",
  "recoverytimes": null,
  "starStatus": false, "isCollected": false,
  "confirmed": false,
  "name": "..."
}
```
- `id`/`warningid` are used interchangeably (falls back id → warningid → stationId).
- `status`: `AlarmStatusEnum` (`decompiled.js:1264221-1264231`) — `0 = OCCURRING`,
  `1 = RECOVERED`. Maps directly to a HA binary_sensor (`on` = occurring).
- `alarmLevel`: numeric severity, scale not confirmed (didn't find the enum
  mapping numbers → Info/Warning/Fault). Treat as opaque int until verified
  against real data, or expose raw.

---

## On-grid / off-grid + station status

**Endpoint** (`decompiled.js:528838-528839`):
```
POST /sems-plant/api/app/v2/stations/basic/info?stationId={stationId}
```

Response includes:

- `gridStatus` — resolved via `getGridStatusInfo()` (`decompiled.js:1270156-1270178`):
  | value | meaning |
  |---|---|
  | `1` | `on_grid` |
  | `0` | `off_grid` |

- `status` — overall station status, via `getStationStatusInfo()`
  (`decompiled.js:1270090-1270154`):
  | value | meaning |
  |---|---|
  | `0` | offline |
  | `1` | running |
  | `2` | fault |
  | `3` | waiting |
  | `11` | constructing |
  | other (e.g. `4294967295`) | unknown/others |

Also present on this response (seen destructured in `decompiled.js:983700-983850`):
`name`, `permissions[]`, `hemsSn`, `powerStationType`, `powerStationTypeUser`,
`powerStationTypeActual`.

One call → two useful HA binary_sensors (online/offline, on/off-grid).

---

## Live power flow (PV / battery / grid / load)

Found adjacent to the station-detail endpoint; very likely wanted alongside
grid status for the same coordinator refresh.

**Endpoint** (`decompiled.js:528848`):
```
GET /sems-plant/api/stations/flow?stationId={stationId}
```

Fields, from `useEnergyFlowNodes` destructuring (`decompiled.js:1779509-1779527`):
```json
{
  "pSystem": 0.0,     // total PV/generation power, kW
  "pThird": 0.0,      // third-party PV power, kW
  "pBat": 0.0,        // battery power, kW
  "pGrid": 0.0,        // grid power, kW
  "soc": 0,            // battery state of charge, %
  "pDiesel": 0.0,      // diesel generator power, kW
  "pEvChar": 0.0,      // EV charger power, kW
  "pConsum": 0.0,      // load/consumption power, kW
  "pHeatPump": 0.0,    // heat pump power, kW
  "flows": [ /* direction indicators, used to animate the flow diagram */ ]
}
```

**Sign conventions (confirmed against real inverter, not just decompiled):**
- `pBat`: **positive = discharging**, **negative = charging**
- `pGrid`: **positive = importing**, **negative = exporting**

(`pSystem`/`pConsum`/etc. sign conventions not separately verified — likely
always non-negative, i.e. magnitude-only, but worth a sanity check against
live data before assuming.)

---

## What's NOT nailed down (flagged for later if needed)

- Exact `alarm/page` request body beyond `pageIndex`/`pageSize` (date range,
  level filter, station filter param names) — built dynamically from UI state
  in the app, wasn't a single literal object to lift.
- `alarmLevel` numeric → severity name mapping.
- Full login request body beyond `{account, pwd}` (e.g. whether MFA/captcha
  fields are conditionally included) — not needed since auth is already solved
  elsewhere, included in original notes for completeness only.

## Raw artifacts (if you need to dig further)

All on this machine at `/home/hayden/Desktop/SEMS/`:
- `hermes_out/decompiled.js` — full pseudocode decompile (200MB, ~3.9M lines)
- `hermes_out/strings.txt` — full Hermes string table (450k lines, good for
  quick `grep` on endpoint paths / config keys / field names)
- `hermes_out/api_paths.txt` — pre-filtered list of `/api/...` and `/v.../...`
  path literals
- `decompiled/` — jadx Java output (native RN bridge modules; not much API
  logic here, mostly BLE/camera/permissions/native glue)
- Tools used: `hermes-dec` at `/home/hayden/tools/hermes-dec-main`,
  `jadx` at `/home/hayden/tools/jadx-1.5.6`

To search for a new endpoint or field: `grep -n "<term>" hermes_out/decompiled.js`
then read a window around the hit — route configs and enums read as plain
JS object literals even though everything else is register soup.
