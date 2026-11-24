# Éles teszt AutoCAD-ben – ellenőrzőlista

Az MCP a rajzot fájlként készíti (DXF/DWG). Az automatikus tesztek a fájlok tartalmát és
szabályosságát ellenőrzik, valódi AutoCAD-ben viszont még nem futottak. Ez a lista azt méri, hogy
az AutoCAD is úgy látja-e a rajzokat, ahogy kell.

## 1. A próbarajzok elkészítése

```bash
.venv/bin/python scripts/make_test_pack.py --dwg
```

A `teszt_csomag` mappába 11 rajz kerül DXF-ben (és `--dwg`-vel DWG-ben is), mindegyikhez egy PNG
előnézet. A PNG azt mutatja, amit az MCP „lát”; ezzel lehet összevetni az AutoCAD képét.

Minden fájlnál először: **Megnyitás** → nincs hibaüzenet, nincs „javítás szükséges” ablak →
**AUDIT** parancs (javítás: Nem) → 0 hiba. Ezután jönnek az alábbi pontok. Jelöld: ✅ jó, ❌ hiba
(a hibánál írd le, mit látsz, vagy küldj képernyőképet).

## 2. Ellenőrzendő pontok

### 01_alap_2d – alap rajzelemek, méretezés, rétegek
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Rétegek (LAYER) | FAL piros 0,5 mm, NYILAS zöld szaggatott, MERET sárga, SZOVEG | |
| 2 | Ívelt polyline, kör, ellipszis, spline | íves szakaszok simák, a spline sima görbe | |
| 3 | Sraffozás szigettel | a belső téglalap üresen marad | |
| 4 | Színátmenet (gradient) | piros → sárga, 30°-ban | |
| 5 | Ékezetes szöveg | „Árvíztűrő tükörfúrógép” hibátlan ő, ű, Ő, Ű betűkkel | |
| 6 | Méretek: lineáris, ferde, szög, sugár, átmérő, ordináta | helyes érték, szerkeszthető (Tulajdonságok) | |
| 7 | Megtört sugárméret (az ív felett) | DIMJOGGED méretként jelölhető ki, a cikcakk és a középpont fogója mozgatható | |
| 8 | Vezérvonal (MLEADER) és táblázat | megjelenik, a táblázat vonalakból és szövegből áll | |
| 9 | AKNA blokk attribútummal | „A-17” attribútum, ATTEDIT-tel szerkeszthető | |
| 10 | Rétegállapot-kezelő (LAYERSTATE) | „Minden látszik” és „Nyílások nélkül” állapot; visszaállítás működik | |
| 11 | Rétegszűrők (Rétegtulajdonság-kezelő bal oldala) | „Falak és méretek” tulajdonságszűrő és „Csoport: szöveg” csoportszűrő | |
| 12 | Elnevezett nézet (VIEW) | „Alaprajz” nézet létezik | |

### 02_3d – 3D testek
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | 3D nézet (pl. SW izometrikus, Árnyalt stílus) | doboz hengeres lyukkal, ék, sweep, loft | |
| 2 | Kijelölés | 3DSOLID (test) típusú elemek | |
| 3 | MASSPROP a lyukas dobozon | térfogat ≈ 2000³ − π·500²·2000 ≈ 6,43·10⁹ mm³ (6,43 m³; a henger sokszöglapos, kis eltérés jó) | |
| 4 | NEZET blokk | 2D vetület, takart élek szaggatott vonallal (FLATSHOT_TAKART réteg) | |

### 03_layout_nyomtatas – papírtér, nyomtatás
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | „A3 lap” layout | A3 fekvő lap, egy nézetablakkal | |
| 2 | Nézetablak lépték | 1:50 (0,02) | |
| 3 | Oldalbeállítás (PAGESETUP) | A3, fekvő, monochrome.ctb | |
| 4 | Nyomtatás PDF-be | a lap tartalma, léptéke rendben | |

### 04_utterv – útterv
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Tengely | két körív átmeneti ívekkel (klotoid), szelvényezés 100 m-enként | |
| 2 | Burkolatszél és burkolati jelek | ±3,5 m, szaggatott tengelyjel és folytonos szélső jel | |
| 3 | Szintvonalak | szintvonalak, fő szintvonalak felirattal | |
| 4 | Ívkitűzési táblázat | a tengely felett | |
| 5 | Hossz-szelvény | terepvonal, tervezett vonal lekerekítő ívekkel, adatsáv | |
| 6 | Keresztszelvények | pályaszerkezeti rétegek, árok, bevágás/töltés terület | |
| 7 | KRESZ-táblák | A-001, C-033-70, B-001, D-001 a megfelelő szelvényeknél, színesen | |
| 8 | Pályaszerkezet rétegoszlop | aszfalt és alapréteg, sraffozással, a rajz jobb oldalán | |
| 9 | ELLENORZES réteg | ha van piros jelölés, az e-UT ellenőrzés talált valamit | |

### 05_csomopont – csomópont, forgalomtechnika
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | T-csomópont | sarokívek R=10 m | |
| 2 | Zebra, stopvonal, parkoló | csíkok, vonal, 90°-os állások | |
| 3 | Jelzőfej | blokk „K1” attribútummal | |
| 4 | Körforgalom | pontos körívek, terelőszigetek | |
| 5 | Fordulóív-vizsgálat | nyerges szerelvény burkológörbéje | |

### 06_kozmu – közmű
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Csatorna | aknák, csövek feliratokkal (DN, anyag, hossz, esés ‰), folyásirány-nyilak | |
| 2 | Csatorna hossz-szelvény | terep, csőfenék és -tető, aknák, adatsáv | |
| 3 | Víz- és gázhálózat | csomóponti nyomások, csőhozamok feliratban | |
| 4 | Közművezetékek | KOZMU_GAZ_MEGLEVO, KOZMU_VIZ_TERVEZETT rétegek | |
| 5 | Ütközésvizsgálat | piros kör a túl közeli szakasznál (KOZMU_UTKOZES) | |

### 07_geodezia – DAT, kisajátítás
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Földrészletek | 0123/4 és 0123/5, a második északi oldala körív | |
| 2 | Terület (Tulajdonságok) | 2000 m² és ≈ 2418 m² | |
| 3 | Kisajátítás | piros sraffozás, felirat (hrsz: m²), táblázat | |
| 4 | Poláris pontok | P1, P2 a helyükön | |
| 5 | `export.dat` | (földmérő programmal, pl. ITR) megnyílik, földrészletek helyesek | |

### 08_villamos – közvilágítás
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Oszlopok | váltott elrendezés, számozás (KV1…), kar, lámpatest | |
| 2 | Kábelnyomvonal | szaggatott vonal oldalanként | |
| 3 | Egyvonalas rajz | transzformátor, megszakító, gyűjtősín, leágazások jelképei | |

### 09_vasut – vasút
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Vágány | sínek és aljak az ív mentén | |
| 2 | Kitérő 54-190-1:9 | egyenes és kitérő ág, VK, M, VV1, VV2 jelek | |
| 3 | Keresztszelvény | sínek, alj, ágyazat, alépítmény, 100 mm túlemelés | |

### 10_xref_fo – külső hivatkozás
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | Külső hivatkozások (XREF) | ALAP → 10_xref_alap.dxf betöltve | |
| 2 | Vágás (XCLIP) | csak a 70 × 40 m-es rész látszik | |

### 11_geo – földrajzi hely
| # | Mit nézz | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | GEOGRAPHICLOCATION | a rajznak van földrajzi helye | |
| 2 | Térkép bekapcsolása (ha elérhető) | Budapest és Debrecen pont a helyén | |

## 3. Claude-dal (éles munkamenetben)

| # | Kérés a Claude-nak | Elvárt | ✅/❌ |
|---|---|---|---|
| 1 | „Nyisd meg a 04_utterv.dxf-et, és mutasd a hossz-szelvényt.” | kép a rajzról, a hossz-szelvényre nagyítva | |
| 2 | „Készíts egy 600 m-es külterületi utat 70 km/h-ra, és ellenőrizd az e-UT szerint.” | tengely, szelvények, ellenőrzési lista | |
| 3 | „Kapcsold be a közmű modult, és tervezz egy 3 aknás csatornát.” | a modul bekapcsol, a csatorna elkészül | |
| 4 | „Mentsd DWG-be.” | a DWG megnyílik AutoCAD-ben | |

## 4. Ha valami hibás

Írd le a fájl nevét, a pont számát és hogy mit látsz (képernyőkép a legjobb). A hibák
többsége a fájl tartalmán javítható, AutoCAD nélkül is.
