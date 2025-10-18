# ACFV
Automated Clip Finder & Video processing toolkit.

## ✨ Features (Current Stage)
- Stage-based pipeline (Validate → ChatExtract → Analyze → Clip)
- Unified configuration via `Settings` (legacy `ConfigManager` bridged)
- Basic interest scoring (chat density + sentiment normalization)
- GUI with Results tab (generated clips) & Logging tab (tails `processing.log`)
- Secret hygiene & pre-commit scan script

## 🧱 Architecture Overview
```
src/acfv/
	arc/
		pipeline/        # stages: validate, chat_extract, analyze, clip
		services/        # scoring and future domain services
		domain/          # settings model (typed configuration)
		ui/              # (placeholder for future UI abstractions)
	interest/          # GUI components & managers
	processing/        # legacy processing modules (chat extract, clip, analyze, etc.)
	app/interest_adapter.py  # internal-only GUI adapter
```

The pipeline is declarative: you supply a `StageContext` with inputs, run stages that mutate context, and consume outputs (`segments`, `clips`).

## 🚀 Quick Start
```python
from PyQt5.QtWidgets import QApplication
from acfv.app.interest_adapter import create_interest_main_window

app = QApplication([])
win = create_interest_main_window()
win.show()
app.exec_()
```
Select video (and optional chat HTML) in GUI, then trigger processing (runPipeline button or integrated controls). Clips appear under the Results tab.

## ⚙️ Configuration
Legacy keys remain in `config.txt`. New typed settings live in `arc/domain/settings.py`. On GUI launch `load_settings(cfg=ConfigManager())` merges values. Adjust weights or window length by editing:
```json
{
	"SEGMENT_WINDOW": 15.0,
	"TOP_SEGMENTS": 8,
	"CHAT_DENSITY_WEIGHT": 0.25
}
```

## 📊 Scoring Logic (Simplified)
Raw window scores = weighted sum(chat_density, sentiment, video_emotion_placeholder). Then z-score normalization + sigmoid → ranking → non-overlapping top segments.

## 📝 Migration Notes
See `MIGRATION_NOTES.md` for full legacy → new architecture mapping, removed components, and next steps.

## 🛠 Development
Install dependencies:
```bash
pip install -r requirements.txt
```
Run secret scan (pre-commit equivalent manual trigger):
```bash
python tools/scan_secrets.py
```

## 🔐 Security & Secrets
Real secret files replaced by `.example` templates. Ensure actual credentials are kept out of version control.

## 📦 Packaging
Use `tools/build_with_pyinstaller.py` (see `CUSTOM_NAME_README.md` for naming customization) to produce a distributable folder.

## 🧪 Future Enhancements
- Integrate video emotion model
- Add transcription & semantic merging stages
- Enforce `max_clip_count` and merging proximity rules
- Expand unit tests (pipeline + scoring)

## 🤝 Contributing
Open an issue with proposed stage/service additions. Keep modules small, pure where possible, and avoid reintroducing sys.path hacks.

---
ACFV is evolving; expect incremental improvements as pipeline depth and analysis richness increase.

### Runtime data locations

All generated files now live under a writable `var/` directory (override with `ACFV_STORAGE_ROOT`).
- `var/settings/config.json` keeps GUI configuration (migrated from `config.txt`).
- `var/secrets/config.json` stores tokens such as the HuggingFace credential.
- `var/processing/` holds logs, progress markers, and clip outputs.

Delete the directory to reset runtime state, or point `ACFV_STORAGE_ROOT` to a custom path for portable deployments.
