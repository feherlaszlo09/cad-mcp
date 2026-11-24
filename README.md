# AutoCAD MCP (cad-mcp)

MCP szerver, amivel a Claude AutoCAD-rajzokat (DXF/DWG) tud **létrehozni, szerkeszteni,
lekérdezni és exportálni** – futó AutoCAD nélkül, Macen. Az eredményt AutoCAD for Macben
ugyanúgy megnyitod, mint bármelyik rajzot.

## Mit tud (20 eszköz + `modules`, 303 művelet)

| Eszköz | Mire jó |
|---|---|
| `drawing` | új rajz, megnyitás (.dxf/.dwg), mentés, váltás rajzok között, visszavonás/újra, rendszerváltozók, AUDIT, PURGE, import, WBLOCK, elnevezett nézetek, UCS, rajztulajdonságok, erőforrások átvétele más rajzból (DesignCenter), eTransmit csomag, tömeges DWG/DXF konvertálás |
| `draw` | vonal, polyline (ívekkel), téglalap (lekerekítve), sokszög, kör (2P, 3P, két érintő+sugár, három érintő), ív, ellipszis, spline, pont, xline/ray, solid, donut, sraffozás (mintával, szigetekkel, belső ponttal), színátmenet, BOUNDARY, REVCLOUD, MLINE, DIVIDE, MEASURE, wipeout, raszterkép, PDF/DWF/DGN alátét, SHX alakzat |
| `draw3d` | doboz, ék, henger, kúp, gúla, gömb, tórusz, csavarvonal, extrudálás, forgatás, sweep, loft, POLYSOLID, PRESSPULL, háló; **valódi 3DSOLID** (`solid=true`); egyesítés/kivonás/metszet, SLICE, metszet, FLATSHOT (látható és takart élekkel, blokkba is), háló↔test |
| `annotate` | szöveg, többsoros szöveg, méretezés (lineáris, ferde, szög, ívhossz, sugár, átmérő, ordináta, megtört sugár, lánc, bázis, QDIM), DIMSPACE, DIMTEDIT/DIMEDIT, DIMBREAK, tűréskeret (GD&T), középjel, középvonal, vezérvonal (klasszikus és multileader, stílussal, igazítva), táblázat, keresés-csere, SCALETEXT, JUSTIFYTEXT, mezők és méretekhez kötött frissítés |
| `edit` | mozgatás, másolás, forgatás, méretezés, tükrözés, ALIGN, tömb (téglalap, poláris, görbe mentén, szerkeszthető), 3D forgatás/tükrözés/tömb, törlés, robbantás, tulajdonságok, MATCHPROP, SETBYLAYER, OFFSET (íves polyline-ra pontos), TRIM, EXTEND (splinére és ellipszisívre is), LENGTHEN, BREAK, FILLET (vonal/ív/kör), CHAMFER, PEDIT (csúcsszerkesztés is), SPLINEDIT, HATCHEDIT, JOIN (splinével, ellipszisívvel is), REVERSE, OVERKILL, STRETCH, GROUP, rajzolási sorrend |
| `query` | elemek listázása/részletei, számlálás, befoglaló méret, távolság, hossz, terület, MASSPROP (súlypont, inercia, térfogat), szövegkeresés, metszéspontok, legközelebbi elemek, hasonlók kijelölése, adatkinyerés CSV-be/táblázatba |
| `layer` | rétegek listája szűrőkkel, létrehozás, módosítás, átnevezés, összevonás, törlés, aktuális réteg, izolálás, rétegállapotok és elnevezett rétegszűrők (az AutoCAD Rétegtulajdonság-kezelője is látja), LAYTRANS, szabványellenőrzés |
| `block` | blokkok listája/tartalma, definiálás, attribútumok (BATTMAN: átnevezés, sorrend, szinkron), beszúrás, átnevezés, törlés, újradefiniálás, import, XREF csatolás/kezelés/beágyazás (XBIND), XCLIP |
| `style` | vonaltípusok, szövegstílusok, méretstílusok, mértékegységek |
| `layout` | papírtér-layoutok (A0–A4), nézetablakok méretaránnyal, oldalbeállítás (papír, tájolás, lépték, tollkiosztás, plotter) |
| `view` | **kép a rajzról a Claude-nak** (elemazonosítókkal, koordinátákkal), nyomtatás PDF/SVG/PNG/JPG/TIFF/EPS-be méretarányosan, CTB tollkiosztással vagy monokróm, többlapos PDF (PUBLISH), STL/OBJ 3D export |
| `road` | **útügyi tervezés**: nyomvonal egyenesekből, klotoidokból (átmeneti ív) és körívekből; szelvényezés (KE, ÍE, ÍV, KV pontokkal); szelvény ↔ koordináta; burkolatszél és eltolt vonalak; burkolati jelek (szaggatott/folytonos, valós szélességgel); kitűzési táblázat; hossz-szelvény lekerekítő ívekkel és adatsávval; keresztszelvények rézsűvel, túlemeléssel, pályaszerkezeti rétegekkel, árokkal, bevágás/töltés területtel, földmunka- és rétegmennyiséggel; KRESZ-tábla jelképek (szelvényre helyezve); körforgalom pontos ívekkel és terelőszigetekkel; szintbeni csomópont (T, X, ferde is) sarokívekkel; hosszirányú árok (fenékszint, esés, mélypontok, folyásirány-nyilak, hossz-szelvényben is); átereszek; vízszállítás (Manning) és lefolyó vízhozam (racionális módszer); tervezési paraméter-ellenőrzés (e-UT 03.01.11 értékeivel); **pályaszerkezet-méretezés** forgalmi terhelésből és megerősítési vizsgálat (e-UT 06.03.14:2026); kitűzési jegyzék; fordulóív-vizsgálat (szóló jármű, nyerges szerelvény); zebra, stop- és várakozóvonal, irányjelző nyilak, záróvonallal határolt terület; parkoló kiosztás; jelzőfejek, jelzésterv, közbenső idők; **hivatalos KRESZ-táblaképek** (513 közkincs tábla) |
| `terrain` | **terepmodell**: geodéziai pontok importja (CSV/TXT, EOV), TIN felület, szintvonalak (fő szintvonal felirattal), terepszint pontban és a nyomvonal mentén |
| `geo` | **georeferencia**: EOV ↔ WGS84 (GPS) ↔ bármely EPSG átszámítás, GPS-pontok a rajzba, AutoCAD földrajzi hely (GEODATA), Google Earth KML export |
| `survey` | **geodézia**: pontlista (alappontok, számított pontok), irányszög és távolság, poláris pontszámítás tájékozással és trigonometriai magassággal, sokszögvonal záróhibákkal és kiegyenlítéssel, előmetszés, ívmetszés, hátrametszés, szintezési vonal, Helmert/affin transzformáció, **DAT import** (földhivatali alaptérkép), **kisajátítás** földrészletenként, megvalósulási ellenőrzés (mért és tervezett), **DAT export** |
| `utility` | **közmű**: csatornahálózat aknákkal, automatikus folyásfenékkel és hidraulikával (részteltség), csatorna hossz-szelvény, vízhálózat-számítás (hurkos is), közművezetékek fajta/állapot/méret/mélység szerint, közmű-ütközésvizsgálat, közművek a keresztszelvényben, **gázhálózat** (kis- és középnyomás) és **távhőhálózat** számítása |
| `electric` | **villamos és közvilágítás**: oszlopkiosztás a tengely mentén (egyoldali, szemközti, váltott), fényeloszlás-fájlok (EULUMDAT, IES), megvilágításszámítás (Eav, Emin, U0, izolux), feszültségesés, egyvonalas jelképek és kapcsolási rajz |
| `rail` | **vasút (KÉ-VA alap)**: túlemelés ívenként (egyensúlyi, hiány, többlet, kifuttatás), vágány alaprajzban, kitérő (pl. 54-190-1:9), ágyazatos keresztszelvény túlemeléssel |
| `python` | vészkijárat: tetszőleges ezdxf Python-kód a nyitott rajzon, ha valamire nincs külön eszköz |
| `batch` | sok lépés egy hívásban, egyben visszavonható; a lépések hivatkozhatnak egymás eredményére (`"$0.handles[0]"`) |

Minden módosítás visszavonható (`drawing.undo`), hiba esetén a rajz automatikusan visszaáll.

## Korlátok (őszintén)

- **Nem az élő AutoCAD-ablakban rajzol**, hanem a rajzfájlt szerkeszti. Ha a rajz nyitva van
  AutoCAD-ben, mentés után újra kell tölteni. Az élő vezérlés a következő szakasz (lent).
- **DWG** az ingyenes ODA File Converterrel megy (telepítve, lent). Ez macOS-alkalmazás, ezért
  csak bejelentkezett asztali munkamenetből fut (a Claude-ból indított szerver ilyen).
- **3D**: valódi 3DSOLID-ok készülnek, de sík lapokból (fazettálva). Doboz, ék, gúla pontos;
  henger, gömb, tórusz palástja sokszöglapos. A logikai műveletek (egyesítés, kivonás, metszet,
  vágás) ilyen testeken mennek; AutoCAD-ben készült görbe felületű testeken nem.
- **Nem megoldható fájlszinten**: parametrikus kényszerek, FILLETEDGE, REGION, AutoLISP
  alkalmazások, dinamikus blokkok, natív TABLE/TABLESTYLE, natív FIELD és asszociatív méret
  (ez utóbbi kettőt az MCP saját mezőivel pótolja, frissítés: `annotate.update_fields`).
- A **spline EXTEND** a végszakasz természetes folytatása (az AutoCAD is így nyújt); JOIN-nál, ha
  spline vagy ellipszisív is van a kijelölésben, egyetlen SPLINE lesz, amelyben a körívek pontosak.
- **OFFSET íves polyline-nál pontos** (ívek ívek maradnak); splinenél és ellipszisnél közelít,
  ahogy az AutoCAD is.
- Az előnézeti kép (`view.png`) az ezdxf rajzolójával készül, apró eltérések lehetnek az
  AutoCAD megjelenítéséhez képest (betűtípus, vonalvastagság).

## Telepítés és bekötés

Lépésről lépésre: **TELEPITES.md**. Röviden, a projekt mappájában:

```bash
./install.sh
```

A telepítő létrehozza a `.venv` környezetet, feltelepíti a csomagokat, kipróbálja a szervert, és
ha a `claude` parancs elérhető, felhasználói szinten beköti a Claude Code-ba (`kek` profillal). A
kézi bekötés parancsát és a Claude Desktop beállítását is kiírja; minta: `mcp-config.example.json`.
A rajzok alapból a `~/Documents/CAD-MCP` mappába kerülnek (`CAD_MCP_WORKDIR`).

A `CAD_MCP_ALLOW_PYTHON=1` környezeti változó bekapcsolja a `python` vészkijáratot (a Claude
Python-kódot futtathat a gépen a rajzon); alapból ki van kapcsolva.

### Kapcsolható modulok

Egy szerver, egy közös rajz, de a Claude csak a bekapcsolt modulok eszközeit látja. Kevesebb eszköz
pontosabb eszközválasztást és kevesebb tokent jelent. A modulok műveletszinten működnek, így a nagy
`road` eszköz is szétválik.

| modul | tartalom | ~token |
|---|---|---|
| `alap` (mindig be) | rajz, rajzolás, szerkesztés, lekérdezés, rétegek, blokkok, stílusok, layoutok, nyomtatás, feliratozás, méretezés | 4 200 |
| `halado` | ritkább 2D parancsok (REVCLOUD, MLINE, alátétek, ALIGN, MATCHPROP, OVERKILL, STRETCH, QDIM, tűréskeret, mezők, XREF/XCLIP, rétegállapot/-szűrő, eTransmit, PUBLISH …) | 4 300 |
| `3d` | 3D testek | 1 000 |
| `ut` | nyomvonal, hossz- és keresztszelvény, csomópont, körforgalom, e-UT ellenőrzés, kitűzés, pályaszerkezet | 2 100 |
| `forgalomtechnika` | burkolati jelek, KRESZ-táblák, jelzőlámpák, parkolók, fordulóív | 1 250 |
| `vizelvezetes` | útárok, áteresz, kapacitás, lefolyás | 450 |
| `terep`, `geo` | terepmodell, EOV/GPS, KML | 700 |
| `geodezia` | geodézia, DAT import/export, kisajátítás | 1 900 |
| `kozmu` | csatorna, víz, gáz, távhő, közművezetékek, ütközésvizsgálat | 1 600 |
| `villamos` | közvilágítás, megvilágítás, feszültségesés, egyvonalas rajz | 900 |
| `vasut` | túlemelés, vágány, kitérő, vasúti keresztszelvény | 650 |

Profilok (a jogosultságok szerint): `kek` (útügy: alap + ut + forgalomtechnika + vizelvezetes +
terep + geo), `vztel` (közmű: alap + kozmu + ut + terep + geo), `geodeta` (alap + geodezia + terep +
geo), `kozvil` (alap + villamos + ut + terep + geo), `keva` (vasút: alap + vasut + ut + terep + geo), `rajz`
(alap + halado + 3d), `minimal` (csak alap), `mind` (minden). A teljes eszközlista kb. 23 400 token; a
`kek` profillal kb. 11 800 (–49%), a `minimal` profillal kb. 6 700 (–71%).

- **Indításkor**: `CAD_MCP_MODULES` környezeti változó (pl. `kek` vagy `alap,geodezia,kozmu`). A fenti
  bekötés `kek`-kel indul.
- **Menet közben**: a mindig látható `modules` eszközzel (*„kapcsold be a közmű modult”*). A Claude
  Code azonnal frissíti az eszközlistát. A választást a munkamappába menti
  (`.cad-mcp-modules.json`), és a következő indításkor ez érvényes.
- **Kikapcsolt modul használata bekapcsolás nélkül**: `modules` → `describe` (a modul műveletei) és
  `run` (bármely művelet futtatása). Ha egy eszköz leírásában ott a „More operations in the disabled
  module(s) …” sor, ott rejtett műveletek vannak.

### Tervezési paraméterek (e-UT)

A `road.design_check` a hatályos **e-UT 03.01.11:2008 (ÚT 2-1.201) Közutak tervezése (KTSZ)**
számértékeivel ellenőriz. A Magyar Közút hivatalos online példányából
(<https://ume.kozut.hu/dokumentum/1490>) kiolvasott értékek oldalszám-hivatkozással az
`assets/eut` mappában vannak, három beépített szabálykészletben:

| név | útosztály | tervezési sebesség |
|---|---|---|
| `eut_kulterulet` | külterületi közutak (K.III–K.VI), 3. fejezet | 30–90 km/h |
| `eut_gyorsforgalmi` | autópálya, autóút (K.I, K.II), 2. fejezet | 80–130 km/h |
| `eut_belterulet` | belterületi közutak (B.III–B.VI), 4. fejezet | 30–80 km/h |

Használat a Claude-dal: *„ellenőrizd az M1 tengelyt 90 km/h-ra a külterületi e-UT szabályokkal”*
(→ `road.design_check name=M1 design_speed=90 rules_file=eut_kulterulet`). Ellenőrzött elemek:
legkisebb körívsugár, átmenetiív-paraméter (Pmin), kötelező átmeneti ív, túlemelés nélküli
legkisebb sugár, legnagyobb túlemelés (7%), burkolatszél relatív hosszesése a
túlemelés-kifuttatásban, kis középponti szögű ívek, egymást követő ívek sugararánya, legnagyobb
hosszesés, domború/homorú lekerekítő sugarak, megállási látótávolság (1,00 m szem- és
0,10/0,30/0,50 m akadálymagassággal), előzési látótávolság domború ívekben (figyelmeztetésként).
A hibák piros jelöléssel a rajzba is kerülnek.

Amit az előírás nem ad meg számmal (pl. legrövidebb egyenes két ív között, A/R arány – ezekre a
10. tervezési útmutatóra hivatkozik), az üres marad; a fájlok `notes` része felsorolja a szöveges
feltételeket (pl. hegyvidéki emelkedő-csökkentés). A túlemelés nagyságát az előírás az 1.5. ábrán
adja – ezt a tervező olvassa le, a program csak a 7%-os felső határt ellenőrzi. Az értékek
újragenerálása: `python3 scripts/build_eut_rules.py`. Saját szabályokhoz üres sablon:
*„készíts tervezési szabálysablont szabaly.json néven”* (`road.design_rules_template`).

### Pályaszerkezet-méretezés (e-UT 06.03.14:2026)

A `road.pavement_design` a hatályos **e-UT 06.03.14:2026 Aszfaltburkolatú útpályaszerkezetek
méretezése és megerősítése** (<https://ume.kozut.hu/dokumentum/2024>, hatályos 2026. április 15-től;
a 06.03.13:2005 helyett) szerint számol:

- **méretezési forgalom (MF)** ÁNET-ből vagy járműosztályonként (B, C1n+C2, D, E+F; M1.1. táblázat),
  az élettartammal (gyorsforgalmi 30, főút 20, egyéb 15 év) és az n, r, s, w, m, f_N szorzókkal;
- **forgalmi terhelési osztály** (A1 … R+, 4.1. táblázat) és a választható **földmű-modulus** (E2m, 5.1. táblázat);
- **típus-pályaszerkezetek** rugalmas (RBA), szemcsés (FZKA/M) és hidraulikus kötőanyagú alapréteggel,
  az aszfalt-összvastagsággal (6.1–6.3. táblázat, az előírás interpolációs és 10%-os szabályával),
  kerékpárutak és járdák (6.4. táblázat);
- az első változat rétegrendje közvetlenül a `road.cross_sections` pályaszerkezetének adható, és a
  rajzba rétegoszlopként is kirajzolható.

Példa: *„méretezd a pályaszerkezetet: főút, ÁNF busz 40, nehéz tehergépkocsi 300, pótkocsis 80,
nyerges 400 jármű/nap, f_N = 1,3"*. Az f_N forgalomfejlődési szorzót (e-UT 02.01.31) a tervező adja
meg. A `road.pavement_strengthening` meglévő pályán a mért behajlásokból számolja a mértékadó és a
megengedett behajlást (7.5–7.8), és megmondja, kell-e erősítés; az erősítőréteg vastagságát (Δh)
az előírás 7.2. ábrájáról kell leolvasni. Az aszfalt-összvastagság rétegekre bontása az e-UT 06.03.21
szerint történik (ez a tervező döntése).

### Geodézia (`survey`)

Koordináták EOV szerint: **[Y, X, H] méterben** (Y kelet = rajz x, X észak = rajz y); az irányszög
északtól az óramutató járásával mérve; szögek tizedfokban vagy `"123-45-12.5"` alakban (gon is).

- **Pontlista**: alappontok és számított pontok név szerint a rajzban (CSV/TXT import); a többi számítás
  név szerint hivatkozik rájuk, az eredmény pontok bekerülnek a listába és a rajzba.
- **Poláris pontszámítás** több tájékozó irányra középtájékozással (javítások másodpercben és mm-ben),
  ferde vagy vízszintes távolsággal, trigonometriai magassággal.
- **Sokszögvonal**: kétszeresen csatlakozó és tájékozott, zárt vagy szabad; bal vagy jobb oldali
  törésszögek; a szögzáróhibát egyenlően, a koordináta-záróhibát a hosszak arányában osztja el;
  f_β, f_Y, f_X, f_l, 1:N, és ellenőrzi a megadott hibahatárokat (a hibahatárt a tervező adja meg).
- **Metszések**: előmetszés irányszögekből vagy szögekből, ívmetszés, hátrametszés 3+ pontra legkisebb
  négyzetekkel (javítások, veszélyes kör figyelmeztetés).
- **Szintezési vonal** záróhiba-elosztással és oldalpontokkal; **Helmert/affin transzformáció** közös
  pontokból javításokkal, a rajzelemek transzformálásával.
- **DAT import**: a földhivatali `.dat` adatcsere-állományt (DAT-M1 szabályzat G függeléke szerint) a
  rajzba teszi: földrészletek helyrajzi számmal, alrészletek, épületek, közigazgatási határok, utak,
  vizek, kerítések, alappontok, feliratok, a körívek pontosan; a megszűnt rekordokat kihagyja.
- **Kisajátítás**: az útsáv (tengely + szélességek szelvény szerint) vagy egy határvonal alapján
  földrészletenként az igénybe vett és a maradó terület (m²), az arány, az új határpontok
  koordinátái; sraffozás, felirat, CSV és táblázat a rajzban.
- **Megvalósulási ellenőrzés** (ME-KÉ, MV-KÉ): mért pontok eltérése a tervezett felülettől, az útterv
  szintjétől (szelvény, eltolás, ΔZ) vagy a tervezett vonaltól, tűréssel, jelöléssel, CSV-vel.

### Közmű (`utility`)

- **Csatornahálózat**: aknák (fedlapszint vagy terepmodellből), csövek; a hiányzó folyásfenék-szinteket
  a legkisebb takarásból és esésből a terepet követve tervezi (bukás, fenék- vagy tetőillesztés);
  teltelt kapacitás, a beérkező vizekből lefelé összegzett vízhozamnál részteltség (h/D) és sebesség
  Manning vagy Prandtl–Colebrook szerint; ellenőrzés a megadott határokra. Kirajzolja az aknákat, a
  csöveket feliratokkal és folyásirány-nyilakkal; **csatorna hossz-szelvény** adatsávval.
- **Vízhálózat**: hurkos hálózat is (globális gradiens módszer, mint az EPANET), Hazen–Williams vagy
  Darcy–Weisbach; csomóponti nyomás (m, bar), csőhozam, sebesség, fajlagos veszteség.
- **Közművezetékek** fajta (víz, szennyvíz, csapadék, gáz, villamos, közvilágítás, távközlés, távhő …),
  állapot (meglévő, tervezett, megszüntetendő), méret és mélység szerint, saját rétegen, felirattal.
- **Közmű-ütközésvizsgálat**: keresztezésnél függőleges, párhuzamos szakaszon vízszintes tiszta
  távolság; a védőtávolságokat a tervező adja meg (sablon: `utility.clearance_rules_template`,
  az MSZ 7487-2 és az üzemeltetők előírásai szerint kitöltendő).
- **Közművek a keresztszelvényben** valós helyükön és magasságukban.

A méretezési határértékeket (legkisebb esés, takarás, sebesség, nyomás, védőtávolság) a program nem
találja ki: a tervező adja meg, és csak a megadottakat ellenőrzi.

### Villamos, közvilágítás (`electric`) és vasút (`rail`)

- **Közvilágítás**: oszlopok a tengely mentén (egyoldali, szemközti, váltott), számozással, karral és
  kábelnyomvonallal. A megvilágítást a lámpatest fényeloszlás-fájljából (EULUMDAT `.ldt` vagy IES
  `.ies`, ezeket a gyártók adják) pontonként számolja: Eav, Emin, Emax, U0, izoluxvonalak. A
  karbantartási tényezőt és a világítási osztály követelményeit a tervező adja meg. A fénysűrűség
  (cd/m²) számítása az útburkolat reflexiós táblázatai nélkül nem készült el.
- **Feszültségesés** sugaras kábelen (Cu/Al, 1 vagy 3 fázis, hőmérséklet, reaktancia), a
  közvilágítási kiosztásból is; **egyvonalas jelképek** és **kapcsolási rajz** (betáp, gyűjtősín,
  leágazások).
- **Gáz- és távhőhálózat** (`utility`): kisnyomású gáz Darcy–Weisbach szerint a gáz felhajtóerejével,
  középnyomású a p₁² − p₂² egyenlettel, hurkos hálózat is; távhőnél a hőigényből tömegáram, előremenő
  és visszatérő veszteség, a fűtőműben szükséges nyomáskülönbség.
- **Vasút**: a tengely, szelvényezés és hossz-szelvény az útügyi eszközökkel készül; mellé jön a
  túlemelés ívenként (egyensúlyi túlemelés, hiány, többlet, kifuttatási hossz a megadott határokkal),
  vágány alaprajzban, kitérő sugárból és hajlásból (pl. `54-190-1:9`; a kitérő a és b méretét a
  típustáblázatból kell megadni, mert a MÁV-adatlapok nem nyilvánosak), ágyazatos keresztszelvény.
- **DAT export** (`survey.export_dat`): a földrészleteket helyrajzi számmal, ívekkel és lyukakkal
  visszaírja DAT-formátumba (oda-vissza ellenőrizve). A földhivatali beadáshoz a kódtáblázatos
  kötelező adatokat (fekvés, elhatárolás, jelkulcs, munkaterület) még ki kell tölteni.

### KRESZ-táblák

Az `assets/kresz` mappában 513 érvényes magyar közúti jelzőtábla SVG-je van a Wikimedia Commonsról
(közkincs és CC0; a forrás és a licenc táblánként az `index.json`-ban): veszélyt jelző (A, 57),
elsőbbségi (B, 6), tilalmi (C, 62), utasítást adó (D, 36), tájékoztató (E–I) és kiegészítő táblák.
A régi, már nem érvényes változatok nincsenek a jegyzékben. A Claude a `road.kresz_list` /
`road.kresz_sign` / `road.kresz_sign_at` eszközzel valódi színes blokként teszi a rajzba (kitöltések
lyukakkal, a tábla feliratai). Frissítés (a Wikimedia kapcsolati címet kér az automatikus letöltéshez):

```bash
KRESZ_CONTACT=sajat@email.hu python3 scripts/fetch_kresz_signs.py
```

### DWG támogatás

Az ingyenes ODA File Converter (Open Design Alliance, Apple által hitelesített) telepítve van:
`/Applications/ODAFileConverter.app`. A szerver magától megtalálja (más helyhez:
`CAD_MCP_ODA_PATH`).

- Megnyitás: `drawing.open path='valami.dwg'`
- Mentés: `drawing.save path='valami.dwg'`; alapból AutoCAD 2018 formátum, régebbi verzióhoz
  `dwg_version`: `R2013`, `R2010`, `R2007`, `R2004`, `R2000`, `R12`.
- Eltávolítás: töröld az alkalmazást az Alkalmazások mappából; ezután a DXF ugyanúgy működik.
- Másik gépre: https://www.opendesign.com/guestfiles/oda_file_converter

## Példa kérések a Claude-nak

- „Rajzolj egy 8×6 méteres szobát 30 cm-es falakkal, sraffozd a falakat, tegyél bele egy
  90-es ajtót, és méretezd be. Mentsd el szoba.dxf néven.”
- „Nyisd meg a ~/Documents/CAD-MCP/alaprajz.dxf-et, és mondd meg, hány darab ASZTAL blokk van
  benne és mennyi a NAPPALI réteg területe.”
- „Minden szöveg a 0-s rétegen legyen a SZOVEG rétegen, és ellenőrizd, hogy van-e elem 0-n.”
- „Csinálj belőle A3-as PDF-et 1:50-ben.”
- „Töltsd be a pontok.csv-t (pontszám;Y;X;Z), készíts terepmodellt és 0,5 m-es szintvonalakat.”
- „Tervezz nyomvonalat ezeken a töréspontokon R=400 és R=300 ívekkel, 80 és 60 m-es klotoiddal,
  szelvényezd 100 m-enként, rajzold meg a 2×3,5 m-es burkolatot és a burkolati jeleket.”
- „Az ívekben legyen 5%-os túlemelés, a pályaszerkezet 4 cm AC-11, 6 cm AC-22, 20 cm CKt,
  25 cm homokos kavics; bevágásban 60 cm mély árok. Add meg a rétegmennyiségeket.”
- „Tegyél 70-es sebességkorlátozó táblát a 0+300-as szelvénybe jobb oldalra, és rajzolj egy
  36 m-es körforgalmat négy ággal a 1+400-nál.”
- „A rajz EOV-ban van: exportáld KML-be, hogy megnézzem Google Earth-ön.”
- „A mellékút a főút 0+150-es szelvényében csatlakozik, R=12 és R=9 sarokívekkel. Tervezz jobb
  oldali árkot, mutasd a mélypontokat, és tegyél oda D60-as átereszt. Elég-e az árok 180 l/s/ha
  esőre 1800 m² burkolatról?”
- „Készíts hossz-szelvényt a terepből, a tervezett szint menjen ezeken a töréspontokon 8000-es
  lekerekítéssel, és 20 m-enként keresztszelvényt bevágás/töltés tömeggel.”

## Honnan tudjuk, hogy tényleg tudja? (lefedettség)

Két hivatalos lista alapján mérjük:

- `coverage/commands.csv`: 250 AutoCAD-parancs (+ az útügyi, Civil 3D-szerű feladatok), mindegyikhez
  státusz: kész / részben / hiányzik / élő AutoCAD kell / nem értelmezhető, és az MCP-művelet neve.
- `coverage/dxf_types.csv`: az Autodesk AutoCAD for Mac 2026 DXF-referenciájának összes elem-,
  táblázat- és objektumtípusa (a súgó tartalomjegyzékéből, `coverage/source/`).

Ellenőrzés két lépésben:

```bash
.venv/bin/python -m pytest -q
```

```bash
.venv/bin/python coverage/check_coverage.py
```

A tesztfutás rögzíti, mely műveletek futottak le ténylegesen (`coverage/ops_tested.json`). Az
ellenőrző hibát jelez, ha a táblázat nem létező műveletre hivatkozik, ha egy művelethez nincs
sikeres teszt, vagy ha a tesztek elbuktak. Eredmény: `coverage/REPORT.md` (jelenleg: 303/303
művelet tesztelve; a fájlszinten értelmezhető 276 tételből 254 kész (92%), 19 részben (7%), 3 hiányzik: natív TABLESTYLE, fénysűrűség-számítás (r-táblák kellenek), MÁV kitérő-típustáblázatok; az útügyi, geodéziai és közműsorok mind készek).

Megjegyzés: az Autodesk online parancslistája csak bejelentkezve tölthető le, ezért a parancstáblázat
a teljes AutoCAD-parancskészletből készült. Ha bejelentkezve exportálod a hivatalos listát, a
táblázat összevethető vele.

## Fejlesztés

```bash
.venv/bin/python -m pytest -q                  # 102 teszt, köztük valódi MCP stdio kapcsolat és DWG
.venv/bin/python examples/demo_floorplan.py    # mintarajz: examples/demo.*
.venv/bin/python examples/demo_road.py         # minta-útterv: examples/road.dxf, road_*.png
.venv/bin/python examples/demo_junction.py     # T-csomópont árokkal, átereszekkel: examples/junction.dxf
.venv/bin/python scripts/make_test_pack.py      # éles AutoCAD-teszt rajzai (TESZTLISTA.md)
```

Új művelet: egy függvény `@op("eszköz", "név", mutates=True)` dekorátorral bármelyik
`src/cad_mcp/ops_*.py` fájlban; a leírása automatikusan bekerül az eszköz súgójába.

## Következő szakasz: élő AutoCAD-kapcsolat

A fájlon nem megoldható parancsok (parametrikus kényszerek, FILLETEDGE, REGION, AutoLISP,
dinamikus blokkok) élő AutoCAD-hídon keresztül jöhetnek: AutoCAD for Macen ObjectARX for Mac
bővítménnyel vagy AutoLISP-pel (teljes AutoCAD for Mac, nem LT). A beillesztés helyét a
TELEPITES.md „Közvetlen (élő) AutoCAD-kapcsolat beillesztése” része írja le.
