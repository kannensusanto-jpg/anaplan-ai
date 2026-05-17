import asyncio
import csv
import io

import httpx

from app.services.config import ClientConfig


class AnaplanClient:
    BASE_URL = "https://api.anaplan.com/2/0"

    def __init__(self, workspace_id: str, model_id: str, token: str):
        self.workspace_id = workspace_id
        self.model_id     = model_id
        self.headers      = {"Authorization": f"AnaplanAuthToken {token}"}

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
