import configparser
import json
import os
import shutil
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


def get_cwd(path=""):
    return os.getcwd()


def list_dir(path="."):
    items = os.listdir(path)
    return "\n".join(items) if items else "（空目录）"


def file_info(path):
    if not os.path.exists(path):
        return f"路径不存在：{path}"
    kind = "目录" if os.path.isdir(path) else "文件"
    ext = os.path.splitext(path)[1]
    return f"{path} 是{kind}，扩展名：{ext or '无'}"


def read_file(path):
    if not os.path.isfile(path):
        return f"文件不存在：{path}"
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def create_file(path, content=""):
    if os.path.exists(path):
        return f"文件已存在：{path}"
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return f"已创建文件：{path}"


def write_file(path, content):
    if not os.path.isfile(path):
        return f"文件不存在：{path}"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return f"已写入文件：{path}"


def create_dir(path):
    os.makedirs(path, exist_ok=True)
    return f"已创建目录：{path}"


def delete_dir(path):
    if not os.path.isdir(path):
        return f"目录不存在：{path}"
    shutil.rmtree(path)
    return f"已删除目录：{path}"


def delete_file(path):
    if not os.path.isfile(path):
        return f"文件不存在：{path}"
    os.remove(path)
    return f"已删除文件：{path}"


def move_path(src, dst):
    if not os.path.exists(src):
        return f"路径不存在：{src}"
    shutil.move(src, dst)
    return f"已重命名/移动：{src} -> {dst}"


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
    {
        "type": "function",
        "function": {
            "name": "get_cwd",
            "description": "获取当前工作目录",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出指定目录下的文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，默认为当前目录"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "获取指定路径的文件信息（类型、扩展名）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件或目录路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定文本文件的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "新建文件并可写入初始内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "初始内容，默认为空"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "修改（覆盖写入）指定文本文件的内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_dir",
            "description": "新建目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_dir",
            "description": "删除目录（含非空目录）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_path",
            "description": "重命名或移动文件/目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string", "description": "源路径"},
                    "dst": {"type": "string", "description": "目标路径"},
                },
                "required": ["src", "dst"],
            },
        },
    },
]


def run_tool(name, args):
    if name == "getdate":
        return getdate()
    if name == "isLeapYear":
        return isLeapYear(args["year"])
    if name == "get_cwd":
        return get_cwd()
    if name == "list_dir":
        return list_dir(args.get("path", "."))
    if name == "file_info":
        return file_info(args["path"])
    if name == "read_file":
        return read_file(args["path"])
    if name == "create_file":
        return create_file(args["path"], args.get("content", ""))
    if name == "write_file":
        return write_file(args["path"], args["content"])
    if name == "create_dir":
        return create_dir(args["path"])
    if name == "delete_dir":
        return delete_dir(args["path"])
    if name == "delete_file":
        return delete_file(args["path"])
    if name == "move_path":
        return move_path(args["src"], args["dst"])
    return f"未知工具：{name}"


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
            result = run_tool(name, args)
            print(result)
            history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
