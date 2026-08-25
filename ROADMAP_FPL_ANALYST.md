# Roadmap Eksekusi — FPL Signal

**Prinsip:** buat alur aplikasi terlihat sejak awal, tetapi jadikan data dan model sebagai sumber kebenaran sebelum fitur analitik dianggap selesai.

## Keputusan Urutan Pengerjaan

Kita mulai dengan **frontend shell**, bukan frontend penuh.

Artinya, pada fase awal pengguna sudah dapat membuka halaman Dashboard, Players, Recommendations, Fixtures, Compare, dan Data Status dengan data contoh yang jelas ditandai. Ini memvalidasi navigasi, filter, dan bentuk insight yang ingin kita tampilkan.

Namun, pekerjaan utama berikutnya adalah arsitektur data, database, dan scoring. UI baru dihubungkan ke data nyata setelah fondasi tersebut stabil. Dengan pola ini kita memperoleh arah produk tanpa membangun tampilan di atas rumus atau data yang belum valid.

---

## Phase 0 — Product Baseline & Repository Foundation ✅

**Status (24 Agustus 2026): selesai.** Foundation Python, virtual environment lokal, dependency, konfigurasi scoring, logging, aplikasi Streamlit minimal, dan automated test baseline telah tersedia.

**Tujuan:** menetapkan batas MVP dan menyiapkan proyek yang dapat dijalankan secara lokal.

**Pekerjaan**

- Buat repository Python dan virtual environment.
- Tambahkan dependency inti: Streamlit, pandas, SQLAlchemy, HTTP client, YAML parser, dan test runner.
- Buat struktur folder awal, `.gitignore`, konfigurasi environment, logging, dan README singkat.
- Tetapkan definisi metrik, posisi FPL, horizon fixture default (5 GW), dan versi awal scoring (`v1.0`).
- Tambahkan `config/scoring.yaml` sebagai satu-satunya tempat pengaturan bobot model.

**Selesai apabila**

- Aplikasi Streamlit dapat dijalankan lokal.
- Konfigurasi dan logging dapat dimuat.
- Struktur proyek siap menerima modul data dan UI.

---

## Phase 1 — Frontend Shell & UX Validation ✅

**Status (24 Agustus 2026): selesai.** Tujuh halaman utama, navigasi, filter, sample dataset fiktif, loading/empty/error state, visual theme, dan automated route smoke test telah tersedia.

**Tujuan:** memvalidasi bentuk aplikasi dan user flow tanpa ketergantungan pada API.

**Pekerjaan**

- Buat layout Streamlit, sidebar navigasi, dan state global dasar.
- Buat halaman Dashboard, Players, Recommendations, Fixtures, Player Detail, Compare, dan Data Status.
- Tambahkan dummy dataset lokal yang ditandai sebagai **sample data**.
- Rancang filter utama: posisi, budget, ownership maksimum, minimum minutes, dan fixture horizon.
- Rancang tabel ranking, score card pemain, matriks fixture, serta komponen “Why recommended?”.

**Selesai apabila**

- User dapat mengikuti alur: Dashboard → filter pemain → ranking → detail → compare.
- Semua halaman memiliki loading, empty state, dan error state sederhana.
- Tidak ada klaim bahwa angka dummy adalah rekomendasi FPL nyata.

---

## Phase 2 — Core Architecture & Data Contracts ✅

**Status (24 Agustus 2026): selesai.** Domain contracts, `FPLClient`, TTL cache, retry/timeout, response validation, timestamped raw JSON store, SQLite schema v1, transactional sessions, idempotent repositories, dan dokumentasi arsitektur telah tersedia.

**Tujuan:** membangun batas modul yang rapi sebelum data nyata masuk.

**Pekerjaan**

- Buat `FPLClient` sebagai satu-satunya akses ke API official FPL.
- Definisikan model/kontrak untuk player, team, fixture, current stats, gameweek history, dan recommendation score.
- Buat koneksi SQLite, schema, repository/upsert, serta migration strategy sederhana.
- Implementasikan caching, timeout, retry, response validation, dan structured logging.
- Tentukan raw-data layout dan aturan timestamp/snapshot.

**Selesai apabila**

- Modul UI tidak melakukan HTTP request atau SQL langsung.
- Test dapat memverifikasi response API palsu dan operasi database dasar.
- Kontrak data terdokumentasi di kode atau README.

---

## Phase 3 — Official FPL Data Ingestion ✅

**Status (24 Agustus 2026): selesai.** Manual official-data refresh mengambil `bootstrap-static` dan `fixtures`, memvalidasi/mentransform respons, menyimpan raw JSON bertimestamp, meng-upsert SQLite secara atomik, dan mempertahankan last-known-good status saat refresh gagal. Live smoke refresh berhasil memuat 20 tim, 609 pemain, 380 fixtures, dan 609 current-stat snapshots.

**Tujuan:** mengambil dan menyimpan data FPL current season secara andal.

**Pekerjaan**

- Integrasikan `bootstrap-static` dan `fixtures` official FPL.
- Simpan respons mentah sebelum transformasi.
- Transform teams, players, gameweeks, dan fixtures ke bentuk internal.
- Jalankan validasi dasar: tipe data, harga, ownership, team ID, fixture ID, dan field wajib.
- Tambahkan tombol **Refresh FPL Data** pada UI dan tampilkan waktu refresh terakhir.

**Selesai apabila**

- Data pemain, tim, dan fixtures berhasil diambil tanpa input manual.
- SQLite dan raw-data backup konsisten setelah refresh.
- Saat API gagal, aplikasi menampilkan last known good data.

---

## Phase 4 — Data Model, ETL, & Fixture Matrix ✅

**Tujuan:** menjadikan data mentah siap dipakai analitik.

**Status (24 Agustus 2026): selesai.** Schema SQLite sudah dimigrasikan aman ke v2 dengan `gameweek_snapshots` dan backfill data live yang telah ada. Refresh sekarang meng-upsert snapshot per `(season, gameweek, player)`, sedangkan halaman Fixtures memakai matrix dan fixture score dari official FDR yang tersimpan di SQLite untuk horizon 1, 3, 5, dan 8. Halaman Data Status menampilkan coverage snapshot dan kesiapan matrix.

**Pekerjaan**

- Lengkapi tabel `teams`, `players`, `player_current_stats`, `fixtures`, dan snapshot.
- Implementasikan upsert idempoten dan duplicate protection.
- Bangun fixture matrix per tim untuk Next 1, 3, 5, dan 8 GW.
- Konversi official FDR menjadi fixture score 0–100 dengan bobot horizon.
- Ganti dummy data pada halaman Fixtures dan Data Status dengan data nyata.

**Selesai apabila**

- Query pemain dan fixture dapat dijalankan konsisten dari SQLite.
- Fixture score dapat diuji dengan unit test.
- UI dapat menampilkan fixtures nyata dan status kualitas data.

---

## Phase 5 — Player Detail History & Feature Engineering ✅

**Tujuan:** menghitung sinyal performa yang dapat dijelaskan.

**Status (24 Agustus 2026): selesai.** Player Detail kini memakai roster official dan melakukan fetch `element-summary/{player_id}` secara on-demand. History tersimpan idempoten di SQLite, sedangkan `player_history_sync` mencegah request ulang pada season/gameweek yang sama—even saat hasil history kosong. Feature set mencakup rolling form 3/5/10 GW, PPM, xG/xA/xGI per 90, bonus, value, minutes security, availability penalty, minimum 270 menit, dan confidence adjustment. Smoke test live Haaland berhasil menyimpan satu history row dan load kedua terbukti memakai cache.

**Pekerjaan**

- Ambil `element-summary/{player_id}` secara on-demand dan cache hasilnya.
- Simpan gameweek history pemain yang telah dibuka atau diproses.
- Hitung form rolling (3/5/10 GW), points per match, xG/90, xA/90, xGI/90, dan value.
- Hitung minutes security dan availability penalty.
- Terapkan minimum minutes dan confidence adjustment untuk mengurangi small-sample bias.
- Tampilkan breakdown feature pada Player Detail.

**Selesai apabila**

- Setiap pemain aktif dengan data cukup memiliki feature set yang jelas sumber dan periodenya.
- Perhitungan utama memiliki unit test.
- Player Detail tidak membuat request berulang tanpa cache.

---

## Phase 6 — Recommendation Engine V1 ✅

**Tujuan:** menghasilkan ranking pemain yang transparan dan dapat dikonfigurasi.

**Status (24 Agustus 2026): selesai.** Seluruh 609 pemain official dinormalisasi dengan tie-aware percentile rank per posisi dan dihitung untuk horizon 1/3/5/8 memakai bobot GK/DEF/MID/FWD dari `scoring.yaml`. Small-sample signal memakai confidence shrinkage, sedangkan status availability menjadi final penalty. Sebanyak 2.436 score records tersimpan dengan model version, GW, horizon, waktu kalkulasi, dan semua component score. Dashboard, Players, Recommendations, dan Compare kini membaca engine official; setiap ranking menampilkan kategori dan dua alasan kontribusi terkuat.

**Pekerjaan**

- Normalisasi metrik dengan percentile rank per posisi.
- Terapkan bobot berbeda untuk GK, DEF, MID, dan FWD dari `scoring.yaml`.
- Hitung component score dan final recommendation score 0–100.
- Simpan `model_version`, waktu kalkulasi, horizon, dan semua component score.
- Tambahkan kategori Elite Target, Strong Buy, Good Option, Watchlist, Neutral, dan Avoid.
- Hubungkan halaman Recommendations dan Players ke engine nyata.

**Selesai apabila**

- Top 20 per posisi tersedia untuk horizon yang dipilih.
- Setiap ranking menampilkan alasan skor, bukan hanya angka akhir.
- Mengubah bobot config dapat dihitung ulang tanpa mengubah kode engine.

---

## Phase 7 — MVP UI Integration & Usability Pass ✅

**Tujuan:** mengubah frontend shell menjadi aplikasi MVP yang benar-benar dapat digunakan.

**Status (24 Agustus 2026): selesai.** Seluruh halaman MVP memakai cache official FPL, sedangkan Player Finder kini memiliki pencarian nama/tim, position, budget, ownership, minimum minutes, pilihan horizon 1/3/5/8 GW, sorting, dan mode differential (&lt;10% ownership). Player Detail menampilkan tren points, minutes, dan xGI ketika history on-demand tersedia. Compare memakai horizon yang sama untuk kedua pemain. Data Status menampilkan freshness, error terakhir, coverage current stats/snapshots/recommendation scores, dan menandai player history sebagai cache on-demand, bukan data hilang. Tooltip ringkas tersedia pada atribut dan kolom utama agar nilai dapat ditelusuri ke sumber atau rumusnya.

**Pekerjaan**

- Hapus dependency pada dummy data untuk halaman MVP.
- Lengkapi filter, sorting, pencarian, budget, ownership, dan minutes.
- Tambahkan visual tren points/minutes/xGI bila data tersedia.
- Selesaikan Compare Player, differential finder, empty/error state, dan copy penjelasan.
- Tambahkan Data Status yang memperlihatkan freshness data, error terakhir, dan data hilang.

**Selesai apabila**

- User dapat refresh data, memilih MID dengan budget tertentu, melihat ranking Next 5 GW, lalu membandingkan dua pemain.
- Semua nilai yang tampil dapat ditelusuri ke data dan rumusnya.

---

## Phase 8 — Historical Data & Gameweek Snapshots ✅

**Tujuan:** membangun data historis untuk reliability signal dan evaluasi model.

**Status (25 Agustus 2026): selesai.** Schema SQLite v5 menambahkan historical player-season, identity mapping, dan historical stability score. Import tiga season (2023–24, 2024–25, 2025–26) memakai aturan confidence: unique candidate di atas 90% otomatis `MATCHED`, sedangkan kandidat ambigu atau 90% ke bawah masuk `REVIEW`. Sebanyak 29 kandidat yang telah diverifikasi kemudian disatukan melalui `config/historical_identity_overrides.yaml` dan ditandai `MATCHED` dengan metode audit `manual_confirmed_override`. Setelah re-import lokal, hasilnya menjadi 1.080 `MATCHED`, 0 `REVIEW`, dan 1.430 `UNMATCHED` dari 2.510 row; 371 pemain aktif memiliki historical stability score dengan minimum 450 menit per season. Score memakai output points/90 berbobot recency, consistency lintas musim, serta evidence shrinkage ke nilai netral 50; contribution model tetap dibatasi bobot posisi 5–10%. Recommendation model v1.1 dihitung ulang setelah perubahan mapping. Snapshot current-season tetap idempoten melalui unique key `(season, gameweek, player_id)`, sedangkan Data Status tidak lagi menampilkan review queue selama seluruh kandidat terkonfirmasi.

**Pekerjaan**

- Import historical dataset yang telah divalidasi.
- Implementasikan player identity mapping dengan status MATCHED / REVIEW / UNMATCHED.
- Hitung historical score sebagai sinyal stabilitas berbobot antar-musim.
- Simpan snapshot current data per gameweek dan cegah snapshot duplikat.
- Tampilkan cakupan dan kualitas historical matching pada Data Status.

**Selesai apabila**

- Player dengan historical match valid memiliki historical score yang tidak mendominasi model.
- Snapshot gameweek dapat dipakai kembali untuk audit dan backtest.

---

## Phase 9 — Backtesting & Model Calibration ✅

**Tujuan:** membuktikan apakah ranking benar-benar berguna, lalu menyempurnakannya berdasarkan bukti.

**Status (24 Agustus 2026): selesai.** Schema SQLite v6 menambahkan dataset player-fixture historis, fixture historis, prediksi per cutoff/model, dan ringkasan run. Backtest time-safe musim 2025–26 selesai untuk horizon 1/3/5 GW pada baseline `production-v1.1` dan `candidate-v1.2`: 29.747 row player-fixture tervalidasi, 380 fixture, 6 run, dan 153.072 prediksi tersimpan. Candidate v1.2 memperbaiki MAE, Spearman, dan top-10 hit rate pada semua horizon, tetapi belum dipromosikan karena bukti baru satu musim dan status availability/injury historis tidak tersedia. Keputusan kalibrasi, definisi metrik, pengecekan kualitas, dan caveat terdokumentasi di `docs/BACKTESTING.md`; model produksi tetap v1.1 sampai validasi lintas musim tersedia.

**Pekerjaan**

- Buat workflow time-safe: gunakan data hingga GW N untuk menilai hasil GW N+1 sampai N+5.
- Simpan prediksi/ranking per model version.
- Hitung MAE, Spearman rank correlation, top-10 hit rate, dan rata-rata actual points top-10.
- Bandingkan versi bobot dan dokumentasikan keputusan perubahan model.

**Selesai apabila**

- Setiap perubahan bobot dapat dibandingkan dengan baseline.
- Recommendation score memiliki batasan dan performa yang terdokumentasi.

---

## Phase 10 — Decision Tools ✅

**Tujuan:** mengubah ranking menjadi bantuan keputusan FPL yang praktis.

**Status (24 Agustus 2026): selesai.** Menu **Decision Tools** sekarang menyediakan Transfer Finder serta Captain Shortlist untuk horizon 1/3/5/8 GW. Transfer Finder membandingkan player out dengan replacement posisi sama yang available, affordable terhadap bank budget, dan memiliki score lebih tinggi. Captain Shortlist menghasilkan profil `Safe`, `Balanced`, dan `Differential` yang berbeda bila data cukup; profil ini memprioritaskan outfield player dan baru fallback ke goalkeeper jika tidak ada pilihan lain. Projected points memakai proxy transparan dari PPM yang disesuaikan confidence × jumlah fixture official × fixture multiplier, sehingga tidak diklaim sebagai prediksi pasti. Setiap output menampilkan fixture, xGI/90, minutes, price, ownership, model reasons, serta decision confidence; validasi squad, free transfer, chip, team limit, price change, dan team news tetap berada di luar scope MVP.

**Pekerjaan**

- Basic transfer recommendation: player out, budget, dan calon replacement.
- Captain recommendation: safe, balanced, dan differential.
- Perhitungan projected gain untuk horizon yang dipilih.
- Penjelasan trade-off: fixture, xGI, minutes, price, dan ownership.

**Selesai apabila**

- Aplikasi memberi rekomendasi transfer/captain dengan alasan dan confidence, bukan instruksi absolut.

---

## Phase 11 — External Enrichment & Advanced Features ✅

**Tujuan:** memperkaya model hanya jika sumber data, legalitas, dan kualitasnya jelas.

**Status (25 Agustus 2026): selesai untuk scope official-data MVP.** Aplikasi sekarang memiliki provider boundary terpisah yang fail-closed melalui `config/external_providers.yaml`; FotMob tercatat sebagai opsi masa depan tetapi tetap `Disabled` karena akses/TOS dan adapter belum divalidasi. Advanced Planner menambahkan custom fixture difficulty sebagai pembanding official FDR, import squad publik dari endpoint official FPL tanpa menyimpan data manager ke arsip/database, visual pitch untuk Starting XI/bench/formasi/C/VC, serta wildcard optimizer heuristik. Draft selalu mematuhi 2 GK, 5 DEF, 5 MID, 3 FWD, budget, status available, maksimal tiga pemain per klub, dan formasi starting XI legal. Jika squad di-import, aplikasi menampilkan proposed same-position changes. Recommendation Engine v1.1 tetap memakai official FDR sampai custom signal lolos backtest multi-season; model prediksi lanjutan juga tetap future work karena bukti kalibrasi saat ini belum cukup untuk promosi.

**Pekerjaan potensial**

- Tambahkan provider layer terpisah untuk sumber eksternal seperti FotMob, melalui akses yang diizinkan.
- Gunakan data tambahan untuk lineup/availability context, match events, atau sinyal rotasi.
- Tambahkan internal custom fixture difficulty, squad import, optimizer, wildcard planner, dan model prediksi lanjutan.

**Aturan integrasi**

- Official FPL tetap sumber utama untuk harga, ownership, points, dan aturan FPL.
- Sumber eksternal adalah enrichment, bukan pengganti tanpa validasi.
- Validasi lisensi/Terms of Service dan identitas pemain sebelum otomatisasi apa pun.

**Selesai apabila**

- Provider eksternal tidak dapat aktif tanpa access mode, Terms review, adapter, dan identity validation yang eksplisit.
- User dapat membandingkan official/custom fixture ease tanpa mengubah model produksi.
- User dapat mengimpor squad publik dan menghasilkan draft 15 pemain yang memenuhi posisi, budget, club limit, serta formasi legal.
- Limitasi optimizer, privasi import, sumber data, dan status FotMob terdokumentasi.

---

## Milestone Produk

| Milestone | Phase | Hasil yang terlihat |
| --- | --- | --- |
| Prototype | 0–1 | UI dapat dinavigasi menggunakan sample data |
| Data-ready | 2–4 | Refresh official FPL dan fixture matrix nyata |
| Analytics MVP | 5–7 | Ranking pemain yang dapat dijelaskan dan difilter |
| Trusted model | 8–9 | Historical context, snapshots, dan backtesting |
| Decision support | 10–11 | Transfer/captain tool dan enrichment lanjutan |

## Urutan Implementasi Terdekat

1. Phase 0: foundation proyek.
2. Phase 1: frontend shell dengan sample data.
3. Phase 2: kontrak data dan SQLite.
4. Phase 3: refresh official FPL.

Setelah Phase 3 selesai, kita evaluasi kembali UI shell dengan data nyata sebelum melanjutkan ke fitur dan scoring engine.


### referensi next improv: 
1. https://fpl.page/
2. spreadsheet dari @BenCrellin
3. https://www.fantasyfootballhub.co.uk/ai-team-rating?via=twitter#import cari tim sendiri
