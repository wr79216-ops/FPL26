# FPL Signal — Schedule Congestion & Blank/Double Gameweek Planner

## Tujuan

Menambahkan radar kepadatan jadwal, Blank Gameweek (BGW), dan Double Gameweek (DGW) ke menu **Advanced Planner**. Fitur ini harus membantu user memahami risiko jadwal tanpa menyajikan proyeksi sebagai kepastian.

Dokumen ini adalah implementation plan. Belum ada perubahan model rekomendasi atau UI produksi dari fitur ini.

## Ringkasan audit workbook `2026_27.xlsx`

Workbook dipakai sebagai referensi pola dan tata letak, bukan sebagai sumber produksi langsung.

### Bagian yang dapat dipakai sebagai referensi 2026/27

- `HA Schedule` memuat 20 klub dan GW1–GW38.
- Seluruh 760 sel klub-GW terisi: 20 klub × 38 GW.
- Tidak ditemukan lawan yang tidak dikenal, self-fixture, pairing yang tidak timbal balik, atau ketidakseimbangan 19 home/19 away.
- Team set saat ini berisi COV, HUL, dan IPS serta tidak lagi berisi BUR, WHU, dan WOL.
- `Condensed shedule with formulas` berguna untuk membaca slot Premier League, EFL Cup, FA Cup, UEFA, international break, dan calon midweek kosong.

### Bagian yang tidak aman untuk diimpor

- `Blank and Double GW sched`, `Blank GW31`, dan `Blank GW34` masih memakai team set musim lama: BUR, WHU, WOL; tidak memuat COV, HUL, IPS.
- Label `Blank GW31` tidak cocok dengan kalender resmi 2026/27: final EFL Cup berimpit dengan Premier League Matchweek 30.
- Label `Blank GW34` tidak cocok dengan kalender resmi 2026/27: semifinal FA Cup berimpit dengan Matchweek 33.
- Terdapat 49 error formula yang terdeteksi di workbook: 2 `#REF!` dan 47 `#N/A`. Error tersebar pada `Blank GW34`, `All fix + FDR Sched`, dan beberapa sheet lama/copy.
- Persentase lama menggunakan fixture cup dan odds lama yang belum relevan untuk draw 2026/27.

Kesimpulan: **struktur kalender current-season berguna; proyeksi BGW/DGW dan formula odds lama tidak boleh menjadi input produksi.**

## Fakta kalender 2026/27 yang menjadi baseline

### Klub Premier League di Eropa

| Kompetisi | Klub | Catatan model |
|---|---|---|
| Champions League | Arsenal, Aston Villa, Liverpool, Manchester City, Manchester United | 8 league-phase matches; knockout tergantung posisi dan kelolosan |
| Europa League | Bournemouth, Crystal Palace, Sunderland | 8 league-phase matches; jadwal Kamis meningkatkan short-rest sebelum liga |
| Conference League | Brighton | Masih bergantung pada hasil play-off hingga 27 Agustus 2026; 6 league-phase matches bila lolos |

### Window kepadatan utama

1. **8–24 September 2026** — awal UCL/UEL berdekatan dengan GW liga dan EFL Cup.
2. **10–24 Oktober 2026** — dua matchday Eropa dan tiga weekend liga dalam sekitar 15 hari.
3. **21 November–19 Desember 2026** — liga, Eropa, dan jadwal domestik akhir tahun bertumpuk.
4. **13–27 Februari 2027** — FA Cup round 4, dua leg European play-off, dan dua GW liga.
5. **6–21 Maret 2027** — FA Cup round 5, dua leg European round of 16, liga, dan final EFL Cup.
6. **3 April–15 Mei 2027** — FA Cup QF/SF, European QF/SF, dan enam GW liga; ini window paling kompleks untuk reschedule.

### Structural blank risk

| Baseline matchweek | Konflik | Risiko |
|---|---|---|
| MW30, 20–21 Mar 2027 | EFL Cup final | Fixture liga kedua finalis harus dipindah |
| MW33, 24–25 Apr 2027 | FA Cup semi-finals | Fixture liga semifinalis harus dipindah |
| MW37, 22–23 May 2027 | FA Cup final | Fixture liga finalis harus dipindah |

Istilah MW di atas mengikuti kalender Premier League. Nomor FPL event/GW tetap harus dibaca dari endpoint resmi FPL karena event assignment dapat berubah setelah reschedule.

## Prinsip sumber data

Urutan sumber kebenaran:

1. **Official FPL fixtures API** — satu-satunya sumber untuk status confirmed BGW/DGW di aplikasi.
2. **PremierLeague.com** — tanggal kompetisi domestik dan pengumuman reschedule.
3. **UEFA.com** — tanggal UCL, UEL, UECL serta status peserta.
4. **Input model terkontrol** — probabilitas cup progression atau scenario allocation yang memiliki timestamp, source, dan confidence.
5. **Workbook pihak ketiga** — referensi visual/analitis saja sampai hak penggunaan dan freshness tervalidasi.

Tidak boleh ada scraping atau penyimpanan workbook pihak ketiga di server Railway sebagai bagian default.

## Definisi status user-facing

| Status | Definisi |
|---|---|
| Confirmed Blank | Official FPL/PL sudah memindahkan fixture sehingga klub tidak memiliki fixture di event tersebut |
| Likely Blank | Probabilitas blank ≥70%, konflik belum terselesaikan |
| Possible Blank | Probabilitas blank 25–69% |
| Confirmed Double | Official FPL memasukkan minimal dua fixture klub dalam satu event |
| Likely Double | Probabilitas double ≥70% berdasarkan blank source dan slot reschedule yang feasible |
| Possible Double | Probabilitas double 25–69% |
| Normal | Belum ada bukti struktural blank/double |

Probability dan confidence harus ditampilkan terpisah. Contoh: `Possible DGW · 52% · confidence low`.

## Model probabilitas

### 1. Probabilitas lolos cup

Jika odds legal dan berizin tersedia, fractional odds `a/b` diubah menjadi raw implied probability:

```text
q_i = b / (a + b)
```

Overround dihapus menggunakan power normalization:

```text
p_i = q_i ^ gamma
pilih gamma sehingga jumlah seluruh p_i = 1
```

Jika odds tidak tersedia, v1 memakai probabilitas manual yang diberi source dan expiry. Model Elo/logistic hanya menjadi kandidat setelah tersedia dataset hasil cup yang cukup untuk kalibrasi.

### 2. Probabilitas satu fixture menjadi blank

Untuk fixture `A vs B` yang berbenturan dengan tahap cup:

```text
P(blank_fixture) = 1 - (1 - P(A lolos)) × (1 - P(B lolos))
```

Jika A dan B berada pada cabang cup yang mutually exclusive, gunakan scenario tree dan jangan memakai union formula independen.

### 3. Probabilitas double pada target GW

```text
P(double di GW j)
= jumlah_skenario P(fixture blank) × P(slot j dipilih | constraints)
```

Constraint minimal:

- kedua klub tersedia pada tanggal kandidat;
- tidak berbenturan dengan UEFA atau domestic cup;
- rest-day minimum;
- fixture belum memiliki kickoff resmi baru;
- tidak menduplikasi fixture yang sudah terpasang;
- mempertimbangkan home venue, broadcast, dan policing bila informasinya tersedia.

Jangan membagi probabilitas rata ke semua midweek kosong. Scenario allocation harus memiliki alasan yang dapat ditampilkan.

## Congestion score

Skor 0–100 dihitung untuk rolling 14 hari per klub:

```text
Congestion = 100 × clip(
    0.40 × normalized_match_count
  + 0.30 × normalized_short_rest
  + 0.15 × normalized_travel
  + 0.15 × normalized_stage_importance,
  0, 1
)
```

- `match_count`: seluruh pertandingan resmi dalam 14 hari.
- `short_rest`: jumlah interval antarpertandingan ≤3 hari, dengan penalti lebih besar untuk 2 hari.
- `travel`: jarak/perjalanan Eropa; bernilai netral sampai draw dan venue diketahui.
- `stage_importance`: knockout/final lebih berat daripada league phase.

Skor ini adalah indikator rotasi dan kelelahan, bukan prediksi cedera atau jaminan menit.

## Dampak ke squad user

Setelah squad resmi diimpor, hitung:

```text
Expected blank starters = Σ starter_weight × P(blank klub pemain)
Expected extra fixtures = Σ squad_weight × P(double klub pemain)
```

Bobot awal:

- starter: 1.00;
- bench outfield: 0.35;
- bench goalkeeper: 0.20;
- captain: tambahan exposure 1.00;

Output yang disarankan:

- jumlah starter berisiko blank;
- klub dengan exposure terbesar;
- target GW yang paling berisiko;
- kandidat transfer yang mengurangi blank exposure;
- peringatan bila rekomendasi transfer justru menambah pemain dari klub dengan congestion tinggi.

Chip strategy tidak otomatis direkomendasikan pada versi pertama.

## Rancangan arsitektur

### Konfigurasi baru

`config/competition_calendar_2026_27.yaml`

- competition code;
- stage;
- start/end date;
- clash matchweek;
- official source URL;
- last verified timestamp.

`config/european_participants_2026_27.yaml`

- team code dan official FPL team ID;
- competition;
- current stage/status;
- qualification conditional;
- source dan last verified.

### Domain/service baru

`src/services/schedule_congestion.py`

- membangun calendar windows;
- menghitung rolling congestion;
- mendeteksi clash domestik;
- membuat blank/double scenarios;
- menghitung squad exposure;
- menghasilkan explanation string yang dapat diaudit.

`src/domain/schedule_risk.py`

- `CompetitionEvent`;
- `TeamCompetitionEntry`;
- `FixtureRiskScenario`;
- `GameweekRiskSummary`;
- `SquadScheduleExposure`.

### Database

Tambahkan tabel:

- `competition_events`;
- `team_competition_entries`;
- `fixture_risk_snapshots`;
- `reschedule_scenarios`.

Setiap snapshot menyimpan `as_of`, source, model version, probability, confidence, dan explanation. Ini mencegah analisis lama terlihat sebagai prediksi current.

## Rancangan UI Advanced Planner

Section baru ditempatkan setelah `Custom fixture difficulty` dan sebelum `Squad import & wildcard planner`.

### 1. Gameweek risk strip

Timeline GW1–38 dengan warna:

- merah: confirmed/likely blank;
- ungu: confirmed/likely double;
- kuning: possible blank/double;
- hijau gelap: normal;
- abu-abu: data belum cukup.

### 2. Team risk matrix

Baris klub, kolom GW, isi status + probability. Filter:

- semua klub / European clubs / squad user;
- next 5 / 8 / sampai GW38;
- confirmed only / include projections.

### 3. Congestion leaders

Tabel klub dengan:

- matches next 14 days;
- shortest rest;
- European competition;
- congestion score;
- potential blank/double exposure.

### 4. Personalised squad exposure

Muncul setelah squad diimpor:

- expected blank starters;
- expected extra fixtures;
- affected players;
- transfer suggestions adjusted by schedule-risk penalty.

Semua label `Model`, `Probability`, `Confidence`, `Blank`, `Double`, dan `Congestion` memiliki tooltip ringkas.

## Integrasi dengan rekomendasi transfer

Versi pertama hanya menampilkan schedule risk secara terpisah. Setelah backtest:

```text
adjusted_transfer_priority
= base_transfer_priority
 + double_gain_weight × expected_extra_fixtures
 - blank_risk_weight × expected_blank_fixtures
 - congestion_weight × congestion_score
```

Bobot tidak boleh masuk production model sebelum backtest menunjukkan perbaikan dan tidak menurunkan stabilitas rekomendasi.

## Tahapan implementasi

### Phase A — Data contracts dan official calendar

- Tambahkan YAML calendar dan participant mapping.
- Validasi semua team code ke official FPL team ID.
- Tambahkan source timestamp dan expiry.
- Unit test: 20 klub, tanggal valid, competition/status enum valid.

### Phase B — Deterministic conflict engine

- Deteksi MW30, MW33, MW37 structural clash.
- Baca fixture resmi untuk confirmed blanks/doubles.
- Buat candidate reschedule slots tanpa probabilitas palsu.
- Unit test scenario tree dan mutually exclusive outcomes.

### Phase C — Probability and confidence engine

- Tambahkan manual probability input yang auditable.
- Tambahkan overround removal jika odds berizin tersedia.
- Hitung blank union/scenario probability dan DGW slot allocation.
- Test range 0–1, sum-to-one, monotonicity, dan stale-input expiry.

### Phase D — Advanced Planner UI

- Gameweek risk strip.
- Team risk matrix.
- Congestion leaders.
- Source, as-of timestamp, tooltip, empty/error state.

### Phase E — Squad personalisation

- Hubungkan ke imported squad.
- Hitung expected blank starters dan extra fixtures.
- Tampilkan affected players.
- Belum mengubah transfer priority.

### Phase F — Backtest dan transfer integration

- Rekonstruksi BGW/DGW musim historis tanpa leakage.
- Kalibrasi Brier score dan reliability buckets.
- Bandingkan rekomendasi dengan/ tanpa schedule adjustment.
- Aktifkan bobot hanya bila tervalidasi.

## Acceptance criteria

- Confirmed status hanya berasal dari official FPL/PL.
- Tidak ada sheet/tab berlabel old/copy yang dapat masuk production path.
- Tidak ada formula error atau missing team mapping.
- Setiap probability memiliki source, as-of, expiry, dan confidence.
- Probabilitas selalu 0–1; mutually exclusive scenarios berjumlah 1.
- UI tetap berguna bila probability source tidak tersedia.
- Imported squad tetap session-only.
- Tidak ada scraping pihak ketiga.
- Seluruh formula memiliki test deterministic dan explanation text.

## Sumber resmi

- Premier League fixtures 2026/27: https://www.premierleague.com/en/news/4675097/all-380-fixtures-for-202627-premier-league-season
- Dampak kompetisi lain, tanggal FA Cup/EFL Cup: https://www.premierleague.com/en/news/4675720/how-do-other-competitions-fixtures-affect-the-premier-league-and-its-clubs
- Champions League dates: https://www.uefa.com/uefachampionsleague/news/02a6-20d57cfcd03e-407c22a7f465-1000--2026-27-champions-league-teams-dates-draws-format-final/
- Europa League dates: https://www.uefa.com/uefaeuropaleague/news/02a6-20d57d095740-e1e0b3de85df-1000--2026-27-europa-league-teams-dates-draws-format-final/
- Conference League dates: https://www.uefa.com/uefaconferenceleague/news/02a6-20d57d15f093-a90cf54c928f-1000--2026-27-conference-league-teams-dates-draws-format-final/

