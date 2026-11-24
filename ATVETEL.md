# Átvétel – CAD MCP továbbfejlesztése és éles AutoCAD-tesztje

Szia! Ez a csomag egy MCP szerver, amelyen keresztül a Claude AutoCAD-rajzokat (DXF/DWG) készít,
szerkeszt és ellenőriz Macen, főleg magyar útügyi tervezéshez (KÉ-K). Fájlon dolgozik, futó
AutoCAD nem kell hozzá. Valódi AutoCAD-ben viszont még senki nem nézte meg a rajzait, és élő
AutoCAD-kapcsolata sincs. Ebben a kettőben kérnénk a segítségedet.

## Hol tart (0.9.1)

- 20 eszköz + `modules`, 303 művelet; 102 automatikus teszt sikeres, 1 kihagyva; fájlszintű
  lefedettség 92% (`coverage/REPORT.md`).
- Modulok: alap, halado, 3d, ut, forgalomtechnika, vizelvezetes, terep, geo, geodezia, kozmu,
  villamos, vasut, python. Profilok: kek, vztel, geodeta, kozvil, keva, rajz, minimal, mind.
- Szabálykészletek: e-UT 03.01.11 (`assets/eut`, oldalszámokkal), e-UT 06.03.14:2026
  pályaszerkezet-méretezés; 513 KRESZ-tábla (`assets/kresz`).
- Csak macOS; Windows-támogatás nem cél.

## Teendők, ajánlott sorrendben

1. **Telepítés** – `TELEPITES.md` (röviden: kicsomagolás állandó helyre, `./install.sh --test`).
2. **Éles teszt AutoCAD for Macben** – a 11 próbarajz külön zipben is jön
   (`cad-mcp-tesztrajzok-0.9.1.zip`, DXF + PNG előnézet, telepítés nélkül is megnyitható). A DWG
   változatot a telepítés után a saját gépeden gyártsd le, mert ez is a teszt része:
   `.venv/bin/python scripts/make_test_pack.py --dwg`. A `TESZTLISTA.md` pontjait
   nézd végig; minden hibához: fájlnév + pontszám + mit látsz (képernyőkép).
3. **A talált hibák javítása** – a hibát először tesztként írd meg (`tests/`), aztán javítsd.
4. **Élő AutoCAD for Mac híd** – ObjectARX for Mac bővítmény (C++, teljes AutoCAD for Mac, nem LT)
   vagy AutoLISP-rutin, amely helyi fájlon / socketen kap parancsot. Részletek: `TELEPITES.md`,
   „Közvetlen (élő) AutoCAD-kapcsolat beillesztése”; a hídra váró parancsok a
   `coverage/commands.csv` „live” sorai.
5. Opcionális: vékony parancssori felület ugyanarra a magra, ha kötegelt munka kell.

## Felépítés

| Hol | Mi |
|---|---|
| `src/cad_mcp/server.py` | MCP szerver; minden hívás az `execute(tool, operation, args, drawing)` függvényen fut át |
| `src/cad_mcp/core.py` | `OPS` nyilvántartás, `@op(tool, név, mutates=...)` dekorátor, `Ctx` (a nyitott ezdxf `Drawing`) |
| `src/cad_mcp/modules.py` | modulok és profilok, melyik művelet melyik modulba tartozik |
| `src/cad_mcp/ops_*.py` | a műveletek témánként (rajzolás, szerkesztés, út, közmű, geodézia …) |
| `src/cad_mcp/dwg.py` | DWG ↔ DXF az ODA File Converterrel |
| `src/cad_mcp/render.py` | PNG/SVG/PDF előnézet (`view.png`) |
| `assets/` | e-UT szabálykészletek, KRESZ-táblák (forrás táblánként az `index.json`-ban) |
| `scripts/` | tesztcsomag, csomagkészítő, KRESZ- és e-UT-adat frissítése |
| `tests/` | pytest; köztük valódi MCP stdio kapcsolat és DWG-oda-vissza teszt |

Új művelet: függvény `@op("eszköz", "név", mutates=True)` dekorátorral egy `ops_*.py` fájlban; a
leírása automatikusan bekerül az eszköz súgójába. Új élő művelet: `@op("live", "...")`.

## Szabályok (fontosak)

- **Szabványszámot soha ne találj ki.** Határérték csak hivatalos forrásból, oldalszámmal kerülhet
  a szabálykészletbe; ami az előírásban nincs számszerűen, azt a tervező adja meg.
- **Személyes adat nem kerülhet a csomagba** (név, e-mail, gépnév). A KRESZ-frissítéshez az
  elérhetőség csak a `KRESZ_CONTACT` környezeti változóban adható meg.
- Minden változás után fusson le a teljes tesztsor: `.venv/bin/python -m pytest -q`.
- A `CLAUDE.md` ugyanezeket a szabályokat adja át a Claude Code-nak, ha azzal fejlesztesz.

## Tippek

- A DWG-átalakító (ODA File Converter) asztali alkalmazás: Claude Code sandboxból vagy SSH-n át nem
  indul, ott DXF-et használj, vagy a parancsot a sandboxon kívül futtasd.
- Az ODA File Converter a DWG-be beírja a gép felhasználónevét (ahogy az AutoCAD is); megosztás előtt erre figyelj.
- Ha a `pip` tanúsítványhibát ad: `PIP_USE_DEPRECATED=legacy-certs` (az `install.sh` ezt magától
  megpróbálja).
- Érdemes rögtön verziókezelést indítani a mappában: `git init && git add -A && git commit -m 0.9.1`
  (a `.gitignore` kész).

## Nyitott pontok (adat hiányzik)

- natív AutoCAD-táblázatstílus (most vonalakból és szövegből áll a táblázat);
- közvilágítási fénysűrűség-számítás (r-táblák kellenének);
- MÁV kitérő-táblázatok;
- repülőtér és hajózás csak általános rajzeszközökkel.

## Visszaküldés

Ha végeztél egy körrel: emeld a verziót a `pyproject.toml`-ban és a `src/cad_mcp/__init__.py`-ban,
írd le röviden a változásokat (mit javítottál, mi maradt), és készíts új csomagot:

```bash
.venv/bin/python scripts/make_package.py --forbid "$USER"
```

A `dist/` mappában megjelenő zipet és a kitöltött `TESZTLISTA.md`-t küldd vissza (vagy, ha
megbeszéljük, egy közös privát Git-tárolóba töltsd fel).

Köszönjük!
