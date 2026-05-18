import asyncio
import csv
import io
import re

import httpx

from app.services.config import ClientConfig


class AnaplanClient:
    BASE_URL = "https://api.anaplan.com/2/0"

    def __init__(self, workspace_id: str, model_id: str, token: str):
        self.workspace_id = workspace_id
        self.model_id     = model_id
        self.headers      = {"Authorization": f"AnaplanAuthToken {token}"}

    # ── View discovery ────────────────────────────────────────────────────────

    def list_views(self) -> list[dict]:
        """Return [{id, name, module_id}] for all views in the model."""
        base = f"{self.BASE_URL}/workspaces/{self.workspace_id}/models/{self.model_id}"
        with httpx.Client(headers=self.headers, timeout=30) as http:
            resp = http.get(f"{base}/views")
            resp.raise_for_status()
        return [
            {
                "id":        v["id"],
                "name":      v.get("name", v["id"]),
                "module_id": v.get("moduleId"),
            }
            for v in resp.json().get("item", [])
        ]

    def read_view_as_rows(self, form_config) -> tuple[list[dict], dict[str, list[str]]]:
        """
        Export the Anaplan view and return standard rows ready for the generation
        pipeline.  Dimension roles are auto-detected from column headers and sample
        values; dimension_roles config overrides detection when supplied.  Every
        non-role, non-measure column is captured as dim_context so Claude receives
        the full intersection context.
        """
        raw = self._run_export(form_config.view_id)
        return _map_flat_csv(raw, form_config)

    # ── Existing methods ──────────────────────────────────────────────────────

    def read_config_module(self, module_id: str) -> ClientConfig:
        data = self._run_export(module_id)
        cfg  = {row["key"]: row["value"] for row in data}
        return ClientConfig(
            tone=cfg.get("TONE", "concise and direct"),
            materiality_dollars=float(cfg.get("MATERIALITY_THRESHOLD_$", 50_000)),
            materiality_pct=float(cfg.get("MATERIALITY_THRESHOLD_%", 0.05)),
            focus_areas=[s.strip() for s in cfg.get("FOCUS_AREAS", "").split(",") if s.strip()],
            rollup_levels=[s.strip() for s in cfg.get("ROLLUP_LEVELS", "").split(",") if s.strip()],
            suppress_favorable=cfg.get("SUPPRESS_FAVORABLE", "FALSE").upper() == "TRUE",
            prior_period_context=cfg.get("PRIOR_PERIOD_CONTEXT", "TRUE").upper() == "TRUE",
        )

    def read_module_data(self, module_id: str) -> list[dict]:
        return self._run_export(module_id)

    def read_hierarchy(self, module_id: str) -> dict[str, list[str]]:
        # Returns parent_member_id → [child_member_ids]
        # Populated from the module's list hierarchy via Anaplan API
        return {}

    def _run_export(self, export_id: str) -> list[dict]:
        """Start an Anaplan export task, poll for completion, and return rows."""
        base = f"{self.BASE_URL}/workspaces/{self.workspace_id}/models/{self.model_id}"

        with httpx.Client(headers=self.headers, timeout=60) as http:
            # Start export task
            resp = http.post(f"{base}/exports/{export_id}/tasks", json={})
            resp.raise_for_status()
            task_id = resp.json()["task"]["taskId"]

            # Poll until complete
            for _ in range(60):
                status_resp = http.get(f"{base}/exports/{export_id}/tasks/{task_id}")
                status_resp.raise_for_status()
                state = status_resp.json()["task"]["taskState"]
                if state == "COMPLETE":
                    break
                if state == "CANCELLED":
                    raise RuntimeError(f"Export task cancelled: {task_id}")
                import time
                time.sleep(2)
            else:
                raise TimeoutError(f"Export task timed out: {task_id}")

            # Download file
            file_resp = http.get(f"{base}/files/{export_id}")
            file_resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(file_resp.text))
        return list(reader)

    async def write_commentary(
        self,
        import_action_id: str,
        file_id: str,
        commentary: dict[str, str],
        rows: list[dict],
    ) -> None:
        csv_bytes = self._build_csv(commentary, rows)
        await self._upload_file(file_id, csv_bytes)
        task_id = await self._run_import(import_action_id)
        await self._poll_task("imports", import_action_id, task_id)

    def _build_csv(self, commentary: dict[str, str], rows: list[dict]) -> bytes:
        if not rows:
            return b""

        # Use actual Anaplan dimension names from _dim_roles (set during parsing)
        sample_roles = rows[0].get("_dim_roles") or {}
        acc_col    = sample_roles.get("account",    "Account")
        entity_col = sample_roles.get("entity",     "Cost Centre")
        time_col   = sample_roles.get("time",       "Time Period")
        comm_col   = sample_roles.get("commentary", "Commentary")

        # Extra dimension columns present across all rows
        extra_cols = list(rows[0].get("dim_context", {}).keys())

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([acc_col, entity_col, time_col, *extra_cols, comm_col])
        for row in rows:
            mid = row["member_id"]
            if mid in commentary:
                extra_vals = [row.get("dim_context", {}).get(c, "") for c in extra_cols]
                writer.writerow([
                    row["account"],
                    row["cost_center"],
                    row["time_period"],
                    *extra_vals,
                    commentary[mid],
                ])
        return buf.getvalue().encode("utf-8")

    async def _upload_file(self, file_id: str, content: bytes) -> None:
        url = f"{self.BASE_URL}/workspaces/{self.workspace_id}/models/{self.model_id}/files/{file_id}"
        async with httpx.AsyncClient() as http:
            resp = await http.put(
                url,
                content=content,
                headers={**self.headers, "Content-Type": "application/octet-stream"},
            )
            resp.raise_for_status()

    async def _run_import(self, import_action_id: str) -> str:
        url = (
            f"{self.BASE_URL}/workspaces/{self.workspace_id}"
            f"/models/{self.model_id}/imports/{import_action_id}/tasks"
        )
        async with httpx.AsyncClient() as http:
            resp = await http.post(url, json={"localeName": "en_US"}, headers=self.headers)
            resp.raise_for_status()
            return resp.json()["task"]["taskId"]

    async def _poll_task(self, resource: str, action_id: str, task_id: str) -> None:
        url = (
            f"{self.BASE_URL}/workspaces/{self.workspace_id}"
            f"/models/{self.model_id}/{resource}/{action_id}/tasks/{task_id}"
        )
        async with httpx.AsyncClient() as http:
            for _ in range(30):
                resp = await http.get(url, headers=self.headers)
                resp.raise_for_status()
                state = resp.json()["task"]["taskState"]
                if state == "COMPLETE":
                    return
                if state == "CANCELLED":
                    raise RuntimeError(f"Anaplan task cancelled: {task_id}")
                await asyncio.sleep(2)
        raise TimeoutError(f"Anaplan task timed out: {task_id}")


# ── Module-level helpers ──────────────────────────────────────────────────────

_TIME_HINTS     = {"period", "time", "month", "quarter", "year", "week", "date", "fiscal"}
_VERSION_HINTS  = {"version", "scenario", "type"}
_ACCOUNT_HINTS  = {"account", "accounts", "line item", "lineitems", "item", "measure", "description"}
_ENTITY_HINTS   = {"entity", "department", "dept", "cost centre", "cost center",
                   "org unit", "business unit", "division", "location", "region", "subsidiary"}
_COMMENT_HINTS  = {"commentary", "comment", "notes", "annotation", "narrative"}
_VERSION_VALUES = {"actual", "actuals", "budget", "plan", "forecast", "fcast",
                   "reforecast", "prior year", "ly", "py", "target"}
_REVENUE_HINTS  = {"revenue", "income", "sales", "turnover", "net revenue"}
_EXPENSE_HINTS  = {"expense", "cost", "opex", "capex", "spend", "salary", "salaries",
                   "headcount", "depreciation", "amortization"}


def _infer_roles(headers: list[str], samples: list[dict], configured: dict) -> dict:
    """
    Return {role: column_name} for account, time, version, entity, commentary.
    Configured dimension_roles take precedence; heuristics fill any gaps.
    """
    roles = {k: v for k, v in configured.items() if v}

    def _match(h: str, hints: set[str]) -> bool:
        hl = h.lower().strip()
        return any(hint in hl for hint in hints)

    for h in headers:
        if "account" not in roles and _match(h, _ACCOUNT_HINTS):
            roles["account"] = h
        if "time" not in roles and _match(h, _TIME_HINTS):
            roles["time"] = h
        if "version" not in roles and _match(h, _VERSION_HINTS):
            roles["version"] = h
        if "entity" not in roles and _match(h, _ENTITY_HINTS):
            roles["entity"] = h
        if "commentary" not in roles and _match(h, _COMMENT_HINTS):
            roles["commentary"] = h

    # Inspect values for version column — if a column's distinct values are
    # all known version member names, it's the version dimension.
    if "version" not in roles and samples:
        for h in headers:
            if h in roles.values():
                continue
            vals = {str(r.get(h, "")).lower().strip() for r in samples[:40] if r.get(h)}
            if vals and vals <= (_VERSION_VALUES | {""}):
                roles["version"] = h
                break

    return roles


def _infer_account_type(account_name: str) -> str:
    al = account_name.lower()
    if any(h in al for h in _REVENUE_HINTS):
        return "revenue"
    return "expense"


def _map_flat_csv(raw: list[dict], fc) -> tuple[list[dict], dict[str, list[str]]]:
    """
    Convert a flat Anaplan export into one row per dimension intersection with
    actual + budget pivoted. Auto-detects dimension roles from column headers
    and values; dimension_roles config takes precedence when supplied.

    Every non-role, non-measure column is captured as dim_context so that
    the generation pipeline can pass the full intersection to Claude.
    """
    if not raw:
        return [], {}

    headers = list(raw[0].keys())
    configured = fc.dimension_roles or {}
    roles = _infer_roles(headers, raw, configured)

    acc_col     = roles.get("account",    "")
    time_col    = roles.get("time",       "")
    version_col = roles.get("version",    "")
    entity_col  = roles.get("entity",     "")
    comm_col    = roles.get("commentary", "")

    actual_member = (fc.actual_version_member or "Actual").lower()
    budget_member = (fc.budget_version_member or "Budget").lower()

    # Columns that play a known dimension role (not measure candidates)
    role_cols = {c for c in (acc_col, time_col, version_col, entity_col, comm_col) if c}

    # Columns that are neither a role col nor the measure — extra context dimensions
    def _is_measure(col: str, sample_vals: list) -> bool:
        numeric = sum(1 for v in sample_vals if _safe_float(v) != 0.0 or str(v).strip() in ("0", "0.0", "0"))
        return numeric / max(len(sample_vals), 1) > 0.5

    measure_col = None
    extra_dim_cols: list[str] = []
    for h in headers:
        if h in role_cols:
            continue
        sample_vals = [r.get(h) for r in raw[:20] if r.get(h) is not None]
        if measure_col is None and sample_vals and _is_measure(h, sample_vals):
            measure_col = h
        else:
            extra_dim_cols.append(h)

    # pivot: key = all dimension values joined  →  {actual, budget, commentary, dim_context}
    groups: dict[str, dict] = {}

    for row in raw:
        account = str(row.get(acc_col) or "").strip() if acc_col else ""
        time    = str(row.get(time_col) or "").strip() if time_col else ""
        entity  = str(row.get(entity_col) or "").strip() if entity_col else ""
        version = str(row.get(version_col) or "").strip().lower() if version_col else ""

        if not account:
            continue

        # Extra dimension values for this row (consistent across versions)
        extra = {c: str(row.get(c) or "").strip() for c in extra_dim_cols if row.get(c)}

        # Build a stable member key from all dimensions except version
        key_parts = [account, entity, time] + [extra.get(c, "") for c in extra_dim_cols]
        key = "|".join(key_parts)

        g = groups.setdefault(key, {
            "account":     account,
            "entity":      entity,
            "time":        time,
            "actual":      0.0,
            "budget":      0.0,
            "commentary":  None,
            "dim_context": extra,
        })

        if measure_col:
            fval = _safe_float(row.get(measure_col))
            if version == actual_member:
                g["actual"] = fval
            elif version == budget_member:
                g["budget"] = fval
        else:
            # Fall back: first parsable numeric value in any non-role column
            for col, val in row.items():
                if col in role_cols:
                    continue
                fval = _safe_float(val)
                if version == actual_member:
                    g["actual"] = fval
                elif version == budget_member:
                    g["budget"] = fval
                break

        if comm_col and row.get(comm_col):
            g["commentary"] = str(row[comm_col]).strip()

    rows = []
    for member_id, g in groups.items():
        actual = g["actual"]
        budget = g["budget"]
        rows.append({
            "member_id":        member_id,
            "account":          g["account"],
            "cost_center":      g["entity"],
            "time_period":      g["time"] or "N/A",
            "actual":           actual,
            "budget":           budget,
            "variance_dollars": actual - budget,
            "variance_pct":     (actual - budget) / budget if budget else 0.0,
            "prior_actual":     0.0,
            "account_type":     _infer_account_type(g["account"]),
            "human_commentary": g["commentary"],
            "parent_member_id": None,
            "dim_context":      g["dim_context"],
            "_dim_roles":       roles,   # carried for write-back
        })

    return rows, {}


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = re.sub(r"[^\d.\-]", "", str(val))
    try:
        return float(cleaned)
    except ValueError:
        return 0.0
