# FPL Signal — Tech Stack, Cakupan, dan Batasan

Dokumen ini adalah ringkasan yang dapat dipakai untuk menjelaskan aplikasi kepada user, reviewer, atau stakeholder non-teknis. Aplikasi ini adalah alat bantu keputusan FPL berbasis data, bukan autopilot dan bukan jaminan poin.

## Ringkasan satu kalimat

FPL Signal mengambil data publik resmi FPL, menyimpannya secara lokal, menghitung fixture dan sinyal pemain secara transparan, lalu menyajikan ranking, perbandingan, gameweek recap, wildcard draft, dan saran transfer yang dapat diaudit.

## Tech stack

| Lapisan | Teknologi | Peran |
|---|---|---|
| Bahasa | Python 3.9+ | Bahasa utama aplikasi, ETL, model, dan test |
| UI | Streamlit | Dashboard lokal, navigasi, filter, tabel, tooltip, dan state sesi |
| Data frame | pandas | Penyajian tabel dan transformasi data tabular |
| HTTP | requests + urllib3 | Request ke endpoint publik FPL dengan timeout, retry, dan validasi |
| Database | SQLite | Penyimpanan lokal single-user yang ringan |
| ORM/repository | SQLAlchemy 2.x | Model database, transaksi, schema, dan idempotent upsert |
| Konfigurasi | YAML / PyYAML | Bobot model, provider policy, scoring, dan pengaturan aplikasi |
| Cache | TTL memory cache + raw JSON store | Mengurangi request berulang dan menyediakan last-known-good data |
| Test | pytest | Unit test, contract test, database test, dan frontend smoke test |
| Version control | Git + GitHub | Source code dan histori perubahan |

Entry point aplikasi adalah `app.py`. Struktur utamanya adalah:

```text
Streamlit UI
    ↓
Application services
    ↓
Domain contracts / feature calculations
    ↓                 ↓
SQLite + repositories  FPLClient
                            ↓
                       Official FPL JSON
```

UI tidak membuat request HTTP atau query database secara langsung. Semua akses data melewati service dan gateway yang tervalidasi.

## Sumber data

### Data current season

Data FPL saat ini berasal dari endpoint publik Fantasy Premier League, terutama:

- `bootstrap-static`: pemain, tim, posisi, status, harga, ownership, current stats, event/gameweek, chip usage, most selected, most transferred in.
- `fixtures`: jadwal, lawan, venue, fixture difficulty rating, dan hasil fixture bila tersedia.
- `element-summary/{player_id}`: history gameweek pemain yang dimuat on-demand pada halaman Player Detail.
- `event/{gameweek}/live`: statistik pemain untuk Gameweek Wrapped ketika endpoint tersedia.
- `entry/{manager_id}` dan `entry/{manager_id}/event/{gameweek}/picks`: metadata dan squad publik manager yang diimpor di Advanced Planner.

Saat refresh berhasil, respons divalidasi lalu disimpan sebagai snapshot JSON bertimestamp dan di-upsert ke SQLite. Jika request berikutnya gagal, aplikasi mempertahankan dataset resmi terakhir yang berhasil.

### Gameweek Wrapped

Gameweek Wrapped menggunakan event FPL terakhir yang relevan dan statistik live pemain. Jika event live tidak dapat diakses, aplikasi memakai gameweek snapshot lokal yang sebelumnya juga diambil dari FPL.

Tile recap meliputi most captained/selected, most bought, most points, xG, xA, xG over/under-performer, best attack, best defence, dan chip usage jika field tersedia.

Catatan: FPL tidak menyediakan tabel team-xGC khusus pada endpoint yang digunakan. Tile “Best defence (xGC)” menggunakan xGC pemain dengan menit terbanyak—biasanya goalkeeper—sebagai proxy team-level dan diberi label proxy.

### Data historical

Historical stability berasal dari aggregate CSV completed season pada public archive `vaastav/Fantasy-Premier-League`, saat ini:

- 2023–24
- 2024–25
- 2025–26

Data historis ini dipakai sebagai sinyal stabilitas lintas musim, bukan sebagai pengganti data current season resmi FPL. Nama pemain dicocokkan ke player ID current menggunakan exact/fuzzy matching dan override terverifikasi. Row ambigu masuk `REVIEW`/`UNMATCHED` dan tidak memengaruhi model.

### Set-piece roles dan historical team context

Advanced Planner memiliki snapshot peran set-piece 2026/27 untuk penalty, direct free-kick, serta corner/indirect free-kick. Snapshot ini tersimpan di `config/set_piece_2026_27.yaml`, lengkap dengan source URL, tanggal `as_of`, urutan taker, dan penanda conditional (`*`). Data role ini adalah perkiraan yang dapat berubah mengikuti starting XI, cedera, transfer, match state, atau keputusan pelatih.

Endpoint publik FPL tidak menyediakan field standar team-level `set_piece_goals`. Karena itu historical set-piece goals (SPG) dipisahkan sebagai konteks tim dari sumber statistik historis yang terdokumentasi. Nilai SPG tidak diatribusikan seluruhnya kepada taker dan tidak digunakan untuk mengubah base Recommendation Engine score.

### Data backtesting

Backtesting memakai dataset completed season 2025–26 yang divalidasi untuk player-gameweek, fixtures, dan teams. Feature hanya boleh memakai informasi sampai cutoff GW N; outcome GW N+1 dan seterusnya dipakai sebagai evaluasi.

## Model dan arti skor

### Recommendation score

Model produksi saat ini adalah `v1.1`. Score 0–100 adalah ranking relatif, bukan probabilitas dan bukan jaminan poin. Pemain dinormalisasi terutama sebagai percentile di dalam posisinya, kemudian diberi bobot berbeda untuk GK, DEF, MID, dan FWD.

Sinyal yang dipakai dapat mencakup:

- official fixture ease;
- form dan points per match;
- expected goals, expected assists, atau expected goal involvements;
- minutes security dan starts/minutes;
- historical stability;
- value terhadap harga;
- bonus, ICT, dan saves untuk posisi yang relevan;
- ownership/differential;
- official availability penalty untuk doubtful, injured, suspended, atau unavailable.

Sinyal dengan sample menit kecil di-shrink menuju nilai netral. Minimum sample yang dikonfigurasi adalah 270 menit untuk feature confidence.

### Fixture score

Official FPL FDR memakai skala 1–5. Aplikasi mengubahnya menjadi fixture ease 0–100, lalu memberi bobot lebih besar kepada fixture terdekat dalam horizon 1, 3, 5, atau 8 GW. Nilai lebih tinggi berarti jadwal relatif lebih mudah.

Advanced Planner juga menampilkan custom fixture difficulty yang memadukan official FDR, kekuatan lawan, dan home/away. Custom score hanya sinyal pembanding; Recommendation Engine produksi tetap memakai official FDR.

### Projected points

Decision Tools menggunakan proxy yang dapat diperiksa:

```text
confidence-adjusted PPM
× jumlah fixture resmi dalam horizon
× fixture multiplier
```

Ini bukan forecast yang sudah dikalibrasi secara probabilistik. Angka tersebut cocok untuk membandingkan opsi dengan asumsi yang sama, bukan untuk menjanjikan poin.

### Transfer suggestions

Transfer suggestion di Advanced Planner menganalisis squad publik yang sedang diimpor. Default-nya satu free transfer, tetapi user dapat memilih jumlah transfer yang ingin dipakai.

Setiap swap harus memenuhi:

- posisi pemain masuk sama dengan pemain keluar;
- pemain masuk berstatus available;
- harga masuk masih sesuai bank;
- maksimal tiga pemain dari satu klub;
- score/model profile pemain masuk lebih baik;
- fixture dan minutes menjadi faktor tambahan dalam prioritas.
- expected set-piece duties dapat menjadi tie-breaker kecil yang terlihat terpisah di tabel; peran ini tidak mengubah Recommendation Engine score 0–100.

Saran memakai harga FPL cache saat ini karena public picks endpoint tidak menyediakan historical selling price user. Planner tidak mengeksekusi transfer dan tidak menghitung paid transfer hit.

### Wildcard draft

Wildcard optimizer adalah deterministic beam-search heuristic. Constraint-nya:

- 2 GK, 5 DEF, 5 MID, 3 FWD;
- maksimal tiga pemain per klub;
- total harga sesuai budget;
- pemain masuk berstatus available;
- starting XI memiliki formasi FPL yang legal.

Hasilnya adalah draft yang konsisten dengan constraint, bukan bukti bahwa draft tersebut merupakan optimum global yang unik.

## Fitur yang tercakup

| Fitur | Cakupan |
|---|---|
| Dashboard | Deadline, top recommendations, fixture radar, signal leaders, Gameweek Wrapped |
| Players | Search, filter posisi/budget/ownership/minutes, sort, differential mode |
| Recommendations | Ranking model untuk horizon 1/3/5/8 GW dan alasan kontribusi |
| Fixtures | Official fixture matrix dan custom comparison di Advanced Planner |
| Player Detail | Official history on-demand, trend points/minutes/xGI, feature breakdown |
| Compare | Perbandingan dua pemain pada horizon yang sama |
| Decision Tools | Transfer finder dan captain shortlist Safe/Balanced/Differential |
| Advanced Planner | Public squad import, pitch view, schedule exposure, set-piece insights, transfer suggestions, wildcard draft |
| Gameweek Wrapped | Recap GW terakhir/current snapshot berbasis event FPL |
| Backtesting | MAE, Spearman, top-10 hit rate, dan actual points top-10 |
| Data Status | Refresh, freshness, coverage, last error, history/backtest readiness |

## Yang tidak tercakup

- Login ke akun FPL atau akses private league.
- Eksekusi transfer, captaincy, chip, atau perubahan squad otomatis.
- Sinkronisasi otomatis squad pribadi tanpa user memasukkan public manager ID.
- Historical purchase price/selling price user yang akurat.
- Deteksi otomatis jumlah free transfer yang benar-benar tersedia untuk setiap user.
- Kalkulasi transfer hit berbayar secara otomatis.
- Price change prediction dan price-rise/fall alert.
- Late team news, press conference, lineup leak, rotation news, atau injury news real-time dari provider eksternal.
- Scraping FotMob atau sumber pihak ketiga lain. Provider eksternal tetap disabled/fail-closed sampai ada akses yang diizinkan dan identity validation.
- Prediksi poin yang terkalibrasi sebagai probabilitas.
- Jaminan ranking, return, green arrow, atau kemenangan mini-league.
- Multi-user authentication, cloud database, role management, dan production-grade concurrent writes.
- Mobile-native app atau deployment server multi-region.

## Batasan teknis dan data

1. **Ketergantungan API** — Endpoint publik FPL dapat lambat, berubah, rate-limited, atau tidak tersedia. Aplikasi memakai timeout, retry, validation, cache, dan last-known-good snapshot, tetapi cache tetap bisa tertinggal.
2. **Data live belum final** — Event yang masih berjalan atau belum `data_checked` dapat berubah. Gameweek recap pada kondisi ini diberi label snapshot, bukan hasil final.
3. **Availability bisa terlambat** — Status official FPL bukan pengganti konfirmasi lineup terakhir. Injury/status FPL dapat berubah setelah refresh.
4. **Harga transfer terbatas** — Harga squad saat ini dan bank tersedia dari data publik, tetapi selling price individual user tidak tersedia. Karena itu transfer suggestion adalah affordability approximation.
5. **History on-demand** — Tidak semua player history langsung ada di database. History baru dimuat ketika diminta atau diproses, kemudian dicache.
6. **Identity matching** — Pergantian nama, transliterasi, pemain baru, dan perpindahan klub dapat membuat row historical masuk review/unmatched. Row tersebut sengaja tidak dipakai agar tidak mencemari score.
7. **Satu musim untuk backtest** — Hasil backtesting 2025–26 belum cukup untuk menyimpulkan model akan stabil lintas musim. Karena itu production model tetap v1.1.
8. **Proxy team xGC** — Best defence pada Gameweek Wrapped memakai proxy dari data pemain, bukan team-xGC feed khusus.
9. **Relative score** — Score dapat berubah ketika populasi pemain, refresh data, atau horizon berubah. Score 80 bukan berarti peluang poin 80%.
10. **Local-first storage** — SQLite cocok untuk penggunaan lokal/single-user. Ia belum dirancang untuk banyak user menulis bersamaan atau deployment horizontal.
11. **Set-piece duties bukan kepastian** — Daftar taker adalah snapshot expected role. Corner dapat dibagi per sisi, penalty dapat berubah setelah miss/substitusi, dan pemain yang tercantum belum tentu berada di lapangan. Gunakan sebagai tie-breaker, bukan alasan tunggal transfer.
12. **Historical SPG bukan data FPL native** — Statistik gol set-piece level tim memiliki definisi provider tertentu, dapat memasukkan/mengecualikan penalty atau own goal secara berbeda, dan tidak tersedia untuk semua klub/promosi. Aplikasi menampilkan source dan musim sampel secara eksplisit.

## Privasi dan keamanan

- Public squad import hanya memakai manager ID publik; tidak meminta password atau cookie login.
- Squad import disimpan di session Streamlit dan tidak diarsipkan ke raw JSON/database.
- Database, raw snapshot, refresh status, dan log lokal dikecualikan dari Git.
- Jangan memasukkan token, password, cookie, atau secret ke file konfigurasi yang akan di-commit.

## Cara menjelaskan ke user

Gunakan jawaban singkat berikut bila ditanya:

> **“Apakah datanya resmi?”**
> Ya. Data current FPL berasal dari endpoint publik resmi FPL. Saat API sedang tidak tersedia, aplikasi menampilkan cache/snapshot terakhir yang sebelumnya diambil dari FPL.

> **“Apakah score 80 berarti pasti mendapat 80 poin?”**
> Tidak. Score adalah ranking relatif 0–100 untuk membandingkan pemain, bukan probabilitas dan bukan jaminan poin.

> **“Apa arti fixture?”**
> Fixture adalah jadwal lawan yang akan dihadapi. Fixture score yang lebih tinggi berarti jadwal relatif lebih mudah berdasarkan official FPL FDR dan horizon yang dipilih.

> **“Kenapa rekomendasinya memilih pemain itu?”**
> Karena kombinasi model pemain, fixture, expected output, minutes security, value, availability, ownership, dan—bila match aman—stabilitas historisnya lebih kuat dibanding alternatif pada posisi yang sama.

> **“Apakah aplikasi bisa transfer otomatis?”**
> Tidak. Aplikasi hanya memberi decision support; user tetap memeriksa official FPL, selling price, free transfer, team news, dan melakukan transfer sendiri.

> **“Apakah ini memakai FotMob atau berita terbaru?”**
> Belum. FotMob dan provider eksternal lain masih disabled. Aplikasi saat ini memakai data resmi FPL dan cache lokal yang tervalidasi.

> **“Mengapa data history pemain belum lengkap?”**
> History dimuat on-demand dan historical aggregate hanya dipakai jika identitas pemain berhasil dicocokkan dengan aman. Data yang ambigu sengaja dikeluarkan dari model.

> **“Apakah pemain ini pasti mengambil penalti atau corner?”**
> Tidak. Set-piece insight adalah snapshot expected role dengan urutan taker dan tanggal sumber. Ia dipakai sebagai tie-breaker kecil setelah minutes, fixture, harga, dan model score; cek line-up dan berita resmi sebelum deadline.

## Referensi teknis dalam repository

- [README.md](../README.md) — setup dan panduan penggunaan.
- [ARCHITECTURE.md](ARCHITECTURE.md) — layer, schema, ingestion, feature, dan backtesting flow.
- [HISTORICAL_DATA.md](HISTORICAL_DATA.md) — sumber, identity matching, dan historical stability.
- [BACKTESTING.md](BACKTESTING.md) — metodologi evaluasi time-safe dan caveat.
- [DECISION_TOOLS.md](DECISION_TOOLS.md) — transfer/captain proxy dan batasan.
- [ADVANCED_PLANNER.md](ADVANCED_PLANNER.md) — squad import, wildcard, provider governance, dan constraints.
- `config/set_piece_2026_27.yaml` — snapshot taker 2026/27 dan historical SPG team context yang memiliki source/as-of.
- `config/scoring.yaml` — model version, horizon default, minimum minutes, penalty, dan position weights.
