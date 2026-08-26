# Changelog model dan prosedur rollback

Dokumen ini mencatat versi yang dapat dilihat user dan cara mengembalikan konfigurasi
model dengan aman. Skor FPL Signal adalah ranking relatif, bukan jaminan poin.

## Versi

### `production-v1.1`

- Versi production yang aktif setelah Phase F.
- Menggabungkan fixture, minutes security, form, historical stability, value, dan sinyal
  official yang sudah tervalidasi.
- Tetap menjadi baseline ketika candidate positional belum memenuhi seluruh gate.

### `candidate-v1.2` (legacy)

- Candidate backtest historis dari evaluasi 2025–26 sebelumnya.
- Hasilnya tersimpan untuk audit, tetapi tidak mengubah ranking production.

### `candidate-v1.3-positional` (experimental)

- Menambahkan sinyal position-aware seperti xGC, clean-sheet rate, attacking rates,
  defensive contribution, discipline, dan conversion rate bila datanya tersedia.
- Bobot berada di `config/positional_candidate_weights.yaml`.
- Candidate dievaluasi leakage-safely per posisi. Ia tidak aktif hanya karena hasilnya
  terlihat lebih baik; seluruh gate coverage/regression dan persetujuan aktivasi harus lulus.

## Prosedur rollback

1. Jika ranking atau payload resmi bermasalah, kembalikan konfigurasi/model ke commit
   production terakhir yang diketahui aman (misalnya `production-v1.1`) dan deploy ulang.
2. Jangan mengubah schema database secara manual atau menurunkan nomor schema. Migrasi
   SQLite bersifat forward-only; simpan/backup Railway volume sebelum migrasi besar.
3. Setelah deploy rollback, buka **Data Status**, pastikan schema dan cache terbaca, lalu
   tekan **Refresh official FPL data**. Jika refresh gagal, aplikasi tetap memakai snapshot
   resmi terakhir yang valid dan menampilkan error-nya.
4. Bersihkan atau hitung ulang cache recommendation setelah pergantian model agar score lama
   tidak tercampur dengan versi baru. Verifikasi model version pada Data Status dan
   Recommendations.
5. Catat commit, waktu, alasan, dan hasil verifikasi di changelog/deployment log.

Rollback hanya mengembalikan model/configuration. Data historis yang sudah dimigrasikan
tetap dipertahankan agar audit tidak hilang; pemulihan data lama dilakukan dengan backup
volume yang eksplisit, bukan dengan `DROP TABLE` atau downgrade schema.

## Aturan rilis

- Production version tidak berubah otomatis setelah backtest.
- Candidate harus memiliki coverage resmi yang cukup, tidak mengalami regresi material per
  posisi, dan mendapat persetujuan aktivasi eksplisit.
- Perubahan field endpoint yang menghapus field inti harus menghentikan refresh secara fail-closed;
  field positional opsional boleh berstatus *Not supplied* dan tidak boleh berubah menjadi
  performa nol yang menyesatkan.
