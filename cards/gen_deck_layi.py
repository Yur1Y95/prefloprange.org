"""Import the LayIpoker 4-colour raster deck into cards/ under the project's
naming convention (drop-in for cardSvgUrl in static/cards.js).

Source: LayIpoker/Cards/<id>_1.png  (id 100 = back, 101..152 = faces)
  clubs   (green) 101..113 = 2..A
  diamonds(blue)  114..126 = 2..A
  hearts  (red)   127..139 = 2..A
  spades  (gray)  140..152 = 2..A

Output: cards/<suit><rank>.png as RGBA (52 faces). Rank tokens match
cardSvgUrl: 2..9 as-is, 10="10", Jack/Queen/King/Ace.

Run:  python3 cards/gen_deck_layi.py
The old SVG deck stays in place (different extension) as the rollback path.
"""
import os
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE, "LayIpoker", "Cards")
OUT = os.path.join(BASE, "cards")

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "Jack", "Queen", "King", "Ace"]
SUIT_BASE = {"club": 101, "diamond": 114, "heart": 127, "spade": 140}


def main():
    n = 0
    for suit, base in SUIT_BASE.items():
        for i, rank in enumerate(RANKS):
            src = os.path.join(SRC, f"{base + i}_1.png")
            im = Image.open(src).convert("RGBA")
            im.save(os.path.join(OUT, f"{suit}{rank}.png"))
            n += 1
    print(f"wrote {n} face PNGs to {OUT}")


if __name__ == "__main__":
    main()
