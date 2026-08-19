# P&G árfigyelő — dm.hu & Rossmann

A **dm Magyarország** és a **Rossmann** webshopjából gyűjti ki a **P&G portfólió**
termékadatait, márka és kiszerelés szerint kategorizálva:

| mező | példa |
|---|---|
| Bolt | Rossmann |
| Kategória | Hajápolás |
| Márka | Head & Shoulders |
| Terméknév | Head & Shoulders Apple Fresh korpásodás elleni sampon - 400 ml |
| Kiszerelés | 400 ml *(mennyiség + egység külön oszlopban is)* |
| Ár | 2 354 Ft |
| Egységár | 5 885 Ft/l |
| EAN | 5410076659456 |
| Dátum | 2026-08-19 |

Két üzemmódban használható — **ugyanaz a kód, ugyanaz az Excel**:

* **A) GitHub-os weboldal** — a felhasználóknak *semmit nem kell telepíteniük*, csak
  megnyitnak egy linket. Naponta automatikusan frissül. **Ingyenes.**
* **B) Helyi program** — Windowson dupla kattintás, saját gépről futtatott,
  gombnyomásra induló lekérés.

---

# A) GitHub-os weboldal (telepítés nélkül, ingyen)

## Hogyan működik

```
  GitHub Actions (naponta 06:00)          GitHub Pages
 ┌──────────────────────────────┐        ┌──────────────────────┐
 │ Ubuntu gép + Python+Chromium │        │  docs/index.html     │
 │  → scrape dm.hu + Rossmann   │──────► │  betölti a JSON-t    │
 │  → latest.json / history.csv │ commit │  táblázat, szűrők,   │
 │  → PG_arak_latest.xlsx       │        │  Excel-letöltés      │
 └──────────────────────────────┘        └──────────────────────┘
```

Fontos: a GitHub Pages önmagában **nem tud** scrape-elni (statikus tárhely, a böngésző
CORS-a tiltja az idegen oldalak lekérését). A tényleges munkát a **GitHub Actions**
végzi egy szerveren, a Pages már csak a kész adatot mutatja.

## Beüzemelés – 6 lépés

1. **Repo létrehozása.** GitHub → *New repository* → név pl. `pg-arak`,
   láthatóság: **Public** (ingyenes csomagon a Pages csak nyilvános repóból megy).
2. **Fájlok feltöltése.** A repo *Add file → Upload files* pontjánál húzd be ennek a
   mappának a teljes tartalmát (a rejtett `.github` mappát is!), majd *Commit changes*.
   Ha van git a gépeden, egyszerűbb:
   ```bash
   git init && git add . && git commit -m "P&G árfigyelő"
   git branch -M main
   git remote add origin https://github.com/<fiók>/pg-arak.git
   git push -u origin main
   ```
3. **Írásjog az Actionsnek.** *Settings → Actions → General → Workflow permissions* →
   **Read and write permissions** → *Save*. (Enélkül nem tudja visszacommitolni az adatot.)
4. **Pages bekapcsolása.** *Settings → Pages → Source: Deploy from a branch* →
   branch **main**, mappa **/docs** → *Save*.
   Az oldal címe: `https://<fiók>.github.io/pg-arak/`
5. **Első futtatás.** *Actions → Napi ár-scrape → Run workflow*.
   Tesztnek állítsd a *max. termék márkánként* mezőt **5**-re — így 1-2 perc alatt lefut,
   és látod, hogy minden rendben van. Utána indítsd újra 0-val (teljes lekérés).
6. **Kész.** Pár perc múlva az oldalon ott az adat. Innentől minden nap magától frissül.

> Az `Actions` fülön az első belépéskor a GitHub kérhet egy megerősítést
> („I understand my workflows, go ahead and enable them”) — nyomd meg.

## Mit tud az oldal

* Szűrés bolt / kategória / márka / kiszerelés szerint + szabadszavas keresés
* **Árváltozás oszlop** az előző futáshoz képest (Ft és %), „csak az árváltozások" szűrővel
* **Összesítő fül**: márka × kiszerelés, boltonkénti átlagár és a két lánc közti különbség
* Letöltés: teljes **Excel**, a szűrt nézet **CSV**-ben, valamint a **teljes idősor** CSV-je
* Mobilon is használható, sötét témát is támogat

## Ütemezés módosítása

`.github/workflows/scrape.yml` → `cron: "0 4 * * *"` (UTC-ben!).
`0 4 * * *` = 06:00 Budapest nyári időben, 05:00 télen.
Kétszer naponta: `- cron: "0 4 * * *"` és `- cron: "0 14 * * *"`.

## Amit érdemes tudni

* A GitHub futtatói **adatközponti IP-ről** mennek, ott a boltok hamarabb korlátoznak.
  Ezért a workflow lassabb tempóval fut (3 szál, 0,8 s késleltetés). Ha hibákat látsz,
  emeld a `--keses` értéket 1,5–2-re.
* Az ütemezés **nem percpontos**, csúcsidőben késhet.
* A GitHub **60 nap inaktivitás után leállíthatja** az ütemezett futásokat — e-mailt
  küld róla, és egy kattintással újraindítható.
* Ha egy futás 0 terméket hoz, a program **nem írja felül** a korábbi adatot.
* Nyilvános repónál az összegyűjtött árak is nyilvánosak lesznek. Ezek amúgy is
  publikus bolti listaárak, de a repo nevében ne szerepeljen cégnév.

---

# B) Helyi program (Windows)

1. Telepítsd a **Python 3.10+** verziót: <https://www.python.org/downloads/>
   → pipáld ki az **„Add python.exe to PATH"** opciót.
2. Dupla kattintás a **`run.bat`** fájlra. Az első indítás létrehozza a virtuális
   környezetet és telepíti a függőségeket (~2–3 perc), utána megnyitja a felületet:
   **http://127.0.0.1:5000**

A felületen kiválasztod a boltot és a márkákat, elindítod, és a végén letöltöd az Excelt.
A fájlok a `kimenet` mappába is mentődnek.

> **Kollégáknak telepítés nélkül, helyi hálón:** indítsd `python app.py` helyett úgy,
> hogy az `app.run(host="127.0.0.1"...)` sorban `0.0.0.0` szerepeljen — ekkor a
> `http://<géped-IP-je>:5000` címen bárki eléri az irodai hálózatról.

### Parancssorból

```bat
.venv\Scripts\activate
python cli.py --lista                                  # márkakulcsok listája
python cli.py --bolt rossmann --marka head-shoulders pantene
python cli.py --bolt dm rossmann --mind --kimenet C:\arak
```

---

# Az Excel felépítése

1. **Termékek** — minden sor egy termék (szűrhető, rendezhető táblázat).
2. **Összesítő** — márka × kiszerelés bontás boltonként: darabszám, átlag-, min-, maxár
   és a boltok közötti árkülönbség. Innen olvasható ki például, hogy a *H&S 400 ml*,
   *625 ml* és *800 ml* mennyibe kerül a két láncnál.
3. **Info** — futási adatok, figyelmeztetések.

---

# Hogyan szedi le az adatokat

**Rossmann (shop.rossmann.hu)** — szerveroldalon renderelt oldal, sima HTTP elég.
A termék-URL-eket a `/markak/<márka>` oldalakról és a termék-sitemapből gyűjti, majd a
termékoldalról olvassa az árat, a *Cikkszám* mezőből az **EAN**-t (GS1 ellenőrzőösszeggel
validálva) és a *Kiszerelés* mezőt.

**dm (dm.hu)** — JavaScript-alapú oldal, a nyers HTML nem tartalmaz árat. Három lépcső,
automatikus választással:

1. **statikus** – hátha mégis benne van az adat a HTML-ben;
2. **API-felderítés** – egy háttérben futó Chromium megnyit 1-2 termékoldalt, elkapja az
   oldal saját JSON-kéréseit, sablont készít belőlük, és a többi terméket már gyors
   HTTP-vel kéri le. Így akkor is működik, ha a dm megváltoztatja az API címét;
3. **böngészős** – minden oldalt kirenderel és a DOM-ból olvas.

A termékadat-kinyerés több stratégiát futtat (JSON-LD → beágyazott JSON → DOM → meta
tagek) és összefésüli az eredményt, így egy CSS-osztály átnevezése nem töri el.

---

# Ha valami nem stimmel

```bat
python diagnose.py https://shop.rossmann.hu/termek/head-shoulders-apple-fresh-sampon-400-ml
python diagnose.py https://www.dm.hu/p/d/3119449/valami --bongeszo --html oldal.html
```

Kiírja, mit lát a program: nevet, árat, EAN-t, kiszerelést, a használt stratégiát és a
termékoldal összes specifikációs mezőjét.

| tünet | teendő |
|---|---|
| dm: 0 termék | helyben: `dm mód` = *csak böngésző* + *látható böngészőablak* |
| Hiányzó EAN | kapcsold be a *Termékoldalak megnyitása* opciót (a CI-ban alapból be van) |
| Kevés termék egy márkánál | hiányzó `slug_tokens` → `pgscraper/brands.py` |
| Actions hiba: „permission denied" | 3. lépés: *Read and write permissions* |
| Az oldal „Nincs még adat" | még nem futott le a workflow, vagy nem /docs a Pages forrása |

**Új márka felvétele** – `pgscraper/brands.py`:

```python
Brand("vicks", "Vicks", "Egészség",
      aliases=["wick"], slug_tokens=["vicks", "wick"], rossmann_slug="vicks"),
```

**Tesztek:** `python -m unittest discover -s tests -v`

---

# Jogi / használati megjegyzés

* A program csak nyilvánosan elérhető, bejelentkezés nélküli oldalakat olvas, udvarias
  sebességgel, és tiszteletben tartja a boltok `robots.txt` fájljában tiltott útvonalakat
  (a dm keresőoldalát például nem használja — helyette a nyilvános termék-sitemapet).
* A süti-sávot a program az **elutasítás / csak a szükséges** gombbal kezeli.
* A webshopok árai eltérhetnek a bolti áraktól, és bármikor változhatnak.
* Az adatok felhasználásánál a boltok ÁSZF-je és a vonatkozó jogszabályok az irányadók —
  belső ár- és portfóliókövetésre szánt eszköz.
