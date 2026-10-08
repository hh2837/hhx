import configparser
import json
import requests

c = configparser.ConfigParser()
c.read("config.ini")
b = c["LLM"]

history = []
while True:
    q = input("请输入你的问题：")
    print("——")
    history.append({"role": "user", "content": q})
    r = requests.post(
        f"{b['base_url']}/chat/completions",
        headers={"Authorization": f"Bearer {b['api_key']}"},
        json={"model": b["model"], "messages": history, "stream": True},
        stream=True,
    )
    answer = ""
    for line in r.iter_lines():
        if not line or not line.startswith(b"data:"):
            continue
        data = line[5:].strip()
        if data == b"[DONE]":
            break
        d = json.loads(data)
        delta = d["choices"][0]["delta"].get("content", "")
        if delta:
            answer += delta
            print(delta, end="", flush=True)
    print()
    history.append({"role": "assistant", "content": answer})
