# MasAca Archive ReOrg

> **Riorganizzazione intelligente di archivi aziendali con AI**

Desktop application (Python + Tkinter) che combina un motore di regole locali con l'AI di OpenAI per analizzare, pianificare e riorganizzare file e cartelle su filesystem Windows. Pensato per archivi aziendali di grandi dimensioni dove la classificazione manuale sarebbe proibitiva.

## Il Concetto: Intelligenza Ibrida e Profili Organizzativi

Riorganizzare decine di migliaia di file è un lavoro troppo complesso per essere fatto totalmente a mano, ma troppo critico per essere affidato ciecamente a un'intelligenza artificiale.

Questo tool usa un approccio ibrido guidato da un **Profilo Organizzativo**:

1. **Il Profilo (Regole Locali Fast-Pass):** Il tool applica regole deterministiche per identificare pattern ovvi, guidate dal profilo attivo.
2. **Lo Strato AI (LLM):** Per i file ambigui, l'AI analizza metadati e modello concettuale, proponendo decisioni.
3. **Controllo Umano & Dry Run:** L'operatore revisiona il piano. Niente tocca i file senza approvazione esplicita.

La riorganizzazione non consiste nello smistare tutto ovunque, ma nel ridurre la frizione cognitiva. Il profilo di default (*Maserati Academy*) si basa su:
* Nomi parlanti.
* Pochi punti di ingresso (7 cartelle principali).
* Regole ovvie anche per chi arriva da fuori.

Queste sono le 7 cartelle del profilo di default:
- `01_Management`: Governance, strategia, team, vendor.
- `02_Training_Projects`: Progetti di formazione in fase di design.
- `03_Training_Delivery`: Erogazione dei corsi (partecipanti, feedback).
- `04_Reports_and_Budget`: Dati finanziari, survey, KPI.
- `05_Shared_Resources`: Asset riutilizzabili, linee guida, template.
- `90_Archive`: Progetti e documenti chiusi.
- `99_Inbox`: Triage (file da valutare) o arrivi temporanei.

---

## ✨ Funzionalità principali

| Feature | Descrizione |
|---|---|
| **Scansione inventario** | Analisi ricorsiva della cartella root con raccolta metadati (dimensione, data modifica, percorso, estensione, top-folder) |
| **Motore di regole** | Classificazione automatica basata su regole JSON personalizzabili (regex su percorso/nome, estensione, top-folder) |
| **Piano AI (OpenAI)** | Invio dei metadati all'API OpenAI per generare un piano di riorganizzazione con azioni (move, archive, quarantine, review, rename) e confidence score |
| **Strategic pass** | Analisi strategica AI dell'intera struttura prima delle decisioni operative |
| **Dry Run** | Simulazione completa senza spostare file reali, con generazione di manifest JSON e CSV |
| **Esecuzione reale** | Esecuzione delle operazioni pianificate con manifest completo per audit |
| **Rollback** | Rollback completo basato su manifest JSON — ripristina lo stato originale |
| **Validazione piano** | Controllo conflitti target, file sorgente mancanti, percorsi duplicati prima dell'esecuzione |
| **Undo/Redo** | Annulla e ripristina modifiche manuali al piano (stack 30 livelli) |
| **Paginazione** | Navigazione a pagine nella tabella per gestire migliaia di file senza rallentamenti |
| **Override manuali** | Modifica azione o percorso target per righe selezionate con validazione input |
| **Export/Import CSV** | Esportazione inventario e piano in CSV, importazione di piani esterni |
| **Persistenza settings** | API key, modello, obiettivi e configurazione salvati automaticamente |
| **Logging** | Log rotante in `%APPDATA%/FileReorgMVP/logs/` con `RotatingFileHandler` |
| **Retry con backoff** | 3 tentativi automatici con attesa crescente (5s/15s/30s) per errori API |

---

## 🖥️ Screenshot

L'interfaccia mostra la tabella con il piano di riorganizzazione, i controlli per scansione, anteprima e AI, la barra di progresso, e i controlli di paginazione e undo/redo.

---

## 🚀 Installazione

### Prerequisiti

- **Python 3.9+** (testato con 3.10)
- **Windows** (l'app usa percorsi Windows-nativi)
- **API Key OpenAI** (per le funzionalità AI — il motore di regole funziona anche senza)

### Setup

```bash
# Clona il repository
git clone https://github.com/hellocardux/MasAca-Archive-ReOrg.git
cd MasAca-Archive-ReOrg

# Nessuna dipendenza esterna — usa solo librerie standard Python
# Avvia l'applicazione
python file_reorg_mvp_ai.py
```

> **Nota:** l'app non richiede `pip install`. Tutte le librerie utilizzate (`tkinter`, `json`, `csv`, `urllib`, `pathlib`, `logging`, `dataclasses`, `threading`, `copy`, `shutil`, `re`) sono parte della libreria standard di Python.

---

## ⚙️ Configurazione

Al primo avvio, clicca **"Configura AI"** per inserire:

| Parametro | Default | Descrizione |
|---|---|---|
| API Key | — | La tua chiave API OpenAI |
| Modello | `gpt-5.4` | Modello GPT da utilizzare |
| Max chunk size | `180` | File per chunk inviato all'API |
| Confidence threshold | `0.72` | Sotto questa soglia → review |
| Include size/dates | `✓` | Invia metadati dimensione e date all'AI |
| Strategic pass | `✓` | Abilita l'analisi strategica prima delle decisioni |

Le impostazioni vengono salvate automaticamente in:
```
%APPDATA%\FileReorgMVP\settings.json
```

---

## 📋 Workflow

```
1. Seleziona cartella root
2. Scansione → inventario file
3. Anteprima regole → classificazione automatica
4. (Opzionale) Piano AI → decisioni intelligenti
5. Review manuale → override dove necessario
6. Dry Run → verifica simulata
7. Esecuzione reale → riorganizzazione
8. (Se necessario) Rollback → ripristino
```

### Azioni disponibili

| Azione | Comportamento |
|---|---|
| `move` | Sposta il file nel percorso target |
| `archive` | Sposta in cartella archivio |
| `quarantine` | Sposta in `_QUARANTINE/` per review successiva |
| `review` | Nessuna azione — da revisionare manualmente |
| `rename` | Rinomina il file |

---

## 🧪 Test

```bash
# Esegui tutti i test (35 test cases)
python -m pytest test_file_reorg.py -v
```

I test coprono:
- Funzioni utility (`normalize_rel_path`, `split_top_folder`, `has_suspicious_version`, `format_size`, `chunk_list`)
- `RuleEngine` (matching regole, flag di rischio, save/load JSON)
- `Planner` (generazione piano da regole)
- `OperationExecutor` (validazione, dry run, esecuzione reale con file reali)

---

## 🏗️ Architettura

L'applicazione è un **singolo file monolite** (`file_reorg_mvp_ai.py`) per semplicità di distribuzione e manutenzione.

### Componenti principali

```
file_reorg_mvp_ai.py
├── Data Models        → FileRecord, OperationPlan, AISettings
├── Helpers            → normalize_rel_path, format_size, chunk_list, ...
├── RuleEngine         → Classificazione basata su regole JSON
├── InventoryScanner   → Scansione filesystem ricorsiva
├── OpenAIClient       → Client HTTP per API OpenAI (con retry)
├── AIPlanner          → Orchestrazione strategic + operational pass
├── Planner            → Generazione piano da regole locali
├── OperationExecutor  → Esecuzione operazioni + rollback
├── CSV Import/Export  → Serializzazione inventario e piani
├── GUI (Tkinter)      → App principale con tema moderno
└── Settings           → Persistenza configurazione in JSON
```

### Flusso dati

```mermaid
graph LR
    A[Filesystem] --> B[InventoryScanner]
    B --> C[FileRecord[]]
    C --> D[RuleEngine]
    C --> E[AIPlanner]
    D --> F[OperationPlan[]]
    E --> F
    F --> G[OperationExecutor]
    G --> H[Manifest JSON/CSV]
    H --> I[Rollback]
```

---

## 📂 Struttura progetto

```
MasAca-Archive-ReOrg/
├── file_reorg_mvp_ai.py   # Applicazione principale (monolite)
├── test_file_reorg.py      # 35 unit test
├── README.md               # Questo file
└── .gitignore              # File ignorati da git
```

---

## 🔐 Note di sicurezza

- L'API key viene salvata **in chiaro** nel file `settings.json` locale. Non committare mai questo file.
- L'app invia **solo metadati** (percorsi, dimensioni, date) all'API OpenAI — **mai il contenuto dei file**.
- Il dry run è abilitato di default per evitare operazioni accidentali.
- Le override manuali validano i percorsi per caratteri non validi e path traversal (`..`).

---

## 📄 Licenza

Questo progetto è ad uso interno. Tutti i diritti riservati.

---

## 📬 Contatti

**Per info e prenotazioni:**
Massimo Cardolicchio — [massimo.cardolicchio@maserati.com](mailto:massimo.cardolicchio@maserati.com)
