# -*- coding: utf-8 -*-
"""模型调用封装：OpenAI-compatible 的 chat/completions 接口。

只做一件事：把 messages + tools 发出去，
把模型回来的「文字思考 / 工具调用」解析成统一结构。
换模型 = 改 config.json 里的 base_url / api_key / model，代码不用动。
"""
import json

import requests


class ModelClient:
    def __init__(self, base_url, api_key, model, timeout=120):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.model = model
        self.timeout = timeout

    def chat(self, messages, tools=None):
        """返回 (assistant_text, tool_calls)。

        tool_calls 是 [{"id":..., "name":..., "arguments":{...}}]，
        没有工具调用时为空列表。
        """
        payload = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        r = requests.post(self.url, headers=self.headers,
                          json=payload, timeout=self.timeout)
        try:
            r.raise_for_status()
        except requests.HTTPError as e:
            # 400 这类错，真正的病因藏在返回 body 里，直接打印出来
            body = (r.text or "")[:2000]
            raise RuntimeError(f"HTTP {r.status_code}：{body}") from e
        msg = r.json()["choices"][0]["message"]
        text = msg.get("content") or ""
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments") or ""}
            calls.append({"id": tc["id"], "name": fn["name"],
                          "arguments": args})
        return text, calls
