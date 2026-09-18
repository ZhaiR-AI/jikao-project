"""Persistent collection categories; title-based defaults for existing uploads."""
import json
import re
from uuid import uuid4
from pathlib import Path
from study_store import _write_json

CATEGORIES = {"mock": "原创模拟卷", "past": "历年真题", "practice": "专项练习", "other": "其他"}
STORE = Path(__file__).resolve().parent / "data" / "collection_categories"


def shelves():
    path = STORE / "_shelves.json"
    custom = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return {**CATEGORIES, **custom}


def save_shelf(name, shelf_id=None):
    name = name.strip()
    if not name or len(name) > 30:
        raise ValueError("分类架名称请填写1—30个字")
    existing = shelves()
    if any(v.casefold() == name.casefold() and k != shelf_id for k, v in existing.items()):
        raise ValueError("已有同名分类架，请换一个名称")
    if shelf_id and shelf_id not in existing:
        raise ValueError("分类架不存在")
    shelf_id = shelf_id or "shelf-" + uuid4().hex
    path = STORE / "_shelves.json"
    custom = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    custom[shelf_id] = name
    STORE.mkdir(parents=True, exist_ok=True)
    _write_json(path, custom)
    return shelf_id


def delete_shelf(shelf_id):
    if shelf_id in CATEGORIES:
        raise ValueError("默认分类架可以改名，不能删除")
    path = STORE / "_shelves.json"
    custom = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if shelf_id not in custom:
        raise ValueError("分类架不存在")
    del custom[shelf_id]
    _write_json(path, custom)


def display_name(paper_id, fallback):
    path = category_path(paper_id)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return data.get("title") or fallback


def rename(paper_id, title):
    title = title.strip()
    if not title or len(title) > 120:
        raise ValueError("卷子名称请填写1—120个字")
    path = category_path(paper_id)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["title"] = title
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, data)


def category_path(collection_id):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", collection_id):
        raise ValueError("无效的集合编号")
    return STORE / f"{collection_id}.json"


def get_category(collection):
    path = category_path(collection["id"])
    if path.exists():
        value = json.loads(path.read_text(encoding="utf-8")).get("category")
        if value in shelves():
            return value, True
    text = collection.get("title", "") + " " + collection.get("source", {}).get("file_name", "")
    if re.search(r"模拟|原创", text):
        return "mock", False
    if "真题" in text:
        return "past", False
    if re.search(r"专项|练习|诊断|题库|训练", text):
        return "practice", False
    return "other", False


def set_category(collection_id, category):
    if category not in shelves() and category != "auto":
        raise ValueError("请选择有效分类")
    path = category_path(collection_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["category"] = category
    _write_json(path, data)
