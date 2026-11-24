# Lefedettségi jelentés (2026-11-22)

Automatikusan készül: `coverage/check_coverage.py`. Minden „kész” vagy „részben” sor mögött létező MCP-művelet áll, amelyet a legutóbbi teljes tesztfutás le is futtatott.

## AutoCAD-parancsok

Összesen 303 tétel.

| Státusz | Darab |
|---|---|
| kész | 254 |
| részben | 19 |
| hiányzik | 3 |
| élő AutoCAD kell | 7 |
| nem értelmezhető | 20 |

**Fájlszinten értelmezhető tételek (276 db) közül: 254 kész (92%), 19 részben (7%), 3 hiányzik (1%).**

### Kategóriánként

| Kategória | kész | részben | hiányzik | élő AutoCAD | n/a |
|---|---|---|---|---|---|
| Rajzolás | 23 | 0 | 0 | 1 | 2 |
| Feliratozás | 13 | 2 | 1 | 0 | 1 |
| Blokkok | 9 | 1 | 0 | 0 | 0 |
| Hivatkozások | 8 | 3 | 0 | 0 | 0 |
| Módosítás | 39 | 1 | 0 | 0 | 2 |
| 3D | 14 | 11 | 0 | 1 | 0 |
| Méretezés | 18 | 1 | 0 | 0 | 0 |
| Rétegek | 22 | 0 | 0 | 0 | 1 |
| Lekérdezés | 12 | 0 | 0 | 0 | 1 |
| Fájl | 20 | 0 | 0 | 0 | 0 |
| Layout | 4 | 0 | 0 | 0 | 0 |
| Nézet | 2 | 0 | 0 | 0 | 6 |
| Beállítás | 4 | 0 | 0 | 0 | 5 |
| Parametrikus | 0 | 0 | 0 | 4 | 0 |
| Automatizálás | 1 | 0 | 0 | 1 | 1 |
| Útügy | 37 | 0 | 0 | 0 | 1 |
| Geodézia | 11 | 0 | 0 | 0 | 0 |
| Közmű | 7 | 0 | 0 | 0 | 0 |
| Villamos | 6 | 0 | 1 | 0 | 0 |
| Vasút | 4 | 0 | 1 | 0 | 0 |

## DXF elem- és objektumtípusok (Autodesk DXF-referencia, AutoCAD for Mac 2026)

Összesen 93 tétel.

| Státusz | Darab |
|---|---|
| kész | 54 |
| részben | 5 |
| hiányzik | 1 |
| élő AutoCAD kell | 5 |
| nem értelmezhető | 28 |

**Fájlszinten értelmezhető tételek (60 db) közül: 54 kész (90%), 5 részben (8%), 1 hiányzik (2%).**

## Hiányzik (fájlszinten megoldható, még nincs kész)

- **TABLESTYLE** (Feliratozás): natív TABLE/TABLESTYLE objektumot az ezdxf nem tud írni
- **FÉNYSŰRŰSÉG-SZÁMÍTÁS (L, cd/m²)** (Villamos): útburkolati reflexiós táblázatok (r-táblák) kellenek hozzá
- **KITÉRŐ-TÍPUSTÁBLÁZATOK (MÁV)** (Vasút): a MÁV kitérő-adatlapjai nem nyilvánosak, a és b méretet a tervező adja
- DXF **TABLESTYLE**: az ezdxf nem tud TABLESTYLE-t írni

## Részben kész

- **TABLE** (Feliratozás): vonalakból és szövegből rajzolt táblázat - natív TABLE objektumot az ezdxf nem tud írni
- **BEDIT** (Blokkok): blokk tartalmának szerkesztése - dinamikus blokk paraméterek/műveletek nem készíthetők
- **XCLIP** (Hivatkozások): téglalap/sokszög vágás és törlés - invertált vágás nincs (az AutoCAD nem nyitná meg)
- **REFEDIT** (Hivatkozások): a hivatkozott fájl megnyitása és szerkesztése - helyben szerkesztés nincs
- **ARRAYEDIT** (Módosítás): szerkeszthető téglalapos tömb (MINSERT) - poláris/görbementi asszociatív tömb nincs
- **DIMBREAK** (Méretezés): a méretet felrobbantja a megszakításhoz
- **FIELD** (Feliratozás): terület, hossz, kerület, sugár, dátum, fájlnév - az MCP frissíti, az AutoCAD-ben sima szöveg
- **CYLINDER** (3D): solid=true: 3DSOLID, de a palást sokszöglapos (fazettált)
- **CONE** (3D): fazettált
- **SPHERE** (3D): fazettált
- **TORUS** (3D): fazettált
- **REVOLVE** (3D): fazettált
- **UNION** (3D): zárt hálókon és fazettált 3DSOLID-okon - AutoCAD-ben készült görbe felületű testeken nem
- **SUBTRACT** (3D): mint UNION
- **INTERSECT** (3D): mint UNION
- **SLICE** (3D): mint UNION
- **PRESSPULL** (3D): zárt terület kihúzása szigetekkel - test lapjának húzása nincs
- **SECTIONPLANE** (3D): metszet körvonala a valós helyén - élő metszősík objektum nincs
- **GEOGRAPHICLOCATION** (Hivatkozások): World Mercator helyi rács a rajz közepén,  AutoCAD-ben ellenőrizendő
- DXF **3DSOLID**: fazettált (sík lapú) ACIS testeket ír - görbe felületű ACIS test írása nincs
- DXF **TABLE**: vonalakból+szövegből rajzolt
- DXF **DIMASSOC**: az MCP köti a méretet az elemekhez és frissíti - natív DIMASSOC objektum nincs
- DXF **FIELD**: MCP-mező, nem natív FIELD objektum
- DXF **GEODATA**: World Mercator helyi rács (AutoCAD-ben ellenőrizendő)

## Csak élő AutoCAD-del (ObjectARX híd)

- **REGION** (Rajzolás): régió (ACIS) csak élő AutoCAD-del
- **FILLETEDGE** (3D)
- **GEOMCONSTRAINT** (Parametrikus)
- **DIMCONSTRAINT** (Parametrikus)
- **AUTOCONSTRAIN** (Parametrikus)
- **PARAMETERS** (Parametrikus)
- **APPLOAD** (Automatizálás): AutoLISP alkalmazások
- DXF **BODY**: ACIS
- DXF **REGION**: ACIS
- DXF **SECTION**: 3D metszősík
- DXF **SURFACE**: ACIS felület
- DXF **SECTION**

## Tesztelési bizonyíték

- MCP-műveletek száma: 303, ebből teszttel lefuttatva: 303.
- Teszt nélküli művelet: 0.
- Legutóbbi teljes tesztfutás: sikeres.
- Táblázatban nem szereplő extra műveletek: block.delete, block.list, draw3d.to_mesh, drawing.list, drawing.switch, geo.location, layer.create_many, layout.fit_viewport, python.run, query.extents, query.groups, query.intersections, query.nearest, road.design_rules_list, road.list, terrain.list.
