import configparser
import json
import subprocess
import requests

c = configparser.ConfigParser()
c.read("config.ini")
b = c["LLM"]


def isLeapYear(year):
    year = int(year)
    if year % 400 == 0:
        return f"{year}年是闰年"
    if year % 100 == 0:
        return f"{year}年不是闰年"
    if year % 4 == 0:
        return f"{year}年是闰年"
    return f"{year}年不是闰年"


def getdate():
    d = subprocess.run("date /t", shell=True, capture_output=True, text=True, encoding="gbk", errors="replace")
    t = subprocess.run("time /t", shell=True, capture_output=True, text=True, encoding="gbk", errors="replace")
    return f"{d.stdout.strip()} {t.stdout.strip()}"


tools = [
    {
        "type": "function",
        "function": {
            "name": "getdate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "计算输入的年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要计算的年份，例如2024"},
                },
                "required": ["year"],
            },
        },
    },
]

history = []
while True:
    q = input("请输入你的问题：")
    print("——")
    history.append({"role": "user", "content": q})

    while True:
        r = requests.post(
            f"{b['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {b['api_key']}"},
            json={"model": b["model"], "messages": history, "tools": tools, "stream": True},
            stream=True,
        )
        answer = ""
        tool_calls = []
        for line in r.iter_lines():
            if not line or not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            d = json.loads(data)
            delta = d["choices"][0]["delta"]
            content = delta.get("content") or ""
            if content:
                answer += content
                print(content, end="", flush=True)
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", len(tool_calls) - 1)
                while len(tool_calls) <= i:
                    tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    tool_calls[i]["id"] = tc["id"]
                f = tc.get("function", {})
                if f.get("name"):
                    tool_calls[i]["function"]["name"] += f["name"]
                if f.get("arguments"):
                    tool_calls[i]["function"]["arguments"] += f["arguments"]
        print()

        if not tool_calls:
            history.append({"role": "assistant", "content": answer})
            break

        history.append({"role": "assistant", "content": answer or None, "tool_calls": tool_calls})
        for tc in tool_calls:
            name = tc["function"]["name"]
            print(f"[调用工具：{name}]")
            args = json.loads(tc["function"]["arguments"] or "{}")
            if name == "getdate":
                result = getdate()
            elif name == "isLeapYear":
                result = isLeapYear(args["year"])
            else:
                result = f"未知工具：{name}"
            print(result)
            history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
