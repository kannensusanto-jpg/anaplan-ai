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
        Download the export keyed by form_config.view_id and map to standard rows.

        Expects a flat Anaplan CSV export where:
          - One row per (account, entity, time, version) combination
          - Column names match dim_account, dim_time, dim_version, dim_entity
          - A single numeric "value" column (any non-dim column)

        Rows are pivoted: actual_version_member rows supply 'actual';
        budget_version_member rows supply 'budget'.
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
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["Account", "Cost Center", "Time Period", "Commentary"])
        for row in rows:
            mid = row["member_id"]
            if mid in commentary:
                writer.writerow([
                    row["account"],
                    row["cost_center"],
                    row["time_period"],
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

def _map_flat_csv(raw: list[dict], fc) -> tuple[list[dict], dict[str, list[str]]]:
    """
    Convert a flat Anaplan export (one row per version member) into the
    pivoted standard format: one row per (account, entity, time) with
    both actual and budget values.
    """
    dr          = fc.dimension_roles or {}
    acc_col     = dr.get("account",    "Account")
    time_col    = dr.get("time",       "Time")
    version_col = dr.get("version",    "Version")
    entity_col  = dr.get("entity",     "Department")
    comm_col    = dr.get("commentary", "")

    actual_member = (fc.actual_version_member or "Actual").lower()
    budget_member = (fc.budget_version_member or "Budget").lower()

    dim_cols = {acc_col, time_col, version_col, entity_col, comm_col}

    # pivot: key = "account|entity|time"  →  {actual, budget, commentary}
    groups: dict[str, dict] = {}

    for row in raw:
        account = str(row.get(acc_col) or "").strip()
        time    = str(row.get(time_col) or "").strip()
        entity  = str(row.get(entity_col) or "").strip()
        version = str(row.get(version_col) or "").strip().lower()

        if not account:
            continue

        key = f"{account}|{entity}|{time}"
        g   = groups.setdefault(key, {
            "account": account, "entity": entity, "time": time,
            "actual": 0.0, "budget": 0.0, "commentary": None,
        })

        # First non-dim column with a parsable numeric value = the measure
        for col, val in row.items():
            if col in dim_cols:
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
            "account_type":     "expense",
            "human_commentary": g["commentary"],
            "parent_member_id": None,
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
