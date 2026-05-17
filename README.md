Na spúšťanie programu je potrebné mať nainštalovaný:

- Python 3
- `pip`

Odporúča sa najprv vytvoriť samostatné Python prostredie a
nainštalovať potrebné balíky a knižnice zo súboru `requirements.txt`.

Pre Windows:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Pre Linux/MacOS:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Po spustení aplikácie sa v termináli zobrazí lokálna adresa,
na ktorej je možné aplikáciu otvoriť v prehliadači, zvyčajne:
http://127.0.0.1:5000.