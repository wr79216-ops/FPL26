# FPL Signal

FPL Signal adalah aplikasi decision-support untuk manager Fantasy Premier League (FPL).
Aplikasi mengambil data publik resmi FPL, menyimpannya secara lokal, lalu menyajikan ranking
pemain, fixture, gameweek recap, saran transfer, wildcard draft, dan analisis jadwal secara
transparan. Aplikasi tidak melakukan transfer otomatis dan tidak menjamin poin.

## Status aplikasi

- Model production saat ini: `production-v1.1`.
- Candidate positional: `candidate-v1.3-positional` (eksperimental, belum menggantikan production).
- Data current season: endpoint publik resmi FPL dengan cache dan snapshot lokal.
- Backtest: dataset completed-season 2025–26 dari arsip CSV Vaastav, bukan feed live FPL.
- Deploy publik: dapat dijalankan di Railway dengan SQLite pada volume persisten.

## Menjalankan secara lokal

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Buka URL yang diberikan Streamlit. Untuk menjalankan test:

```bash
PYTHONPATH=. pytest
```

## Alur penggunaan yang disarankan

1. Buka **Data Status** dan pilih **Refresh official FPL data**.
2. Gunakan **Dashboard** untuk deadline, top recommendations, fixture radar, Gameweek Wrapped,
   dan top transfer-in pada gameweek berjalan.
3. Buka **Recommendations**, pilih GK/DEF/MID/FWD, lalu baca score breakdown dan official
   season evidence. Score 0–100 adalah ranking relatif, bukan probabilitas poin.
4. Gunakan **Player Detail** untuk memuat history resmi seorang pemain secara on-demand.
5. Gunakan **Compare** dan **Decision Tools** untuk membandingkan pemain, transfer, dan captain
   shortlist dengan asumsi yang sama.
6. Buka **Advanced Planner** untuk mengimpor squad publik berdasarkan manager ID, melihat
   exposure jadwal, insight set-piece, saran transfer, dan wildcard draft legal.
7. Buka **Backtesting** untuk melihat evaluasi time-safe model; halaman ini untuk validasi,
   bukan prediksi pasti.

## Fitur utama

| Menu | Fungsi |
|---|---|
| Dashboard | Deadline countdown, konteks GW, rekomendasi, fixture radar, signal leaders, Gameweek Wrapped, top transfer-in |
| Players | Cari/filter pemain berdasarkan posisi, harga, ownership, menit, dan horizon |
| Recommendations | Ranking position-relative dan alasan kontribusi yang dapat diaudit |
| Fixtures | Matriks fixture resmi dan fixture ease untuk horizon 1/3/5/8 GW |
| Player Detail | History resmi, tren points/minutes/xGI, dan confidence-adjusted features |
| Compare | Perbandingan dua pemain pada horizon yang sama |
| Decision Tools | Transfer finder dan captain shortlist Safe/Balanced/Differential |
| Advanced Planner | Squad publik, schedule congestion, blank/double GW planning, set-piece, transfer, wildcard |
| Backtesting | MAE, Spearman, Top-10 hit rate, actual points, dan release gate candidate |
| Data Status | Refresh, freshness, coverage, schema, sumber, dan error terakhir |

## Sumber data dan aturan missing value

Data current-season berasal dari endpoint publik resmi FPL: `bootstrap-static`, `fixtures`,
`element-summary/{player_id}`, `event/{gameweek}/live`, dan endpoint squad publik. Respons
divalidasi di `FPLClient`, disimpan sebagai raw snapshot, kemudian di-upsert ke SQLite. Jika
refresh gagal, snapshot resmi terakhir yang valid tetap digunakan.

Field positional seperti xGC, goals conceded, penalties saved/missed, cards, dan defensive
contribution disimpan nullable. Jika field tidak dikirim FPL, UI menampilkan **Not supplied**;
aplikasi tidak mengarang angka nol. Contract test akan menghentikan proses jika field inti yang
dibutuhkan ranking hilang dari payload.

Backtesting memakai CSV completed-season yang telah divalidasi dan hanya menggunakan informasi
sampai cutoff GW N untuk memprediksi outcome GW N+1 dan seterusnya. Data historical bukan
pengganti data current-season resmi.

## Batasan penting

- Tidak ada login, akses private league, atau eksekusi transfer/chip/captain otomatis.
- Selling price individual, free transfer aktual, transfer hit, price-change alert, late team
  news, lineup leak, dan injury news real-time tidak tersedia.
- Score adalah ranking relatif dalam posisi/horizon; score 80 bukan berarti 80 poin.
- Fixture adalah jadwal lawan. Fixture ease lebih tinggi berarti jadwal relatif lebih mudah,
  bukan jaminan clean sheet atau return.
- Set-piece taker adalah snapshot expected role dan hanya tie-breaker kecil.
- Historical identity yang ambigu masuk review/unmatched dan tidak memengaruhi score.
- Backtest satu musim belum cukup untuk menyimpulkan performa lintas musim.
- SQLite cocok untuk local-first/single-user; concurrent multi-user production belum menjadi
  cakupan MVP.
- Provider eksternal seperti FotMob masih disabled dan fail-closed.

## Model positional dan rilis

`candidate-v1.3-positional` menampilkan sinyal yang lebih relevan per posisi, misalnya xGC dan
saves untuk GK, clean sheet/xGI untuk DEF, xGI/bonus untuk MID, serta xG/conversion untuk FWD.
Candidate diuji leakage-safely per posisi dengan gate coverage dan regresi. Sampai ada hasil
yang memenuhi gate dan persetujuan aktivasi eksplisit, ranking live tetap `production-v1.1`.

Setelah deployment yang menjalankan migrasi schema, buka **Data Status** dan tekan **Refresh
official FPL data**. Untuk menghitung ulang gate candidate, jalankan import historical/backtest.
Schema SQLite bersifat forward-only; prosedur rollback model dan changelog ada di
[docs/MODEL_CHANGELOG.md](docs/MODEL_CHANGELOG.md).

## Struktur repository

```text
app.py                         # entry point Streamlit
src/api/                       # gateway FPL + validasi contract
src/services/                  # orchestration dan use case
src/domain/                    # domain contracts
src/features/                  # fixture, feature, positional signals, scoring
src/database/                  # SQLite, SQLAlchemy, migrations, repositories
src/ui/                        # halaman dan komponen Streamlit
config/                        # scoring, candidate weights, provider policy
docs/                          # arsitektur, scope, backtest, planner, changelog
tests/                         # unit, contract, database, dan frontend smoke test
```

## Dokumentasi lanjutan

- [Tech stack, cakupan, dan batasan](docs/TECHSTACK_AND_SCOPE.md)
- [Arsitektur dan schema](docs/ARCHITECTURE.md)
- [Model changelog dan rollback](docs/MODEL_CHANGELOG.md)
- [Backtesting](docs/BACKTESTING.md)
- [Positional Recommendation Signals Plan](docs/POSITIONAL_RECOMMENDATION_SIGNALS_PLAN.md)
- [Schedule Congestion Planner Plan](docs/SCHEDULE_CONGESTION_PLANNER_PLAN.md)
- [Advanced Planner](docs/ADVANCED_PLANNER.md)
- [Historical Data](docs/HISTORICAL_DATA.md)

## Data-source policy

Official FPL endpoints adalah sumber kebenaran untuk harga, ownership, points, status, dan
fixture. Sumber pihak ketiga hanya boleh menjadi enrichment terpisah melalui akses yang
diizinkan, validasi identitas pemain, dan dokumentasi lisensi/terms. Tidak ada scraping
provider eksternal dalam runtime MVP.
