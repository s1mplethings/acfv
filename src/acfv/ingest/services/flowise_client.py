import json
import requests
from typing import Optional

class FlowiseClient:
    """轻量 Flowise Chatflow 调用客户端"""
    def __init__(
        self,
        base_url: str = "http://localhost:3000",
        chatflow_id: str = "",
        api_key: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.chatflow_id = chatflow_id
        self.api_key = api_key
        self.timeout = timeout

    def is_ready(self) -> bool:
        return bool(self.chatflow_id)

    def predict(self, question: str, override: Optional[dict] = None) -> str:
        if not self.chatflow_id:
            raise ValueError("Flowise chatflow_id 未配置")
        url = f"{self.base_url}/api/v1/prediction/{self.chatflow_id}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"question": question, "overrideConfig": override or {}}
        resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        # Flowise 可能返回 text / answer / data 等不同字段
        return data.get("text") or data.get("answer") or json.dumps(data, ensure_ascii=False)
