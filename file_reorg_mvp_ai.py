import copy
import csv
import json
import logging
import logging.handlers
import os
import time
import re
import shutil
import threading
import traceback
import urllib.request
import urllib.error
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog


APP_NAME = "File Reorganization MVP + AI"
APP_VERSION = "0.5.0"

# =========================
# Logging Setup
# =========================

_LOG_DIR = os.path.join(os.environ.get("APPDATA", str(Path.home())), "FileReorgMVP", "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "file_reorg.log")

logger = logging.getLogger("FileReorg")
logger.setLevel(logging.DEBUG)

_fh = logging.handlers.RotatingFileHandler(
    _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setLevel(logging.INFO)
_ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(_ch)

# =========================
# Organization Profile
# =========================

@dataclass
class FolderDefinition:
    """Describes one top-level folder in the organization model."""
    name: str
    description: str
    question: str
    contains: List[str] = field(default_factory=list)
    not_contains: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    subfolders: List[str] = field(default_factory=list)


@dataclass
class OrganizationProfile:
    """A complete, serializable organizational model for folder reorganization."""
    name: str
    description: str
    folders: List[FolderDefinition] = field(default_factory=list)
    rules: List[dict] = field(default_factory=list)
    objectives: str = ""
    decision_guide: List[Dict[str, str]] = field(default_factory=list)

    def top_level_names(self):
        return [f.name for f in self.folders]

    def archive_subfolders(self):
        """Mirror active folder names inside the archive folder."""
        archive = None
        active = []
        for f in self.folders:
            if f.name.startswith("90_"):
                archive = f
            elif not f.name.startswith("99_"):
                active.append(f.name.split("_", 1)[-1] if "_" in f.name else f.name)
        return active

    def to_dict(self):
        return {
            "name": self.name,
            "description": self.description,
            "folders": [asdict(f) for f in self.folders],
            "rules": self.rules,
            "objectives": self.objectives,
            "decision_guide": self.decision_guide,
        }

    @classmethod
    def from_dict(cls, data):
        folders = [FolderDefinition(**fd) for fd in data.get("folders", [])]
        return cls(
            name=data.get("name", "Custom"),
            description=data.get("description", ""),
            folders=folders,
            rules=data.get("rules", []),
            objectives=data.get("objectives", ""),
            decision_guide=data.get("decision_guide", []),
        )


def build_default_masaca_profile():
    """Build the default Maserati Academy organization profile (simplified 7-folder model)."""
    folders = [
        FolderDefinition(
            name="01_Management",
            description="Tutto ciò che serve a gestire l'Academy come funzione.",
            question="Questo file serve a organizzare il lavoro interno dell'Academy?",
            contains=["planning", "meeting note", "processi", "calendario", "documenti organizzativi",
                      "decisioni", "governance", "SOP", "ruoli e responsabilità", "operating model"],
            not_contains=["contenuto formativo", "erogazione training", "report numerici", "budget"],
            examples=["annual planning Academy", "process map LMS", "weekly management meeting notes",
                      "ruoli e responsabilità", "operating model"],
            subfolders=["Planning", "Meetings", "Processes", "Calendars"],
        ),
        FolderDefinition(
            name="02_Training_Projects",
            description="Tutto ciò che riguarda la creazione o revisione di training.",
            question="Questo file serve a costruire o aggiornare un contenuto formativo?",
            contains=["storyboard", "bozze deck", "source content", "input SME",
                      "review comments", "master file finali", "brief", "development"],
            not_contains=["logistica erogazione", "liste partecipanti sessione", "budget"],
            examples=["deck finale training Grecale", "storyboard modulo Aftersales",
                      "brief nuovo corso Commercial", "review comments MC20"],
            subfolders=["Commercial", "Aftersales_Technical", "Luxury_Customer_Experience", "Cross_Academy"],
        ),
        FolderDefinition(
            name="03_Training_Delivery",
            description="Tutto ciò che serve a erogare concretamente il training.",
            question="Questo file serve a organizzare o supportare una sessione/training già in campo?",
            contains=["session planning", "liste partecipanti", "calendari training",
                      "materiale per trainer", "logistica", "deployment per region",
                      "comunicazioni operative ai dealer"],
            not_contains=["sviluppo contenuti", "storyboard", "budget"],
            examples=["lista partecipanti sessione APAC", "calendario training Q2",
                      "trainer guide sessione virtuale", "comunicazione dealer EMEA"],
            subfolders=["Global", "Regions", "Virtual", "In_Person"],
        ),
        FolderDefinition(
            name="04_Reports_and_Budget",
            description="Tutto ciò che serve a misurare, controllare, rendicontare.",
            question="Questo file serve per numeri, performance, budget o controllo?",
            contains=["attendance report", "completion report", "KPI", "dashboard export",
                      "survey result", "budget", "invoice", "forecast", "vendor financial tracking"],
            not_contains=["contenuto formativo", "logistica"],
            examples=["report mensile attendance", "budget Q3 2025", "KPI dashboard export",
                      "invoice vendor training"],
            subfolders=["Reports", "Budget"],
        ),
        FolderDefinition(
            name="05_Shared_Resources",
            description="Tutto ciò che viene riusato da tutti.",
            question="Questo file è un materiale standard, riutilizzabile o di supporto?",
            contains=["template", "asset grafici", "loghi", "immagini", "icone",
                      "standard", "linee guida", "modelli Excel/PPT/Word",
                      "naming conventions", "checklist"],
            not_contains=["file specifico di un progetto", "report", "budget"],
            examples=["template email dealer invitation", "logo Maserati",
                      "linee guida brand", "checklist pre-sessione"],
            subfolders=["Templates", "Brand_Assets", "Guidelines", "Tools"],
        ),
        FolderDefinition(
            name="90_Archive",
            description="Tutto ciò che non è più attivo, ma va tenuto.",
            question="Questo file serve ancora davvero nel lavoro corrente?",
            contains=["materiale non più attivo", "progetti chiusi", "versioni superate"],
            not_contains=["file attivi", "file in lavorazione"],
            examples=["training Levante 2022", "vecchio operating model",
                      "report annuale 2021"],
            subfolders=["Management", "Training_Projects", "Training_Delivery",
                        "Reports_and_Budget", "Shared_Resources"],
        ),
        FolderDefinition(
            name="99_Inbox",
            description="File appena arrivati, scaricati, esportati, ricevuti. Zona di transito.",
            question="Non so ancora dove va, ma so che non deve restare in desktop o in root.",
            contains=["file appena ricevuti", "download", "export da Teams", "file da classificare"],
            not_contains=["file già classificati"],
            examples=["allegato email appena ricevuto", "export chat Teams",
                      "file scaricato da SharePoint"],
            subfolders=[],
        ),
    ]

    rules = [
        {
            "name": "Attendance Report",
            "priority": 10,
            "condition": {"path_contains": ["Attendance Report", "attendance"]},
            "action": "move",
            "target_rel": r"04_Reports_and_Budget\Reports\Attendance"
        },
        {
            "name": "KPI Report",
            "priority": 15,
            "condition": {"path_contains": ["KPI", "dashboard", "completion report"]},
            "action": "move",
            "target_rel": r"04_Reports_and_Budget\Reports"
        },
        {
            "name": "Budget Finance",
            "priority": 20,
            "condition": {"path_contains": ["Budget & Finance", "Budget", "invoice", "forecast"]},
            "action": "move",
            "target_rel": r"04_Reports_and_Budget\Budget"
        },
        {
            "name": "Operations Management",
            "priority": 30,
            "condition": {"path_contains": ["Operations", "Management", "Planning", "SOP"]},
            "action": "move",
            "target_rel": r"01_Management"
        },
        {
            "name": "Teams Exports",
            "priority": 40,
            "condition": {"path_contains": ["File di chat di Microsoft Teams"]},
            "action": "move",
            "target_rel": r"99_Inbox"
        },
        {
            "name": "Training Delivery",
            "priority": 45,
            "condition": {"path_contains": ["Delivery", "session planning", "partecipanti", "trainer guide"]},
            "action": "move",
            "target_rel": r"03_Training_Delivery"
        },
        {
            "name": "Archive Backup or OLD",
            "priority": 50,
            "condition": {"path_contains": ["Backup", r"\\OLD\\", r"\\old\\"]},
            "action": "archive",
            "target_rel": r"90_Archive"
        },
        {
            "name": "Academy Training Content",
            "priority": 60,
            "condition": {"path_contains": ["Academy - Documenti", "Training_Projects", "storyboard"]},
            "action": "move",
            "target_rel": r"02_Training_Projects"
        },
        {
            "name": "Templates and Resources",
            "priority": 65,
            "condition": {"path_contains": ["Template", "template", "Brand_Assets", "Guidelines", "linee guida"]},
            "action": "move",
            "target_rel": r"05_Shared_Resources"
        },
        {
            "name": "Root files",
            "priority": 70,
            "condition": {"top_folder_is": "[ROOT]"},
            "action": "review",
            "target_rel": r"99_Inbox"
        },
        {
            "name": "Media to Shared Resources",
            "priority": 80,
            "condition": {"extension_in": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"]},
            "action": "move",
            "target_rel": r"05_Shared_Resources\Brand_Assets"
        },
        {
            "name": "Fallback docs",
            "priority": 999,
            "condition": {"extension_in": [".xlsx", ".xls", ".xlsm", ".csv", ".docx", ".doc", ".pdf", ".pptx", ".ppt", ".txt", ".msg"]},
            "action": "review",
            "target_rel": r"99_Inbox"
        }
    ]

    objectives = (
        "Primary context: Maserati Academy training department. "
        "Goal: simplified and human-readable folder organization with exactly 7 top-level folders. "
        "File placement follows a simple question-based decision model. "
        "Teams (Commercial, Aftersales_Technical, Luxury_Customer_Experience, Cross_Academy) "
        "are subfolders of 02_Training_Projects, not top-level. "
        "Operations is a cross-cutting function, primarily living in 01_Management, 03_Training_Delivery, and 04_Reports_and_Budget. "
        "When unsure, use 99_Inbox. Never leave files in root. "
        "Reduce cognitive friction: use human-readable names, few entry points, obvious rules. "
        "The AI must propose a plan, not execute filesystem changes. "
        "When confidence is low, prefer review instead of risky moves."
    )

    decision_guide = [
        {"question": "Serve a gestire il lavoro interno Academy?", "folder": "01_Management"},
        {"question": "Serve a creare o aggiornare un training?", "folder": "02_Training_Projects"},
        {"question": "Serve a erogare un training?", "folder": "03_Training_Delivery"},
        {"question": "Serve a misurare o rendicontare?", "folder": "04_Reports_and_Budget"},
        {"question": "Serve come risorsa comune riutilizzabile?", "folder": "05_Shared_Resources"},
        {"question": "Non è più attivo ma va conservato?", "folder": "90_Archive"},
        {"question": "È appena arrivato e va classificato?", "folder": "99_Inbox"},
    ]

    return OrganizationProfile(
        name="Maserati Academy",
        description=(
            "Modello semplificato a 7 cartelle per la Maserati Academy. "
            "Struttura parlante, pochi punti di ingresso, regole ovvie anche per chi arriva da fuori."
        ),
        folders=folders,
        rules=rules,
        objectives=objectives,
        decision_guide=decision_guide,
    )


# Build defaults from profile
_DEFAULT_PROFILE = build_default_masaca_profile()

DEFAULT_TOP_LEVELS = _DEFAULT_PROFILE.top_level_names()

DEFAULT_OBJECTIVES = _DEFAULT_PROFILE.objectives


# =========================
# Models
# =========================

@dataclass
class FileRecord:
    source_path: str
    relative_path: str
    name: str
    extension: str
    size_bytes: int
    modified_at: str
    top_folder: str
    suggested_action: str = "review"
    suggested_target_rel: str = ""
    risk_flags: List[str] = field(default_factory=list)
    selected: bool = True
    decision_source: str = "rule"
    ai_reason: str = ""
    ai_confidence: float = 0.0
    needs_review: bool = False


@dataclass
class OperationPlan:
    source_path: str
    action: str
    target_path: str
    relative_target_path: str
    status: str = "planned"
    message: str = ""
    rollback_source: str = ""
    rollback_target: str = ""


@dataclass
class AISettings:
    provider: str = "OpenAI"
    api_key: str = ""
    model: str = "gpt-4o"
    max_chunk_size: int = 180
    confidence_threshold: float = 0.72
    include_size: bool = True
    include_dates: bool = True
    strategic_enabled: bool = True


# =========================
# Helpers
# =========================

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def now_compact():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_rel_path(path_str):
    return str(path_str).replace("/", "\\").strip("\\").strip()


def split_top_folder(relative_path):
    rel = normalize_rel_path(relative_path)
    if not rel:
        return "[ROOT]"
    parts = [p for p in rel.split("\\") if p]
    return parts[0] if parts else "[ROOT]"


def path_modified_iso(path_obj):
    try:
        ts = path_obj.stat().st_mtime
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def ensure_dir(path_obj):
    path_obj.mkdir(parents=True, exist_ok=True)


def unique_target_path(path_obj):
    if not path_obj.exists():
        return path_obj
    stem = path_obj.stem
    suffix = path_obj.suffix
    parent = path_obj.parent
    i = 1
    while True:
        candidate = parent / ("%s__dup%03d%s" % (stem, i, suffix))
        if not candidate.exists():
            return candidate
        i += 1


def has_suspicious_version(name):
    pattern = r"(\(\d+\)|\bcopy\b|\bcopia\b|\bv\d+(\.\d+)?\b|\bfinal\b|\bdef\b)"
    return bool(re.search(pattern, name, flags=re.IGNORECASE))


def format_size(size_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return "%d %s" % (int(size), units[idx])
    return "%.2f %s" % (size, units[idx])


def chunk_list(items, size):
    chunks = []
    current = []
    for item in items:
        current.append(item)
        if len(current) >= size:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


# =========================
# Rule Engine
# =========================

DEFAULT_RULES = _DEFAULT_PROFILE.rules


class RuleEngine(object):
    def __init__(self, rules=None):
        if rules is None:
            rules = DEFAULT_RULES
        self.rules = sorted(rules, key=lambda x: x.get("priority", 9999))

    def save_rules(self, path_obj):
        with path_obj.open("w", encoding="utf-8") as f:
            json.dump(self.rules, f, ensure_ascii=False, indent=2)

    def load_rules(self, path_obj):
        with path_obj.open("r", encoding="utf-8") as f:
            self.rules = sorted(json.load(f), key=lambda x: x.get("priority", 9999))

    def apply(self, record):
        full = record.source_path.replace("/", "\\")
        ext = record.extension.lower()
        top = record.top_folder

        for rule in self.rules:
            cond = rule.get("condition", {})
            if self._match(cond, full, ext, top):
                record.suggested_action = rule.get("action", "review")
                record.suggested_target_rel = rule.get("target_rel", "")
                record.decision_source = "rule"
                break

        if has_suspicious_version(record.name):
            record.risk_flags.append("version_or_duplicate_pattern")

        if len(full) > 220:
            record.risk_flags.append("long_path_risk")

        if top == "[ROOT]":
            record.risk_flags.append("root_file")

        if re.search(r"\\(old|OLD)\\", full):
            record.risk_flags.append("old_path")

        if re.search(r"backup", full, flags=re.IGNORECASE):
            record.risk_flags.append("backup_path")

    def _match(self, cond, full, ext, top):
        if "path_contains" in cond:
            ok = False
            for token in cond["path_contains"]:
                if token.startswith("\\") or token.endswith("\\") or "\\" in token:
                    if re.search(token, full, flags=re.IGNORECASE):
                        ok = True
                        break
                else:
                    if token.lower() in full.lower():
                        ok = True
                        break
            if not ok:
                return False

        if "extension_in" in cond:
            allowed = [x.lower() for x in cond["extension_in"]]
            if ext not in allowed:
                return False

        if "top_folder_is" in cond:
            if top != cond["top_folder_is"]:
                return False

        return True


# =========================
# Inventory / Planning
# =========================

class InventoryScanner(object):
    def scan(self, root, stop_flag=None):
        logger.info("Starting scan of: %s", root)
        records = []
        for dirpath, _, filenames in os.walk(root):
            if stop_flag and stop_flag():
                logger.info("Scan stopped by user after %d files.", len(records))
                break

            for filename in filenames:
                source = Path(dirpath) / filename
                try:
                    rel = source.relative_to(root)
                except Exception:
                    continue

                rel_str = normalize_rel_path(str(rel))
                top = split_top_folder(rel_str)
                ext = source.suffix.lower()

                try:
                    size_bytes = source.stat().st_size
                except Exception:
                    size_bytes = 0

                record = FileRecord(
                    source_path=str(source),
                    relative_path=rel_str,
                    name=source.name,
                    extension=ext,
                    size_bytes=size_bytes,
                    modified_at=path_modified_iso(source),
                    top_folder=top
                )
                records.append(record)

        logger.info("Scan completed. Total files found: %d", len(records))
        return records


class Planner(object):
    def __init__(self, rule_engine):
        self.rule_engine = rule_engine

    def build_plan(self, root, records):
        plans = []

        for record in records:
            self.rule_engine.apply(record)
            target_rel = self._compute_target_rel(record)
            target_abs = str(root / target_rel) if target_rel else ""

            plan = OperationPlan(
                source_path=record.source_path,
                action=record.suggested_action,
                target_path=target_abs,
                relative_target_path=target_rel,
                status="planned",
                message=""
            )
            plans.append(plan)

        return plans

    def _compute_target_rel(self, record):
        src_rel = normalize_rel_path(record.relative_path)
        src_parts = [p for p in src_rel.split("\\") if p]

        if record.suggested_action in ("move", "archive"):
            base = normalize_rel_path(record.suggested_target_rel)
            if record.top_folder != "[ROOT]" and len(src_parts) > 1:
                tail = "\\".join(src_parts[1:-1])
            else:
                tail = ""

            if tail:
                return normalize_rel_path(base + "\\" + tail + "\\" + record.name)
            return normalize_rel_path(base + "\\" + record.name)

        if record.suggested_action == "review":
            base = normalize_rel_path(record.suggested_target_rel or r"99_Inbox")
            return normalize_rel_path(base + "\\" + record.name)

        if record.suggested_action == "quarantine":
            return normalize_rel_path(r"_QUARANTINE\%s" % record.name)

        if record.suggested_action == "rename":
            base = normalize_rel_path(record.suggested_target_rel or record.relative_path)
            return base

        return ""


# =========================
# AI Layer
# =========================

class AIClient(object):
    def __init__(self, provider, api_key, model):
        self.provider = provider.strip()
        self.api_key = api_key.strip()
        self.model = model.strip()

    def responses_structured(self, system_prompt, user_payload, schema_name, schema):
        if not self.api_key:
            raise ValueError("Missing API key.")
        if not self.model:
            raise ValueError("Missing model name.")

        if self.provider == "OpenAI":
            return self._openai_request(system_prompt, user_payload, schema_name, schema)
        elif self.provider == "OpenRouter":
            return self._openrouter_request(system_prompt, user_payload, schema_name, schema)
        else:
            raise ValueError("Unsupported AI provider: %s" % self.provider)

    def _openai_request(self, system_prompt, user_payload, schema_name, schema):
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {"type": "input_text", "text": system_prompt}
                    ]
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": json.dumps(user_payload, ensure_ascii=False)}
                    ]
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema
                }
            }
        }

        data = json.dumps(payload).encode("utf-8")

        max_retries = 3
        retry_delays = [5, 15, 30]
        last_error = None

        for attempt in range(max_retries):
            request = urllib.request.Request(
                url="https://api.openai.com/v1/responses",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.api_key
                },
                method="POST"
            )

            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    raw = response.read().decode("utf-8")
                logger.debug("OpenAI response received (%d bytes) on attempt %d.", len(raw), attempt + 1)
                last_error = None
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")
                if e.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning("OpenAI HTTPError %s (attempt %d/%d). Retry in %ds...",
                                   e.code, attempt + 1, max_retries, wait)
                    time.sleep(wait)
                    last_error = RuntimeError("OpenAI HTTPError %s: %s" % (e.code, detail))
                    continue
                logger.error("OpenAI HTTPError %s: %s", e.code, detail)
                raise RuntimeError("OpenAI HTTPError %s: %s" % (e.code, detail))
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning("OpenAI request failed (attempt %d/%d): %s. Retry in %ds...",
                                   attempt + 1, max_retries, e, wait)
                    time.sleep(wait)
                    last_error = RuntimeError("OpenAI request failed: %s" % e)
                    continue
                logger.error("OpenAI request failed after %d attempts: %s", max_retries, e)
                raise RuntimeError("OpenAI request failed: %s" % e)

        if last_error:
            raise last_error

        response_json = json.loads(raw)

        if "output_text" in response_json and response_json["output_text"]:
            text = response_json["output_text"]
            return json.loads(text)

        # fallback parsing
        output = response_json.get("output", [])
        for item in output:
            content = item.get("content", [])
            for part in content:
                if part.get("type") == "output_text":
                    return json.loads(part.get("text", ""))

        raise RuntimeError("Could not parse structured OpenAI response.")

    def _openrouter_request(self, system_prompt, user_payload, schema_name, schema):
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False)
                }
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema
                }
            }
        }

        data = json.dumps(payload).encode("utf-8")

        max_retries = 3
        retry_delays = [5, 15, 30]
        last_error = None

        for attempt in range(max_retries):
            request = urllib.request.Request(
                url="https://openrouter.ai/api/v1/chat/completions",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + self.api_key,
                    "HTTP-Referer": "https://github.com/mcard/DirReOrg", # Required by OpenRouter
                    "X-Title": "DirReOrg AI Analyzer"
                },
                method="POST"
            )

            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    raw = response.read().decode("utf-8")
                logger.debug("OpenRouter response received (%d bytes) on attempt %d.", len(raw), attempt + 1)
                last_error = None
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")
                if e.code in (429, 500, 502, 503) and attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning("OpenRouter HTTPError %s (attempt %d/%d). Retry in %ds...",
                                   e.code, attempt + 1, max_retries, wait)
                    time.sleep(wait)
                    last_error = RuntimeError("OpenRouter HTTPError %s: %s" % (e.code, detail))
                    continue
                logger.error("OpenRouter HTTPError %s: %s", e.code, detail)
                raise RuntimeError("OpenRouter HTTPError %s: %s" % (e.code, detail))
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = retry_delays[attempt]
                    logger.warning("OpenRouter request failed (attempt %d/%d): %s. Retry in %ds...",
                                   attempt + 1, max_retries, e, wait)
                    time.sleep(wait)
                    last_error = RuntimeError("OpenRouter request failed: %s" % e)
                    continue
                logger.error("OpenRouter request failed after %d attempts: %s", max_retries, e)
                raise RuntimeError("OpenRouter request failed: %s" % e)

        if last_error:
            raise last_error

        response_json = json.loads(raw)

        try:
            content = response_json["choices"][0]["message"]["content"]
            if content.startswith("```json"):
                content = content[7:-3].strip()
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error("Failed to parse OpenRouter response: %s\nRaw response: %s", e, raw)
            raise RuntimeError("Could not parse structured OpenRouter response.")


class AIPlanner(object):
    def __init__(self, settings, profile=None):
        self.settings = settings
        self.profile = profile or _DEFAULT_PROFILE
        self.client = AIClient(settings.provider, settings.api_key, settings.model)

    def _folder_context_text(self):
        """Build a textual description of the folder model for AI prompts."""
        lines = ["FOLDER MODEL (%s):" % self.profile.name]
        for f in self.profile.folders:
            lines.append("- %s: %s" % (f.name, f.description))
            if f.subfolders:
                lines.append("  Subfolders: %s" % ", ".join(f.subfolders))
            if f.examples:
                lines.append("  Examples: %s" % "; ".join(f.examples[:4]))
        lines.append("")
        lines.append("DECISION GUIDE (ask in order):")
        for item in self.profile.decision_guide:
            lines.append("- %s -> %s" % (item["question"], item["folder"]))
        return "\n".join(lines)

    def strategic_schema(self):
        return {
            "type": "object",
            "properties": {
                "proposed_taxonomy": {
                    "type": "object",
                    "properties": {
                        "top_levels": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "notes": {"type": "string"}
                    },
                    "required": ["top_levels", "notes"],
                    "additionalProperties": False
                },
                "candidate_rules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "match_hint": {"type": "string"},
                            "action": {"type": "string"},
                            "target_rel": {"type": "string"},
                            "reason": {"type": "string"}
                        },
                        "required": ["name", "match_hint", "action", "target_rel", "reason"],
                        "additionalProperties": False
                    }
                },
                "strategic_notes": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["proposed_taxonomy", "candidate_rules", "strategic_notes"],
            "additionalProperties": False
        }

    def operational_schema(self):
        return {
            "type": "object",
            "properties": {
                "file_decisions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_path": {"type": "string"},
                            "action": {"type": "string"},
                            "target_rel_path": {"type": "string"},
                            "reason": {"type": "string"},
                            "confidence": {"type": "number"},
                            "needs_review": {"type": "boolean"}
                        },
                        "required": ["source_path", "action", "target_rel_path", "reason", "confidence", "needs_review"],
                        "additionalProperties": False
                    }
                },
                "batch_notes": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["file_decisions", "batch_notes"],
            "additionalProperties": False
        }

    def build_inventory_summary(self, records):
        top_folders = {}
        ext_counts = {}
        date_min = ""
        date_max = ""

        for record in records:
            top_folders.setdefault(record.top_folder, {
                "count": 0,
                "sample_paths": [],
                "sample_names": [],
                "extensions": {}
            })

            top_folders[record.top_folder]["count"] += 1

            if len(top_folders[record.top_folder]["sample_paths"]) < 6:
                top_folders[record.top_folder]["sample_paths"].append(record.relative_path)

            if len(top_folders[record.top_folder]["sample_names"]) < 12:
                top_folders[record.top_folder]["sample_names"].append(record.name)

            ext = record.extension.lower() or "[none]"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            top_folders[record.top_folder]["extensions"][ext] = top_folders[record.top_folder]["extensions"].get(ext, 0) + 1

            if record.modified_at:
                if not date_min or record.modified_at < date_min:
                    date_min = record.modified_at
                if not date_max or record.modified_at > date_max:
                    date_max = record.modified_at

        summary = {
            "total_files": len(records),
            "allowed_top_levels": self.profile.top_level_names(),
            "global_extension_counts": ext_counts,
            "modified_range": {"min": date_min, "max": date_max},
            "top_folder_summary": top_folders
        }
        return summary

    def strategic_pass(self, records, objectives):
        summary = self.build_inventory_summary(records)

        folder_context = self._folder_context_text()

        system_prompt = (
            "You are a file-organization analyst for a corporate training department. "
            "Your job is to propose a clean reorganization strategy for work documents. "
            "Never propose destructive actions. "
            "Stay within the provided allowed top-level folders. When uncertain, use 99_Inbox. "
            "Focus on reducing cognitive friction: human-readable names, few entry points, obvious rules. "
            "Focus on archival clarity, future maintainability, and findability by people unfamiliar with the old structure.\n\n"
            "CRITICAL: All notes, strategic explanations, and reasons MUST be written in Italian.\n\n"
            + folder_context
        )

        user_payload = {
            "objectives": objectives,
            "inventory_summary": summary
        }

        return self.client.responses_structured(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema_name="strategic_reorganization_plan",
            schema=self.strategic_schema()
        )

    def operational_pass_chunk(self, records_chunk, objectives, strategic_plan):
        compact_records = []
        for record in records_chunk:
            item = {
                "source_path": record.source_path,
                "relative_path": record.relative_path,
                "name": record.name,
                "extension": record.extension,
                "top_folder": record.top_folder,
                "risk_flags": record.risk_flags
            }
            if self.settings.include_size:
                item["size_bytes"] = record.size_bytes
            if self.settings.include_dates:
                item["modified_at"] = record.modified_at
            compact_records.append(item)

        folder_context = self._folder_context_text()

        system_prompt = (
            "You are a file reorganization planner for a corporate training department. "
            "For each file, propose an action and a target relative path. "
            "Use only these actions: move, archive, review, quarantine, rename. "
            "Default to review when confidence is low or ambiguity is high. "
            "Do not invent filesystem changes outside the allowed top-level structure. "
            "Target paths must include the filename. "
            "Do not change filename unless there is a very strong reason. "
            "This is only a proposal, not execution.\n\n"
            "CRITICAL: The 'reason' field MUST be written in Italian. Explain your choice in brief Italian.\n\n"
            + folder_context
        )

        user_payload = {
            "objectives": objectives,
            "allowed_top_levels": self.profile.top_level_names(),
            "decision_guide": self.profile.decision_guide,
            "strategic_plan": strategic_plan,
            "records": compact_records
        }

        return self.client.responses_structured(
            system_prompt=system_prompt,
            user_payload=user_payload,
            schema_name="operational_reorganization_plan",
            schema=self.operational_schema()
        )

    def generate_ai_plan(self, records, objectives, progress_callback=None):
        strategic = None
        if self.settings.strategic_enabled:
            if progress_callback:
                progress_callback("AI strategic analysis...")
            strategic = self.strategic_pass(records, objectives)
        else:
            strategic = {
                "proposed_taxonomy": {"top_levels": DEFAULT_TOP_LEVELS, "notes": ""},
                "candidate_rules": [],
                "strategic_notes": []
            }

        decisions = []
        chunks = chunk_list(records, self.settings.max_chunk_size)
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            if progress_callback:
                progress_callback("AI file analysis chunk %d/%d..." % (i + 1, total), i + 1, total)
            result = self.operational_pass_chunk(chunk, objectives, strategic)
            decisions.extend(result.get("file_decisions", []))

        return {
            "strategic": strategic,
            "file_decisions": decisions
        }


# =========================
# Execution / Rollback
# =========================

class OperationExecutor(object):
    def __init__(self, root, log_dir):
        self.root = root
        self.log_dir = log_dir
        ensure_dir(self.log_dir)

    def validate_plan(self, plans):
        errors = []
        seen_targets = set()

        for plan in plans:
            src = Path(plan.source_path)
            if not src.exists():
                errors.append("Missing source: %s" % plan.source_path)
                continue

            if plan.action in ("move", "archive", "rename", "quarantine"):
                if not plan.target_path:
                    errors.append("Missing target for: %s" % plan.source_path)
                    continue

                try:
                    src.resolve().relative_to(self.root.resolve())
                except Exception:
                    errors.append("Source outside root: %s" % plan.source_path)

                dst = Path(plan.target_path)
                dst_key = str(dst).lower()

                if dst_key in seen_targets:
                    errors.append("Duplicate target in plan: %s" % plan.target_path)
                seen_targets.add(dst_key)

                if len(str(dst)) > 240:
                    errors.append("Long target path risk: %s" % plan.target_path)

        return errors

    def execute(self, plans, dry_run=True):
        logger.info("Executing plan: %d operations, dry_run=%s", len(plans), dry_run)
        timestamp = now_compact()
        manifest_json = self.log_dir / ("manifest_%s.json" % timestamp)
        manifest_csv = self.log_dir / ("manifest_%s.csv" % timestamp)

        manifest_rows = []

        for plan in plans:
            row = {
                "timestamp": now_str(),
                "source_path": plan.source_path,
                "action": plan.action,
                "target_path": plan.target_path,
                "relative_target_path": plan.relative_target_path,
                "status": "planned",
                "message": "",
                "rollback_source": "",
                "rollback_target": "",
                "dry_run": dry_run
            }

            try:
                src = Path(plan.source_path)

                if plan.action == "review":
                    row["status"] = "skipped"
                    row["message"] = "review_only"
                    manifest_rows.append(row)
                    continue

                if plan.action in ("move", "archive", "quarantine", "rename"):
                    dst = Path(plan.target_path)
                    dst = unique_target_path(dst)

                    if dry_run:
                        row["status"] = "dry_run"
                        row["target_path"] = str(dst)
                        row["rollback_source"] = str(dst)
                        row["rollback_target"] = str(src)
                    else:
                        ensure_dir(dst.parent)
                        shutil.move(str(src), str(dst))
                        row["status"] = "done"
                        row["target_path"] = str(dst)
                        row["rollback_source"] = str(dst)
                        row["rollback_target"] = str(src)
                else:
                    row["status"] = "skipped"
                    row["message"] = "unknown_action:%s" % plan.action

            except Exception as e:
                row["status"] = "error"
                row["message"] = "%s: %s" % (type(e).__name__, e)
                logger.error("Execution error for %s: %s", plan.source_path, e)

            manifest_rows.append(row)

        with manifest_json.open("w", encoding="utf-8") as f:
            json.dump(manifest_rows, f, ensure_ascii=False, indent=2)

        if manifest_rows:
            fieldnames = list(manifest_rows[0].keys())
        else:
            fieldnames = [
                "timestamp", "source_path", "action", "target_path", "relative_target_path",
                "status", "message", "rollback_source", "rollback_target", "dry_run"
            ]

        with manifest_csv.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in manifest_rows:
                writer.writerow(row)

        logger.info("Execution complete. Manifest: %s", manifest_json)
        return manifest_json, manifest_csv

    def rollback(self, manifest_json_path, dry_run=True):
        logger.info("Starting rollback from: %s, dry_run=%s", manifest_json_path, dry_run)
        with manifest_json_path.open("r", encoding="utf-8") as f:
            rows = json.load(f)

        done = 0
        errors = 0
        messages = []

        for row in rows:
            if row.get("status") != "done":
                continue

            src = row.get("rollback_source")
            dst = row.get("rollback_target")

            if not src or not dst:
                continue

            try:
                src_p = Path(src)
                dst_p = Path(dst)

                if not src_p.exists():
                    messages.append("Skip missing rollback source: %s" % src)
                    continue

                if dry_run:
                    done += 1
                    messages.append("DRY-RUN rollback: %s -> %s" % (src, dst))
                else:
                    ensure_dir(dst_p.parent)
                    dst_p = unique_target_path(dst_p)
                    shutil.move(str(src_p), str(dst_p))
                    done += 1
                    messages.append("Rolled back: %s -> %s" % (src, str(dst_p)))

            except Exception as e:
                errors += 1
                messages.append("Rollback error for %s: %s: %s" % (src, type(e).__name__, e))

        return done, errors, messages


# =========================
# CSV Export/Import
# =========================

def export_inventory_csv(records, output_path):
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_path", "relative_path", "name", "extension", "size_bytes", "modified_at",
                "top_folder", "suggested_action", "suggested_target_rel", "risk_flags", "selected",
                "decision_source", "ai_reason", "ai_confidence", "needs_review"
            ]
        )
        writer.writeheader()
        for record in records:
            row = asdict(record)
            row["risk_flags"] = "|".join(record.risk_flags)
            writer.writerow(row)


def export_plan_csv(plans, output_path):
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "source_path", "action", "target_path", "relative_target_path", "status", "message"
            ]
        )
        writer.writeheader()
        for plan in plans:
            writer.writerow(asdict(plan))


def import_plan_csv(csv_path):
    plans = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            plans.append(
                OperationPlan(
                    source_path=row.get("source_path", ""),
                    action=row.get("action", "review"),
                    target_path=row.get("target_path", ""),
                    relative_target_path=row.get("relative_target_path", ""),
                    status=row.get("status", "planned"),
                    message=row.get("message", "")
                )
            )
    return plans


# =========================
# GUI Dialogs
# =========================

class HelpWindow(tk.Toplevel):
    def __init__(self, master, profile=None):
        tk.Toplevel.__init__(self, master)
        self.title("Guida - Come usare il tool")
        self.geometry("1020x820")
        self.transient(master)
        self.grab_set()

        self.profile = profile or _DEFAULT_PROFILE

        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)

        title = ttk.Label(
            container,
            text="Guida rapida: flusso locale + livello AI",
            font=("Segoe UI", 14, "bold")
        )
        title.pack(anchor="w", pady=(0, 10))

        help_text = self._build_help_text()

        text = tk.Text(container, wrap="word", font=("Segoe UI", 10))
        text.pack(fill="both", expand=True)
        text.insert("1.0", help_text)
        text.config(state="disabled")

        btns = ttk.Frame(container)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Chiudi", command=self.destroy).pack(side="right")

    def _build_help_text(self):
        p = self.profile
        sections = []

        # Scope
        sections.append(
            "SCOPO DEL REPOSITORY\n"
            "Profilo attivo: %s\n"
            "%s\n\n" % (p.name, p.description)
        )

        # Workflow
        sections.append(
            "FLUSSO CONSIGLIATO\n"
            "1. Seleziona la root\n"
            "2. Scansiona la cartella\n"
            "3. Facoltativo: crea anteprima con regole locali\n"
            "4. Configura AI\n"
            "5. Genera piano con AI\n"
            "6. Controlla action, target, confidence e reason\n"
            "7. Correggi manualmente le righe dubbie\n"
            "8. Esegui prima in Dry Run\n"
            "9. Solo dopo fai una prova reale su una porzione limitata\n\n"
        )

        # Folder descriptions
        sections.append("STRUTTURA CARTELLE\n")
        for f in p.folders:
            sections.append("%s\n" % f.name)
            sections.append("  %s\n" % f.description)
            sections.append("  Domanda: %s\n" % f.question)
            if f.subfolders:
                sections.append("  Sottocartelle: %s\n" % ", ".join(f.subfolders))
            if f.examples:
                sections.append("  Esempi: %s\n" % "; ".join(f.examples[:4]))
            sections.append("\n")

        # Decision guide
        sections.append("DOVE SALVARE UN FILE?\n")
        for item in p.decision_guide:
            sections.append("  %s \u2192 %s\n" % (item["question"], item["folder"]))
        sections.append("\n")

        # Rules
        sections.append(
            "REGOLE D'USO\n"
            "\u2022 Niente file in root\n"
            "\u2022 Niente nomi vaghi (\"varie\", \"temp\", \"stuff\")\n"
            "\u2022 99_Inbox va svuotata periodicamente\n"
            "\u2022 Versioni coerenti — evitare \"v2_final_FINAL\"\n"
            "\u2022 Archivio separato — se il file non \u00e8 pi\u00f9 attivo, va in 90_Archive\n"
            "\u2022 Usare la sottocartella progetto quando il file \u00e8 legato a un training specifico\n\n"
        )

        # Filing examples
        sections.append(
            "ESEMPI CONCRETI\n"
            "\u2022 Deck finale training Grecale \u2192 02_Training_Projects\\Commercial\\Grecale\\Final\n"
            "\u2022 Lista partecipanti sessione APAC \u2192 03_Training_Delivery\\Regions\\APAC\n"
            "\u2022 Report mensile attendance \u2192 04_Reports_and_Budget\\Reports\n"
            "\u2022 Template email dealer invitation \u2192 05_Shared_Resources\\Templates\n"
            "\u2022 Vecchio training Levante 2022 \u2192 90_Archive\\Training_Projects\n"
            "\u2022 Export chat Teams appena ricevuto \u2192 99_Inbox\n\n"
        )

        # AI + safety
        sections.append(
            "COME FUNZIONA L'AI\n"
            "Passo strategico:\n"
            "- riceve una sintesi dell'albero e il modello cartelle\n"
            "- propone tassonomia e note strategiche\n\n"
            "Passo operativo:\n"
            "- riceve chunk di file con metadati + guida decisionale\n"
            "- restituisce decisioni file-per-file con confidence e motivazione\n\n"
            "PRINCIPIO DI SICUREZZA\n"
            "AI = proposta.\n"
            "Motore locale = validazione + esecuzione.\n"
            "Questa separazione evita danni stupidi."
        )

        return "".join(sections)


class AISettingsDialog(tk.Toplevel):
    def __init__(self, master, settings):
        tk.Toplevel.__init__(self, master)
        self.title("Configura AI")
        self.geometry("640x360")
        self.transient(master)
        self.grab_set()

        self.result = None
        self.settings = settings

        self.provider_var = tk.StringVar(value=settings.provider)
        self.api_key_var = tk.StringVar(value=settings.api_key)
        self.model_var = tk.StringVar(value=settings.model)
        self.max_chunk_var = tk.StringVar(value=str(settings.max_chunk_size))
        self.threshold_var = tk.StringVar(value=str(settings.confidence_threshold))
        self.include_size_var = tk.BooleanVar(value=settings.include_size)
        self.include_dates_var = tk.BooleanVar(value=settings.include_dates)
        self.strategic_var = tk.BooleanVar(value=settings.strategic_enabled)

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="API Provider:").grid(row=0, column=0, sticky="w", pady=4)
        self.provider_combo = ttk.Combobox(frame, textvariable=self.provider_var, values=["OpenAI", "OpenRouter"], state="readonly", width=30)
        self.provider_combo.grid(row=0, column=1, sticky="w", pady=4)
        self.provider_combo.bind("<<ComboboxSelected>>", self.on_provider_change)

        ttk.Label(frame, text="API Key:").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.api_key_var, width=70, show="*").grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(frame, text="Model:").grid(row=2, column=0, sticky="w", pady=4)
        self.model_combo = ttk.Combobox(frame, textvariable=self.model_var, width=40)
        self.model_combo.grid(row=2, column=1, sticky="w", pady=4)
        # Initialize model values based on current provider
        self.on_provider_change()

        ttk.Label(frame, text="Chunk size:").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.max_chunk_var, width=12).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Confidence threshold:").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.threshold_var, width=12).grid(row=4, column=1, sticky="w", pady=4)

        ttk.Checkbutton(frame, text="Include size metadata", variable=self.include_size_var).grid(row=5, column=1, sticky="w", pady=4)
        ttk.Checkbutton(frame, text="Include modified date metadata", variable=self.include_dates_var).grid(row=6, column=1, sticky="w", pady=4)
        ttk.Checkbutton(frame, text="Enable strategic pass before file analysis", variable=self.strategic_var).grid(row=7, column=1, sticky="w", pady=4)

        note = (
            "Questo pannello configura solo il livello di proposta AI.\n"
            "L'esecuzione dei file rimane locale e separata."
        )
        ttk.Label(frame, text=note, foreground="#555555").grid(row=8, column=0, columnspan=2, sticky="w", pady=(12, 8))

        btns = ttk.Frame(frame)
        btns.grid(row=9, column=0, columnspan=2, sticky="e", pady=(18, 0))

        ttk.Button(btns, text="Annulla", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Salva", command=self.on_save).pack(side="right", padx=4)

        frame.columnconfigure(1, weight=1)

    def on_provider_change(self, event=None):
        provider = self.provider_var.get()
        if provider == "OpenAI":
            self.model_combo['values'] = ["gpt-4o", "gpt-4o-mini", "o1-mini", "o3-mini"]
            if event: # Only autoselect if user triggered the change
                self.model_var.set("gpt-4o")
        elif provider == "OpenRouter":
            self.model_combo['values'] = [
                "openai/gpt-4o",
                "openai/gpt-4o-mini",
                "anthropic/claude-3.5-sonnet",
                "google/gemini-2.5-flash",
                "meta-llama/llama-3.3-70b-instruct"
            ]
            if event:
                self.model_var.set("openai/gpt-4o")

    def on_save(self):
        try:
            chunk_size = int(self.max_chunk_var.get().strip())
            threshold = float(self.threshold_var.get().strip())
        except Exception:
            messagebox.showerror("Valori non validi", "Chunk size deve essere intero. Confidence threshold deve essere numerico.")
            return

        self.result = AISettings(
            provider=self.provider_var.get().strip(),
            api_key=self.api_key_var.get().strip(),
            model=self.model_var.get().strip(),
            max_chunk_size=chunk_size,
            confidence_threshold=threshold,
            include_size=self.include_size_var.get(),
            include_dates=self.include_dates_var.get(),
            strategic_enabled=self.strategic_var.get()
        )
        self.destroy()


class ProfileViewerDialog(tk.Toplevel):
    """Dialog to view, export, import, and reset the organization profile."""
    def __init__(self, master, profile):
        tk.Toplevel.__init__(self, master)
        self.title("\U0001F4C2 Profilo organizzativo")
        self.geometry("780x620")
        self.transient(master)
        self.grab_set()

        self.result = None
        self.profile = profile

        container = ttk.Frame(self, padding=14)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Profilo: %s" % profile.name,
            font=("Segoe UI", 13, "bold")
        ).pack(anchor="w", pady=(0, 4))

        ttk.Label(
            container,
            text=profile.description,
            foreground="#555555",
            wraplength=720
        ).pack(anchor="w", pady=(0, 10))

        # Profile summary
        summary_lines = []
        summary_lines.append("Cartelle top-level: %d" % len(profile.folders))
        for f in profile.folders:
            subs = " (%s)" % ", ".join(f.subfolders) if f.subfolders else ""
            summary_lines.append("  %s%s" % (f.name, subs))
        summary_lines.append("")
        summary_lines.append("Regole di classificazione: %d" % len(profile.rules))
        summary_lines.append("")
        summary_lines.append("Guida decisionale:")
        for item in profile.decision_guide:
            summary_lines.append("  %s \u2192 %s" % (item["question"], item["folder"]))

        text = tk.Text(container, wrap="word", font=("Segoe UI", 10))
        text.pack(fill="both", expand=True, pady=(0, 10))
        text.insert("1.0", "\n".join(summary_lines))
        text.config(state="disabled")

        btns = ttk.Frame(container)
        btns.pack(fill="x")

        ttk.Button(btns, text="Esporta profilo JSON", command=self._export).pack(side="left", padx=4)
        ttk.Button(btns, text="Importa profilo JSON", command=self._import).pack(side="left", padx=4)
        ttk.Button(btns, text="Ripristina default", command=self._reset).pack(side="left", padx=4)
        ttk.Button(btns, text="Chiudi", command=self.destroy).pack(side="right", padx=4)

    def _export(self):
        path = filedialog.asksaveasfilename(
            title="Esporta profilo",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
            initialfile="profile_%s.json" % self.profile.name.replace(" ", "_").lower()
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.profile.to_dict(), f, ensure_ascii=False, indent=2)
            messagebox.showinfo("Esportato", "Profilo esportato in:\n%s" % path)
        except Exception as e:
            messagebox.showerror("Errore", "Impossibile esportare: %s" % e)

    def _import(self):
        path = filedialog.askopenfilename(
            title="Importa profilo",
            filetypes=[("JSON files", "*.json")]
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            new_profile = OrganizationProfile.from_dict(data)
            if not new_profile.folders:
                messagebox.showerror("Profilo non valido", "Il profilo non contiene cartelle.")
                return
            self.result = new_profile
            messagebox.showinfo("Importato", "Profilo \"%s\" caricato. Chiudi per applicare." % new_profile.name)
        except Exception as e:
            messagebox.showerror("Errore", "Impossibile importare: %s" % e)

    def _reset(self):
        if messagebox.askyesno("Ripristina default", "Ripristinare il profilo Maserati Academy di default?"):
            self.result = build_default_masaca_profile()
            messagebox.showinfo("Ripristinato", "Profilo default ripristinato. Chiudi per applicare.")


class TargetSelectionDialog(tk.Toplevel):
    def __init__(self, master, profile, file_count):
        tk.Toplevel.__init__(self, master)
        self.title("Imposta Target Destinazione")
        self.geometry("500x380")
        self.transient(master)
        self.grab_set()

        self.result = None
        self.profile = profile

        frame = ttk.Frame(self, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame, 
            text="Spostamento di %d file" % file_count, 
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(0, 10))

        ttk.Label(frame, text="1. Scegli la cartella principale:").pack(anchor="w", pady=(0, 4))
        
        self.top_folder_var = tk.StringVar()
        top_folders = [f.name for f in self.profile.folders]
        if top_folders:
            self.top_folder_var.set(top_folders[0])
            
        self.combo = ttk.Combobox(frame, textvariable=self.top_folder_var, values=top_folders, state="readonly", width=40)
        self.combo.pack(anchor="w", pady=(0, 15))

        ttk.Label(frame, text="2. Aggiungi percorso interno (opzionale):").pack(anchor="w", pady=(0, 4))
        self.sub_folder_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.sub_folder_var, width=50).pack(anchor="w", pady=(0, 4))
        
        ttk.Label(
            frame, 
            text="Esempio: scrivendo 'Progetto\\Grecale', il file andrà in\n[Cartella Principale]\\Progetto\\Grecale\\[NomeFile]",
            foreground="#666666",
            font=("Segoe UI", 9)
        ).pack(anchor="w", pady=(0, 20))

        btns = ttk.Frame(frame)
        btns.pack(fill="x", side="bottom")

        ttk.Button(btns, text="Annulla", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Applica Target", style="Primary.TButton", command=self.on_apply).pack(side="right", padx=4)

    def on_apply(self):
        top = self.top_folder_var.get().strip()
        sub = self.sub_folder_var.get().strip()

        # Input validation for subfolder
        if sub:
            for ch in ['<', '>', ':', '"', '|', '?', '*']:
                if ch in sub:
                    messagebox.showerror(
                        "Caratteri non validi",
                        "Il percorso contiene un carattere non valido: '%s'" % ch
                    )
                    return
            if '..' in sub:
                messagebox.showerror("Percorso non valido", "Il percorso non può contenere '..'")
                return

        path = top
        if sub:
            path = top + "\\" + sub.strip("\\/")
            
        self.result = normalize_rel_path(path)
        self.destroy()


# =========================
# Main App
# =========================

class App(tk.Tk):

    # --- Color Palette (Monochrome Elegant) ---
    BG = "#f5f5f5"
    SURFACE = "#ffffff"
    PRIMARY = "#2d2d2d"
    PRIMARY_DARK = "#1a1a1a"
    ACCENT = "#525252"
    TEXT = "#1a1a1a"
    TEXT_MUTED = "#737373"
    BORDER = "#d4d4d4"
    SUCCESS = "#4a7c59"
    WARNING = "#a16207"
    DANGER = "#b91c1c"
    BTN_FACE = "#e8e8e8"
    BTN_ACTIVE = "#d4d4d4"
    BTN_PRESSED = "#bfbfbf"
    BTN_PRIMARY = "#2d2d2d"
    BTN_DANGER = "#991b1b"
    ROW_EVEN = "#ffffff"
    ROW_ODD = "#fafafa"
    RISK_BG = "#fef2f2"
    REVIEW_BG = "#fefce8"
    AI_BG = "#f5f5f5"
    PAGE_SIZES = [50, 100, 500, 1000]

    def __init__(self):
        tk.Tk.__init__(self)

        self.title("%s %s" % (APP_NAME, APP_VERSION))
        self.geometry("1680x930")
        self.minsize(1360, 780)

        self.root_dir = tk.StringVar()
        self.status_var = tk.StringVar(value="Pronto.")
        self.filter_var = tk.StringVar()
        self.dry_run_var = tk.BooleanVar(value=True)

        self.records = []
        self.plans = []
        self.profile = _DEFAULT_PROFILE
        self.rule_engine = RuleEngine(self.profile.rules)
        self.stop_requested = False
        self.ai_settings = AISettings()
        self.objectives_text = DEFAULT_OBJECTIVES
        self.last_ai_strategic = None

        # Pagination
        self.page_size = 500
        self.current_page = 0
        self.filtered_records = []
        self.page_label_var = tk.StringVar(value="")
        self.page_size_var = tk.StringVar(value="500")

        # Undo / Redo
        self.undo_stack = []
        self.redo_stack = []

        self._apply_theme()
        self._load_settings()
        self._build_ui()
        logger.info("Application started (v%s). Profile: %s. Log file: %s", APP_VERSION, self.profile.name, _LOG_FILE)

    def _apply_theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        self.configure(bg=self.BG)

        style.configure(".", font=("Segoe UI", 10), background=self.BG)
        style.configure("TFrame", background=self.BG)
        style.configure("TLabel", background=self.BG, foreground=self.TEXT)
        style.configure("TLabelframe", background=self.BG, foreground=self.TEXT,
                         bordercolor=self.BORDER)
        style.configure("TLabelframe.Label", background=self.BG, foreground=self.ACCENT,
                         font=("Segoe UI", 10, "bold"))
        style.configure("TCheckbutton", background=self.BG, foreground=self.TEXT)
        style.configure("TEntry", fieldbackground=self.SURFACE, bordercolor=self.BORDER)

        # Buttons — light background, clearly readable
        style.configure("TButton", font=("Segoe UI", 9), padding=(10, 5),
                         background=self.BTN_FACE, foreground=self.TEXT)
        style.map("TButton",
                  background=[("active", self.BTN_ACTIVE), ("pressed", self.BTN_PRESSED)])

        style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"),
                         background=self.BTN_PRIMARY, foreground="#ffffff")
        style.map("Primary.TButton",
                  background=[("active", "#404040"), ("pressed", "#1a1a1a")],
                  foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])

        style.configure("Danger.TButton", font=("Segoe UI", 9, "bold"),
                         background=self.BTN_DANGER, foreground="#ffffff")
        style.map("Danger.TButton",
                  background=[("active", "#b91c1c"), ("pressed", "#7f1d1d")],
                  foreground=[("active", "#ffffff"), ("pressed", "#ffffff")])

        style.configure("Small.TButton", font=("Segoe UI", 8), padding=(6, 3),
                         background=self.BTN_FACE, foreground=self.TEXT)
        style.map("Small.TButton",
                  background=[("active", self.BTN_ACTIVE), ("pressed", self.BTN_PRESSED)])

        # Headers
        style.configure("Header.TLabel", font=("Segoe UI", 18, "bold"),
                         foreground=self.PRIMARY_DARK, background=self.BG)
        style.configure("SubHeader.TLabel", font=("Segoe UI", 10),
                         foreground=self.TEXT_MUTED, background=self.BG)
        style.configure("Credits.TLabel", font=("Segoe UI", 8),
                         foreground="#a3a3a3", background=self.BG)
        style.configure("Workflow.TLabel", font=("Segoe UI", 9, "bold"),
                         foreground=self.ACCENT, background=self.BG)
        style.configure("Legend.TLabel", font=("Segoe UI", 8, "italic"),
                         foreground=self.TEXT_MUTED, background=self.BG)

        # Progress bar
        style.configure("TProgressbar", troughcolor=self.BORDER,
                         background=self.ACCENT, thickness=5)

        # Treeview
        style.configure("Treeview", font=("Segoe UI", 9), rowheight=26,
                         background=self.SURFACE, fieldbackground=self.SURFACE,
                         foreground=self.TEXT, borderwidth=0)
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"),
                         background="#e5e5e5", foreground=self.TEXT, relief="flat")
        style.map("Treeview.Heading", background=[("active", "#d4d4d4")])
        style.map("Treeview",
                  background=[("selected", "#404040")],
                  foreground=[("selected", "#ffffff")])

    def _build_ui(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        self._build_header(outer)
        self._build_workflow_box(outer)
        self._build_controls(outer)
        self._build_summary(outer)
        self._build_tree(outer)
        self._build_pagination(outer)
        self._build_bottom_bar(outer)
        self._build_credits(outer)

    def _build_header(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(0, 10))

        ttk.Label(frame, text=APP_NAME, style="Header.TLabel").pack(side="left")
        ttk.Label(frame, text="v%s" % APP_VERSION, style="SubHeader.TLabel").pack(side="left", padx=(8, 0), pady=(6, 0))

        ttk.Button(frame, text="\u2753 Guida", command=self.open_help).pack(side="right")

    def _build_workflow_box(self, parent):
        lf = ttk.LabelFrame(parent, text="\u2728 Workflow consigliato", padding=10)
        lf.pack(fill="x", pady=(0, 8))

        steps = (
            "\u2460 Scegli root  \u2794  \u2461 Scansiona  \u2794  \u2462 Preview regole (opz.)  \u2794  "
            "\u2463 Configura AI  \u2794  \u2464 Piano AI  \u2794  \u2465 Rivedi  \u2794  "
            "\u2466 Dry Run  \u2794  \u2467 Esecuzione reale"
        )
        ttk.Label(lf, text=steps, style="Workflow.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(lf, text=(
            "L\u2019AI propone il piano \u2022 Il motore locale valida ed esegue \u2022 "
            "Confidence bassa \u2192 review automatica"
        ), style="SubHeader.TLabel").pack(anchor="w")

    def _build_controls(self, parent):
        root_box = ttk.LabelFrame(parent, text="\U0001F4C1 Cartella di lavoro", padding=10)
        root_box.pack(fill="x", pady=(0, 8))

        row1 = ttk.Frame(root_box)
        row1.pack(fill="x")

        ttk.Label(row1, text="Root folder:").pack(side="left")
        ttk.Entry(row1, textvariable=self.root_dir, width=90).pack(side="left", padx=6)
        ttk.Button(row1, text="Sfoglia\u2026", command=self.choose_root).pack(side="left", padx=(0, 6))
        ttk.Checkbutton(row1, text="Dry Run", variable=self.dry_run_var).pack(side="left", padx=(12, 0))

        row2 = ttk.Frame(root_box)
        row2.pack(fill="x", pady=(10, 0))

        ttk.Button(row2, text="\u2460 Scansiona", style="Primary.TButton", command=self.scan_root).pack(side="left")
        ttk.Button(row2, text="\u2461 Preview regole", command=self.build_preview).pack(side="left", padx=6)
        ttk.Button(row2, text="\u2462 Configura AI", command=self.configure_ai).pack(side="left", padx=6)
        ttk.Button(row2, text="\u2463 Piano AI", style="Primary.TButton", command=self.generate_ai_plan).pack(side="left", padx=6)
        ttk.Button(row2, text="\u2464 Esegui piano", style="Danger.TButton", command=self.execute_plan).pack(side="left", padx=6)
        ttk.Button(row2, text="\u2465 Rollback", command=self.rollback_manifest).pack(side="left", padx=6)

        row3 = ttk.Frame(root_box)
        row3.pack(fill="x", pady=(10, 0))

        ttk.Button(row3, text="Esporta inventario CSV", style="Small.TButton", command=self.export_inventory).pack(side="left")
        ttk.Button(row3, text="Esporta piano CSV", style="Small.TButton", command=self.export_plan).pack(side="left", padx=4)
        ttk.Button(row3, text="Importa piano CSV", style="Small.TButton", command=self.import_plan).pack(side="left", padx=4)
        ttk.Button(row3, text="Salva regole JSON", style="Small.TButton", command=self.save_rules).pack(side="left", padx=4)
        ttk.Button(row3, text="Carica regole JSON", style="Small.TButton", command=self.load_rules).pack(side="left", padx=4)

        row4 = ttk.Frame(root_box)
        row4.pack(fill="x", pady=(10, 0))

        ttk.Label(row4, text="\U0001F50D Filtro:").pack(side="left", padx=(0, 4))
        entry_filter = ttk.Entry(row4, textvariable=self.filter_var, width=40)
        entry_filter.pack(side="left")
        entry_filter.bind("<KeyRelease>", lambda e: self._filter_changed())

        ttk.Button(row4, text="Imposta target selezionate", command=self.override_target_for_selected).pack(side="left", padx=8)
        ttk.Button(row4, text="Imposta azione selezionate", command=self.override_action_for_selected).pack(side="left")

    def _build_summary(self, parent):
        frame = ttk.LabelFrame(parent, text="\U0001F4CA Riepilogo", padding=8)
        frame.pack(fill="x", pady=(0, 6))

        self.summary_label = ttk.Label(frame, text="Nessun dato caricato.")
        self.summary_label.pack(anchor="w")

        self.legend_label = ttk.Label(
            frame,
            text=(
                "review = revisione manuale \u2022 move = spostamento \u2022 archive = archivio \u2022 "
                "quarantine = quarantena \u2022 Source dec. = rule / ai / manual"
            ),
            style="Legend.TLabel"
        )
        self.legend_label.pack(anchor="w", pady=(4, 0))

    def _build_tree(self, parent):
        columns = (
            "selected", "source_path", "action", "relative_target_path",
            "decision_source", "ai_confidence", "ai_reason",
            "size_bytes", "modified_at", "top_folder", "risk_flags"
        )

        frame = ttk.LabelFrame(parent, text="\U0001F4CB Piano corrente", padding=6)
        frame.pack(fill="both", expand=True, pady=(0, 4))

        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("selected", text="Sel")
        self.tree.heading("source_path", text="Percorso sorgente")
        self.tree.heading("action", text="Azione")
        self.tree.heading("relative_target_path", text="Target proposto")
        self.tree.heading("decision_source", text="Origine dec.")
        self.tree.heading("ai_confidence", text="Confidence")
        self.tree.heading("ai_reason", text="Motivazione")
        self.tree.heading("size_bytes", text="Dimensione")
        self.tree.heading("modified_at", text="Ultima modifica")
        self.tree.heading("top_folder", text="Top folder")
        self.tree.heading("risk_flags", text="Rischi")

        self.tree.column("selected", width=40, anchor="center")
        self.tree.column("source_path", width=370)
        self.tree.column("action", width=80, anchor="center")
        self.tree.column("relative_target_path", width=310)
        self.tree.column("decision_source", width=85, anchor="center")
        self.tree.column("ai_confidence", width=80, anchor="center")
        self.tree.column("ai_reason", width=250)
        self.tree.column("size_bytes", width=90, anchor="e")
        self.tree.column("modified_at", width=130)
        self.tree.column("top_folder", width=130)
        self.tree.column("risk_flags", width=180)

        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.tree.tag_configure("risk", background=self.RISK_BG)
        self.tree.tag_configure("review", background=self.REVIEW_BG)
        self.tree.tag_configure("ai", background=self.AI_BG)
        self.tree.tag_configure("oddrow", background=self.ROW_ODD)

    def _build_pagination(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(2, 4))

        ttk.Button(frame, text="\u23EE", style="Small.TButton", width=3, command=self._page_first).pack(side="left")
        ttk.Button(frame, text="\u25C0", style="Small.TButton", width=3, command=self._page_prev).pack(side="left", padx=2)
        ttk.Label(frame, textvariable=self.page_label_var).pack(side="left", padx=8)
        ttk.Button(frame, text="\u25B6", style="Small.TButton", width=3, command=self._page_next).pack(side="left", padx=2)
        ttk.Button(frame, text="\u23ED", style="Small.TButton", width=3, command=self._page_last).pack(side="left")

        ttk.Label(frame, text="   File/pagina:").pack(side="left", padx=(16, 4))
        page_combo = ttk.Combobox(frame, textvariable=self.page_size_var,
                                   values=["50", "100", "500", "1000"], width=6, state="readonly")
        page_combo.pack(side="left")
        page_combo.bind("<<ComboboxSelected>>", lambda e: self._on_page_size_change())

    def _build_bottom_bar(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(4, 2))

        # Selection buttons
        ttk.Button(frame, text="Inverti selezione", style="Small.TButton",
                   command=self.toggle_selected_rows).pack(side="left")
        ttk.Button(frame, text="Sel. tutto", style="Small.TButton",
                   command=self.select_all).pack(side="left", padx=3)
        ttk.Button(frame, text="Desel. tutto", style="Small.TButton",
                   command=self.select_none).pack(side="left", padx=3)

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y", padx=8)

        # Undo / Redo
        self.undo_btn = ttk.Button(frame, text="\u21A9 Annulla", style="Small.TButton",
                                    command=self.undo, state="disabled")
        self.undo_btn.pack(side="left", padx=2)
        self.redo_btn = ttk.Button(frame, text="\u21AA Ripristina", style="Small.TButton",
                                    command=self.redo, state="disabled")
        self.redo_btn.pack(side="left", padx=2)

        ttk.Separator(frame, orient="vertical").pack(side="left", fill="y", padx=8)

        ttk.Button(frame, text="Obiettivi AI", style="Small.TButton",
                   command=self.edit_objectives).pack(side="left")
        ttk.Button(frame, text="\U0001F4C2 Profilo", style="Small.TButton",
                   command=self.manage_profile).pack(side="left", padx=4)

        # Progress + status (right side)
        self.progress_bar = ttk.Progressbar(frame, length=180, mode="indeterminate")
        self.progress_bar.pack(side="right", padx=(8, 0))
        ttk.Label(frame, textvariable=self.status_var).pack(side="right", padx=8)

    def _build_credits(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=(4, 0))
        ttk.Separator(frame).pack(fill="x", pady=(0, 4))
        ttk.Label(
            frame,
            text="Per info e prenotazioni: Massimo Cardolicchio (massimo.cardolicchio@maserati.com)",
            style="Credits.TLabel"
        ).pack(anchor="center")

    # ---------- Pagination ----------

    def _filter_changed(self):
        self.current_page = 0
        self.refresh_tree()

    def _page_first(self):
        self.current_page = 0
        self.refresh_tree()

    def _page_prev(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.refresh_tree()

    def _page_next(self):
        total_pages = self._total_pages()
        if self.current_page < total_pages - 1:
            self.current_page += 1
            self.refresh_tree()

    def _page_last(self):
        self.current_page = max(0, self._total_pages() - 1)
        self.refresh_tree()

    def _on_page_size_change(self):
        try:
            self.page_size = int(self.page_size_var.get())
        except ValueError:
            self.page_size = 500
        self.current_page = 0
        self.refresh_tree()

    def _total_pages(self):
        total = len(self.filtered_records)
        if total == 0:
            return 1
        return (total + self.page_size - 1) // self.page_size

    # ---------- Undo / Redo ----------

    def _save_undo_state(self):
        state = copy.deepcopy(self.records)
        self.undo_stack.append(state)
        if len(self.undo_stack) > 30:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self._update_undo_buttons()

    def undo(self):
        if not self.undo_stack:
            return
        self.redo_stack.append(copy.deepcopy(self.records))
        self.records = self.undo_stack.pop()
        self._rebuild_plans_from_records()
        self.refresh_tree()
        self._update_undo_buttons()
        self.status_var.set("Annullato.")
        logger.info("Undo performed.")

    def redo(self):
        if not self.redo_stack:
            return
        self.undo_stack.append(copy.deepcopy(self.records))
        self.records = self.redo_stack.pop()
        self._rebuild_plans_from_records()
        self.refresh_tree()
        self._update_undo_buttons()
        self.status_var.set("Ripristinato.")
        logger.info("Redo performed.")

    def _update_undo_buttons(self):
        self.undo_btn.config(state="normal" if self.undo_stack else "disabled")
        self.redo_btn.config(state="normal" if self.redo_stack else "disabled")

    # ---------- Help / Settings ----------

    def open_help(self):
        HelpWindow(self, profile=self.profile)

    def configure_ai(self):
        dialog = AISettingsDialog(self, self.ai_settings)
        self.wait_window(dialog)
        if dialog.result is not None:
            self.ai_settings = dialog.result
            self._save_settings()
            self.status_var.set("Configurazione AI aggiornata e salvata.")

    def edit_objectives(self):
        current = self.objectives_text
        text = simpledialog.askstring(
            "Obiettivi AI",
            "Descrivi gli obiettivi e i vincoli per l'AI.\nLascia il testo in inglese o in italiano, va bene comunque.",
            initialvalue=current
        )
        if text is not None and text.strip():
            self.objectives_text = text.strip()
            self._save_settings()
            self.status_var.set("Obiettivi AI aggiornati e salvati.")

    def manage_profile(self):
        dialog = ProfileViewerDialog(self, self.profile)
        self.wait_window(dialog)
        if dialog.result is not None:
            self._apply_profile(dialog.result)
            self._save_settings()
            self.status_var.set("Profilo aggiornato: %s" % self.profile.name)

    def _apply_profile(self, profile):
        self.profile = profile
        self.rule_engine = RuleEngine(profile.rules)
        self.objectives_text = profile.objectives
        logger.info("Profile applied: %s (%d folders, %d rules)",
                    profile.name, len(profile.folders), len(profile.rules))

    # ---------- Settings persistence ----------

    def _settings_file(self):
        return os.path.join(_LOG_DIR, "..", "settings.json")

    def _save_settings(self):
        data = {
            "provider": self.ai_settings.provider,
            "api_key": self.ai_settings.api_key,
            "model": self.ai_settings.model,
            "max_chunk_size": self.ai_settings.max_chunk_size,
            "confidence_threshold": self.ai_settings.confidence_threshold,
            "include_size": self.ai_settings.include_size,
            "include_dates": self.ai_settings.include_dates,
            "strategic_enabled": self.ai_settings.strategic_enabled,
            "objectives": self.objectives_text,
            "last_root": self.root_dir.get(),
        }
        # Save custom profile if it differs from default
        if self.profile.name != _DEFAULT_PROFILE.name or self.profile.to_dict() != _DEFAULT_PROFILE.to_dict():
            data["custom_profile"] = self.profile.to_dict()
        try:
            path = self._settings_file()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info("Settings saved to %s", path)
        except Exception as e:
            logger.warning("Could not save settings: %s", e)

    def _load_settings(self):
        try:
            path = self._settings_file()
            if not os.path.exists(path):
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.ai_settings = AISettings(
                provider=data.get("provider", "OpenAI"),
                api_key=data.get("api_key", ""),
                model=data.get("model", "gpt-4o"),
                max_chunk_size=int(data.get("max_chunk_size", 180)),
                confidence_threshold=float(data.get("confidence_threshold", 0.72)),
                include_size=bool(data.get("include_size", True)),
                include_dates=bool(data.get("include_dates", True)),
                strategic_enabled=bool(data.get("strategic_enabled", True)),
            )
            if data.get("objectives"):
                self.objectives_text = data["objectives"]
            if data.get("last_root"):
                self.root_dir.set(data["last_root"])
            # Load custom profile if present
            if data.get("custom_profile"):
                try:
                    loaded = OrganizationProfile.from_dict(data["custom_profile"])
                    if loaded.folders:
                        self._apply_profile(loaded)
                        logger.info("Loaded custom profile: %s", loaded.name)
                except Exception as pe:
                    logger.warning("Could not load custom profile: %s", pe)
            logger.info("Settings loaded from %s", path)
        except Exception as e:
            logger.warning("Could not load settings: %s", e)

    # ---------- UI actions ----------

    def choose_root(self):
        folder = filedialog.askdirectory(title="Seleziona la cartella root")
        if folder:
            self.root_dir.set(folder)

    def scan_root(self):
        root = self._get_root_path()
        if not root:
            return

        self.status_var.set("Scansione in corso...")
        self.records = []
        self.plans = []
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._update_undo_buttons()
        self.refresh_tree()
        self.stop_requested = False
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(12)

        def worker():
            try:
                scanner = InventoryScanner()
                records = scanner.scan(root, stop_flag=lambda: self.stop_requested)
                self.records = records
                self.after(0, self._scan_done)
            except Exception as e:
                self.after(0, lambda err=e: self._show_error("Errore scansione", err))

        threading.Thread(target=worker, daemon=True).start()

    def _scan_done(self):
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", value=0)
        self.status_var.set("Scansione completata. File trovati: %d" % len(self.records))
        self.update_summary()
        self.refresh_tree()

    def build_preview(self):
        root = self._get_root_path()
        if not root:
            return

        if not self.records:
            messagebox.showwarning("Nessun dato", "Devi prima eseguire la scansione.")
            return

        planner = Planner(self.rule_engine)
        self.plans = planner.build_plan(root, self.records)

        plan_map = {}
        for plan in self.plans:
            plan_map[plan.source_path] = plan

        for record in self.records:
            plan = plan_map.get(record.source_path)
            if plan:
                record.suggested_action = plan.action
                record.suggested_target_rel = plan.relative_target_path
                if not record.decision_source:
                    record.decision_source = "rule"

        self.status_var.set("Anteprima con regole completata. Righe pianificate: %d" % len(self.plans))
        self.update_summary()
        self.refresh_tree()

    def generate_ai_plan(self):
        root = self._get_root_path()
        if not root:
            return

        if not self.records:
            messagebox.showwarning("Nessun dato", "Prima devi eseguire la scansione.")
            return

        if not self.ai_settings.api_key.strip():
            messagebox.showwarning("AI non configurata", "Apri 'Configura AI' e inserisci la API key.")
            return

        confirm = messagebox.askyesno(
            "Genera piano con AI",
            "Il tool invierà metadati e percorsi dei file all'API OpenAI per generare un piano di riorganizzazione.\n\nContinuare?"
        )
        if not confirm:
            return

        self.status_var.set("Generazione piano AI in corso...")
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start(12)

        def progress(message, current=0, total=0):
            def _update():
                self.status_var.set(message)
                if total > 0:
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate", maximum=total, value=current)
            self.after(0, _update)

        def worker():
            try:
                planner = AIPlanner(self.ai_settings, profile=self.profile)
                result = planner.generate_ai_plan(self.records, self.objectives_text, progress_callback=progress)
                self.last_ai_strategic = result.get("strategic")
                self.after(0, lambda: self._apply_ai_result(root, result))
            except Exception as e:
                self.after(0, lambda err=e: self._show_error("Errore AI", err))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_ai_result(self, root, ai_result):
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", value=0)
        self._save_undo_state()
        decisions = ai_result.get("file_decisions", [])
        decision_map = {}
        for item in decisions:
            decision_map[item.get("source_path", "")] = item

        for record in self.records:
            d = decision_map.get(record.source_path)
            if not d:
                continue

            confidence = float(d.get("confidence", 0.0))
            needs_review = bool(d.get("needs_review", False))
            action = d.get("action", "review")
            target_rel = normalize_rel_path(d.get("target_rel_path", ""))
            reason = d.get("reason", "")

            if confidence < self.ai_settings.confidence_threshold:
                needs_review = True

            if needs_review and action not in ("quarantine",):
                action = "review"

            record.suggested_action = action
            record.suggested_target_rel = target_rel
            record.ai_reason = reason
            record.ai_confidence = confidence
            record.needs_review = needs_review
            record.decision_source = "ai"

        self._rebuild_plans_from_records()

        strategy_notes = []
        if self.last_ai_strategic:
            strategy_notes = self.last_ai_strategic.get("strategic_notes", [])

        self.status_var.set("Piano AI generato. Decisioni AI: %d" % len(decisions))
        self.refresh_tree()

        note_text = "\n".join(strategy_notes[:8]) if strategy_notes else "Nessuna nota strategica disponibile."
        messagebox.showinfo(
            "Piano AI generato",
            "Il piano AI è stato applicato alla tabella.\n\n"
            "Le righe con confidence bassa sono state spinte verso review.\n\n"
            "Prime note strategiche:\n%s" % note_text
        )

    def execute_plan(self):
        root = self._get_root_path()
        if not root:
            return

        if not self.records:
            messagebox.showwarning("Nessun dato", "Non c'è nulla da eseguire.")
            return

        if not self.plans:
            self._rebuild_plans_from_records()

        selected_sources = set([r.source_path for r in self.records if r.selected])
        plans = [p for p in self.plans if p.source_path in selected_sources]

        if not plans:
            messagebox.showwarning("Nessuna selezione", "Non ci sono righe selezionate da eseguire.")
            return

        executor = OperationExecutor(root, root / "_reorg_logs")
        validation_errors = executor.validate_plan(plans)

        if validation_errors:
            preview = "\n".join(validation_errors[:20])
            messagebox.showerror(
                "Validazione fallita",
                "Ci sono problemi da risolvere prima dell'esecuzione:\n\n%s" % preview
            )
            return

        dry_run = self.dry_run_var.get()

        if dry_run:
            confirm = messagebox.askyesno(
                "Conferma Dry Run",
                "Stai per eseguire una simulazione.\n\n"
                "Il tool NON sposterà i file reali.\n"
                "Verranno generati i manifest della simulazione.\n\n"
                "Continuare?"
            )
            if not confirm:
                return
        else:
            confirm = messagebox.askyesno(
                "Conferma esecuzione reale",
                "Stai per eseguire operazioni REALI sul filesystem.\n\n"
                "Questo può spostare davvero i file.\n\n"
                "Hai già controllato il piano in Dry Run?\n\n"
                "Continuare?"
            )
            if not confirm:
                return

        try:
            manifest_json, manifest_csv = executor.execute(plans, dry_run=dry_run)
            self.status_var.set("Esecuzione completata. Manifest: %s" % manifest_json.name)

            mode_text = "SIMULAZIONE (Dry Run)" if dry_run else "ESECUZIONE REALE"
            messagebox.showinfo(
                "Operazione completata",
                "%s completata.\n\nManifest JSON:\n%s\n\nManifest CSV:\n%s" % (
                    mode_text, manifest_json, manifest_csv
                )
            )
        except Exception as e:
            self._show_error("Errore esecuzione", e)

    def rollback_manifest(self):
        root = self._get_root_path()
        if not root:
            return

        manifest = filedialog.askopenfilename(
            title="Seleziona il manifest JSON",
            filetypes=[("JSON files", "*.json")]
        )
        if not manifest:
            return

        dry_run = messagebox.askyesno(
            "Modalità rollback",
            "Vuoi eseguire il rollback in Dry Run?\n\n"
            "Sì = simulazione rollback\n"
            "No = rollback reale"
        )

        try:
            executor = OperationExecutor(root, root / "_reorg_logs")
            done, errors, messages = executor.rollback(Path(manifest), dry_run=dry_run)
            msg = "\n".join(messages[:25]) if messages else "Nessun dettaglio disponibile."
            messagebox.showinfo(
                "Rollback completato",
                "Operazioni rollback riuscite: %d\nErrori: %d\n\n%s" % (done, errors, msg)
            )
            self.status_var.set("Rollback completato. OK=%d, Errori=%d" % (done, errors))
        except Exception as e:
            self._show_error("Errore rollback", e)

    def export_inventory(self):
        if not self.records:
            messagebox.showwarning("Nessun dato", "Devi prima eseguire la scansione.")
            return

        path = filedialog.asksaveasfilename(
            title="Salva inventario CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return

        export_inventory_csv(self.records, Path(path))
        self.status_var.set("Inventario esportato: %s" % path)

    def export_plan(self):
        if not self.plans:
            messagebox.showwarning("Nessun piano", "Non c'è un piano da esportare.")
            return

        path = filedialog.asksaveasfilename(
            title="Salva piano CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return

        export_plan_csv(self.plans, Path(path))
        self.status_var.set("Piano esportato: %s" % path)

    def import_plan(self):
        path = filedialog.askopenfilename(
            title="Apri piano CSV",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return

        try:
            self.plans = import_plan_csv(Path(path))
            plan_map = {}
            for plan in self.plans:
                plan_map[plan.source_path] = plan

            for record in self.records:
                if record.source_path in plan_map:
                    plan = plan_map[record.source_path]
                    record.suggested_action = plan.action
                    record.suggested_target_rel = plan.relative_target_path
                    record.decision_source = "manual"

            self.refresh_tree()
            self.update_summary()
            self.status_var.set("Piano importato: %s" % path)
        except Exception as e:
            self._show_error("Errore import piano", e)

    def save_rules(self):
        path = filedialog.asksaveasfilename(
            title="Salva regole JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")]
        )
        if not path:
            return

        try:
            self.rule_engine.save_rules(Path(path))
            self.status_var.set("Regole salvate: %s" % path)
        except Exception as e:
            self._show_error("Errore salvataggio regole", e)

    def load_rules(self):
        path = filedialog.askopenfilename(
            title="Carica regole JSON",
            filetypes=[("JSON files", "*.json")]
        )
        if not path:
            return

        try:
            self.rule_engine.load_rules(Path(path))
            self.status_var.set("Regole caricate: %s" % path)
        except Exception as e:
            self._show_error("Errore caricamento regole", e)

    def toggle_selected_rows(self):
        selected_items = self.tree.selection()
        if not selected_items:
            return

        source_paths = [self.tree.item(item, "values")[1] for item in selected_items]
        source_set = set(source_paths)

        for record in self.records:
            if record.source_path in source_set:
                record.selected = not record.selected

        self.refresh_tree()

    def select_all(self):
        for record in self.records:
            record.selected = True
        self.refresh_tree()

    def select_none(self):
        for record in self.records:
            record.selected = False
        self.refresh_tree()

    def override_target_for_selected(self):
        if not self.records:
            return

        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Nessuna selezione", "Seleziona prima una o pi\u00f9 righe.")
            return

        dialog = TargetSelectionDialog(self, self.profile, len(selected_items))
        self.wait_window(dialog)
        
        if not dialog.result:
            return

        rel_target_dir = dialog.result

        self._save_undo_state()
        source_paths = set([self.tree.item(item, "values")[1] for item in selected_items])

        for record in self.records:
            if record.source_path in source_paths:
                record.suggested_target_rel = normalize_rel_path(rel_target_dir + "\\" + record.name)
                record.decision_source = "manual"
                record.ai_reason = "Manual target override"
                record.ai_confidence = 1.0

        self._rebuild_plans_from_records()
        self.refresh_tree()

    def override_action_for_selected(self):
        if not self.records:
            return

        action = simpledialog.askstring(
            "Imposta azione",
            "Inserisci l'azione per le righe selezionate:\n\nmove | archive | quarantine | review | rename"
        )
        if not action:
            return

        action = action.strip().lower()
        if action not in ("move", "archive", "quarantine", "review", "rename"):
            messagebox.showerror("Azione non valida", "Valori ammessi: move, archive, quarantine, review, rename")
            return

        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Nessuna selezione", "Seleziona prima una o più righe.")
            return

        self._save_undo_state()
        source_paths = set([self.tree.item(item, "values")[1] for item in selected_items])

        for record in self.records:
            if record.source_path in source_paths:
                record.suggested_action = action
                record.decision_source = "manual"
                record.ai_reason = "Manual action override"
                record.ai_confidence = 1.0
                if action == "quarantine":
                    record.suggested_target_rel = normalize_rel_path(r"_QUARANTINE\%s" % record.name)

        self._rebuild_plans_from_records()
        self.refresh_tree()

    # ---------- internal ----------

    def _rebuild_plans_from_records(self):
        root = self._get_root_path()
        if not root:
            return

        self.plans = []
        for record in self.records:
            target_abs = str(root / record.suggested_target_rel) if record.suggested_target_rel else ""
            self.plans.append(
                OperationPlan(
                    source_path=record.source_path,
                    action=record.suggested_action,
                    target_path=target_abs,
                    relative_target_path=record.suggested_target_rel
                )
            )

    def refresh_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        term = self.filter_var.get().strip().lower()

        # Build filtered list
        self.filtered_records = []
        for record in self.records:
            text_blob = " | ".join([
                record.source_path,
                record.suggested_action,
                record.suggested_target_rel,
                record.top_folder,
                " ".join(record.risk_flags),
                record.ai_reason,
                record.decision_source
            ]).lower()

            if term and term not in text_blob:
                continue
            self.filtered_records.append(record)

        # Pagination
        total_pages = self._total_pages()
        if self.current_page >= total_pages:
            self.current_page = max(0, total_pages - 1)

        start = self.current_page * self.page_size
        end = min(start + self.page_size, len(self.filtered_records))
        page_records = self.filtered_records[start:end]

        for idx, record in enumerate(page_records):
            tags = []
            if record.risk_flags:
                tags.append("risk")
            elif record.suggested_action == "review" or record.needs_review:
                tags.append("review")
            elif record.decision_source == "ai":
                tags.append("ai")
            elif idx % 2 == 1:
                tags.append("oddrow")

            confidence_text = ""
            if record.ai_confidence:
                confidence_text = "%.2f" % record.ai_confidence

            self.tree.insert(
                "",
                "end",
                values=(
                    "\u2714" if record.selected else "",
                    record.source_path,
                    record.suggested_action,
                    record.suggested_target_rel,
                    record.decision_source,
                    confidence_text,
                    record.ai_reason,
                    format_size(record.size_bytes),
                    record.modified_at,
                    record.top_folder,
                    ",".join(record.risk_flags)
                ),
                tags=tuple(tags)
            )

        # Update pagination label
        total_f = len(self.filtered_records)
        self.page_label_var.set("Pagina %d / %d  (%d file)" % (
            self.current_page + 1, total_pages, total_f))

        self.update_summary()

    def update_summary(self):
        total = len(self.records)
        selected = sum(1 for r in self.records if r.selected)

        actions = {}
        for record in self.records:
            actions[record.suggested_action] = actions.get(record.suggested_action, 0) + 1

        review_count = sum(1 for r in self.records if r.suggested_action == "review" or r.needs_review)
        risk_count = sum(1 for r in self.records if r.risk_flags)
        total_size = sum(r.size_bytes for r in self.records)
        ai_count = sum(1 for r in self.records if r.decision_source == "ai")
        manual_count = sum(1 for r in self.records if r.decision_source == "manual")
        avg_conf = 0.0
        ai_with_conf = [r.ai_confidence for r in self.records if r.ai_confidence > 0]
        if ai_with_conf:
            avg_conf = sum(ai_with_conf) / len(ai_with_conf)

        action_text = ", ".join(["%s:%d" % (k, v) for k, v in sorted(actions.items())]) if actions else "nessuna"
        text = (
            "File: %d | Selezionati: %d | Dimensione totale: %s | "
            "Righe con rischio: %d | Righe review: %d | AI decisions: %d | Manual overrides: %d | "
            "Avg AI confidence: %.2f | Azioni: %s"
        ) % (total, selected, format_size(total_size), risk_count, review_count, ai_count, manual_count, avg_conf, action_text)

        self.summary_label.config(text=text)

    def _get_root_path(self):
        value = self.root_dir.get().strip()
        if not value:
            messagebox.showwarning("Root mancante", "Seleziona prima una cartella root.")
            return None

        path_obj = Path(value)
        if not path_obj.exists() or not path_obj.is_dir():
            messagebox.showerror("Root non valida", "La cartella root selezionata non è valida.")
            return None

        return path_obj

    def _show_error(self, title, error_obj):
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate", value=0)
        detail = "".join(traceback.format_exception(type(error_obj), error_obj, error_obj.__traceback__))
        logger.error("%s: %s", title, error_obj)
        messagebox.showerror(title, "%s: %s\n\n%s" % (type(error_obj).__name__, error_obj, detail))
        self.status_var.set("%s: %s: %s" % (title, type(error_obj).__name__, error_obj))


# =========================
# Main
# =========================

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()