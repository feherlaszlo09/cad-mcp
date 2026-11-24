# CAD MCP – telepítés és első lépések

Ez a csomag egy MCP szerver: a Claude ezen keresztül készít, szerkeszt, ellenőriz és ment
AutoCAD-rajzokat (DXF/DWG) Macen. A számítások a rajzfájlon futnak, ehhez nem kell futó AutoCAD;
az eredményt AutoCAD for Macben ugyanúgy megnyitod, mint bármelyik rajzot. Fő terület az útügyi tervezés
(KÉ-K), mellette közmű, geodézia, közvilágítás, vasút és az általános 2D/3D rajzolás.

## Mi kell hozzá

- **macOS** és **Python 3.10 vagy újabb** (python.org telepítő vagy Homebrew: `brew install python@3.12`).
- **Claude Code** (vagy Claude Desktop).
- DWG-hez az ingyenes **ODA File Converter** Macre (.dmg, az Alkalmazások mappába húzva):
  https://www.opendesign.com/guestfiles/oda_file_converter (nélküle DXF-fel megy minden).

## Telepítés

Csomagold ki a zipet egy állandó helyre (pl. `~/Documents/cad-mcp`), mert a beállítás erre a
mappára hivatkozik.

Terminálban, a mappában:

```bash
./install.sh
```

A telepítő létrehozza a `.venv` környezetet, feltelepíti a csomagokat, kipróbálja a szervert,
és ha a `claude` parancs elérhető, be is köti a Claude Code-ba (minden munkamenetben látszik).
Ha nem, kiírja a kézi bekötés parancsát és a Claude Desktop beállítását.

Kapcsolók: `--modules mind` (induló modulok), `--no-register` (bekötés nélkül), `--test` (a végén
lefuttatja a 100+ automatikus tesztet).

## Első próba

Indíts egy új Claude Code munkamenetet, és kérj például:

- *„Rajzolj egy 10 × 6 m-es alaprajzot 30 cm-es falakkal, méretezd, és mutasd.”*
- *„Készíts egy 600 m-es külterületi út tervét 70 km/h-ra: tengely átmeneti ívekkel, hossz-szelvény,
  keresztszelvények, burkolati jelek, KRESZ-táblák, és ellenőrizd az e-UT szerint.”*
- *„Mentsd el proba.dwg néven.”*

A rajzok a `~/Documents/CAD-MCP` mappába kerülnek (a `CAD_MCP_WORKDIR` változóval átállítható).

## Modulok

A Claude csak a bekapcsolt modulok eszközeit látja (kevesebb eszköz = pontosabb munka, kevesebb
token). Induláskor a `kek` (útügyi) profil él. Menet közben: *„kapcsold be a közmű modult”*.
Profilok: `kek`, `vztel` (közmű), `geodeta`, `kozvil` (villamos), `keva` (vasút), `rajz`, `minimal`,
`mind`. Részletek a README-ben.

## Éles teszt AutoCAD-ben

```bash
.venv/bin/python scripts/make_test_pack.py --dwg
```

Ez a `teszt_csomag` mappába 11 próbarajzot készít; a `TESZTLISTA.md` pontjait kell végignézni
AutoCAD-ben. A hibákról fájlnév + pont + képernyőkép a legjobb visszajelzés.

## Közvetlen (élő) AutoCAD-kapcsolat beillesztése

Az MCP most fájlon dolgozik. Élő AutoCAD for Mac kapcsolattal két módon használható együtt:

1. **Egymás mellett, kódváltoztatás nélkül.** Az élő kapcsolatot adó MCP vagy bővítmény is be
   van kötve a Claude-ba. Ez az MCP tervez, számol és ment DXF/DWG-be; az élő kapcsolat megnyitja,
   beilleszti (XREF/INSERT) vagy frissíti a rajzot a futó AutoCAD-ben.
2. **Beépítve.** A szerver minden művelete egy helyen fut át: `src/cad_mcp/server.py` →
   `execute(tool, operation, args, drawing)`, a műveletek nyilvántartása `core.OPS`. A nyitott rajz
   egy ezdxf `Drawing` (`Ctx.doc`). Egy élő réteg így készülhet:
   - minden módosító művelet után (`OPS[tool][op].mutates`) a rajzot a munkamappába menti, és a
     futó AutoCAD-et utasítja az újratöltésre vagy a módosított elemek átvételére. AutoCAD for Macen
     erre az ObjectARX for Mac bővítmény (C++, a teljes AutoCAD for Mac-hez, nem LT) vagy egy
     AutoLISP-rutin való, amely helyi fájlon vagy socketen át kapja a parancsokat;
   - azok a parancsok, amelyek csak élő AutoCAD-ben működnek (parametrikus kényszerek, FILLETEDGE,
     REGION, AutoLISP, dinamikus blokkok szerkesztése), új műveletként kerülnek be
     `@op("live", "...")` alakban, és a hídon keresztül futnak.
   A `coverage/commands.csv` „live” sorai mutatják, mi vár ilyen hídra.

## Fontos tudnivalók

- A tervezési határértékeket (e-UT táblázatok) a beépített szabálykészletek a hivatalos előírásból
  tartalmazzák, oldalszám-hivatkozással; ami az előírásban nincs számszerűen, azt a program nem
  találja ki, hanem a tervező adja meg. A tervezői felelősséget a program nem helyettesíti.
- A KRESZ-táblaképek közkincsek (Wikimedia Commons, forrás táblánként az `assets/kresz/index.json`
  fájlban). Frissítés: `KRESZ_CONTACT=sajat@email.hu python3 scripts/fetch_kresz_signs.py`.
- A `python` vészkijárat (tetszőleges Python-kód a rajzon) alapból ki van kapcsolva; bekapcsolás:
  `CAD_MCP_ALLOW_PYTHON=1` a szerver környezeti változói között.
