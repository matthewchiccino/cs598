"""Smoke test: ask Claude to draw a UN member country's outline as SVG.

Usage:
  python3 src/draw_test.py                      # interactive: type a name, TAB to autocomplete
  python3 src/draw_test.py United Kingdom       # or pass it directly (spaces are fine, no quotes needed)
  python3 src/draw_test.py --model claude-sonnet-5-5 Japan
  python3 src/draw_test.py --list               # print all valid names

Only the official list below is accepted (no "USA", no "British"). Needs ANTHROPIC_API_KEY in .env.
"""
import argparse
import difflib
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONDITION = "oneshot"  # later: selfcorrect, resample, memory (see DESIGN.md)

# 193 UN member states + 2 UN observer states (Palestine, Vatican City) = 195.
# Short, ASCII, common English names so they are easy to type.
COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina",
    "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados",
    "Belarus", "Belgium", "Belize", "Benin", "Bhutan", "Bolivia", "Bosnia and Herzegovina",
    "Botswana", "Brazil", "Brunei", "Bulgaria", "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia",
    "Cameroon", "Canada", "Central African Republic", "Chad", "Chile", "China", "Colombia",
    "Comoros", "Costa Rica", "Cote d'Ivoire", "Croatia", "Cuba", "Cyprus", "Czechia",
    "Democratic Republic of the Congo", "Denmark", "Djibouti", "Dominica", "Dominican Republic",
    "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini",
    "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia", "Georgia", "Germany", "Ghana",
    "Greece", "Grenada", "Guatemala", "Guinea", "Guinea-Bissau", "Guyana", "Haiti", "Honduras",
    "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy",
    "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos",
    "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg",
    "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands",
    "Mauritania", "Mauritius", "Mexico", "Micronesia", "Moldova", "Monaco", "Mongolia",
    "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia", "Nauru", "Nepal", "Netherlands",
    "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia", "Norway",
    "Oman", "Pakistan", "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Qatar", "Republic of the Congo", "Romania", "Russia",
    "Rwanda", "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa",
    "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal", "Serbia", "Seychelles",
    "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands", "Somalia",
    "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname",
    "Sweden", "Switzerland", "Syria", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo",
    "Tonga", "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda",
    "Ukraine", "United Arab Emirates", "United Kingdom", "United States", "Uruguay", "Uzbekistan",
    "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen", "Zambia", "Zimbabwe",
]
assert len(COUNTRIES) == 195 and len(set(COUNTRIES)) == 195
LOOKUP = {c.lower(): c for c in COUNTRIES}  # case-insensitive exact match only


def suggest(text, n=6):
    """Closest valid names, for when the input isn't valid."""
    t = text.lower()
    hits = [c for c in COUNTRIES if t and t in c.lower()]
    hits += difflib.get_close_matches(text, COUNTRIES, n=n, cutoff=0.5)
    return list(dict.fromkeys(hits))[:n]


def setup_autocomplete():
    """TAB completes country names (prefix match, case-insensitive, spaces OK)."""
    try:
        import readline
    except ImportError:
        return
    matches = []

    def completer(text, state):
        nonlocal matches
        if state == 0:
            matches = [c for c in COUNTRIES if c.lower().startswith(text.lower())]
        return matches[state] if state < len(matches) else None

    readline.set_completer_delims("\n")  # default delims include space; that broke multi-word names
    readline.set_completer(completer)
    if "libedit" in (readline.__doc__ or ""):  # macOS python
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def ask_country():
    """Prompt until the user enters a valid country (or blank to quit)."""
    setup_autocomplete()
    print("Type a country and press TAB to autocomplete. Enter on a blank line to quit.")
    while True:
        text = input("Country> ").strip()
        if not text:
            return None
        if text.lower() in LOOKUP:
            return LOOKUP[text.lower()]
        print(f"  '{text}' is not on the UN list.")
        s = suggest(text)
        if s:
            print("  Did you mean: " + ", ".join(s))


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def draw(client, country, model):
    prompt = (
        f"Draw the outline of {country} as a single SVG. Use only what you know, no lookups. "
        'Use viewBox="0 0 100 100", one <path> with a fill and a dark stroke, and nothing else. '
        "Reply with only the SVG code."
    )
    resp = client.messages.create(
        model=model, max_tokens=8000, messages=[{"role": "user", "content": prompt}]
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    match = re.search(r"<svg.*?</svg>", text, re.S)
    if not match:
        print(f"No SVG found in reply:\n{text}")
        return
    # Name = country __ model __ condition __ timestamp, e.g.
    # south_africa__claude-haiku-5-5__oneshot__20261109-1142.svg
    slug = re.sub(r"[^a-z0-9]+", "_", country.lower()).strip("_")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "runs" / f"{slug}__{model}__{CONDITION}__{stamp}.svg"
    out.parent.mkdir(exist_ok=True)
    out.write_text(match.group(0))
    print(f"Saved {out}  ({resp.usage.input_tokens} in / {resp.usage.output_tokens} out tokens)")
    print(f"View it:  open '{out}'")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("country", nargs="*", help="country name (omit for interactive prompt)")
    ap.add_argument("--model", default="claude-haiku-5-5")
    ap.add_argument("--list", action="store_true", help="print all valid country names")
    args = ap.parse_args()

    if args.list:
        print("\n".join(COUNTRIES))
        return

    # Validate before touching the API, so typos cost nothing.
    if args.country:
        text = " ".join(args.country)
        if text.lower() not in LOOKUP:
            print(f"'{text}' is not on the UN list.")
            s = suggest(text)
            if s:
                print("Did you mean: " + ", ".join(s))
            sys.exit(1)
        countries = [LOOKUP[text.lower()]]
    else:
        countries = None  # interactive loop below

    load_env()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("No ANTHROPIC_API_KEY. Copy .env.example to .env and paste your key.")
    import anthropic

    client = anthropic.Anthropic()

    if countries:
        draw(client, countries[0], args.model)
    else:
        while (c := ask_country()) is not None:
            draw(client, c, args.model)


if __name__ == "__main__":
    main()
