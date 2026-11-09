# CS 598 research: can LLMs fix their own SVG country drawings?

See [DESIGN.md](DESIGN.md) for the plan and `reference/` for the assignment.

## Quick start
```bash
pip install anthropic
cp .env.example .env        # then paste your API key into .env (never commit it)
python3 src/draw_test.py Italy
open runs/    # files are named country__model__condition__timestamp.svg
```
