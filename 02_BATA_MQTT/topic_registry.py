"""
MQTT Status Topic 관리
- Machine number(1~999) 기준으로 BAGO/M{N}/Status 토픽을 관리
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent
REGISTRY_PATH = ROOT / "config" / "topic_machines.json"
TOPIC_PATTERN = re.compile(r"^BAGO/M(\d{1,3})/Status$")
MAX_MANAGED_MACHINES = 100


def ensure_registry() -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        data = {"machine_numbers": [2]}
        REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_machine_no(machine_no: int) -> None:
    if not isinstance(machine_no, int):
        raise ValueError("machine_no must be int")
    if machine_no < 1 or machine_no > 999:
        raise ValueError("machine_no must be in range 1..999")


def load_machine_numbers() -> List[int]:
    ensure_registry()
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    nums = raw.get("machine_numbers", [])
    cleaned: Set[int] = set()
    for n in nums:
        i = int(n)
        _validate_machine_no(i)
        cleaned.add(i)
    return sorted(cleaned)


def save_machine_numbers(machine_numbers: List[int]) -> None:
    cleaned: Set[int] = set()
    for n in machine_numbers:
        i = int(n)
        _validate_machine_no(i)
        cleaned.add(i)

    if len(cleaned) > MAX_MANAGED_MACHINES:
        raise ValueError(f"managed machine numbers cannot exceed {MAX_MANAGED_MACHINES}")

    data = {"machine_numbers": sorted(cleaned)}
    REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add_machine(machine_no: int) -> Dict:
    machine_no = int(machine_no)
    _validate_machine_no(machine_no)
    nums = load_machine_numbers()
    already = machine_no in nums
    if not already:
        if len(nums) >= MAX_MANAGED_MACHINES:
            raise ValueError(f"managed machine numbers cannot exceed {MAX_MANAGED_MACHINES}")
        nums.append(machine_no)
        save_machine_numbers(nums)
    return {
        "status": "success",
        "action": "add",
        "machine_no": machine_no,
        "already_exists": already,
        "topic": machine_to_topic(machine_no),
        "machine_numbers": load_machine_numbers(),
    }


def remove_machine(machine_no: int) -> Dict:
    machine_no = int(machine_no)
    _validate_machine_no(machine_no)
    nums = load_machine_numbers()
    existed = machine_no in nums
    if existed:
        nums = [n for n in nums if n != machine_no]
        save_machine_numbers(nums)
    return {
        "status": "success",
        "action": "remove",
        "machine_no": machine_no,
        "existed": existed,
        "topic": machine_to_topic(machine_no),
        "machine_numbers": load_machine_numbers(),
    }


def machine_to_topic(machine_no: int) -> str:
    machine_no = int(machine_no)
    _validate_machine_no(machine_no)
    return f"BAGO/M{machine_no}/Status"


def get_topics() -> List[str]:
    return [machine_to_topic(n) for n in load_machine_numbers()]


def parse_machine_from_topic(topic: str):
    m = TOPIC_PATTERN.match(topic or "")
    if not m:
        return None
    return int(m.group(1))


def is_managed_status_topic(topic: str) -> bool:
    machine_no = parse_machine_from_topic(topic)
    if machine_no is None:
        return False
    return machine_no in set(load_machine_numbers())


def get_registry_summary() -> Dict:
    nums = load_machine_numbers()
    return {
        "status": "success",
        "machine_numbers": nums,
        "topics": [machine_to_topic(n) for n in nums],
        "count": len(nums),
        "max_machines": MAX_MANAGED_MACHINES,
        "topic_pattern": "BAGO/M{1..999}/Status",
    }
